"""
Image to Excel BOM Extraction Tool

Strategy:
  1. If the image has a visible grid (horizontal + vertical rules), detect the
     grid, carve the image into cells, OCR each cell individually. This is the
     reliable path for bordered tables like engineering-drawing BOMs.
  2. Otherwise, fall back to word-position bucketing using Tesseract's
     image_to_data output.

Output columns and row count always mirror the source image — no BOM schema
expansion.
"""

from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import pandas as pd
import pytesseract
from PIL import Image, ImageOps

from pdf_tool import HEADER_KEYWORDS, generate_clean_excel
from ai_helpers import classify_column


SUPPORTED_EXTS = {".jpg", ".jpeg", ".png"}


# ---------------------------------------------------------------------------
# OCR confusion correction
# ---------------------------------------------------------------------------
# Tesseract regularly confuses visually similar characters at small sizes:
#   0 ↔ O ↔ Q
#   1 ↔ I ↔ l ↔ |
#   5 ↔ S
#   2 ↔ Z
#   6 ↔ G
#   8 ↔ B
# We use two strategies:
#   1. Character whitelists per column type (digit-only for qty, alphanumeric
#      for MPN, etc.) — Tesseract simply won't emit the wrong glyph.
#   2. Post-OCR correction: if a cell is in a digit column but Tesseract
#      returned "S", rewrite to "5". Same for O→0, l/I→1, Z→2, etc.

_DIGIT_FIX = str.maketrans({
    "S": "5", "s": "5",
    "O": "0", "o": "0", "Q": "0",
    "I": "1", "l": "1", "i": "1", "|": "1",
    "Z": "2", "z": "2",
    "B": "8",
    "G": "6",
    "T": "7",
    "g": "9",
    "?": "7",
})

_LETTER_FIX = str.maketrans({
    "0": "O",
    "1": "I",
    "5": "S",
    "8": "B",
    "6": "G",
})


def correct_digit_string(text: str) -> str:
    """Force a string into digit-only form, fixing common letter→digit confusions."""
    if not text:
        return text
    fixed = text.translate(_DIGIT_FIX)
    # Drop anything that's still not a digit / decimal point / sign
    return "".join(c for c in fixed if c.isdigit() or c in ".,-+")


def correct_alphanumeric(text: str) -> str:
    """For MPN-ish cells: keep punctuation, but try to reconcile mixed strings.

    Heuristic: if the cell starts with letters and ends with digits, we trust
    the boundary; we only fix obvious solo-character confusions inside runs of
    digits (e.g. "BC54O7" -> "BC5407" if surrounding chars are digits)."""
    if not text:
        return text
    out = list(text)
    n = len(out)
    for i, c in enumerate(out):
        prev_d = i > 0 and out[i - 1].isdigit()
        next_d = i + 1 < n and out[i + 1].isdigit()
        if c in "OoSIlZBG?" and prev_d and next_d:
            out[i] = _DIGIT_FIX.get(ord(c), c) if isinstance(_DIGIT_FIX.get(ord(c), c), str) else c
    return "".join(out)


# Per-column-type Tesseract char whitelists. Empty string = no restriction.
_TESS_WHITELIST = {
    "qty": "0123456789.,",
    "item_number": "0123456789.-",
    "revision": "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.-",
}


def _whitelist_config(col_type: Optional[str], psm: int = 7) -> str:
    base = f"--oem 3 --psm {psm}"
    wl = _TESS_WHITELIST.get(col_type or "")
    if wl:
        # Quoted so commas in the list don't break the config string
        base += f' -c tessedit_char_whitelist="{wl}"'
    return base


def _post_correct_cell(text: str, col_type: Optional[str]) -> str:
    if not text:
        return text
    if col_type in {"qty", "item_number"}:
        return correct_digit_string(text)
    if col_type == "mpn":
        return correct_alphanumeric(text)
    return text


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------

def _auto_crop_to_table(bgr: np.ndarray) -> np.ndarray:
    """
    Crop the image to the largest dense text region (the table area).

    Skips when there's no clear bounding box — never crops away too much.
    Reduces OCR noise from logos, page chrome, marketing footers around the
    actual BOM table.
    """
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    # Binarize
    _, bin_img = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    # Dilate to merge nearby text into blobs
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 9))
    dilated = cv2.dilate(bin_img, kernel, iterations=2)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return bgr
    # Largest contour by area
    biggest = max(contours, key=cv2.contourArea)
    x, y, cw, ch = cv2.boundingRect(biggest)
    # Sanity: the crop must cover a meaningful chunk of the page
    if cw * ch < 0.25 * w * h:
        return bgr
    # Add a small margin
    pad = 12
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(w, x + cw + pad), min(h, y + ch + pad)
    return bgr[y0:y1, x0:x1]


def _deskew(bgr: np.ndarray) -> np.ndarray:
    """Detect dominant text rotation and straighten the image.

    Skew of even 1-2° meaningfully degrades cell OCR; phone photos of printed
    BOMs commonly come in 3-6° off. We use Hough lines on the inverted
    binary mask: most lines in a table are horizontal grid rules + horizontal
    text baselines, so the median angle is the page skew."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=200,
                            minLineLength=max(60, gray.shape[1] // 6),
                            maxLineGap=20)
    if lines is None or len(lines) == 0:
        return bgr
    angles = []
    for x1, y1, x2, y2 in lines[:, 0]:
        if x2 == x1:
            continue
        ang = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        # Only consider near-horizontal lines (text baselines + grid)
        if -20 < ang < 20:
            angles.append(ang)
    if len(angles) < 5:
        return bgr
    angle = float(np.median(angles))
    # Don't bother rotating for sub-half-degree skew (rotation = blur cost)
    if abs(angle) < 0.5:
        return bgr
    h, w = bgr.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(bgr, M, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def _load_bgr(image_path: str) -> np.ndarray:
    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")
    # Upscale small screenshots aggressively so Tesseract has enough pixel
    # density on thin strokes. 2200 works well for typical BOM screenshots.
    w, h = img.size
    target = 2200
    if max(w, h) < target:
        scale = target / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    arr = np.array(img)
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    # Deskew BEFORE sharpening — sharpening before rotation magnifies any
    # interpolation blur from the rotate.
    bgr = _deskew(bgr)
    # Auto-crop to the table bounding box — drops logos, page chrome,
    # marketing borders before OCR.
    bgr = _auto_crop_to_table(bgr)
    # Unsharp mask — crispens text edges, big boost for low-res table scans.
    blurred = cv2.GaussianBlur(bgr, (0, 0), sigmaX=1.5)
    bgr = cv2.addWeighted(bgr, 1.6, blurred, -0.6, 0)
    return bgr


def _binarize(gray: np.ndarray) -> np.ndarray:
    # Adaptive threshold keeps thin grid lines even under uneven lighting.
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 10
    )


# ---------------------------------------------------------------------------
# Grid-based extraction (primary path)
# ---------------------------------------------------------------------------

def _detect_grid_lines(binary: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Return (horizontal_mask, vertical_mask) of grid lines."""
    h, w = binary.shape
    h_kernel_len = max(20, w // 30)
    v_kernel_len = max(20, h // 30)
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (h_kernel_len, 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_kernel_len))
    horiz = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel, iterations=1)
    vert = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel, iterations=1)
    return horiz, vert


def _line_positions(line_mask: np.ndarray, axis: int, min_gap: int = 8) -> List[int]:
    """Collapse a projection into distinct line centers along the given axis."""
    proj = (line_mask > 0).sum(axis=axis)
    threshold = proj.max() * 0.5 if proj.max() > 0 else 0
    if threshold == 0:
        return []
    above = proj >= threshold
    runs: List[Tuple[int, int]] = []
    start: Optional[int] = None
    for i, v in enumerate(above):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(above) - 1))
    centers: List[int] = []
    for s, e in runs:
        center = (s + e) // 2
        if not centers or center - centers[-1] >= min_gap:
            centers.append(center)
        else:
            centers[-1] = (centers[-1] + center) // 2
    return centers


def _ocr_cell(cell_img: np.ndarray, col_type: Optional[str] = None) -> str:
    """OCR a single cell with optional column-type-aware character whitelist.

    Column types like "qty" restrict Tesseract's output alphabet to digits,
    eliminating S/5, O/0, l/1 confusion at the source. After OCR we still
    run a post-correction pass for any letters that slipped through (e.g.
    when the whitelist is too restrictive and Tesseract drops the char)."""
    if cell_img.size == 0:
        return ""
    gray = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    if h == 0 or w == 0:
        return ""
    if max(h, w) < 90:
        scale = 3
    elif max(h, w) < 200:
        scale = 2
    else:
        scale = 1
    if scale > 1:
        gray = cv2.resize(gray, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
    # Slight denoise + OTSU binarization produces high-contrast input for Tesseract.
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bordered = cv2.copyMakeBorder(binary, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
    pil = Image.fromarray(bordered)

    # Two-pass approach for digit cells: try the strict whitelist first; if it
    # returns empty (Tesseract dropped everything), fall back to no-whitelist
    # and post-correct. Prevents losing data when the whitelist is too tight.
    config_strict = _whitelist_config(col_type, psm=7)
    text = pytesseract.image_to_string(pil, config=config_strict)
    cleaned = " ".join(text.split()).strip()
    cleaned = cleaned.strip("|[]_- ").replace("|", "").strip()

    if not cleaned and col_type in {"qty", "item_number"}:
        # Fallback: unrestricted OCR, then force-correct digit confusions
        text = pytesseract.image_to_string(pil, config="--oem 3 --psm 7")
        cleaned = " ".join(text.split()).strip().strip("|[]_- ").replace("|", "").strip()

    return _post_correct_cell(cleaned, col_type)


def _erase_grid(bgr: np.ndarray, horiz: np.ndarray, vert: np.ndarray) -> np.ndarray:
    """Paint detected grid lines white on a copy of the image so OCR doesn't pick them up."""
    grid = cv2.bitwise_or(horiz, vert)
    # Slight dilation so the erase covers anti-aliased edges of the line.
    kernel = np.ones((3, 3), np.uint8)
    grid = cv2.dilate(grid, kernel, iterations=1)
    cleaned = bgr.copy()
    cleaned[grid > 0] = [255, 255, 255]
    return cleaned


def _extract_by_grid(bgr: np.ndarray) -> Optional[Dict]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    binary = _binarize(gray)
    horiz, vert = _detect_grid_lines(binary)

    y_lines = _line_positions(horiz, axis=1)
    x_lines = _line_positions(vert, axis=0)

    # Need at least a top+bottom horizontal and left+right vertical rule for
    # this path to make sense, plus some internal lines.
    if len(y_lines) < 3 or len(x_lines) < 3:
        return None

    # Pair consecutive lines into row and column slices with a 1px inset
    # so grid pixels don't leak into cell crops.
    rows: List[Tuple[int, int]] = []
    for i in range(len(y_lines) - 1):
        top, bot = y_lines[i] + 1, y_lines[i + 1] - 1
        if bot - top >= 8:
            rows.append((top, bot))
    cols: List[Tuple[int, int]] = []
    for i in range(len(x_lines) - 1):
        left, right = x_lines[i] + 1, x_lines[i + 1] - 1
        if right - left >= 8:
            cols.append((left, right))
    if len(rows) < 2 or len(cols) < 2:
        return None

    # Erase grid lines so residual pixels don't confuse OCR
    clean_bgr = _erase_grid(bgr, horiz, vert)

    # OCR the whole cleaned image and bucket each word into its cell.
    # Two passes (PSM 4 = variable-column text, PSM 11 = sparse text) catch
    # different things — PSM 11 especially finds isolated single-digit cells
    # (like BOM Qty columns) that PSM 4's layout analysis tends to skip.
    gray = cv2.cvtColor(clean_bgr, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    pil = Image.fromarray(binary)

    cells: List[List[List[Tuple[int, int, str]]]] = [
        [[] for _ in cols] for _ in rows
    ]

    def absorb(data: Dict, min_conf: float) -> None:
        for i, text in enumerate(data["text"]):
            text = (text or "").strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            if conf < min_conf:
                continue
            x = int(data["left"][i])
            y = int(data["top"][i])
            w = int(data["width"][i])
            h = int(data["height"][i])
            cx = x + w // 2
            cy = y + h // 2
            row_idx = next((ri for ri, (t, b) in enumerate(rows) if t <= cy <= b), None)
            if row_idx is None:
                continue
            col_idx = next((ci for ci, (l, r) in enumerate(cols) if l <= cx <= r), None)
            if col_idx is None:
                continue
            cells[row_idx][col_idx].append((x, y, text))

    # Pass 1: PSM 4 (multi-column table mode) — captures most text cleanly
    absorb(
        pytesseract.image_to_data(pil, output_type=pytesseract.Output.DICT, config="--oem 3 --psm 4"),
        min_conf=30,
    )
    # Pass 2: only fill cells that came out empty from pass 1, using PSM 11
    # sparse-text mode which better catches isolated single-character cells.
    empty_targets = {
        (ri, ci) for ri, row in enumerate(cells) for ci, c in enumerate(row) if not c
    }
    if empty_targets:
        fill_cells: Dict[Tuple[int, int], List[Tuple[int, int, str]]] = {
            (ri, ci): [] for ri, ci in empty_targets
        }
        data2 = pytesseract.image_to_data(
            pil, output_type=pytesseract.Output.DICT, config="--oem 3 --psm 11"
        )
        for i, text in enumerate(data2["text"]):
            text = (text or "").strip()
            if not text:
                continue
            try:
                conf = float(data2["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            # Fill pass is permissive — isolated digits often get low conf.
            if conf < 0:
                continue
            x = int(data2["left"][i])
            y = int(data2["top"][i])
            w = int(data2["width"][i])
            h = int(data2["height"][i])
            cx = x + w // 2
            cy = y + h // 2
            row_idx = next((ri for ri, (t, b) in enumerate(rows) if t <= cy <= b), None)
            col_idx = next((ci for ci, (l, r) in enumerate(cols) if l <= cx <= r), None)
            if row_idx is not None and col_idx is not None and (row_idx, col_idx) in empty_targets:
                fill_cells[(row_idx, col_idx)].append((x, y, text))
        for (ri, ci), words in fill_cells.items():
            cells[ri][ci] = words

    # Identify the header row first so we can classify columns by type before
    # OCRing data cells. Header cells use unrestricted OCR (text is words).
    # Data cells in columns classified as "qty"/"item_number" get a strict
    # digit whitelist applied at OCR time → fixes S/5, O/0, I/1 confusion.
    def _words_to_text(words: List[Tuple[int, int, str]]) -> str:
        return " ".join(t for _, _, t in sorted(words, key=lambda w: (w[1], w[0])))

    header_idx_for_types = 0
    for i, r in enumerate(cells):
        if any(_words_to_text(c) for c in r):
            header_idx_for_types = i
            break

    tentative_header = [
        _words_to_text(cells[header_idx_for_types][ci]) if cells[header_idx_for_types][ci] else ""
        for ci in range(len(cols))
    ]
    col_types: List[Optional[str]] = [classify_column(h) for h in tentative_header]

    # Pass 3: any cell STILL empty — crop and OCR that individual cell. This
    # catches narrow columns (e.g. BOM Qty) that Tesseract skips at full-image scale.
    # We pass the column type so digit-only columns use the digit whitelist.
    for ri, (top, bot) in enumerate(rows):
        for ci, (left, right) in enumerate(cols):
            if cells[ri][ci]:
                continue
            crop = clean_bgr[top:bot, left:right]
            if crop.size == 0:
                continue
            # Don't whitelist on the header row itself (it's text, not data)
            ct = None if ri == header_idx_for_types else col_types[ci]
            text = _ocr_cell(crop, col_type=ct)
            if text:
                cells[ri][ci] = [(left, top, text)]

    # Pass 4: per-column post-correction. For digit-typed columns, every
    # data cell already-extracted gets force-corrected (S→5, O→0, etc.).
    # This catches confusions from passes 1 & 2 where we couldn't whitelist.
    for ri in range(len(rows)):
        if ri == header_idx_for_types:
            continue
        for ci in range(len(cols)):
            ct = col_types[ci]
            if ct not in {"qty", "item_number"}:
                continue
            words = cells[ri][ci]
            if not words:
                continue
            cells[ri][ci] = [(x, y, _post_correct_cell(t, ct)) for (x, y, t) in words if _post_correct_cell(t, ct)]

    # Build final cell strings. Most BOM cells are single-line, so sort by x
    # primarily; for multi-line cells the (y, x) secondary gives correct order.
    def _finalize_cell(words: List[Tuple[int, int, str]]) -> str:
        if not words:
            return ""
        ys = sorted(w[1] for w in words)
        line_h = max(8, (ys[-1] - ys[0]) // max(1, len(set(ys))))
        words_sorted = sorted(words, key=lambda w: (w[1] // max(1, line_h), w[0]))
        text = " ".join(t for _, _, t in words_sorted)
        # Strip grid-residue characters at edges (| : . _ - and combos).
        text = text.strip(" |:._-")
        # Remove stray single-character residue tokens like isolated "|" or ":".
        toks = [t for t in text.split() if t not in {"|", ":", ".", "_", "-", "•"}]
        return " ".join(toks)

    rendered: List[List[str]] = [[_finalize_cell(cell) for cell in row] for row in cells]
    cells = rendered  # type: ignore[assignment]

    # First non-empty row becomes the header
    header_idx = 0
    for i, r in enumerate(cells):
        if any(c.strip() for c in r):
            header_idx = i
            break
    header_cols_raw = cells[header_idx]
    header_cols = _dedupe_columns(header_cols_raw)

    data_rows = [r for r in cells[header_idx + 1 :] if any(c.strip() for c in r)]
    if not data_rows:
        return None

    df = pd.DataFrame(data_rows, columns=header_cols)

    # Confidence = share of non-empty cells
    total = len(data_rows) * len(header_cols) or 1
    non_empty = sum(1 for r in data_rows for c in r if c.strip())
    confidence = round(min(1.0, 0.5 + 0.5 * (non_empty / total)), 3)

    return {
        "table_data": df,
        "header_row": header_cols,
        "confidence": confidence,
        "page_numbers": [1],
        "is_bom_like": _header_is_bom_like(header_cols),
        "extraction_method": "grid",
    }


# ---------------------------------------------------------------------------
# Word-position fallback (for images without visible grid lines)
# ---------------------------------------------------------------------------

def _ocr_words(pil_image: Image.Image) -> List[Dict]:
    data = pytesseract.image_to_data(
        pil_image, output_type=pytesseract.Output.DICT, config="--oem 3 --psm 6"
    )
    words: List[Dict] = []
    for i, text in enumerate(data["text"]):
        text = (text or "").strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < 0:
            continue
        words.append({
            "text": text,
            "left": int(data["left"][i]),
            "top": int(data["top"][i]),
            "width": int(data["width"][i]),
            "height": int(data["height"][i]),
            "conf": conf,
        })
    return words


def _group_lines(words: List[Dict]) -> List[List[Dict]]:
    if not words:
        return []
    heights = sorted(w["height"] for w in words)
    median_h = heights[len(heights) // 2]
    tol = max(8, int(median_h * 0.6))
    sorted_words = sorted(words, key=lambda w: (w["top"], w["left"]))
    lines: List[List[Dict]] = []
    for w in sorted_words:
        if lines and abs(w["top"] - lines[-1][0]["top"]) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda x: x["left"]) for line in lines]


def _score_header(line: List[Dict]) -> float:
    text = " ".join(w["text"] for w in line).lower()
    if len(text) < 4:
        return 0.0
    score = 0.0
    for keyword, weight in HEADER_KEYWORDS.items():
        if keyword in text:
            score += weight
    return score


def _find_header(lines: List[List[Dict]]) -> Tuple[Optional[int], bool]:
    best_idx, best_score = None, 0.0
    for idx, line in enumerate(lines[: min(len(lines), 25)]):
        s = _score_header(line)
        if s > best_score:
            best_score, best_idx = s, idx
    if best_score >= 8:
        return best_idx, True
    for idx, line in enumerate(lines):
        if len(line) >= 2:
            return idx, False
    return None, False


def _merge_adjacent_header_words(header_line: List[Dict]) -> List[Dict]:
    if not header_line:
        return header_line
    merged: List[Dict] = [header_line[0].copy()]
    for w in header_line[1:]:
        prev = merged[-1]
        gap = w["left"] - (prev["left"] + prev["width"])
        avg_h = (prev["height"] + w["height"]) / 2
        if gap < avg_h * 1.1:
            prev["text"] = f"{prev['text']} {w['text']}"
            prev["width"] = (w["left"] + w["width"]) - prev["left"]
            prev["height"] = max(prev["height"], w["height"])
        else:
            merged.append(w.copy())
    return merged


def _column_bounds(header_line: List[Dict]) -> List[Tuple[int, int, str]]:
    bounds: List[Tuple[int, int, str]] = []
    for i, w in enumerate(header_line):
        left = w["left"]
        right = w["left"] + w["width"]
        if i + 1 < len(header_line):
            next_left = header_line[i + 1]["left"]
            right = (right + next_left) // 2
        if bounds:
            prev_right = bounds[-1][1]
            left = min(left, prev_right)
        bounds.append((left, right, w["text"]))
    if bounds:
        first = bounds[0]
        bounds[0] = (0, first[1], first[2])
        last = bounds[-1]
        bounds[-1] = (last[0], 10**9, last[2])
    return bounds


def _assign_to_columns(line: List[Dict], bounds: List[Tuple[int, int, str]]) -> List[str]:
    cells = ["" for _ in bounds]
    for w in line:
        cx = w["left"] + w["width"] // 2
        for idx, (l, r, _) in enumerate(bounds):
            if l <= cx < r:
                cells[idx] = (cells[idx] + " " + w["text"]).strip() if cells[idx] else w["text"]
                break
    return cells


def _extract_by_words(bgr: np.ndarray) -> Dict:
    pil = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
    words = _ocr_words(pil)
    lines = _group_lines(words)
    if not lines:
        raise ValueError(
            "No readable text detected in the image. Make sure the image is a clear screenshot."
        )
    header_idx, is_bom_like = _find_header(lines)
    if header_idx is None:
        raise ValueError("No readable text detected in the image.")

    header_line = _merge_adjacent_header_words(lines[header_idx])
    bounds = _column_bounds(header_line)
    header_cols = _dedupe_columns([b[2] for b in bounds])

    # Classify each column by header text so we can post-correct digit columns
    col_types_words: List[Optional[str]] = [classify_column(h) for h in header_cols]

    rows: List[List[str]] = []
    for line in lines[header_idx + 1:]:
        cells = _assign_to_columns(line, bounds)
        if any(c.strip() for c in cells):
            # Post-correct digit-typed columns (5↔S, O↔0, l/I↔1, Z↔2…)
            corrected = [
                _post_correct_cell(cell, col_types_words[i]) if i < len(col_types_words) else cell
                for i, cell in enumerate(cells)
            ]
            rows.append(corrected)

    ocr_good = sum(1 for w in words if w["conf"] >= 70)
    ocr_conf = ocr_good / max(1, len(words))
    header_conf = min(1.0, _score_header(header_line) / 30.0) if is_bom_like else 0.3
    confidence = round(min(1.0, 0.4 + 0.3 * ocr_conf + 0.3 * header_conf), 3)

    df = pd.DataFrame(rows, columns=header_cols)
    return {
        "table_data": df,
        "header_row": header_cols,
        "confidence": confidence,
        "page_numbers": [1],
        "is_bom_like": is_bom_like,
        "extraction_method": "words",
    }


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _dedupe_columns(cols: List[str]) -> List[str]:
    seen: Dict[str, int] = {}
    out: List[str] = []
    for i, c in enumerate(cols):
        n = (c or "").strip() or f"Column {i + 1}"
        seen[n] = seen.get(n, 0) + 1
        if seen[n] > 1:
            n = f"{n} ({seen[n]})"
        out.append(n)
    return out


def _header_is_bom_like(cols: List[str]) -> bool:
    text = " ".join(cols).lower()
    return any(k in text for k in ["mpn", "part number", "p/n", "part #", "qty", "quantity", "ref des", "refdes", "manufacturer"])


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_bom_from_image(image_path: str, output_excel_path: str) -> Dict:
    """Extract the table from an image and write an Excel file mirroring the
    source's column count and order exactly."""
    warnings: List[str] = []
    bgr = _load_bgr(image_path)

    result = _extract_by_grid(bgr)
    if result is None:
        result = _extract_by_words(bgr)

    if result["confidence"] < 0.6:
        warnings.append(
            f"Table detected with low confidence ({result['confidence']:.0%}). Manual review recommended."
        )

    df_out: pd.DataFrame = result["table_data"]
    if df_out.empty:
        raise ValueError(
            "Detected a header row but could not extract any data rows. "
            "Try a higher-resolution image or crop more tightly to the table."
        )

    generate_clean_excel(df_out, output_excel_path)

    return {
        "success": True,
        "excel_path": output_excel_path,
        "metadata": {
            "pages_processed": result["page_numbers"],
            "rows_extracted": len(df_out),
            "confidence": result["confidence"],
            "columns_detected": list(df_out.columns),
            "extraction_method": result.get("extraction_method", "words"),
        },
        "warnings": warnings,
    }

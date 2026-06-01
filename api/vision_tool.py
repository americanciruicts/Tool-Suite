"""
Local-Ollama vision fallback for PDF→Excel BOM extraction.

The default extractor (pdf_tool.py) reads the PDF's digital text layer with
pdfplumber and reconstructs the table from word coordinates. That is fast,
deterministic, and exact on clean tabular BOMs — but it degrades on dense
engineering drawings: rotated/stacked MIL-STD parts lists, wrapped reference
designators, multi-block side-by-side layouts. This module is the fallback for
those cases, and it runs entirely on the server's local Ollama install (free,
no external API).

Strategy:
  1. Render the relevant PDF pages to images (pdf2image / poppler).
  2. Large drawings (A0/A1) are tiled into overlapping panels so the BOM text
     stays legible for the vision model.
  3. Each tile is sent to a local Ollama vision model with a strict instruction
     to transcribe the parts list as JSON, disambiguating visually similar
     glyphs — 5 vs S, 0 vs O/Q, 1 vs I/l, 8 vs B, 2 vs Z, 6 vs G — because a
     single wrong character in a part number makes it useless.
  4. Rows from all tiles are merged and de-duplicated.

Degrades gracefully: vision_available() returns False — and extract_bom_via_vision
returns None — if pdf2image/poppler are missing or Ollama is unreachable. The
text path then remains the default and nothing breaks.
"""

from __future__ import annotations

import base64
import io
import json
import os
import urllib.request
import urllib.error
from typing import Dict, List, Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Tunables (env-overridable so ops can trade accuracy vs cost without a deploy)
# ---------------------------------------------------------------------------
# Inside Docker, localhost is the container — reach the host's Ollama via
# host.docker.internal (compose maps it to the host gateway).
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
# A vision-capable Ollama model. minicpm-v is small and strong at OCR/document
# transcription; llama3.2-vision / qwen2.5vl also work if pulled.
MODEL = os.environ.get("BOM_VISION_MODEL", "minicpm-v")
RENDER_DPI = int(os.environ.get("BOM_VISION_DPI", "200"))
TILE_MAX = int(os.environ.get("BOM_VISION_TILE_MAX", "1500"))   # px long edge per tile
TILE_OVERLAP = int(os.environ.get("BOM_VISION_TILE_OVERLAP", "160"))  # px overlap so rows split across a seam still appear whole in one tile
MAX_TILES = int(os.environ.get("BOM_VISION_MAX_TILES", "16"))   # cost/time ceiling per PDF
MAX_PAGES = int(os.environ.get("BOM_VISION_MAX_PAGES", "5"))
REQUEST_TIMEOUT = int(os.environ.get("BOM_VISION_TIMEOUT", "120"))

# Output column order — descriptive headers so pdf_tool.detect_column_type() /
# the engineering-header fallback map them onto the BOM schema. "CAGE/Code Ident"
# has no canonical type and stays on the raw tab only.
COLUMNS = [
    "Item No.",
    "Reference Designation",
    "Qty",
    "CAGE/Code Ident",
    "Part Number",
    "Description",
    "Manufacturer",
]

_FIELD_MAP = {
    "item": "Item No.",
    "refdes": "Reference Designation",
    "qty": "Qty",
    "cage": "CAGE/Code Ident",
    "part_number": "Part Number",
    "description": "Description",
    "manufacturer": "Manufacturer",
}
_INV = {label: src for src, label in _FIELD_MAP.items()}

_PROMPT = (
    "You transcribe Bill of Materials (BOM) / 'LIST OF MATERIALS OR PARTS LIST' "
    "tables from this engineering-drawing image panel into structured JSON.\n\n"
    "Rules:\n"
    "1. Output ONLY real BOM line items. Ignore drawing notes, title blocks, "
    "revision history, dimensions, and callout balloons.\n"
    "2. One logical BOM item = one row. If a cell's text wraps across lines "
    "(common for reference-designator lists like 'C257,C264,C279-281'), join it "
    "into a single value — do not split it into extra rows.\n"
    "3. Transcribe characters EXACTLY. Distinguish visually similar glyphs with "
    "care: 5 vs S, 0 vs O vs Q, 1 vs I vs l, 8 vs B, 2 vs Z, 6 vs G, 7 vs T. "
    "Part numbers are case- and digit-sensitive — prefer the literal glyph over "
    "a 'plausible' guess.\n"
    "4. Leave a field empty ('') if the column is absent or the cell is blank. "
    "Never invent values.\n"
    "5. Respond with ONLY a JSON object of this exact shape (no prose, no "
    "markdown fences):\n"
    '{"rows": [{"item": "", "refdes": "", "qty": "", "cage": "", '
    '"part_number": "", "description": "", "manufacturer": ""}]}\n'
    "If this panel has no BOM rows, respond {\"rows\": []}."
)


def _ollama_url(path: str) -> str:
    return f"{OLLAMA_BASE_URL}{path}"


def vision_available() -> bool:
    """True only if the render deps exist and the local Ollama server responds."""
    try:
        import pdf2image  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception:
        return False
    try:
        with urllib.request.urlopen(_ollama_url("/api/tags"), timeout=4) as r:
            return r.status == 200
    except Exception:
        return False


def _tile_image(img):
    """Split a PIL image into overlapping tiles whose long edge ≤ TILE_MAX.
    Small pages (letter/A4 at moderate DPI) return as a single tile."""
    w, h = img.size
    if max(w, h) <= TILE_MAX:
        return [img]
    step = max(TILE_MAX - TILE_OVERLAP, TILE_MAX // 2)
    tiles = []
    y = 0
    while y < h:
        x = 0
        while x < w:
            tiles.append(img.crop((x, y, min(x + TILE_MAX, w), min(y + TILE_MAX, h))))
            if x + TILE_MAX >= w:
                break
            x += step
        if y + TILE_MAX >= h:
            break
        y += step
    return tiles


def _render_tiles(pdf_path: str) -> List[bytes]:
    """Render up to MAX_PAGES pages, tile them, return PNG bytes (≤ MAX_TILES)."""
    from pdf2image import convert_from_path

    pages = convert_from_path(pdf_path, dpi=RENDER_DPI, first_page=1, last_page=MAX_PAGES)
    out: List[bytes] = []
    for page in pages:
        for tile in _tile_image(page):
            buf = io.BytesIO()
            tile.save(buf, format="PNG")
            out.append(buf.getvalue())
            if len(out) >= MAX_TILES:
                return out
    return out


def _extract_rows_from_tile(png_bytes: bytes) -> List[Dict[str, str]]:
    """Send one tile to Ollama and return its transcribed rows (may be empty)."""
    b64 = base64.b64encode(png_bytes).decode("ascii")
    body = json.dumps({
        "model": MODEL,
        "prompt": _PROMPT,
        "images": [b64],
        "stream": False,
        "format": "json",          # ask Ollama to constrain output to valid JSON
        "options": {"temperature": 0},  # deterministic-ish transcription
    }).encode("utf-8")
    req = urllib.request.Request(
        _ollama_url("/api/generate"), data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    text = payload.get("response", "")
    try:
        data = json.loads(text)
    except Exception:
        return []
    rows = data.get("rows", []) if isinstance(data, dict) else []
    return [r for r in rows if isinstance(r, dict)]


def _row_key(row: Dict[str, str]) -> str:
    """De-dup key — overlapping tiles re-capture the same rows at their seams."""
    def norm(k):
        return str(row.get(k, "")).strip().lower()
    return "|".join((norm("item"), norm("part_number"), norm("refdes"), norm("description")))


def extract_bom_via_vision(pdf_path: str) -> Optional[pd.DataFrame]:
    """
    Transcribe a PDF's BOM with a local Ollama vision model. Returns a DataFrame
    with the COLUMNS schema, or None if the vision path is unavailable / empty.
    """
    if not vision_available():
        return None

    tiles = _render_tiles(pdf_path)
    if not tiles:
        return None

    seen = set()
    merged: List[Dict[str, str]] = []
    for png in tiles:
        try:
            rows = _extract_rows_from_tile(png)
        except Exception:
            continue  # one bad tile shouldn't sink the whole extraction
        for r in rows:
            if not (str(r.get("part_number", "")).strip() or str(r.get("description", "")).strip()):
                continue
            key = _row_key(r)
            if key in seen:
                continue
            seen.add(key)
            merged.append(r)

    if not merged:
        return None

    return pd.DataFrame(
        {label: [str(r.get(_INV[label], "")) for r in merged] for label in COLUMNS}
    )

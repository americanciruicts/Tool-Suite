"""
Deterministic parser for cable / wire-harness drawings.

These drawings don't carry a parts-list table — the BOM is a set of callouts
scattered on the drawing:

    4 POSITION CONNECTOR HOUSING
    MOLEX PN# 0009508040 X2
    MOLEX HOUSING PN
    51065-0500
    SOCKET, FEMALE (18-24 awg) X8
    SHRINK TUBING, 3/4" DIA  230-0018-001 X2

plus a wire table (WIRE / COLOR / SIZE / SIGNAL). The columnar parsers in
layout_parse.py find nothing here, so this module pulls the callouts directly:

  * "<label> PN# <part> [xN]"     — inline maker/part callout
  * "<label> PN" / "<label> PN:"  — label line, part number on the next line
  * "1  YELLOW  24 AWG  REQUEST"   — wire-table rows

When the PDF has no usable text layer (the part numbers were flattened to vector
outlines, as on plotted Thomas&Betts drawings), the page is rasterised with
`pdftoppm` and OCR'd with `tesseract` (both already in the image) to recover the
text first. Returns None when no callouts are found, so callers fall through to
the other extraction paths.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from typing import Dict, List, Optional

import pandas as pd

COLUMNS = ["Item No.", "Part Number", "Description", "Qty", "Manufacturer"]

# Manufacturer names that commonly lead a harness callout, so we can split the
# maker out of the description ("MOLEX HOUSING" -> Mfg MOLEX / desc HOUSING).
_MAKERS = (
    "MOLEX", "CAROL", "TE", "AMP", "TYCO", "SAMTEC", "JST", "HIROSE", "AMPHENOL",
    "DEUTSCH", "PHOENIX", "WAGO", "HARTING", "FCI", "ITT", "LAPP", "BELDEN",
    "ALPHA", "PANDUIT", "TYCOELECTRONICS",
)

# Min characters of real text layer before we fall back to OCR.
_MIN_TEXT = 60

# Material / consumable callouts that typically carry no part number on a harness
# drawing. Ordered longest-first so "HEAT SHRINK" wins over "SHRINK".
_MATERIAL_KW = [
    "HEAT SHRINK", "SHRINK TUBING", "SHRINK SLEEVE", "SHRINK", "SLEEVING",
    "SLEEVE", "CABLE TIE", "TIE WRAP", "ZIP TIE", "WIRE MARKER", "CABLE MARKER",
    "WIRE LABEL", "MARKER", "LABEL", "LACING", "HARNESS TAPE", "TAPE",
    "GROMMET", "BRAID", "CONVOLUTE", "LOOM", "SOLDER", "FLUX", "POTTING",
    "EPOXY", "ADHESIVE", "TUBING",
]
# Where a material phrase ends: the next maker name or a PN label on the line.
_CALLOUT_BREAK = re.compile(
    r"\b(?:" + "|".join(list(_MAKERS) + ["PN", "P/N", "PN#"]) + r")\b", re.I
)


def _looks_like_partno(tok: str) -> bool:
    """A harness part number has a digit, is reasonably long, and is a single
    alphanumeric/dash/dot/slash token (no spaces)."""
    tok = tok.strip().rstrip(",.;")
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-/.]{3,}", tok)) and any(c.isdigit() for c in tok)


def _split_maker(label: str) -> tuple:
    """Return (manufacturer, description) — splits a known leading maker word
    off the callout label."""
    label = re.sub(r"\s+", " ", label).strip(" :-")
    if not label:
        return "", ""
    first = label.split()[0].upper().rstrip(".,")
    if first in _MAKERS:
        rest = label[len(label.split()[0]):].strip(" :-")
        return label.split()[0], rest or label
    return "", label


def _pdf_text(pdf_path: str, max_pages: int = 4) -> str:
    """Text layer via pdfplumber (fast); empty string if none/unavailable."""
    try:
        import pdfplumber
    except Exception:
        return ""
    out: List[str] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:max_pages]:
                try:
                    out.append(page.extract_text() or "")
                except Exception:
                    continue
    except Exception:
        return ""
    return "\n".join(out)


def _ocr_text(pdf_path: str, max_pages: int = 2, dpi: int = 300) -> str:
    """Rasterise the first pages with pdftoppm and OCR them with tesseract.
    Best-effort: returns '' if either binary is missing or fails."""
    out: List[str] = []
    with tempfile.TemporaryDirectory() as td:
        prefix = os.path.join(td, "pg")
        try:
            subprocess.run(
                ["pdftoppm", "-r", str(dpi), "-png", "-l", str(max_pages), pdf_path, prefix],
                check=True, capture_output=True, timeout=120,
            )
        except Exception:
            return ""
        for name in sorted(os.listdir(td)):
            if not name.endswith(".png"):
                continue
            try:
                # Default page segmentation keeps a callout's label and part
                # number on adjacent lines (sparse mode --psm 11 scatters them).
                res = subprocess.run(
                    ["tesseract", os.path.join(td, name), "-"],
                    capture_output=True, text=True, timeout=120,
                )
                out.append(res.stdout or "")
            except Exception:
                continue
    # Normalise OCR dash variants (em/en/figure dash, minus) to a plain hyphen
    # so part numbers like 230-0018-001 reassemble.
    return re.sub(r"[‐-―−]", "-", "\n".join(out))


# A "structured" part number — has an internal dash/dot/hash group, so it can't
# be confused with a bare dimension ("38", "5Nm") on a label-free callout line.
_STRUCTURED_PN = re.compile(r"^[A-Za-z0-9]+(?:[#][A-Za-z0-9]+|(?:[-.][A-Za-z0-9]+){1,})$")
# A description-ish label: mostly letters, the kind of phrase that precedes a
# callout ("4 POSITION CONNECTOR HOUSING", "SHRINK TUBING, 3/4\" DIA").
_DESC_LABEL = re.compile(r"[A-Za-z]{3,}")


# Title-block / assembly-level phrases — these name the whole drawing, not a
# component, so a bare part number sitting under them is the drawing's own
# number (e.g. "M3PS to M3 Vin Power Cable" / 500-0153-000), not a BOM line.
_ASSEMBLY_RE = re.compile(r"\b(?:ASSEMBLY|ASSY|HARNESS|DWG|DRAWING|CABLE\s+ASSY)\b", re.I)
# Drawing-view / annotation labels that are never a component description.
_VIEW_RE = re.compile(
    r"\b(?:SIDE|TOP|FRONT|BACK|REAR|BOTTOM|ISO|DETAIL|SECTION)\s+VIEW\b|"
    r"\b(?:DETAIL|SECTION|VIEW|NOTES?|SCALE|TYP)\b\s*[A-Z]?$", re.I)


def _is_desc_label(s: str) -> bool:
    s = s.strip()
    if len(s) < 4 or re.search(r"\b(?:PN|P/?N)\b", s, re.I):
        return False
    letters = sum(c.isalpha() for c in s)
    return letters >= 4 and letters >= len(s.replace(" ", "")) * 0.4


def _parse_callouts(text: str) -> List[Dict[str, str]]:
    """Pull harness BOM line items out of drawing text (or OCR'd text)."""
    lines = [l.strip() for l in text.splitlines()]
    rows: List[Dict[str, str]] = []
    seen: set = set()

    def add(partno: str, label: str, qty: str = "", maker: Optional[str] = None):
        partno = partno.strip().rstrip(",.;")
        # Keep the FULL callout text as the description ("MOLEX HOUSING", not
        # "HOUSING") so the BOM mirrors the drawing; record the maker in its own
        # column (passed explicitly when the label is a context line w/o a maker).
        if maker is None:
            maker, _ = _split_maker(label)
        desc = re.sub(r"\s+", " ", label).strip(" :-")
        # Dedup by part number when there is one (the same callout is often
        # printed at both ends of the harness); else by description (wires).
        key = ("pn:" + partno.upper()) if partno else ("d:" + desc.upper())
        if (not partno and not desc) or key in seen:
            return
        seen.add(key)
        rows.append({
            "Part Number": partno,
            "Description": desc or "Part",
            "Qty": qty or "1",
            "Manufacturer": maker,
        })

    def _prev_label(i: int) -> str:
        """Nearest descriptive line above i — a callout's label sits directly
        above its part number ("SHRINK TUBING" / "230-0018-001"). Skips the bare
        maker word and assembly-level title phrases."""
        for j in range(i - 1, max(i - 6, -1), -1):
            cand = lines[j].strip()
            if _VIEW_RE.search(cand):
                continue
            if not _is_desc_label(cand):
                continue
            if cand.upper().rstrip(".,") in _MAKERS or _ASSEMBLY_RE.search(cand):
                continue
            return cand
        return ""

    for i, l in enumerate(lines):
        if not l:
            continue

        # 1) Inline maker/part callout: "<label> PN# 0009508040 X2" / "P/N: 1234".
        m = re.search(
            r"(.*?)\b(?:PN|P/?N)\b\s*[#:]?\s*([A-Za-z0-9][A-Za-z0-9\-/.]{3,})(?:\s*[xX]\s*(\d+))?",
            l,
        )
        if m and _looks_like_partno(m.group(2)):
            label = (m.group(1) or "").strip()
            mk, rest = _split_maker(label)
            # A bare maker name (or nothing) before "PN" → use the context line
            # as the description and keep the maker in its own column.
            if not label or (rest in ("", label) and label.upper() in _MAKERS):
                ctx = _prev_label(i)
                if ctx:
                    add(m.group(2), ctx, m.group(3) or "", maker=mk or None)
                    continue
            add(m.group(2), label, m.group(3) or "")
            continue

        # 2) "Maker#0009520071 [X8]"  (no "PN" keyword).
        m = re.match(r"^([A-Za-z]{2,})#\s*([A-Za-z0-9][A-Za-z0-9\-/.]{3,})(?:\s*[xX]\s*(\d+))?", l)
        if m and _looks_like_partno(m.group(2)):
            maker = m.group(1) if m.group(1).upper() in _MAKERS else ""
            ctx = _prev_label(i)
            add(m.group(2), ctx or maker, m.group(3) or "", maker=maker or None)
            continue

        # 3) Label line ending in "PN", part number on the next non-empty line.
        if re.search(r"\b(?:PN|P/?N)#?:?$", l, re.I):
            label = re.sub(r"\b(?:PN|P/?N)#?:?$", "", l, flags=re.I).strip()
            for j in range(i + 1, min(i + 3, len(lines))):
                if not lines[j]:
                    continue
                first = lines[j].split()[0]
                qm = re.search(r"[xX]\s*(\d+)\b", lines[j])
                if _looks_like_partno(first):
                    add(first, label, qm.group(1) if qm else "")
                break
            continue

        # 4) A standalone dashed part number under a description label, with no
        #    "PN" keyword: "SHRINK TUBING, 3/4\" DIA" / "230-0018-001 X2". Require
        #    an internal hyphen + length so OCR noise ("21.0") can't qualify.
        first = l.split()[0].rstrip(",.;")
        if "-" in first and len(first) >= 7 and _STRUCTURED_PN.match(first) and _looks_like_partno(first):
            ctx = _prev_label(i)
            # Skip if this context line was already used for another part — on a
            # dense OCR'd drawing a stray number near an existing callout would
            # otherwise duplicate that callout's description with a wrong PN.
            already = any(r["Description"].upper() == ctx.upper() for r in rows)
            if ctx and not already and not _ASSEMBLY_RE.search(ctx):
                qm = re.search(r"[xX]\s*(\d+)\b", l)
                add(first, ctx, qm.group(1) if qm else "")
                continue

    # 5) Material / consumable callouts that carry NO part number (heat shrink,
    #    sleeving, labels, ties, tape …). These are real BOM lines the PN rules
    #    skip. Capture the descriptive phrase from the keyword up to where the
    #    next callout (a maker name or a "PN" label) begins on the same line.
    covered = " || ".join(r["Description"].upper() for r in rows)
    for l in lines:
        u = l.upper()
        for kw in _MATERIAL_KW:
            p = u.find(kw)
            if p < 0:
                continue
            if kw in covered:  # already captured alongside its part number
                break
            tail = l[p:]
            cut = _CALLOUT_BREAK.search(tail[len(kw):])
            desc = (tail[: len(kw) + cut.start()] if cut else tail).strip(" -:,.")
            qm = re.search(r"[xX]\s*(\d+)\b", l[p:])
            if len(desc) >= 4 and not _ASSEMBLY_RE.search(desc):
                add("", desc, qm.group(1) if qm else "")
            break

    # Wire table rows: "1  YELLOW  24 AWG  REQUEST" (signal optional).
    for l in lines:
        m = re.match(r"^\d+\s+([A-Z]{3,12})\s+(\d+\s*AWG)\s*(.*)$", l)
        if m:
            sig = m.group(3).strip()
            desc = f"Wire, {m.group(1)}, {m.group(2)}" + (f", {sig}" if sig else "")
            add("", desc, "1")

    return rows


def parse_harness_bom(pdf_path: str, max_pages: int = 4) -> Optional[pd.DataFrame]:
    """Extract a harness/cable BOM from callouts (and a wire table). Uses the
    text layer when present, else OCR. Returns a DataFrame or None."""
    text = _pdf_text(pdf_path, max_pages)
    rows = _parse_callouts(text) if len(text.strip()) >= _MIN_TEXT else []

    if not rows:
        ocr = _ocr_text(pdf_path, max_pages=min(max_pages, 2))
        if ocr.strip():
            rows = _parse_callouts(ocr)

    if len(rows) < 2:
        return None

    for n, r in enumerate(rows, start=1):
        r["Item No."] = str(n)
    return pd.DataFrame(rows, columns=COLUMNS)

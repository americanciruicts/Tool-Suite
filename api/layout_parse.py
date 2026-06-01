"""
Deterministic parser for columnar engineering-drawing parts lists.

Many drawing BOMs (MIL-STD-100 / ASME Y14.34 "LIST OF MATERIALS OR PARTS LIST")
render as fixed-width columns:

    REFERENCE-DESIGNATORS  ITEM  QTY  CAGE  PART-NUMBER  [SMT]  DESCRIPTION  ...  MANUFACTURER

`pdftotext -layout` preserves those columns, so we can parse them directly —
instantly and for free, with no LLM. The CAGE/code-ident token (4–5 alphanumerics
preceded by the item number and quantity) is a reliable anchor for each row.

Returns None if poppler isn't available or no parts rows are found, so callers
fall back to the other extraction paths.
"""

from __future__ import annotations

import re
import subprocess
from typing import Dict, List, Optional

import pandas as pd

COLUMNS = [
    "Item No.", "Reference Designation", "Qty", "CAGE/Code Ident",
    "Part Number", "Description", "Manufacturer",
]

_CAGE = re.compile(r"^[0-9A-Z]{4,5}$")
_REFDES_LINE = re.compile(
    r"^[A-Z]{1,4}\d+[A-Z]?(?:[-,]\d+)*(?:[,\s]+[A-Z]{0,4}\d+[A-Z]?(?:[-,]\d+)*)*[,]?$"
)
# Component-category words that sit between description and manufacturer in the
# layout — they must not be mistaken for the manufacturer.
_CATEGORIES = {
    "RESISTOR", "CAPACITOR", "IC", "DIODE", "LED", "TRANSISTOR", "MOSFET",
    "CONNECTOR", "INDUCTOR", "CRYSTAL", "OSCILLATOR", "SWITCH", "FUSE", "RELAY",
    "FERRITE", "PWB", "PCB", "HARDWARE", "LABEL", "SOCKET", "TRANSCEIVER",
    "REGULATOR", "SENSOR", "FILTER", "JUMPER", "HEADER", "MEMORY",
}


def _looks_like_partno(tok: str) -> bool:
    """A real part number is a single token (no spaces/commas) of decent length."""
    return bool(tok) and " " not in tok and "," not in tok and len(tok) >= 3


def _layout_text(pdf_path: str, max_pages: int) -> str:
    return subprocess.run(
        ["pdftotext", "-layout", "-f", "1", "-l", str(max_pages), pdf_path, "-"],
        capture_output=True, text=True, timeout=90,
    ).stdout or ""


def parse_bom_from_layout(pdf_path: str, max_pages: int = 6) -> Optional[pd.DataFrame]:
    try:
        text = _layout_text(pdf_path, max_pages)
    except Exception:
        return None
    if not text.strip():
        return None

    rows: List[Dict[str, str]] = []
    pending_refdes = ""
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        toks = re.split(r"\s{2,}", s)

        # Find the CAGE anchor: a 4-5 char token preceded by item# and qty (ints).
        c = None
        for i in range(2, len(toks)):
            if _CAGE.match(toks[i]) and toks[i - 1].isdigit() and toks[i - 2].isdigit():
                c = i
                break

        if c is None or c + 1 >= len(toks):
            # A wrapped reference-designator line just above a row with no leading
            # designators (kept to one line — accumulating across lines mis-attributes
            # designators to the wrong row without coordinate info).
            if _REFDES_LINE.match(s):
                pending_refdes = s.rstrip(",")
            continue

        item, qty, cage = toks[c - 2], toks[c - 1], toks[c]
        partno = toks[c + 1]
        rem = toks[c + 2:]

        # If the "part number" token has spaces/commas, the part-number column
        # was blank and this is really the description shifted left by one.
        if not _looks_like_partno(partno):
            rem = [partno] + rem
            partno = ""

        # Reference designators: this row's own leading tokens (minus a stray
        # drawing-zone letter); else the single wrapped line just above it.
        if c - 2 >= 1:
            refdes = re.sub(r"^[A-Z]\s+", "", " ".join(toks[: c - 2]).rstrip(","))
        else:
            refdes = pending_refdes
        pending_refdes = ""

        if rem and rem[0].isdigit() and len(rem[0]) <= 2:  # drop SMT/layer code
            rem = rem[1:]
        desc = rem[0] if rem else ""
        # Manufacturer = last token that isn't a category word (maker names are
        # often truncated by the column width, but better than a category).
        mfr = ""
        for tok in reversed(rem[1:]):
            if tok.upper() in _CATEGORIES:
                continue
            if tok.isdigit() and len(tok) <= 2:   # trailing SMT/layer digit
                continue
            mfr = tok
            break

        # Keep the row if it has a part number or a description.
        if not (partno or desc):
            continue

        rows.append({
            "Item No.": item,
            "Reference Designation": refdes,
            "Qty": qty,
            "CAGE/Code Ident": cage,
            "Part Number": partno,
            "Description": desc,
            "Manufacturer": mfr,
        })

    if len(rows) < 2:
        return None

    seen = set()
    out: List[Dict[str, str]] = []
    for r in rows:
        key = (r["Item No."], r["Part Number"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)

    # Sort by item number ascending (parts lists print in descending order).
    def _item_key(r):
        v = str(r["Item No."]).strip()
        return (0, int(v)) if v.isdigit() else (1, 0)
    out.sort(key=_item_key)

    return pd.DataFrame(out, columns=COLUMNS)

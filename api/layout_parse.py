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


# Header/title words that must never be mistaken for data.
_STOP = {
    "REFERENCE", "DESIGNATION", "ITEM", "QTY", "CODE", "IDENT", "PART", "OR",
    "NOMENCLATURE", "IDENTIFYING", "NO.", "DESCRIPTION", "MANUFACTURER",
    "SPECIFICATION/", "MATERIAL", "LIST", "OF", "MATERIALS", "PARTS",
    "REVISIONS", "ZONE", "LTR", "APPROVED", "REV", "DATE(YR-MO-", "DATE(YEAR-MO-DA)",
    "NO", "DWG", "SEE", "SHEET", "NOTE", "NOTES", "CONT", "CONT.", "USED", "ON",
}
_DESG = re.compile(r"^[A-Z]{1,4}\d")


def _detect_tables(words):
    """Find parts-list table headers and return each table's column x positions.
    Handles the two side-by-side sub-tables on MIL-STD/ASME drawings."""
    from collections import defaultdict
    rowsby = defaultdict(list)
    for w in words:
        if w["text"].upper() in ("DESIGNATION", "NO.", "REQD", "IDENT",
                                  "IDENTIFYING", "DESCRIPTION", "MANUFACTURER"):
            rowsby[round(w["top"] / 8)].append(w)
    tabs = []
    for grp in rowsby.values():
        up = {w["text"].upper() for w in grp}
        if "DESIGNATION" in up and "MANUFACTURER" in up:
            def gx(name):
                return [w for w in grp if w["text"].upper() == name][0]["x0"]
            des, reqd, ident, idno, desc, man = (
                gx("DESIGNATION"), gx("REQD"), gx("IDENT"),
                gx("IDENTIFYING"), gx("DESCRIPTION"), gx("MANUFACTURER"))
            nos = [w["x0"] for w in grp if w["text"].upper() == "NO." and des < w["x0"] < reqd]
            tabs.append({
                "refdes": des, "item": nos[0] if nos else (des + reqd) / 2,
                "qty": reqd, "cage": ident, "partno": idno, "desc": desc, "mfr": man,
                "top": [w for w in grp if w["text"].upper() == "DESIGNATION"][0]["top"],
            })
    return tabs


def parse_bom_coords(pdf_path: str, max_pages: int = 8) -> Optional[pd.DataFrame]:
    """
    Coordinate-based parser for columnar drawing parts lists. Uses each word's
    x/y position to assign it to a column and to the nearest item row — which
    correctly reassembles wide cells that wrap across lines (long reference-
    designator lists, full manufacturer names). Handles inverted tables (header
    at the bottom, rows above it).
    """
    try:
        import pdfplumber
        from collections import defaultdict
    except Exception:
        return None

    out: List[Dict[str, str]] = []
    try:
        pdf = pdfplumber.open(pdf_path)
    except Exception:
        return None
    with pdf:
        for page in pdf.pages[:max_pages]:
            try:
                words = page.extract_words(keep_blank_chars=False)
            except Exception:
                continue
            if not words:
                continue
            for t in _detect_tables(words):
                cols = ["refdes", "item", "qty", "cage", "partno", "desc", "mfr"]
                xs = [t[c] for c in cols]
                edges = [(xs[i] + xs[i + 1]) / 2 for i in range(len(xs) - 1)]

                def colof(w):
                    cx = (w["x0"] + w["x1"]) / 2
                    if cx < t["refdes"] - 80:
                        return None
                    for i, e in enumerate(edges):
                        if cx < e:
                            return cols[i]
                    return "mfr" if cx < t["mfr"] + 220 else None

                # Data rows are above the header on these inverted tables.
                body = [w for w in words
                        if w["top"] < t["top"] - 6 and colof(w) and w["text"].upper() not in _STOP]
                bytop = defaultdict(list)
                for w in body:
                    bytop[round(w["top"] / 6)].append(w)

                anchors = []
                for line in bytop.values():
                    items = [w for w in line if w["text"].isdigit() and colof(w) == "item" and len(w["text"]) <= 3]
                    cages = [w for w in line if _CAGE.match(w["text"]) and colof(w) == "cage"]
                    if items and cages:
                        qtys = [w for w in line if w["text"].isdigit() and colof(w) == "qty"]
                        pns = [w for w in line if colof(w) == "partno" and w["text"].upper() not in _STOP]
                        anchors.append({
                            "item": items[0]["text"], "top": items[0]["top"],
                            "qty": qtys[0]["text"] if qtys else "",
                            "cage": cages[0]["text"],
                            "partno": " ".join(w["text"] for w in sorted(pns, key=lambda w: w["x0"])),
                        })
                if not anchors:
                    continue
                anchors.sort(key=lambda a: a["top"])
                atops = [a["top"] for a in anchors]
                lo = min(atops) - 40
                cells = [defaultdict(list) for _ in anchors]
                for w in body:
                    if not (lo <= w["top"] <= t["top"]):
                        continue
                    col = colof(w)
                    # Assign part-number by nearest row too — on the two-table
                    # layout a row's part number can sit a hair off the item line.
                    if col in ("refdes", "desc", "mfr", "partno"):
                        i = min(range(len(atops)), key=lambda k: abs(atops[k] - w["top"]))
                        cells[i][col].append(w)

                for a, cell in zip(anchors, cells):
                    def txt(col):
                        return [w["text"] for w in sorted(cell[col], key=lambda w: (w["top"], w["x0"]))]
                    refdes = " ".join(x for x in txt("refdes") if _DESG.match(x) or "," in x or "-" in x)
                    desc = " ".join(txt("desc"))
                    mfr = " ".join(x for x in txt("mfr")
                                   if x.upper() not in _CATEGORIES and not x.isdigit()
                                   and len(x) > 1 and x.upper() not in _STOP)
                    # Part number: drop bare SMT/layer digits and header words.
                    partno = " ".join(x for x in txt("partno")
                                      if x.upper() not in _STOP and not (x.isdigit() and len(x) <= 2))
                    if not partno:
                        partno = a["partno"]
                    if partno or desc:
                        out.append({
                            "Item No.": a["item"], "Reference Designation": refdes,
                            "Qty": a["qty"], "CAGE/Code Ident": a["cage"],
                            "Part Number": partno, "Description": desc, "Manufacturer": mfr,
                        })

    if len(out) < 2:
        return None
    seen = set()
    rows = []
    for r in out:
        key = (r["Item No."], r["Part Number"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(r)
    rows.sort(key=lambda r: int(r["Item No."]) if str(r["Item No."]).isdigit() else 9999)
    return pd.DataFrame(rows, columns=COLUMNS)


def parse_bom(pdf_path: str, max_pages: int = 8) -> Optional[pd.DataFrame]:
    """Best columnar BOM parse: coordinate-based first (reassembles wrapped
    cells / full manufacturer names), then the text-layout parser as fallback."""
    try:
        df = parse_bom_coords(pdf_path, max_pages)
        if df is not None and len(df) >= 2:
            return df
    except Exception:
        pass
    return parse_bom_from_layout(pdf_path, max_pages)


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

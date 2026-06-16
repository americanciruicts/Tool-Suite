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


# ---------------------------------------------------------------------------
# Generic parts-list table parser (non-CAGE drawings).
#
# Many drawing BOMs are NOT MIL-STD/ASME CAGE tables — they're a plain
#   ITEM NO. | PART NUMBER | DESCRIPTION | QTY.
# table dropped into the corner of the drawing (e.g. WheelRight, SolidWorks
# default BOMs). The two parsers above key off a CAGE code, so they miss these.
# This parser instead:
#   1) finds the header row by BOM keywords and reads its column x-extents,
#   2) anchors each data row on the item-number column's running sequence
#      (1, 2, 3 …) — robust against drawing notes that share a y with a row,
#   3) bounds the table region (header keywords on the left, item sequence at
#      the top/bottom, a title-block keyword as the hard floor) so surrounding
#      drawing text and the title block don't leak into cells,
#   4) reassembles word coordinates into cells, keeping the part number that
#      sits in the item column's whitespace with the row's part-number cell.
# Returns the raw table with the drawing's own headers; the caller maps it to
# the BOM/quote schema.
# ---------------------------------------------------------------------------

# Header tokens that mark a parts-list header row.
_GH_HEAD = {
    "item", "no", "part", "parts", "number", "p/n", "pn", "mpn", "description",
    "desc", "qty", "quantity", "req", "reqd", "manufacturer", "mfg", "mfr",
    "ref", "reference", "designator", "designation", "cage", "value", "val",
    "rev", "uom", "comments", "notes",
}
# A real BOM header has words from at least two of these groups.
_GH_ANCHOR = [
    {"part", "number", "p/n", "pn", "mpn"},
    {"description", "desc"},
    {"qty", "quantity", "req", "reqd"},
    {"item", "no"},
]
# First word of a title-block phrase — acts as the table's hard bottom floor.
_GH_STOP = {
    "UNLESS", "TOLERANCES", "DEBUR", "DEBURR", "DIMENSIONS", "PROPRIETARY",
    "CONFIDENTIAL", "FINISH", "MATERIAL:", "DO",
}


def _gh_norm(t: str) -> str:
    return t.lower().strip().rstrip(".:")


def _gh_find_header(words) -> Optional[tuple]:
    """Return (header_bottom_y, [column dicts]) for the best BOM header row, or
    None. Each column dict has name + x0/x1 and lo/hi assignment boundaries."""
    from collections import defaultdict

    lines = defaultdict(list)
    for w in words:
        lines[round(w["top"] / 4)].append(w)

    best = None
    for y in sorted(lines):
        grp = lines[y]
        toks = {_gh_norm(w["text"]) for w in grp}
        hits = sum(1 for a in _GH_ANCHOR if toks & a)
        kw = sum(1 for w in grp if _gh_norm(w["text"]) in _GH_HEAD)
        if hits >= 2 and kw >= 2 and (best is None or (hits, kw) > best[0]):
            best = ((hits, kw), y, grp)
    if not best:
        return None

    _, _, grp = best
    hy = grp[0]["top"]
    # Header labels can wrap (ITEM / NO.); pull the whole 16pt band's keywords.
    band = [w for w in words if abs(w["top"] - hy) < 16 and _gh_norm(w["text"]) in _GH_HEAD]
    if not band:
        return None

    # Cluster header words into columns by x gap.
    cols_raw: List[list] = []
    cur: list = []
    last = None
    for w in sorted(band, key=lambda w: w["x0"]):
        if last is not None and w["x0"] - last > 22 and cur:
            cols_raw.append(cur)
            cur = []
        cur.append(w)
        last = w["x1"]
    if cur:
        cols_raw.append(cur)

    cols = []
    for c in cols_raw:
        c = sorted(c, key=lambda w: (w["top"], w["x0"]))
        cols.append({
            "name": " ".join(w["text"] for w in c),
            "x0": min(w["x0"] for w in c),
            "x1": max(w["x1"] for w in c),
        })
    if len(cols) < 2:
        return None

    for i, c in enumerate(cols):
        c["lo"] = c["x0"] - 18 if i == 0 else (cols[i - 1]["x1"] + c["x0"]) / 2
        c["hi"] = c["x1"] + 45 if i == len(cols) - 1 else (c["x1"] + cols[i + 1]["x0"]) / 2
    return max(w["bottom"] for w in band), cols


def parse_generic_table(pdf_path: str, max_pages: int = 8) -> Optional[pd.DataFrame]:
    """Parse a plain item/part/description/qty parts-list table embedded in a
    drawing, anchored on the item-number column. Returns the table with the
    drawing's own column names, or None if no such table is found."""
    try:
        import pdfplumber
        from collections import defaultdict
    except Exception:
        return None
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
            hdr = _gh_find_header(words)
            if not hdr:
                continue
            header_bottom, cols = hdr

            item_idx = next(
                (i for i, c in enumerate(cols) if re.search(r"item|^no", c["name"].lower())), 0
            )
            qty_idx = next(
                (i for i, c in enumerate(cols) if re.search(r"qty|quantity|req", c["name"].lower())), None
            )
            itc = cols[item_idx]
            lo, hi = cols[0]["lo"], cols[-1]["hi"]

            body = [w for w in words
                    if w["top"] > header_bottom + 1 and lo <= (w["x0"] + w["x1"]) / 2 <= hi]

            # Item anchors: digits in the item column forming the run 1, 2, 3 …
            cand = [w for w in body
                    if w["text"].isdigit()
                    and itc["lo"] <= (w["x0"] + w["x1"]) / 2 < itc["hi"]
                    and int(w["text"]) < 999]
            cand.sort(key=lambda w: w["top"])
            anchors = []
            nxt = 1
            for w in cand:
                if int(w["text"]) == nxt:
                    anchors.append(w)
                    nxt += 1
            if len(anchors) < 3:
                continue

            tops = [a["top"] for a in anchors]
            gaps = sorted(tops[i + 1] - tops[i] for i in range(len(tops) - 1))
            med = gaps[len(gaps) // 2] if gaps else 20
            ylo = tops[0] - 6
            yhi = tops[-1] + min(med * 1.4, 30)
            # A title-block keyword below the first row is the hard bottom floor.
            stop_tops = [w["top"] for w in body
                         if w["text"].upper().rstrip(".:") in _GH_STOP and w["top"] > tops[0] - 2]
            if stop_tops:
                yhi = min(yhi, min(stop_tops) - 2)

            cells = [defaultdict(list) for _ in anchors]
            for w in body:
                if not (ylo <= w["top"] <= yhi):
                    continue
                cx = (w["x0"] + w["x1"]) / 2
                ci = next((j for j, c in enumerate(cols) if c["lo"] <= cx < c["hi"]), None)
                if ci is None:
                    continue
                k = min(range(len(tops)), key=lambda i: abs(tops[i] - w["top"]))
                cells[k][ci].append(w)

            rows: List[Dict[str, str]] = []
            for a, cell in zip(anchors, cells):
                vals = [sorted(cell[j], key=lambda w: (round(w["top"] / 6), w["x0"]))
                        for j in range(len(cols))]
                # Words left in the item column besides the anchor digit are the
                # row's part number (it starts in the item column's whitespace).
                leftover = [w for w in vals[item_idx]
                            if not (w["text"] == a["text"]
                                    and abs(w["top"] - a["top"]) < 3
                                    and abs(w["x0"] - a["x0"]) < 3)]
                row: Dict[str, str] = {}
                for j, c in enumerate(cols):
                    if j == item_idx:
                        row[c["name"]] = a["text"]
                        continue
                    lst = vals[j]
                    if j == item_idx + 1 and leftover:
                        lst = sorted(leftover + lst, key=lambda w: (round(w["top"] / 6), w["x0"]))
                    row[c["name"]] = " ".join(w["text"] for w in lst)
                if qty_idx is not None:
                    m = re.search(r"\d+(?:\.\d+)?", row[cols[qty_idx]["name"]])
                    if m:
                        row[cols[qty_idx]["name"]] = m.group(0)
                rows.append(row)

            if len(rows) >= 3:
                return pd.DataFrame(rows, columns=[c["name"] for c in cols])
    return None


# ---------------------------------------------------------------------------
# Wide text-layer BOM table parser (PCB / "Part Information" exports).
#
# Electronics BOM exports (Altium, WiTricity "Part Information", etc.) are wide
# tables — Designator | Part Number | Description | Manufacturer | Package | … —
# often 15-20 columns and hundreds of rows, with NO gridlines and NO item-number
# column (rows are keyed by reference designator). The grid detector and the
# item-anchored parser both miss them. `pdftotext -layout` preserves the column
# alignment, so we read the header line's column character-offsets and slice each
# data row by them. Maps cleanly downstream (Part Number→MPN, Description, etc.).
# ---------------------------------------------------------------------------

# Header keywords that mark a wide BOM table header line.
_WIDE_HEAD = {
    "designator", "designators", "refdes", "ref des", "reference",
    "part number", "part no", "part #", "p/n", "mpn", "manufacturer part",
    "description", "desc", "manufacturer", "mfg", "mfr", "qty", "quantity",
    "value", "package", "footprint", "comment", "comments", "rohs", "item",
    "customer", "vendor", "supplier", "tolerance", "voltage",
}
# Header must contain a part-number-ish column to be a real BOM.
_WIDE_PN = ("part number", "part no", "part #", "p/n", "mpn", "manufacturer part")


# Known column names that may be glued to a neighbour by a single space in the
# header (e.g. "ITEM NO. PART NUMBER", "QTY. UOM") — used to split them apart.
_SPLIT_AT = [
    "manufacturer part number", "part number", "part no", "mpn", "p/n",
    "description", "manufacturer", "quantity", "qty", "uom", "value", "package",
    "footprint", "comment", "designator", "customer", "vendor", "supplier",
]
# Column names that begin the drawing's revisions / title block, not the BOM —
# the BOM table ends here (these tables sit side-by-side on many drawings).
_TRUNCATE_AT = {
    "rev", "rev.", "revision", "revisions", "ltr", "zone", "author", "eco",
    "approved", "appvd", "drawn", "checked", "sheet", "by",
}


def _wide_columns(header: str) -> List[tuple]:
    """Column (start_offset, name) pairs from a layout header line — each token
    group separated by 2+ spaces is one column. Merged column names glued by a
    single space ("ITEM NO. PART NUMBER") are split at the inner column keyword;
    columns from an adjacent revisions/title block are dropped once the BOM
    columns (a part number + description) have been seen."""
    raw = []
    for m in re.finditer(r"\S(?:.*?\S)?(?=\s{2,}|$)", header):
        name = m.group().strip()
        if name:
            raw.append((m.start(), name))

    # Split a glued "<colA> <colB>" token at the inner keyword's offset.
    cols: List[tuple] = []
    for start, name in raw:
        low = name.lower()
        cut = None
        for kw in _SPLIT_AT:
            i = low.find(kw)
            if i > 0 and low[i - 1] == " ":  # keyword starts mid-token
                if cut is None or i < cut:
                    cut = i
        if cut is not None:
            cols.append((start, name[:cut].strip()))
            cols.append((start + cut, name[cut:].strip()))
        else:
            cols.append((start, name))

    # Truncate at the revisions/title block once we have a real BOM (PN + desc).
    have_pn = False
    have_desc = False
    for idx, (start, name) in enumerate(cols):
        low = name.lower().strip()
        if any(p in low for p in _WIDE_PN):
            have_pn = True
        if "desc" in low:
            have_desc = True
        if idx > 0 and low.rstrip(".") in _TRUNCATE_AT and have_pn and have_desc:
            return cols[:idx] + [(start, "__END__")]  # sentinel marks right edge
    return cols


def _wide_data_starts(lines: List[str], right_edge: int) -> List[int]:
    """Column start offsets derived from the data rows' whitespace: a column
    begins at a non-space position preceded by a >=2-wide run of positions that
    are blank in (almost) every row. Description-internal spaces don't qualify
    (they aren't blank across all rows), so wide text cells stay intact."""
    if not lines:
        return []
    width = min(max(len(l) for l in lines), right_edge)
    n = len(lines)
    gap = []
    for i in range(width):
        blank = sum(1 for l in lines if i >= len(l) or l[i] == " ")
        gap.append(blank >= n - 1)
    starts = []
    for i in range(width):
        if gap[i]:
            continue
        if i == 0 or (gap[i - 1] and (i < 2 or gap[i - 2])):
            starts.append(i)
    return starts


def parse_wide_text_table(pdf_path: str, max_pages: int = 6) -> Optional[pd.DataFrame]:
    """Parse a wide, gridless text-layer BOM table. Column edges come from the
    data's whitespace; column names come from the header tokens above them.
    Returns the table with its own headers, or None."""
    try:
        text = _layout_text(pdf_path, max_pages)
    except Exception:
        return None
    if not text.strip():
        return None
    lines = text.splitlines()

    # Find the header: a line with >=3 BOM keywords incl. a part-number column.
    header_idx = None
    best = -1
    for idx, l in enumerate(lines[:80]):
        low = l.lower()
        hits = sum(1 for k in _WIDE_HEAD if k in low)
        if hits >= 3 and any(p in low for p in _WIDE_PN) and hits > best:
            best, header_idx = hits, idx
    if header_idx is None:
        return None

    header_cols = _wide_columns(lines[header_idx])
    # A trailing "__END__" sentinel marks where an adjacent revisions/title block
    # begins: keep its offset as the BOM's right edge but drop it as a column.
    right_edge = 10 ** 6
    if header_cols and header_cols[-1][1] == "__END__":
        right_edge = header_cols[-1][0]
        header_cols = header_cols[:-1]
    if len(header_cols) < 3:
        return None

    # Column boundaries from the DATA's whitespace "rivers", not the header —
    # headers are often centred over wide columns, so slicing by header offsets
    # bleeds a long description's left edge into the part-number column. Data
    # rows are fixed-width, so the gaps that are blank across (almost) every row
    # are the true column edges.
    data_lines = [l for l in lines[header_idx + 1: header_idx + 60]
                  if l.strip() and l[:right_edge if right_edge < 10**6 else len(l)].strip()][:30]
    starts = _wide_data_starts(data_lines, right_edge)
    if len(starts) < 3:
        # Fall back to header offsets if data-based detection found too few.
        starts = [c[0] for c in header_cols]
    # Drop spurious columns from drawing-zone letters (A–H) in the far-left
    # margin, left of the table's first header token.
    first_h = header_cols[0][0] if header_cols else 0
    starts = [s for s in starts if first_h - 2 <= s < right_edge]
    if len(starts) < 3:
        return None
    bounds = starts + [right_edge]

    # Name each data column from the header token nearest its start — one token
    # to one column, so an over-split data column gets "Column N" rather than
    # duplicating a real header (which would break downstream mapping).
    names: List[Optional[str]] = [None] * len(starts)
    for hs, nm in header_cols:
        j = min(range(len(starts)), key=lambda k: abs(starts[k] - hs))
        if names[j] is None:
            names[j] = nm
    names = [n if n else f"Column {i + 1}" for i, n in enumerate(names)]

    # The part-number column anchors a real data row — notes/title text below the
    # table won't have a part-number-like value there.
    pn_idx = next(
        (i for i, n in enumerate(names) if any(p in n.lower() for p in _WIDE_PN)),
        None,
    )
    _PN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/.]{3,}$")

    def _valid_row(vals: List[str]) -> bool:
        if pn_idx is not None and pn_idx < len(vals):
            tok = vals[pn_idx].strip().split(" ")[0] if vals[pn_idx].strip() else ""
            return bool(tok) and any(c.isdigit() for c in tok) and bool(_PN_RE.match(tok))
        # No identifiable PN column → fall back to "some part-number-ish cell".
        for v in vals[: min(5, len(vals))]:
            s = v.strip()
            if len(s) >= 4 and any(c.isalpha() for c in s) and any(c.isdigit() for c in s):
                return True
        return False

    rows: List[List[str]] = []
    for l in lines[header_idx + 1:]:
        if not l.strip():
            continue
        low = l.lower()
        # Skip a repeated header or page furniture.
        if sum(1 for k in _WIDE_HEAD if k in low) >= 4:
            continue
        vals = [l[bounds[i]:bounds[i + 1]].strip() for i in range(len(starts))]
        if _valid_row(vals):
            rows.append(vals)

    if len(rows) < 5:
        return None

    # De-duplicate blank/repeated column names so the DataFrame is well-formed.
    seen: Dict[str, int] = {}
    uniq: List[str] = []
    for i, n in enumerate(names):
        n = n or f"Column {i + 1}"
        seen[n] = seen.get(n, 0) + 1
        uniq.append(n if seen[n] == 1 else f"{n} ({seen[n]})")
    return pd.DataFrame(rows, columns=uniq)


# ---------------------------------------------------------------------------
# Coordinate-space columnar BOM parser (report-style gridless tables).
#
# The most common gridless BOMs (ERP "single level BOM report" exports,
# Agile/Arena BOM exports, PCB part-info lists) are fixed-width columnar tables
# with NO gridlines and a clear header row. pdfplumber.extract_tables() finds
# nothing (no lines); the old char-offset text slicer mangled them because it
# sliced the *reflowed* extract_text() output at the *header label's* character
# positions, cutting every word mid-character.
#
# This parser works in coordinate space instead:
#   1) find the header row (the line richest in BOM-column keywords),
#   2) detect each column's LEFT EDGE from the data — a column begins where word
#      coverage resumes after a >=2pt run that is blank across (nearly) every
#      row. Detecting left edges (not gap midpoints) keeps a variable-width
#      cell's trailing words in their own column (a long manufacturer name whose
#      last word lands in a mostly-blank zone stays in the manufacturer column
#      instead of leaking into the next), which was the core misalignment bug,
#   3) assign each data word to a column by its left edge,
#   4) anchor rows on the item column and merge continuation lines (alternate
#      manufacturers / wrapped descriptions) into their row,
#   5) name columns from the header tokens above them.
# Returns the table with the drawing's own headers; the caller maps it to schema.
# ---------------------------------------------------------------------------

_CC_HEAD = {
    "item", "no", "no.", "part", "parts", "number", "num", "p/n", "pn", "mpn",
    "description", "desc", "qty", "quantity", "req", "reqd", "required",
    "manufacturer", "mfg", "mfr", "ref", "reference", "designator",
    "designation", "designators", "cage", "value", "val", "rev", "revision",
    "uom", "comments", "notes", "model", "bom", "cost", "assy", "per",
    "lifecycle", "phase", "distributor", "vendor", "supplier", "package",
    "footprint", "rohs", "customer", "location", "loc", "st", "std", "pkg",
    "chan", "change", "type",
}
_CC_ANCHOR = [
    {"part", "number", "p/n", "pn", "mpn", "num"},
    {"description", "desc"},
    {"qty", "quantity", "req", "reqd", "required", "per"},
    {"item", "no", "no."},
    {"manufacturer", "mfg", "mfr"},
]
_CC_STOPLINE = re.compile(
    r"unless|tolerance|proprietary|confidential|^\s*notes?:|drawn by|approved by|copyright",
    re.I,
)
_CC_DASHRUN = re.compile(r"[-]{8,}")
# A "placeholder/marker" word that carries no BOM data: a lone dash (the report's
# "ditto / not-applicable" filler on alternate-manufacturer continuation lines),
# any dash variant, or a selection/check glyph (e.g. the caron "ˇ" prepended to
# each primary row). These are dropped when assembling a cell so they never bleed
# a stray "-" into Item Number / Revision / Quantity etc.
_CC_JUNK_WORD = re.compile(r"^[-–—‐‑·•◦▪▫□☐■✓✔ˇˆ˜|¦]{1,3}$")


def _cc_norm(t: str) -> str:
    return t.lower().strip().rstrip(".:")


def _cc_find_header(words):
    """Return (header_band_words, header_bottom_y) for the richest BOM header
    line, or None. Skips title-block / document-header lines by requiring words
    from >=2 BOM anchor groups and >=3 header keywords on the line."""
    from collections import defaultdict
    lines = defaultdict(list)
    for w in words:
        lines[round(w["top"] / 3)].append(w)
    best = None
    for y in sorted(lines):
        grp = lines[y]
        toks = {_cc_norm(w["text"]) for w in grp}
        hits = sum(1 for a in _CC_ANCHOR if toks & a)
        kw = sum(1 for w in grp if _cc_norm(w["text"]) in _CC_HEAD)
        if hits >= 2 and kw >= 3 and len(grp) >= 3:
            score = (hits, kw)
            if best is None or score > best[0]:
                best = (score, y, grp)
    if not best:
        return None
    _, _, grp = best
    hy = min(w["top"] for w in grp)
    # Header labels can wrap (QTY / PER ASSY): pull the whole band's keywords.
    band = [w for w in words
            if hy - 2 <= w["top"] <= hy + 18 and _cc_norm(w["text"]) in _CC_HEAD]
    if not band:
        return None
    return band, max(w["bottom"] for w in band)


def _cc_column_starts(lines, x_lo, x_hi):
    """Column left edges in coordinate space. occ[i] = #rows covering bin i; a
    bin is blank if covered in <=~12% of rows; a column starts at a non-blank
    bin preceded by >=2 blank bins (or the left edge)."""
    import math
    rows = [l for l in lines if len(l) >= 2]
    n = len(rows)
    if n < 2:
        return None
    lo = int(x_lo)
    hi = int(x_hi) + 1
    W = hi - lo
    if W <= 1:
        return None
    occ = [0] * W
    for row in rows:
        covered = [False] * W
        for w in row:
            a = max(lo, int(w["x0"]))
            b = min(hi, int(w["x1"]) + 1)
            for i in range(a - lo, b - lo):
                if 0 <= i < W:
                    covered[i] = True
        for i in range(W):
            if covered[i]:
                occ[i] += 1
    tol = max(0, math.ceil(n * 0.12))
    blank = [occ[i] <= tol for i in range(W)]
    starts = []
    for i in range(W):
        if blank[i]:
            continue
        if i == 0 or (blank[i - 1] and (i < 2 or blank[i - 2])):
            starts.append(lo + i)
    if not starts:
        return None
    return sorted(set(starts)) + [hi]


def _cc_name_columns(cuts, band):
    names = []
    for k in range(len(cuts) - 1):
        a, b = cuts[k], cuts[k + 1]
        toks = [w for w in band if a <= (w["x0"] + w["x1"]) / 2 < b]
        toks.sort(key=lambda w: (round(w["top"] / 4), w["x0"]))
        nm = " ".join(w["text"] for w in toks).strip()
        names.append(nm if nm else f"Column {k + 1}")
    return names


def parse_columnar_coords(pdf_path: str, max_pages: int = 8) -> Optional[pd.DataFrame]:
    """Parse a gridless, fixed-width columnar BOM from word coordinates. Returns
    the table with the drawing's own headers, or None if no such table is found
    (so callers fall through to the other parsers)."""
    try:
        import pdfplumber
        from collections import defaultdict
    except Exception:
        return None
    try:
        pdf = pdfplumber.open(pdf_path)
    except Exception:
        return None

    # Pass 1: collect every qualifying page's table region (header band + data
    # lines). A multi-page report BOM repeats its header on every page; we parse
    # them as ONE table using a single column layout (below) so continuation
    # pages align to the same columns instead of being silently dropped — the old
    # code returned the first page only, losing pages 2..N of a multi-page BOM.
    pages_data: List[Dict] = []
    with pdf:
        for page in pdf.pages[:max_pages]:
            try:
                words = page.extract_words()
            except Exception:
                continue
            if not words:
                continue
            hdr = _cc_find_header(words)
            if not hdr:
                continue
            band, header_bottom = hdr
            x_lo = min(w["x0"] for w in band) - 6
            x_hi = max(w["x1"] for w in band) + 30
            body = [w for w in words
                    if w["top"] > header_bottom + 1
                    and x_lo - 30 <= (w["x0"] + w["x1"]) / 2 <= x_hi + 30]
            if not body:
                continue

            lines_map = defaultdict(list)
            for w in body:
                lines_map[round(w["top"] / 4)].append(w)
            ylines = []
            for y in sorted(lines_map):
                ln = sorted(lines_map[y], key=lambda w: w["x0"])
                # A title-block / notes keyword ends the table region.
                if _CC_STOPLINE.search(" ".join(w["text"] for w in ln)):
                    break
                ylines.append(ln)
            if len(ylines) < 3:
                continue
            pages_data.append({"band": band, "x_lo": x_lo, "x_hi": x_hi,
                               "ylines": ylines})

    if not pages_data:
        return None

    # Detect the column layout ONCE, from the first page (the table's reference
    # layout — its full-width descriptions keep the maker and part-number columns
    # apart), and reuse it for every page so columns line up consistently across
    # pages instead of each continuation page re-deriving its own edges.
    primary = pages_data[0]
    cuts = _cc_column_starts(primary["ylines"], primary["x_lo"], primary["x_hi"])
    if not cuts or len(cuts) < 3:
        return None
    names = _cc_name_columns(cuts, primary["band"])
    ncol = len(names)

    def colof(w):
        cx = w["x0"] + 1
        if cx < cuts[0]:
            return 0
        for i in range(len(cuts) - 1):
            if cuts[i] <= cx < cuts[i + 1]:
                return i
        return ncol - 1

    # The item/anchor column defines row boundaries: a column whose header
    # names item/line/no — NOT 'Part Number'/'Mfg Part Num' (those are the
    # MPN). Matching 'part' anchored rows on the MPN, so a line item with a
    # blank MPN (e.g. a PWB sub-assembly) merged into the row above it.
    # Fall back to the leftmost column, which carries the line's item no.
    item_idx = next(
        (i for i, nm in enumerate(names)
         if re.search(r"\bitem\b|\bline\b|^no\.?$", nm.lower())), 0)

    # Pass 2: build rows across ALL pages with the shared column layout. Lines
    # stream in page order, so an alternate-manufacturer continuation that spills
    # onto the next page still merges into its item row.
    rows: List[List[str]] = []
    for d in pages_data:
        for ln in d["ylines"]:
            cells = ["" for _ in range(ncol)]
            for w in sorted(ln, key=lambda w: w["x0"]):
                ci = colof(w)
                if ci is None:
                    continue
                if _CC_JUNK_WORD.match(w["text"]):
                    continue  # drop dash placeholders / row-marker glyphs
                cells[ci] = (cells[ci] + " " + w["text"]).strip()
            itemval = cells[item_idx].strip()
            is_anchor = (bool(itemval) and bool(re.search(r"[0-9]", itemval))
                         and len(itemval.split()) <= 2)
            nonempty = sum(1 for c in cells if c.strip())
            if is_anchor or not rows:
                if nonempty >= 2:
                    rows.append(cells)
            else:
                prev = rows[-1]
                for i in range(ncol):
                    if cells[i].strip():
                        prev[i] = ((prev[i] + " " + cells[i]).strip()
                                   if prev[i].strip() else cells[i])

    # --- column post-processing -----------------------------------------
    # Merge interior unnamed ("Column N") columns into the previous real
    # column (a narrow data river inside one logical cell).
    def _unnamed(nm):
        return bool(re.match(r"Column \d+$", nm))
    merged_names: List[str] = []
    keep_map: List[List[int]] = []
    for j, nm in enumerate(names):
        if _unnamed(nm) and merged_names:
            keep_map[-1].append(j)
        else:
            merged_names.append(nm)
            keep_map.append([j])

    def _join(cells, idxs):
        return " ".join(cells[k] for k in idxs if cells[k].strip()).strip()
    rows = [[_join(r, idxs) for idxs in keep_map] for r in rows]
    names = merged_names
    # Drop columns empty across all rows.
    nz = [any(r[c].strip() for r in rows) for c in range(len(names))]
    names = [names[c] for c in range(len(names)) if nz[c]]
    rows = [[r[c] for c in range(len(nz)) if nz[c]] for r in rows]
    if len(names) < 2:
        return None
    # Order-preserving token dedup per cell (collapses alt-source repeats
    # merged from continuation lines, e.g. "AUSTRIA AUSTRIA").
    def _dedup(cell):
        seen = set()
        out = []
        for t in cell.split():
            if t not in seen:
                seen.add(t)
                out.append(t)
        return " ".join(out)
    rows = [[_dedup(c) for c in r] for r in rows]
    # Keep component rows: >=3 filled cells, no long dash run (drops
    # assembly-title / separator lines), and a real line identity — either
    # a part-number-ish alphanumeric cell, OR (for a no-MPN line item like
    # a PWB sub-assembly) an item-number value plus a worded description.
    def _row_ok(r: List[str]) -> bool:
        if sum(1 for c in r if c.strip()) < 3:
            return False
        if any(_CC_DASHRUN.search(c) for c in r):
            return False
        if any(re.search(r"[A-Za-z].*[0-9]|[0-9].*[A-Za-z]", c) for c in r):
            return True
        itemv = r[item_idx].strip() if item_idx < len(r) else ""
        has_item = bool(re.search(r"\d", itemv))
        has_desc = any(len(re.findall(r"[A-Za-z]{3,}", c)) >= 2 for c in r)
        return has_item and has_desc
    good = [r for r in rows if _row_ok(r)]
    # De-duplicate column names so the DataFrame is well-formed.
    seen: Dict[str, int] = {}
    uniq: List[str] = []
    for nm in names:
        seen[nm] = seen.get(nm, 0) + 1
        uniq.append(nm if seen[nm] == 1 else f"{nm} ({seen[nm]})")
    if len(good) >= 3:
        return pd.DataFrame(good, columns=uniq)
    return None


def parse_bom(pdf_path: str, max_pages: int = 8, include_generic: bool = False) -> Optional[pd.DataFrame]:
    """Best columnar BOM parse: CAGE-anchored coordinate parser first
    (reassembles wrapped cells / full manufacturer names), then the text-layout
    parser.

    With ``include_generic=True``, also tries the generic item-anchored
    parts-list parser (plain item/part/description/qty drawing BOMs without a
    CAGE code). That parser is broader and can fire on complex multi-column
    tables, so it's opt-in: callers use it only as a last resort, after the
    primary table detector has had its turn, to avoid preempting a cleaner
    grid-based extraction."""
    try:
        df = parse_bom_coords(pdf_path, max_pages)
        if df is not None and len(df) >= 2:
            return df
    except Exception:
        pass
    df = parse_bom_from_layout(pdf_path, max_pages)
    if df is not None and len(df) >= 2:
        return df
    if include_generic:
        def _well_formed(d) -> bool:
            # Mappable: enough rows and unique column names. Duplicate headers
            # (a side-by-side revisions table glued onto the BOM) crash the
            # downstream mapper, so those fall through to the wide-table parser.
            if d is None or len(d) < 3:
                return False
            names = [str(c).lower() for c in d.columns]
            return len(set(names)) == len(names)

        # Coordinate-space columnar parser first — handles report-style gridless
        # BOMs (ERP/Agile/Arena exports) that the char-offset slicer mangled.
        try:
            cc = parse_columnar_coords(pdf_path, max_pages)
            if _well_formed(cc):
                return cc
        except Exception:
            pass
        try:
            df = parse_generic_table(pdf_path, max_pages)
            if _well_formed(df):
                return df
        except Exception:
            pass
        try:
            wide = parse_wide_text_table(pdf_path, max_pages)
            if _well_formed(wide):
                return wide
        except Exception:
            pass
        return None
    return None


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

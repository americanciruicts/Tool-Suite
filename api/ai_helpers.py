"""
Shared AI helpers for the BOM toolchain.

Three things this module does that the rest of the code wants:

1. Fuzzy column-type classification (mpn / qty / refdes / description /
   manufacturer / customer_pn / vendor / vendor_pn / item_number / revision).
   Replaces dozens of hand-written elif chains with one rapidfuzz lookup.

2. Content-based column validation. A header is a clue, but values are proof —
   if a column is *labeled* "Part Number" but every cell is "1" / "2" / "3",
   it's actually the item-number column.

3. Quantity and MPN normalization. Same MPN written as "BC547" vs "BC-547"
   should match. "10K" vs "10000" qty should match.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Tuple

try:
    from rapidfuzz import fuzz, process
    _HAS_RAPIDFUZZ = True
except ImportError:  # pragma: no cover - rapidfuzz is in requirements
    _HAS_RAPIDFUZZ = False


# ---------------------------------------------------------------------------
# Canonical column-type taxonomy (label -> alias list, weighted by specificity)
# ---------------------------------------------------------------------------

# Aliases ordered roughly by specificity. The fuzzy matcher uses all of them
# but the explicit substring check below uses the order to break ties.
COLUMN_ALIASES = {
    "mpn": [
        "manufacturer part number", "manufacturer part no", "manufacturer pn",
        "manufacturer p/n", "mfr part number", "mfr part no", "mfr pn", "mfr p/n",
        "mfg part number", "mfg part no", "mfg pn", "mfg p/n",
        "manufacturing part number", "model number", "model no", "model #",
        "part number", "part no", "part #", "part#", "p/n", "pn", "mpn",
    ],
    "manufacturer": [
        "manufacturer name", "manufacturer", "mfg name", "mfg", "mfr name", "mfr",
        "maker", "brand",
    ],
    "customer_pn": [
        "customer part number", "customer part no", "customer pn", "customer p/n",
        "internal part number", "internal pn", "internal p/n", "company pn",
        "kjr p/n", "house p/n",
    ],
    "vendor": [
        "vendor name", "supplier name", "vendor", "supplier", "source", "distributor",
    ],
    "vendor_pn": [
        "vendor part number", "vendor part no", "vendor pn", "vendor p/n",
        "supplier part number", "supplier part no", "supplier pn", "supplier p/n",
        "distributor pn", "distributor p/n",
    ],
    "qty": [
        "quantity per assembly", "qty per assembly", "quantity per",
        "qty per", "qty/assy", "per assy", "qty required", "required qty",
        "qty", "qnty", "q'ty", "qnt", "quantity", "amount", "count",
    ],
    "refdes": [
        "reference designator", "reference designation", "ref designator",
        "ref des", "refdes", "ref. des", "refdes/loc", "ref des/loc",
        "designator", "reference", "location", "loc", "position",
    ],
    "description": [
        "part description", "component description", "item description",
        "description", "desc", "notes", "note", "comment", "comments",
        "remarks", "remark",
    ],
    "item_number": [
        "item number", "item no", "item #", "item#", "line number",
        "line no", "line #", "item", "line", "no.", "seq",
    ],
    "revision": [
        "revision", "rev", "rev.", "version",
    ],
    "uom": [
        "uom", "u/m", "u.o.m", "unit of measure", "unit of measurement",
        "unit", "units", "measure",
    ],
}

# Build flat alias -> type list for rapidfuzz
_FLAT_CHOICES: List[Tuple[str, str]] = []
for ctype, aliases in COLUMN_ALIASES.items():
    for a in aliases:
        _FLAT_CHOICES.append((a, ctype))


# Hand-tuned overrides to break common ties before fuzzy match runs.
# (substring → type). Order matters: longest/most specific first.
_PRIORITY_SUBSTR = [
    ("unit of measure", "uom"),
    ("uom", "uom"),
    ("u/m", "uom"),
    ("manufacturer part", "mpn"),
    ("mfr part", "mpn"),
    ("mfg part", "mpn"),
    ("mfr p/n", "mpn"), ("mfg p/n", "mpn"),
    ("mfr pn", "mpn"), ("mfg pn", "mpn"),
    ("model number", "mpn"), ("model no", "mpn"),
    ("vendor part", "vendor_pn"), ("supplier part", "vendor_pn"),
    ("vendor pn", "vendor_pn"), ("vendor p/n", "vendor_pn"),
    ("supplier pn", "vendor_pn"), ("supplier p/n", "vendor_pn"),
    ("customer part", "customer_pn"),
    ("customer pn", "customer_pn"), ("customer p/n", "customer_pn"),
    ("reference designator", "refdes"), ("reference designation", "refdes"),
    ("ref des", "refdes"), ("refdes", "refdes"), ("designator", "refdes"),
    ("description", "description"), ("part desc", "description"),
    ("manufacturer name", "manufacturer"), ("mfr name", "manufacturer"),
    ("mfg name", "manufacturer"),
    ("item no", "item_number"), ("item #", "item_number"),
    ("line no", "item_number"), ("line #", "item_number"),
    ("quantity", "qty"), ("qty", "qty"),
    ("part number", "mpn"), ("part no", "mpn"), ("part #", "mpn"),
    ("p/n", "mpn"), ("mpn", "mpn"),
    ("vendor", "vendor"), ("supplier", "vendor"), ("distributor", "vendor"),
    ("manufacturer", "manufacturer"),
]


def _normalize_header(s) -> str:
    if s is None:
        return ""
    s = str(s).lower().strip()
    # Collapse whitespace and strip trailing punctuation that doesn't change meaning
    s = re.sub(r"\s+", " ", s)
    s = s.rstrip(":.")
    return s


def classify_column(header: str, fuzzy_threshold: int = 86) -> Optional[str]:
    """
    Classify a column header into a canonical type.

    Returns one of: mpn / manufacturer / customer_pn / vendor / vendor_pn /
    qty / refdes / description / item_number / revision — or None.

    Strategy:
      1. Skip obviously-too-long strings (descriptions accidentally containing keywords).
      2. Priority substring overrides (handles ambiguous cases like
         "vendor part number" vs "part number").
      3. rapidfuzz against the flat alias list.
    """
    norm = _normalize_header(header)
    if not norm or len(norm) > 60:
        return None

    # 1. Priority substrings (longest-match-wins via order)
    for needle, ctype in _PRIORITY_SUBSTR:
        if needle in norm:
            return ctype

    # 2. Fuzzy match against alias list
    if not _HAS_RAPIDFUZZ:
        return None
    choices = [a for a, _ in _FLAT_CHOICES]
    match = process.extractOne(norm, choices, scorer=fuzz.WRatio)
    if match is None:
        return None
    matched_alias, score, idx = match
    if score < fuzzy_threshold:
        return None
    return _FLAT_CHOICES[idx][1]


# ---------------------------------------------------------------------------
# Content validation — does a column's data look like the type we think it is?
# ---------------------------------------------------------------------------

_MPN_CHAR_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-_/.+ ]{2,49}$", re.IGNORECASE)
_QTY_CHAR_RE = re.compile(r"^\s*[0-9]+([.,][0-9]+)?\s*[KkMmuUnNpP]?\s*$")
_INT_QTY_RE = re.compile(r"^\s*[0-9]+\s*$")
_REFDES_TOKEN_RE = re.compile(r"^[A-Z]{1,4}[0-9]+([\-,/ ]+[A-Z]{1,4}?[0-9]+)*$", re.IGNORECASE)


def is_mpn_like(value) -> bool:
    """Fast heuristic: looks like a manufacturer part number."""
    if value is None:
        return False
    s = str(value).strip()
    if len(s) < 3 or len(s) > 50:
        return False
    if not _MPN_CHAR_RE.match(s):
        return False
    has_alpha = any(c.isalpha() for c in s)
    has_digit = any(c.isdigit() for c in s)
    return has_alpha or has_digit


def is_qty_like(value) -> bool:
    if value is None:
        return False
    s = str(value).strip()
    if not s or len(s) > 10:
        return False
    return bool(_QTY_CHAR_RE.match(s))


def is_refdes_like(value) -> bool:
    if value is None:
        return False
    s = str(value).strip()
    if len(s) < 2 or len(s) > 200:
        return False
    # RefDes patterns: R1, U23, "R1, R2, R3", "C1-C5"
    return bool(_REFDES_TOKEN_RE.match(s.replace(" ", "").replace(",", " ").split()[0])) if s else False


def score_column_content(values: Iterable, expected_type: str) -> float:
    """
    Return a 0-1 score for how well a column's values match an expected type.

    Empty/None values are skipped (don't count for or against the score).
    """
    vals = [v for v in values if v is not None and str(v).strip()]
    if not vals:
        return 0.0
    sample = vals[:50]

    if expected_type == "mpn":
        hits = sum(1 for v in sample if is_mpn_like(v))
        return hits / len(sample)
    if expected_type == "qty":
        # Primarily integers, sometimes decimals; very short strings.
        hits = sum(1 for v in sample if is_qty_like(v))
        return hits / len(sample)
    if expected_type == "refdes":
        hits = sum(1 for v in sample if is_refdes_like(v))
        return hits / len(sample)
    if expected_type == "description":
        # Descriptions are long and have spaces.
        long_text = sum(1 for v in sample if len(str(v).strip()) >= 6 and " " in str(v))
        return long_text / len(sample)
    if expected_type == "item_number":
        ints = sum(1 for v in sample if _INT_QTY_RE.match(str(v).strip()))
        return ints / len(sample)
    return 0.0


def best_column_for_type(headers: List[str], df, expected_type: str,
                         min_header_score: int = 70) -> Optional[int]:
    """
    Pick the best column index for a given type by combining:
      - fuzzy header match score
      - content-pattern score (data inspection)

    Falls back to header-only when df is None or empty.
    """
    if not headers:
        return None
    candidates: List[Tuple[int, float]] = []
    for idx, h in enumerate(headers):
        cls = classify_column(h)
        header_match = 1.0 if cls == expected_type else 0.0
        # Soft fuzzy header score (continuous)
        if _HAS_RAPIDFUZZ:
            choices = [a for a, t in _FLAT_CHOICES if t == expected_type]
            if choices:
                m = process.extractOne(_normalize_header(h), choices, scorer=fuzz.WRatio)
                soft = (m[1] if m else 0) / 100.0
            else:
                soft = 0.0
        else:
            soft = 0.0
        header_score = max(header_match, soft if soft >= min_header_score / 100 else 0.0)

        content_score = 0.0
        if df is not None and idx < len(df.columns):
            try:
                content_score = score_column_content(df.iloc[:, idx].tolist(), expected_type)
            except Exception:
                content_score = 0.0

        # Combined: header weighted heavier, but content can override on ties.
        # MPN especially: a column without MPN-like content shouldn't win.
        if expected_type == "mpn":
            combined = 0.55 * header_score + 0.45 * content_score
            # Strong penalty if content really doesn't look like an MPN column
            if header_score >= 0.7 and content_score < 0.2:
                combined *= 0.4
        else:
            combined = 0.7 * header_score + 0.3 * content_score
        candidates.append((idx, combined))

    candidates.sort(key=lambda x: x[1], reverse=True)
    if not candidates or candidates[0][1] < 0.4:
        return None
    return candidates[0][0]


# ---------------------------------------------------------------------------
# Quantity normalization — handle units and SI prefixes
# ---------------------------------------------------------------------------

_QTY_SUFFIX_MAP = {
    "k": 1_000.0,
    "m": 1_000_000.0,
    "g": 1_000_000_000.0,
}

# Map of common ASCII vulgar fractions (including unicode) to their decimal value
_FRACTION_MAP = {
    "1/2": 0.5, "1/3": 1.0 / 3.0, "2/3": 2.0 / 3.0,
    "1/4": 0.25, "3/4": 0.75, "1/8": 0.125, "3/8": 0.375,
    "5/8": 0.625, "7/8": 0.875,
    "½": 0.5, "⅓": 1.0 / 3.0, "⅔": 2.0 / 3.0,
    "¼": 0.25, "¾": 0.75, "⅛": 0.125, "⅜": 0.375,
    "⅝": 0.625, "⅞": 0.875,
}


def normalize_quantity(value) -> Optional[float]:
    """
    Convert a quantity string to a float. Returns None if not parseable.

    Handles:
      - Plain ints/floats: "10", "10.0", "10,5" (european decimal)
      - SI prefixes commonly seen in BOMs for resistor/cap *values* (not qty,
        but we apply only to qty columns so it's fine to be generous): "10K" -> 10000
      - Trailing units we want to ignore: "10 pcs", "10 ea", "10x"
    """
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    # Drop common trailing words/units
    s = re.sub(r"\s*(pcs|pc|ea|each|x|qty|nos)\.?\s*$", "", s)
    # Pure fraction (e.g. "1/4", "½")
    if s in _FRACTION_MAP:
        return _FRACTION_MAP[s]
    # Mixed number "1 1/2" → 1.5
    mixed = re.match(r"^(\d+)\s+(\d+/\d+|[½⅓⅔¼¾⅛⅜⅝⅞])\s*$", s)
    if mixed:
        whole = float(mixed.group(1))
        frac_str = mixed.group(2)
        frac = _FRACTION_MAP.get(frac_str)
        if frac is not None:
            return whole + frac
    # Bare fraction "3/4" via regex (handles unmapped a/b like "5/16")
    bare_frac = re.match(r"^(\d+)/(\d+)\s*$", s)
    if bare_frac:
        try:
            num = float(bare_frac.group(1))
            den = float(bare_frac.group(2))
            return num / den if den else None
        except ValueError:
            pass
    # Comma handling: thousands separator if ", followed by exactly 3 digits"
    # (e.g. "1,000"), otherwise european decimal ("1,5"). Don't touch if a dot
    # is already present (mixed notation like "1,000.5" — strip the comma).
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        if re.search(r",\d{3}(\D|$)", s) or re.search(r",\d{3},", s):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    # SI prefix?
    multiplier = 1.0
    if s and s[-1] in _QTY_SUFFIX_MAP:
        multiplier = _QTY_SUFFIX_MAP[s[-1]]
        s = s[:-1].strip()
    try:
        return float(s) * multiplier
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# MPN normalization & similarity
# ---------------------------------------------------------------------------

def parse_alternate_mpns(value) -> List[str]:
    """
    Split a cell that contains multiple alternate MPNs into a list.

    Common formats:
        "BC547 / 2N3904"
        "BC547, 2N3904"
        "BC547 OR 2N3904"
        "BC547 ALT 2N3904"
        "BC547\\n2N3904"

    Returns a list of trimmed candidate MPNs (length >= 1). The first item
    is the "primary"; subsequent items are alternates. Returns [] for empty.
    """
    if value is None:
        return []
    s = str(value).strip()
    if not s:
        return []
    # Split on common alternate markers. Be careful with `/` since it appears
    # inside MPNs ("LM7805/T") — only treat it as a separator when surrounded
    # by spaces or appearing alongside another known separator.
    parts = re.split(r"\s+(?:or|alt|alternate|equiv|equivalent)\s+|[\n;]+|\s*\|\s*|\s*//\s*|(?<=\s)/(?=\s)", s, flags=re.IGNORECASE)
    out = [p.strip(" ,.;") for p in parts if p.strip(" ,.;")]
    # If only one piece and contains comma-separated likely-MPNs (each looks
    # MPN-like), split on commas too. Avoids splitting RefDes lists like
    # "R1, R2, R3" which would not be in an MPN cell anyway.
    if len(out) == 1 and "," in s:
        commas = [p.strip() for p in s.split(",") if p.strip()]
        if len(commas) >= 2 and all(is_mpn_like(p) for p in commas):
            out = commas
    return out


def normalize_mpn(value) -> str:
    """
    Canonical form for matching: uppercase, strip whitespace and ASCII
    punctuation that often differs across BOMs (`-`, `.`, `_`, `/`, space).

    Use the *normalized* form ONLY for matching/lookup. Always show the
    original string back to the user.
    """
    if value is None:
        return ""
    s = str(value).strip().upper()
    if not s or s in {"NAN", "NONE", "NULL"}:
        return ""
    # Collapse any internal punctuation that varies between datasheets/BOMs
    return re.sub(r"[\s\-_./]+", "", s)


def mpn_similarity(a: str, b: str) -> float:
    """0-1 similarity ratio between two MPNs (rapidfuzz token_ratio)."""
    if not a or not b:
        return 0.0
    if not _HAS_RAPIDFUZZ:
        return 1.0 if a == b else 0.0
    return fuzz.ratio(a, b) / 100.0


def find_fuzzy_mpn_match(target: str, candidates: Iterable[str],
                         threshold: float = 0.88) -> Optional[Tuple[str, float]]:
    """
    Find the best candidate MPN that fuzzy-matches the target above threshold.

    Returns (candidate, score) or None. Useful for catching one-character
    typos across two BOM revisions ("BC547" vs "BC547BTA", "0805" vs "O805").
    """
    if not target:
        return None
    cand_list = [c for c in candidates if c]
    if not cand_list:
        return None
    if not _HAS_RAPIDFUZZ:
        return None
    # WRatio handles three cases we want as fuzzy hits:
    #   - one-character typo: "BC547" vs "BC548"
    #   - punctuation-only diff: "BC547" vs "BC-547"
    #   - manufacturing suffix added/removed: "BC547" vs "BC547BTA"
    # …without firing on completely unrelated parts.
    match = process.extractOne(target, cand_list, scorer=fuzz.WRatio)
    if match is None:
        return None
    matched, score, _ = match
    if score / 100.0 < threshold:
        return None
    return matched, score / 100.0


# ---------------------------------------------------------------------------
# Description similarity
# ---------------------------------------------------------------------------

def description_similarity(a, b) -> float:
    """0-1 similarity using token_set_ratio so word order/extra tokens don't tank the score."""
    if not a or not b:
        return 0.0
    if not _HAS_RAPIDFUZZ:
        a_norm = " ".join(str(a).lower().split())
        b_norm = " ".join(str(b).lower().split())
        return 1.0 if a_norm == b_norm else 0.0
    return fuzz.token_set_ratio(str(a), str(b)) / 100.0

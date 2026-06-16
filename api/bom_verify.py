"""
On-prem agentic verify/repair pass for extracted BOMs.

The deterministic parsers (pdf_tool/layout_parse) are fast and exact on clean
tables but degrade on dense engineering drawings — columns merge, drawing
callouts bleed into cells, OCR-only vector drawings misread glyphs. This module
adds a SECOND opinion from the server's local Ollama vision model and reconciles
it against the deterministic result, cell by cell:

  1. Score every cell of the deterministic BOM. A cell is "suspect" when it
     fails its column's validator (a part-number column holding junk, a qty that
     isn't a number, a manufacturer name with a part number glued on, a blank
     P/N next to a named manufacturer, doubled-OCR text, …).
  2. If the table looks weak (low parser confidence OR several suspect rows) and
     the local VLM is reachable, transcribe the drawing with the VLM
     (vision_tool) — entirely on the server, no external API.
  3. Align the VLM rows to the deterministic rows by item number (description
     fuzzy-match fallback) and, FOR SUSPECT CELLS ONLY, adopt the VLM value when
     it clearly validates better than the deterministic one. Genuine
     disagreements where both look plausible are left as-is and FLAGGED for a
     human, never silently overwritten.

Everything degrades gracefully: if the VLM is unavailable or returns nothing,
the deterministic result is returned unchanged. Controlled by env flags so ops
can tune or disable without a code change:

  BOM_AI_VERIFY            on/off          (default: true)
  BOM_AI_VERIFY_CONF       float 0..1      run when parser confidence < this (default 0.85)
  BOM_AI_VERIFY_MIN_SUSPECT int            …or when at least this many rows are suspect (default 2)
"""

from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

import pandas as pd

from ai_helpers import is_mpn_like, is_qty_like

# Quote-template columns this pass reconciles (Item#/SMT/TH/Loc are left alone —
# Item# is an index, SMT/TH is re-inferred from the repaired desc/PN downstream).
_FIELDS = ("Description", "Mfg", "Mfg P/N", "Qty")


def _enabled() -> bool:
    # Default OFF: the local vision models are impractically slow on a CPU-only
    # host (minutes per page). Set BOM_AI_VERIFY=true once a GPU is installed —
    # then the pass runs in seconds and repairs/flags suspect cells automatically.
    return os.environ.get("BOM_AI_VERIFY", "false").lower() in ("1", "true", "yes")


def _conf_trigger() -> float:
    try:
        return float(os.environ.get("BOM_AI_VERIFY_CONF", "0.85"))
    except Exception:
        return 0.85


def _min_suspect() -> int:
    try:
        return int(os.environ.get("BOM_AI_VERIFY_MIN_SUSPECT", "2"))
    except Exception:
        return 2


def ai_verify_available() -> bool:
    """True only if enabled AND the local Ollama vision model is reachable."""
    if not _enabled():
        return False
    try:
        from vision_tool import vision_available
        return vision_available()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Per-cell suspicion — does a deterministic cell look wrong for its column?
# ---------------------------------------------------------------------------

_DOUBLED_OCR_RE = re.compile(r"\b(?:([A-Za-z])\1){2,}\b")  # RRJJ, PPIINN
_HAS_ALPHA = re.compile(r"[A-Za-z]")


def _txt(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in ("nan", "none") else s


def _looks_like_wire_or_material(desc: str) -> bool:
    """Wires, ties, sleeving etc. legitimately carry no manufacturer P/N, so a
    blank P/N on those rows is NOT suspect."""
    return bool(re.search(
        r"\b(WIRE|CABLE|TIE|SLEEV|SHRINK|TUBING|TAPE|LABEL|SOLDER|GROMMET|"
        r"BRAID|LACING|HEAT\s*SHRINK|MARKER)\b", desc, re.I))


def _suspect_fields(row: pd.Series) -> List[str]:
    """The columns of one BOM row whose value looks wrong for its type."""
    desc = _txt(row.get("Description"))
    mfg = _txt(row.get("Mfg"))
    pn = _txt(row.get("Mfg P/N"))
    qty = _txt(row.get("Qty"))
    bad: List[str] = []

    # Description: doubled-OCR, or content that is essentially not words.
    if desc and (_DOUBLED_OCR_RE.search(desc) or not _HAS_ALPHA.search(desc)):
        bad.append("Description")

    # Mfg P/N: present but not part-number-shaped (leftover junk), OR blank while
    # a real manufacturer is named and the line isn't a wire/material.
    if pn and not is_mpn_like(pn.split()[0]):
        bad.append("Mfg P/N")
    elif not pn and mfg and _HAS_ALPHA.search(mfg) and not _looks_like_wire_or_material(desc):
        bad.append("Mfg P/N")

    # Mfg: a part number glued onto the maker name (HIROSE-style column merge),
    # or a value that is mostly digits (leader callouts bled in).
    if mfg:
        toks = mfg.split()
        if len(toks) > 1 and any(is_mpn_like(t) and any(c.isdigit() for c in t) for t in toks[1:]):
            bad.append("Mfg")
        elif not _HAS_ALPHA.search(mfg):
            bad.append("Mfg")

    # Qty: present but not a quantity (a number / count / dimension).
    if qty and not is_qty_like(qty):
        bad.append("Qty")

    return bad


# ---------------------------------------------------------------------------
# Reconciliation helpers
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _desc_match(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _ai_better(field: str, ai: str, det: str, desc: str) -> bool:
    """Adopt the VLM value only when it clearly validates better than the
    deterministic one — never on a coin-flip (those are flagged instead)."""
    ai, det = ai.strip(), det.strip()
    if not ai or ai == det:
        return False
    if field == "Mfg P/N":
        ai_ok = is_mpn_like(ai.split()[0]) if ai.split() else False
        det_ok = is_mpn_like(det.split()[0]) if det.split() else False
        return ai_ok and not det_ok                      # det was junk/blank, AI is a real PN
    if field == "Qty":
        return is_qty_like(ai) and not is_qty_like(det)
    if field == "Mfg":
        # AI maker is a clean name; det had a PN glued on or was numeric noise.
        return bool(_HAS_ALPHA.search(ai)) and len(ai.split()) <= 3 and (
            not _HAS_ALPHA.search(det) or len(det.split()) > len(ai.split()))
    if field == "Description":
        return bool(_HAS_ALPHA.search(ai)) and not _HAS_ALPHA.search(det)
    return False


def verify_and_repair(
    bom_df: pd.DataFrame,
    pdf_path: str,
    det_confidence: float = 1.0,
    progress_cb=None,
) -> Tuple[pd.DataFrame, Dict]:
    """Reconcile a deterministic BOM against the local VLM's reading. Returns
    (possibly-repaired df, report). The report is JSON-serialisable:
        {ran, ai_rows, changes:[{row,field,from,to}], flags:[{row,field,...}]}
    """
    report: Dict = {"ran": False, "ai_rows": 0, "changes": [], "flags": []}
    if bom_df is None or bom_df.empty or not ai_verify_available():
        return bom_df, report

    suspects: Dict[int, List[str]] = {}
    for i in range(len(bom_df)):
        f = _suspect_fields(bom_df.iloc[i])
        if f:
            suspects[i] = f

    # Trigger only when the table looks weak — keeps clean BOMs fast (no VLM call).
    if det_confidence >= _conf_trigger() and len(suspects) < _min_suspect():
        return bom_df, report

    try:
        from vision_tool import extract_bom_via_vision
        ai_df = extract_bom_via_vision(pdf_path, progress_cb=progress_cb)
    except Exception:
        ai_df = None
    if ai_df is None or ai_df.empty:
        return bom_df, report

    try:
        from pdf_tool import map_to_quote_template_schema, _infer_smt_th
        ai_bom = map_to_quote_template_schema(ai_df)
    except Exception:
        return bom_df, report
    if ai_bom is None or ai_bom.empty:
        return bom_df, report

    report["ran"] = True
    report["ai_rows"] = int(len(ai_bom))

    ai_by_item: Dict[str, pd.Series] = {}
    for _, r in ai_bom.iterrows():
        key = _norm(r.get("Item#", ""))
        if key and key not in ai_by_item:
            ai_by_item[key] = r

    def _match(det_row: pd.Series) -> Optional[pd.Series]:
        cand = ai_by_item.get(_norm(det_row.get("Item#", "")))
        if cand is not None:
            return cand
        best, score = None, 0.0
        d = _txt(det_row.get("Description"))
        if not d:
            return None
        for _, r in ai_bom.iterrows():
            s = _desc_match(d, _txt(r.get("Description")))
            if s > score:
                best, score = r, s
        return best if score >= 0.6 else None

    out = bom_df.copy()
    changed_rows: set = set()
    for i, fields in suspects.items():
        ai_row = _match(out.iloc[i])
        if ai_row is None:
            for f in fields:
                report["flags"].append({"row": i + 1, "field": f,
                                         "value": _txt(out.iloc[i][f]),
                                         "reason": "low-confidence; AI found no matching row"})
            continue
        for f in fields:
            det_val = _txt(out.iloc[i][f])
            ai_val = _txt(ai_row.get(f))
            if _ai_better(f, ai_val, det_val, _txt(out.iloc[i].get("Description"))):
                out.iat[i, out.columns.get_loc(f)] = ai_val
                changed_rows.add(i)
                report["changes"].append({"row": i + 1, "field": f, "from": det_val, "to": ai_val})
            elif ai_val and ai_val != det_val:
                report["flags"].append({"row": i + 1, "field": f, "det": det_val, "ai": ai_val,
                                         "reason": "deterministic and AI disagree — verify"})

    # Re-infer SMT/TH for any row whose description/part number we repaired.
    if changed_rows and "SMT/TH" in out.columns:
        for i in changed_rows:
            out.iat[i, out.columns.get_loc("SMT/TH")] = _infer_smt_th(
                f"{_txt(out.iloc[i].get('Description'))} {_txt(out.iloc[i].get('Mfg P/N'))}")

    return out, report

"""
Text-layer BOM extraction via a local Ollama *text* model.

For engineering drawings the BOM data is present in the PDF's text layer — the
part numbers, CAGE codes and reference-designator lists are all there — but the
geometry parser garbles their arrangement (MIL-STD parts lists run bottom-to-top
in multiple side-by-side blocks). Rather than read pixels (slow, and the vision
tiling can miss the parts-list region on a huge A0), we hand the raw extracted
text to a local text LLM and ask it to reconstruct the BOM line items.

This is fast (text inference, no image rendering), free (local Ollama), and works
off data that is actually in the file. Degrades to None if Ollama is unreachable
or pdfplumber is unavailable.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Dict, List, Optional

import pandas as pd

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
# Accuracy vs speed presets (user-selectable). llama3 is more accurate; gemma2:2b
# is much faster on CPU. Default model when none is requested.
MODEL_ACCURACY = os.environ.get("BOM_TEXT_MODEL_ACCURACY", "llama3")
MODEL_SPEED = os.environ.get("BOM_TEXT_MODEL_SPEED", "gemma2:2b")
TEXT_MODEL = os.environ.get("BOM_TEXT_MODEL", MODEL_ACCURACY)


def model_for_quality(quality: Optional[str]) -> str:
    """Map a 'quality' preset to an Ollama text model."""
    return MODEL_SPEED if (quality or "").lower() == "speed" else MODEL_ACCURACY
MAX_PAGES = int(os.environ.get("BOM_TEXT_MAX_PAGES", "6"))
MAX_CHARS = int(os.environ.get("BOM_TEXT_MAX_CHARS", "26000"))
NUM_CTX = int(os.environ.get("BOM_TEXT_NUM_CTX", "12288"))
TIMEOUT = int(os.environ.get("BOM_TEXT_TIMEOUT", "240"))

# Output columns — descriptive headers so pdf_tool maps them onto the BOM schema.
COLUMNS = [
    "Item No.", "Reference Designation", "Qty", "CAGE/Code Ident",
    "Part Number", "Description", "Manufacturer",
]
_FIELD_MAP = {
    "item": "Item No.", "refdes": "Reference Designation", "qty": "Qty",
    "cage": "CAGE/Code Ident", "part_number": "Part Number",
    "description": "Description", "manufacturer": "Manufacturer",
}
_INV = {label: src for src, label in _FIELD_MAP.items()}

_PROMPT = (
    "The text below is a Bill of Materials / parts list extracted from an "
    "engineering-drawing PDF (it may still contain some notes/title-block lines). "
    "Each parts row typically has these columns in order: REFERENCE-DESIGNATORS, "
    "ITEM NO., QTY, CAGE/CODE-IDENT (4-5 chars), PART/IDENTIFYING NUMBER, an "
    "optional SMT/layer code, DESCRIPTION, and MANUFACTURER. A long "
    "reference-designator list may wrap onto its own line just above its row.\n\n"
    "Extract ONLY the real BOM line items. For each item capture whatever is "
    "present: item number, quantity, manufacturer, part/identifying number, "
    "description/nomenclature, reference designators (locations like "
    "'C257,C264,C279-281'), and CAGE/code-ident.\n\n"
    "Rules:\n"
    "- One logical part = one row. Join wrapped reference-designator lists into a "
    "single value.\n"
    "- Transcribe part numbers and CAGE codes EXACTLY, character for character.\n"
    "- Ignore notes, title block, revisions, dimensions, approvals, distribution "
    "statements.\n"
    "- Leave a field as \"\" if absent. Do not invent values.\n"
    "- Respond with ONLY this JSON (no prose): {\"rows\":[{\"item\":\"\",\"qty\":\"\","
    "\"manufacturer\":\"\",\"part_number\":\"\",\"description\":\"\",\"refdes\":\"\","
    "\"cage\":\"\"}]}\n\n"
    "TEXT:\n{text}\n"
)


def _ollama_url(path: str) -> str:
    return f"{OLLAMA_BASE_URL}{path}"


def text_llm_available() -> bool:
    try:
        import pdfplumber  # noqa: F401
    except Exception:
        return False
    try:
        with urllib.request.urlopen(_ollama_url("/api/tags"), timeout=4) as r:
            return r.status == 200
    except Exception:
        return False


def _extract_text(pdf_path: str) -> str:
    """Extract the parts-list text. Prefer poppler's `pdftotext -layout`, which
    preserves the parts-list rows/columns (pdfplumber's reading-order scrambles
    them). Then keep only lines that look like parts rows / reference-designator
    lists so the model gets a compact, clean table instead of pages of notes."""
    import re
    import subprocess

    layout = ""
    try:
        layout = subprocess.run(
            ["pdftotext", "-layout", "-f", "1", "-l", str(MAX_PAGES), pdf_path, "-"],
            capture_output=True, text=True, timeout=90,
        ).stdout or ""
    except Exception:
        layout = ""

    if layout.strip():
        # A parts row has: ITEM(1-3 digits) QTY(1-4 digits) CAGE(4-5 alnum) PARTNO…
        part_row = re.compile(r"\s\d{1,3}\s+\d{1,4}\s+[0-9A-Z]{4,5}\s+\S{3,}")
        # A wrapped reference-designator line (e.g. "C257,C264,C279-281,").
        refdes_line = re.compile(
            r"^[A-Z]{1,4}\d+[A-Z]?(?:[-,]\d+)*(?:[,\s]+[A-Z]{0,4}\d+[A-Z]?(?:[-,]\d+)*)*[,]?$"
        )
        kept: List[str] = []
        for ln in layout.splitlines():
            s = ln.strip()
            if not s:
                continue
            if part_row.search(ln) or refdes_line.match(s) or "IDENTIFYING NO" in ln.upper():
                kept.append(s)
        compact = "\n".join(kept)
        if len(compact) > 200:  # got a real parts list
            return compact[:MAX_CHARS]
        return layout[:MAX_CHARS]  # fall back to the full (capped) layout text

    # Last resort: pdfplumber reading-order text, parts-list pages first.
    import pdfplumber
    pages: List[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:MAX_PAGES]:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                pages.append("")
    refdes = re.compile(r"\b[A-Z]{1,3}\d+(?:[-,]\d+)*\b")

    def score(t: str) -> int:
        u = t.upper()
        s = sum(5 for kw in ("LIST OF MATERIALS", "PARTS LIST", "REQD", "CODE IDENT",
                             "IDENTIFYING NO", "NOMENCLATURE", "MANUFACTURER") if kw in u)
        return s + len(refdes.findall(t))

    order = sorted(range(len(pages)), key=lambda i: score(pages[i]), reverse=True)
    return "\n\n".join(pages[i] for i in order)[:MAX_CHARS]


def extract_bom_via_text_llm(pdf_path: str, progress_cb=None, model: Optional[str] = None) -> Optional[pd.DataFrame]:
    """Reconstruct BOM rows from the PDF text layer using a local text LLM.
    Returns a DataFrame (COLUMNS schema) or None."""
    if not text_llm_available():
        return None
    text = _extract_text(pdf_path)
    if not text.strip():
        return None
    use_model = model or TEXT_MODEL
    if progress_cb:
        try:
            progress_cb(35, f"AI structuring BOM from text ({use_model})")
        except Exception:
            pass

    body = json.dumps({
        "model": use_model,
        "prompt": _PROMPT.replace("{text}", text),
        "stream": False,
        "format": "json",
        "think": False,
        "options": {"temperature": 0, "num_ctx": NUM_CTX},
    }).encode("utf-8")
    req = urllib.request.Request(
        _ollama_url("/api/generate"), data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    raw = payload.get("response", "")
    try:
        data = json.loads(raw)
    except Exception:
        # Some thinking models wrap JSON; grab the outermost {...}.
        import re
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except Exception:
            return None

    rows = data.get("rows", []) if isinstance(data, dict) else []
    clean: List[Dict[str, str]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if not (str(r.get("part_number", "")).strip() or str(r.get("description", "")).strip()):
            continue
        clean.append(r)
    if not clean:
        return None

    return pd.DataFrame(
        {label: [str(r.get(_INV[label], "")) for r in clean] for label in COLUMNS}
    )

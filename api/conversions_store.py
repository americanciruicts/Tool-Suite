"""
Server-side history of PDF/image → BOM conversions.

Persists each successful conversion to the mounted data volume so the "Recent
uploads" page is permanent and shared across browsers/devices (the previous
Recent list lived only in each browser's localStorage). Each entry is stored as
two files under DATA_DIR/conversions:

    <id>.json  — lightweight record: original filename, kind, timestamp, the
                 preview columns/rows + metadata (everything needed to re-open a
                 preview), but NOT the file bytes.
    <id>.bin   — the converted output file bytes (xlsx/docx) for download.

Listing reads only the small .json files. Deduplicated by source-file SHA so
re-uploading the same file refreshes the existing entry instead of piling up.
Best-effort: every function swallows errors and degrades gracefully so history
never breaks a conversion.
"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from typing import Dict, List, Optional, Tuple

DATA_DIR = os.path.join(os.getenv("DATA_DIR", "/app/data"), "conversions")
MAX_KEEP = 300  # cap stored history; oldest pruned beyond this

_PREVIEW_KEYS = (
    "filename", "columns", "rows", "total_rows", "preview_truncated",
    "mime", "metadata", "warnings",
)


def _ensure() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _path(cid: str, ext: str) -> str:
    return os.path.join(DATA_DIR, f"{cid}{ext}")


def _entries() -> List[Dict]:
    """All stored records (lightweight), newest first."""
    _ensure()
    out: List[Dict] = []
    for name in os.listdir(DATA_DIR):
        if name.endswith(".json"):
            try:
                with open(os.path.join(DATA_DIR, name), "r") as f:
                    out.append(json.load(f))
            except Exception:
                continue
    out.sort(key=lambda r: r.get("ts", 0), reverse=True)
    return out


def _fmt(filename: Optional[str]) -> str:
    return "word" if str(filename or "").lower().endswith(".docx") else "excel"


def save(payload: Dict, original_filename: str, kind: str, sha: Optional[str] = None) -> Optional[str]:
    """Persist a successful conversion. Returns its id, or None on failure.
    If an entry with the same source SHA exists, it is replaced (kept fresh)."""
    try:
        _ensure()
        if sha:
            for e in _entries():
                if e.get("sha") == sha:
                    delete(e["id"])  # replace the stale duplicate
                    break

        cid = uuid.uuid4().hex
        record = {k: payload.get(k) for k in _PREVIEW_KEYS}
        record.update({
            "id": cid,
            "ts": time.time(),
            "original_filename": original_filename,
            "kind": kind,
            "sha": sha,
            "format": _fmt(payload.get("filename")),
        })

        b64 = payload.get("excel_base64")
        if b64:
            with open(_path(cid, ".bin"), "wb") as f:
                f.write(base64.b64decode(b64))
        with open(_path(cid, ".json"), "w") as f:
            json.dump(record, f)

        _prune()
        return cid
    except Exception:
        return None


def list_recent(limit: int = 100) -> List[Dict]:
    """Summaries for the Recent uploads page (no file bytes, no preview rows)."""
    items = []
    for e in _entries()[:limit]:
        items.append({
            "id": e.get("id"),
            "ts": e.get("ts"),
            "original_filename": e.get("original_filename"),
            "kind": e.get("kind"),
            "filename": e.get("filename"),
            "format": e.get("format") or _fmt(e.get("filename")),
            "total_rows": e.get("total_rows", 0),
        })
    return items


def get(cid: str) -> Optional[Dict]:
    """Full preview record for re-opening a conversion (columns/rows/metadata)."""
    p = _path(cid, ".json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r") as f:
            return json.load(f)
    except Exception:
        return None


def get_file(cid: str) -> Optional[Tuple[bytes, str, str]]:
    """Return (bytes, download_filename, mime) for the stored output file."""
    e = get(cid)
    if not e:
        return None
    binp = _path(cid, ".bin")
    if not os.path.exists(binp):
        return None
    try:
        with open(binp, "rb") as f:
            data = f.read()
    except Exception:
        return None
    return data, e.get("filename", "download"), e.get(
        "mime", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def delete(cid: str) -> bool:
    ok = False
    for ext in (".json", ".bin"):
        try:
            os.remove(_path(cid, ext))
            ok = True
        except FileNotFoundError:
            pass
        except Exception:
            pass
    return ok


def clear_all() -> None:
    _ensure()
    for name in os.listdir(DATA_DIR):
        try:
            os.remove(os.path.join(DATA_DIR, name))
        except Exception:
            pass


def _prune() -> None:
    for e in _entries()[MAX_KEEP:]:
        delete(e.get("id", ""))

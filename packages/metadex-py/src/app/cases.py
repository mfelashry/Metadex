"""Temporary evidence cases for visual search.

A case holds only images the caller uploaded (or the built-in demo set).
Files, previews, and embeddings live under a private directory and are removed
when the case is deleted or its clock runs out. Responses never include a
filesystem path.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("metadex.cases")

from PIL import Image

from app.analyze import MAX_BYTES, MAX_PIXELS, MAX_UPLOAD_FILES, AnalysisError, analyze_bytes
from app import vision

MAX_CASE_FILES = MAX_UPLOAD_FILES
DEFAULT_TTL_SECONDS = 6 * 60 * 60
DEFAULT_TOTAL_BYTES = 100 * 1024 * 1024
MAX_QUERY_LENGTH = 400
MAX_OPEN_CASES = 30
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,80}$")
_ITEM_RE = re.compile(r"^i\d{3,6}$")
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._ ()-]")

MATCH_DISCLAIMER = (
    "A search match is visual similarity only. It is not evidence that an image is malicious."
)
INDICATOR_DISCLAIMER = (
    "A forensic indicator is a reason to review the file. It is not, by itself, proof of an attack."
)
SCORE_MEANING = (
    "Relative cosine similarity between the query and the image. "
    "Higher means closer in the model's visual space. "
    "This is not a probability, a confidence percentage, or a danger score."
)

_lock = threading.Lock()
_cases: dict[str, dict] = {}
_loaded = False
_sweeper_started = False
_stop = threading.Event()


class CaseError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def ttl_seconds() -> int:
    raw = os.environ.get("METADEX_CASE_TTL_SECONDS", str(DEFAULT_TTL_SECONDS))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_TTL_SECONDS
    return max(0, value)


def max_total_bytes() -> int:
    raw = os.environ.get("METADEX_CASE_MAX_TOTAL_BYTES", str(DEFAULT_TOTAL_BYTES))
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_TOTAL_BYTES
    return max(MAX_BYTES, value)


def max_open_cases() -> int:
    raw = os.environ.get("METADEX_MAX_CASES", str(MAX_OPEN_CASES))
    try:
        value = int(raw)
    except ValueError:
        return MAX_OPEN_CASES
    return max(1, value)


def case_root() -> Path:
    raw = os.environ.get("METADEX_CASE_DIR", "").strip()
    path = Path(raw) if raw else Path(tempfile.gettempdir()) / "metadex-cases"
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def display_filename(name: str | None, index: int) -> str:
    """A name safe to show and impossible to use as a path."""
    raw = (name or "").replace("\\", "/").replace("\x00", "").split("/")[-1]
    raw = _UNSAFE_NAME.sub("_", raw).strip(" .")
    if raw in {"", ".", ".."}:
        raw = f"image-{index + 1}"
    return raw[:120]


def clean_query(text: str) -> str:
    cleaned = "".join(ch for ch in text if ch >= " " or ch in "\n\t")
    cleaned = " ".join(cleaned.split())
    return cleaned[:MAX_QUERY_LENGTH]


def start_sweeper() -> None:
    global _sweeper_started
    with _lock:
        if _sweeper_started:
            return
        _sweeper_started = True
        threading.Thread(target=_sweep_loop, name="metadex-case-sweeper", daemon=True).start()


def stop_sweeper() -> None:
    _stop.set()


def _sweep_loop() -> None:
    while not _stop.wait(60):
        try:
            expire_due()
        except Exception:
            continue


def ensure_store() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        root = case_root()
    for child in list(root.iterdir()):
        manifest_path = child / "manifest.json"
        if not child.is_dir() or not manifest_path.is_file():
            shutil.rmtree(child, ignore_errors=True)
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            shutil.rmtree(child, ignore_errors=True)
            continue
        case_id = str(data.get("id") or "")
        if not _ID_RE.match(case_id) or child.name != case_id:
            shutil.rmtree(child, ignore_errors=True)
            continue
        if float(data.get("expires_at") or 0) <= time.time():
            shutil.rmtree(child, ignore_errors=True)
            continue
        if data.get("status") == "indexing":
            data["status"] = "failed"
            data["stage"] = "failed"
            data["model_error"] = "Indexing was interrupted. Create the case again."
            _write_manifest(data)
        with _lock:
            _cases[case_id] = data


def expire_due() -> None:
    ensure_store()
    now = time.time()
    with _lock:
        dead = [case_id for case_id, case in _cases.items() if float(case.get("expires_at") or 0) <= now]
    for case_id in dead:
        _destroy(case_id)


def reset_for_tests() -> None:
    """Clear memory and the configured case directory. Tests must set METADEX_CASE_DIR first."""
    global _loaded
    root = Path(os.environ["METADEX_CASE_DIR"])
    with _lock:
        _cases.clear()
        _loaded = False
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)


def drop_memory_for_tests() -> None:
    """Forget the in-memory index without deleting files, so a reload can be tested."""
    global _loaded
    with _lock:
        _cases.clear()
        _loaded = False


def force_expire(case_id: str) -> None:
    ensure_store()
    with _lock:
        case = _cases.get(case_id)
        if case:
            case["expires_at"] = 0
    expire_due()


def start_case(name: str, items: list[dict], *, source: str, suggested: list[str] | None = None, rejected: list[dict] | None = None) -> dict:
    ensure_store()
    expire_due()
    with _lock:
        if len(_cases) >= max_open_cases():
            raise CaseError(429, "Delete a case or wait for one to expire before creating another.")
        case_id = secrets.token_urlsafe(18)
        while case_id in _cases or not _ID_RE.match(case_id):
            case_id = secrets.token_urlsafe(18)
        now = time.time()
        folder = case_root() / case_id
        folder.mkdir(parents=True, exist_ok=False)
        try:
            os.chmod(folder, 0o700)
        except OSError:
            pass
        files = []
        for index, item in enumerate(rejected or []):
            files.append(
                {
                    "id": f"i{index:03d}",
                    "filename": item["filename"],
                    "status": "error",
                    "error": item["reason"],
                    "role": None,
                    "role_label": None,
                    "forensic_summary": None,
                    "embedding": None,
                }
            )
        case = {
            "id": case_id,
            "name": _case_name(name),
            "source": source,
            "status": "indexing" if items else "ready",
            "stage": "analyzing" if items else "ready",
            "done": 0,
            "total": len(items),
            "created_at": now,
            "expires_at": now + ttl_seconds(),
            "device": None,
            "using_gpu": False,
            "model": None,
            "model_error": None,
            "suggested_queries": list(suggested or []),
            "files": files,
            "next_index": len(files),
        }
        _cases[case_id] = case
        _write_manifest(case)
    if items:
        threading.Thread(target=_index, args=(case_id, items), name=f"metadex-index-{case_id[:8]}", daemon=True).start()
    return public_case(_require(case_id))


def list_cases() -> list[dict]:
    """Open cases, without embeddings or filesystem paths."""
    ensure_store()
    expire_due()
    with _lock:
        copies = [_manifest_copy(case) for case in _cases.values()]
    copies.sort(key=lambda case: float(case.get("created_at") or 0), reverse=True)
    return [public_case(case) for case in copies]


def get_case(case_id: str) -> dict:
    case = _require(case_id)
    with _lock:
        return public_case(_manifest_copy(case))


def delete_case(case_id: str) -> None:
    _require(case_id)
    _destroy(case_id)


def preview_bytes(case_id: str, item_id: str) -> bytes:
    case = _require(case_id)
    row = _find_item(case, item_id)
    if row.get("status") == "error":
        raise CaseError(404, "That image has no preview.")
    path = _item_path(case_id, item_id, "preview.jpg")
    if not path.is_file():
        raise CaseError(404, "That image has no preview.")
    return path.read_bytes()


def item_detail(case_id: str, item_id: str) -> dict:
    case = _require(case_id)
    with _lock:
        row = _find_item(case, item_id)
        status = row.get("status")
    if status == "error":
        raise CaseError(404, "That image was not analyzed.")
    path = _item_path(case_id, item_id, "report.json")
    if not path.is_file():
        raise CaseError(404, "Forensic details for that image are gone.")
    detail = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(detail, dict):
        detail.pop("embedding", None)
    return detail


def search(case_id: str, query: str) -> dict:
    live = _require(case_id)
    with _lock:
        case = _manifest_copy(live)
    if case["status"] == "indexing":
        raise CaseError(409, "Indexing and forensic analysis are still running.")
    if case["status"] == "failed":
        raise CaseError(409, case.get("model_error") or "This case could not be indexed.")
    text = clean_query(query)
    if not text:
        raise CaseError(400, "Enter a description to search.")
    indexed = [row for row in case["files"] if row.get("status") == "indexed" and row.get("embedding")]
    info = vision.status()
    if not indexed:
        return _search_body(case, text, [], info, note="No images were indexed, so there is nothing to rank.")
    try:
        query_vector = vision.embed_text(text)
    except vision.EncoderError as exc:
        raise CaseError(503, str(exc)) from exc
    info = vision.status()
    ranked = []
    for row in indexed:
        score = vision.cosine(query_vector, row["embedding"])
        ranked.append((score, row))
    ranked.sort(key=lambda item: (-item[0], item[1]["filename"].lower()))
    results = []
    for index, (score, row) in enumerate(ranked, start=1):
        results.append(
            {
                "id": row["id"],
                "rank": index,
                "filename": row["filename"],
                "similarity": round(score, 6),
                "preview_url": f"/api/cases/{case['id']}/items/{row['id']}/preview",
                "role": row.get("role"),
                "role_label": row.get("role_label"),
                "forensic_summary": row.get("forensic_summary"),
            }
        )
    return _search_body(case, text, results, info, note=None)


def public_case(case: dict) -> dict:
    files = []
    errors = []
    indexed = 0
    for row in case["files"]:
        if row.get("status") == "error":
            errors.append({"filename": row["filename"], "reason": row.get("error") or "Rejected"})
        else:
            if row.get("status") == "indexed":
                indexed += 1
        files.append(_public_file(case["id"], row))
    return {
        "id": case["id"],
        "name": case["name"],
        "source": case["source"],
        "status": case["status"],
        "stage": case["stage"],
        "progress": {"done": case.get("done") or 0, "total": case.get("total") or 0},
        "created_at": _iso(case["created_at"]),
        "expires_at": _iso(case["expires_at"]),
        "device": case.get("device"),
        "using_gpu": bool(case.get("using_gpu")),
        "model": case.get("model"),
        "model_error": case.get("model_error"),
        "indexed_count": indexed,
        "file_errors": errors,
        "files": files,
        "suggested_queries": case.get("suggested_queries") or [],
        "disclaimer": MATCH_DISCLAIMER,
        "indicator_disclaimer": INDICATOR_DISCLAIMER,
        "limits": {
            "max_files": MAX_CASE_FILES,
            "max_bytes": MAX_BYTES,
            "max_pixels": MAX_PIXELS,
            "max_total_bytes": max_total_bytes(),
        },
    }


def forensic_summary(report: dict) -> dict:
    image = report.get("image_analysis") or {}
    structure = image.get("structure") or {}
    meta = image.get("metadata") or {}
    appended = image.get("appended_data") or {}
    lsb = image.get("lsb") or {}
    evidence = appended.get("evidence") or {}
    clues = ((meta.get("evidence") or {}).get("clues")) or []
    anomalies = []
    for anomaly in structure.get("anomalies") or []:
        anomalies.append(anomaly if isinstance(anomaly, str) else str(anomaly))
    for clue in clues:
        if any(token in clue for token in ("carrier", "unusually long", "COM segment", "GPS")):
            anomalies.append(clue)
    payloads = []
    for message in (report.get("messages_found") or [])[:6]:
        payloads.append(
            {
                "method": message.get("method"),
                "where": message.get("where"),
                "preview": str(message.get("text") or "")[:180],
            }
        )
    trailing = int(evidence.get("trailing_bytes") or structure.get("trailing_bytes") or 0)
    signature = evidence.get("embedded_signature")
    note = appended.get("explanation") or structure.get("note") or ""
    if isinstance(signature, dict) and signature.get("type"):
        note = f"Trailing bytes begin with a {signature['type']} signature. {note}"
    hidden = (report.get("conclusions") or {}).get("hidden_data") or {}
    suspicion = report.get("suspicion") or {}
    integrity = report.get("integrity") or {}
    return {
        "headline": hidden.get("headline") or "Forensic check finished",
        "level": suspicion.get("level") or "none",
        "level_label": suspicion.get("level_label") or "No indicators",
        "indicator_count": hidden.get("indicator_count") or 0,
        "statement": hidden.get("statement") or INDICATOR_DISCLAIMER,
        "metadata_anomalies": anomalies[:6],
        "appended": {
            "present": appended.get("status") == "indicator" or trailing > 0,
            "trailing_bytes": trailing,
            "note": note,
        },
        "lsb": {
            "status": lsb.get("status") or "not_applicable",
            "note": lsb.get("explanation") or "",
        },
        "recovered_payloads": payloads,
        "integrity": {
            "unchanged": bool(integrity.get("unchanged")),
            "statement": integrity.get("statement") or "",
        },
        "top_reasons": list(suspicion.get("top_reasons") or [])[:3],
        "disclaimer": INDICATOR_DISCLAIMER,
    }


def public_detail(report: dict, row: dict) -> dict:
    image = report.get("image_analysis") or {}
    fileinfo = report.get("file") or {}
    suspicion = report.get("suspicion") or {}
    appended = image.get("appended_data") or {}
    return {
        "id": row["id"],
        "filename": row["filename"],
        "format": row.get("format") or fileinfo.get("format"),
        "size_bytes": fileinfo.get("size_bytes"),
        "width": row.get("width") or fileinfo.get("width"),
        "height": row.get("height") or fileinfo.get("height"),
        "sha256": fileinfo.get("sha256"),
        "role": row.get("role"),
        "role_label": row.get("role_label"),
        "forensic_summary": row.get("forensic_summary") or forensic_summary(report),
        "suspicion": {
            "score": suspicion.get("score"),
            "level": suspicion.get("level"),
            "level_label": suspicion.get("level_label"),
            "statement": suspicion.get("statement"),
            "top_reasons": suspicion.get("top_reasons") or [],
        },
        "messages": report.get("messages_found") or [],
        "findings": [
            {"name": item.get("name"), "result": item.get("result"), "detail": item.get("detail")}
            for item in (report.get("findings") or [])[:12]
        ],
        "image_analysis": {
            "structure": {
                "status": (image.get("structure") or {}).get("status"),
                "trailing_bytes": (image.get("structure") or {}).get("trailing_bytes"),
                "anomalies": (image.get("structure") or {}).get("anomalies") or [],
                "note": (image.get("structure") or {}).get("note"),
            },
            "metadata": {
                "status": (image.get("metadata") or {}).get("status"),
                "explanation": (image.get("metadata") or {}).get("explanation"),
                "clues": ((image.get("metadata") or {}).get("evidence") or {}).get("clues") or [],
            },
            "appended_data": {
                "status": appended.get("status"),
                "explanation": appended.get("explanation"),
                "trailing_bytes": (appended.get("evidence") or {}).get("trailing_bytes"),
                "embedded_signature": (appended.get("evidence") or {}).get("embedded_signature"),
            },
            "lsb": {
                "status": (image.get("lsb") or {}).get("status"),
                "explanation": (image.get("lsb") or {}).get("explanation"),
            },
            "entropy": image.get("entropy"),
        },
        "integrity": report.get("integrity"),
        "narrative": report.get("narrative"),
        "limitations": report.get("limitations"),
        "disclaimer": INDICATOR_DISCLAIMER,
        "match_disclaimer": MATCH_DISCLAIMER,
    }


def _index(case_id: str, items: list[dict]) -> None:
    model_failed = False
    batch = vision.embed_batch_size(vision.status().get("device"))
    pending = 0
    try:
        for offset, item in enumerate(items, start=1):
            if not _alive(case_id):
                _destroy(case_id)
                return
            _set_progress(case_id, _finished_count(case_id), "analyzing")
            _accept_one(case_id, item)
            pending += 1
            if not model_failed and pending >= batch:
                model_failed = _embed_latest(case_id)
                pending = 0
                batch = max(1, vision.embed_batch_size(vision.status().get("device")))
                _set_progress(case_id, _finished_count(case_id), "indexing")
        if pending and not model_failed and _alive(case_id):
            model_failed = _embed_latest(case_id)
        if not _alive(case_id):
            _destroy(case_id)
            return
        info = vision.status()
        with _lock:
            case = _cases.get(case_id)
            if not case:
                return
            case["done"] = case["total"]
            if model_failed or (case.get("model_error") and not any(row.get("status") == "indexed" for row in case["files"])):
                case["status"] = "failed"
                case["stage"] = "failed"
            else:
                case["status"] = "ready"
                case["stage"] = "ready"
                case["device"] = info.get("device")
                case["using_gpu"] = bool(info.get("using_gpu"))
                case["model"] = info.get("model")
            _write_manifest(case)
    except Exception:
        log.exception("Case indexing failed")
        _fail(case_id, "Indexing failed before the case was ready. Check the server log and create the case again.")


def _accept_one(case_id: str, item: dict) -> None:
    if not _alive(case_id):
        return
    filename = display_filename(item.get("filename"), item.get("index") or 0)
    data = item.get("data") or b""
    try:
        report = analyze_bytes(data, filename, None, None)
    except AnalysisError as exc:
        _append_error(case_id, filename, _error_text(exc), item)
        return
    except Exception:
        log.exception("Image analysis failed")
        _append_error(case_id, filename, "This image could not be analyzed.", item)
        return
    try:
        decoded = Image.open(io.BytesIO(data))
        decoded.load()
        preview = _preview_bytes(decoded)
        rgb = decoded.convert("RGB").copy()
        rgb.load()
        decoded.close()
    except Exception:
        _append_error(case_id, filename, "This image could not be previewed.", item)
        return
    row = _error_row(case_id, filename, None, item)
    if row is None or not _alive(case_id):
        return
    row["status"] = "analyzed"
    row["error"] = None
    row["format"] = report["file"]["format"]
    row["width"] = report["file"]["width"]
    row["height"] = report["file"]["height"]
    row["sha256"] = report["file"]["sha256"]
    row["forensic_summary"] = forensic_summary(report)
    row["_rgb"] = rgb
    if not _alive(case_id):
        return
    folder = _item_path(case_id, row["id"], "")
    folder.mkdir(parents=True, exist_ok=True)
    _write_private(_item_path(case_id, row["id"], "original.bin"), data)
    _write_private(_item_path(case_id, row["id"], "preview.jpg"), preview)
    _write_private(
        _item_path(case_id, row["id"], "report.json"),
        json.dumps(public_detail(report, row)).encode("utf-8"),
    )
    if not _alive(case_id):
        shutil.rmtree(case_root() / case_id, ignore_errors=True)
        return
    _append_file(case_id, row)


def _finished_count(case_id: str) -> int:
    with _lock:
        case = _cases.get(case_id)
        if not case:
            return 0
        return sum(1 for row in case["files"] if row.get("status") in {"indexed", "error"})


def _embed_latest(case_id: str) -> bool:
    """Return True when the model itself failed and embedding should stop.

    Rows that already have an embedding are left alone.
    """
    with _lock:
        case = _cases.get(case_id)
        if not case:
            return False
        pending = [
            row
            for row in case["files"]
            if row.get("status") == "analyzed" and row.get("_rgb") is not None and not row.get("embedding")
        ]
    images = []
    rows = []
    for row in pending:
        rgb = row.get("_rgb")
        if rgb is None or row.get("embedding"):
            row.pop("_rgb", None)
            continue
        images.append(rgb)
        rows.append(row)
    if not rows:
        return False
    try:
        vectors = vision.embed_images(images)
    except vision.EncoderError as exc:
        for row in rows:
            row.pop("_rgb", None)
            row["status"] = "analyzed"
            row["embedding"] = None
        _fail_model(case_id, str(exc))
        return True
    except Exception:
        for row in rows:
            row.pop("_rgb", None)
            row["status"] = "error"
            row["error"] = "This image could not be embedded."
            row["embedding"] = None
        return False
    for row, vector in zip(rows, vectors):
        row.pop("_rgb", None)
        row["embedding"] = vector
        row["status"] = "indexed"
    with _lock:
        case = _cases.get(case_id)
        if case:
            case["done"] = sum(1 for row in case["files"] if row.get("status") in {"indexed", "error"})
            _write_manifest(case)
    return False


def _append_file(case_id: str, row: dict) -> None:
    with _lock:
        case = _cases.get(case_id)
        if not case:
            return
        case["files"].append(row)
        case["done"] = sum(1 for item in case["files"] if item.get("status") in {"indexed", "error"})
        _write_manifest(case)


def _append_error(case_id: str, filename: str, reason: str, item: dict) -> None:
    row = _error_row(case_id, filename, reason, item)
    if row is not None:
        _append_file(case_id, row)


def _error_row(case_id: str, filename: str, reason: str | None, item: dict) -> dict | None:
    with _lock:
        case = _cases.get(case_id)
        if not case:
            return None
        index = case["next_index"]
        case["next_index"] = index + 1
    return {
        "id": f"i{index:03d}",
        "filename": filename,
        "status": "error" if reason else "analyzed",
        "error": reason,
        "format": None,
        "width": None,
        "height": None,
        "sha256": None,
        "role": item.get("role"),
        "role_label": item.get("role_label"),
        "forensic_summary": None,
        "embedding": None,
    }


def _set_progress(case_id: str, done: int, stage: str) -> None:
    with _lock:
        case = _cases.get(case_id)
        if not case or case.get("status") == "failed":
            return
        case["stage"] = stage
        case["done"] = done


def _fail_model(case_id: str, message: str) -> None:
    with _lock:
        case = _cases.get(case_id)
        if not case:
            return
        case["model_error"] = message
        case["status"] = "failed"
        case["stage"] = "failed"
        info = None
    try:
        info = vision.status()
    except Exception:
        info = None
    with _lock:
        case = _cases.get(case_id)
        if not case:
            return
        if info:
            case["device"] = info.get("device")
            case["using_gpu"] = False
            case["model"] = info.get("model")
        _write_manifest(case)


def _fail(case_id: str, message: str) -> None:
    with _lock:
        case = _cases.get(case_id)
        if not case:
            return
        case["status"] = "failed"
        case["stage"] = "failed"
        case["model_error"] = message
        _write_manifest(case)


def _alive(case_id: str) -> bool:
    with _lock:
        case = _cases.get(case_id)
        return bool(case) and float(case.get("expires_at") or 0) > time.time()


def _require(case_id: str) -> dict:
    if not _ID_RE.match(case_id or ""):
        raise CaseError(404, "This case does not exist or it has expired.")
    ensure_store()
    expire_due()
    with _lock:
        case = _cases.get(case_id)
    if not case:
        raise CaseError(404, "This case does not exist or it has expired.")
    return case


def _find_item(case: dict, item_id: str) -> dict:
    if not _ITEM_RE.match(item_id or ""):
        raise CaseError(404, "That image is not in this case.")
    for row in case["files"]:
        if row["id"] == item_id:
            return row
    raise CaseError(404, "That image is not in this case.")


def _destroy(case_id: str) -> None:
    with _lock:
        case = _cases.pop(case_id, None)
    folder = case_root() / case_id
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)
    if case is None and not folder.exists():
        return


def _item_path(case_id: str, item_id: str, name: str) -> Path:
    if not _ID_RE.match(case_id) or not _ITEM_RE.match(item_id):
        raise CaseError(404, "That image is not in this case.")
    base = (case_root() / case_id / "items" / item_id).resolve()
    root = (case_root() / case_id).resolve()
    if root != base and root not in base.parents:
        raise CaseError(404, "That image is not in this case.")
    if not name:
        return base
    return base / name


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _write_manifest(case: dict) -> None:
    folder = case_root() / case["id"]
    folder.mkdir(parents=True, exist_ok=True)
    payload = _manifest_copy(case)
    target = folder / "manifest.json"
    temporary = folder / "manifest.json.tmp"
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temporary, target)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass


def _manifest_copy(case: dict) -> dict:
    files = []
    for row in case["files"]:
        files.append({key: value for key, value in row.items() if key != "_rgb"})
    return {
        "id": case["id"],
        "name": case["name"],
        "source": case["source"],
        "status": case["status"],
        "stage": case["stage"],
        "done": case.get("done") or 0,
        "total": case.get("total") or 0,
        "created_at": case["created_at"],
        "expires_at": case["expires_at"],
        "device": case.get("device"),
        "using_gpu": bool(case.get("using_gpu")),
        "model": case.get("model"),
        "model_error": case.get("model_error"),
        "suggested_queries": case.get("suggested_queries") or [],
        "files": files,
        "next_index": case.get("next_index") or len(files),
    }


def _public_file(case_id: str, row: dict) -> dict:
    body = {
        "id": row["id"],
        "filename": row["filename"],
        "status": row.get("status"),
        "error": row.get("error"),
        "format": row.get("format"),
        "width": row.get("width"),
        "height": row.get("height"),
        "role": row.get("role"),
        "role_label": row.get("role_label"),
        "forensic_summary": row.get("forensic_summary"),
        "preview_url": None
        if row.get("status") == "error"
        else f"/api/cases/{case_id}/items/{row['id']}/preview",
    }
    return body


def _search_body(case: dict, query: str, results: list, info: dict, note: str | None) -> dict:
    return {
        "case_id": case["id"],
        "query": query,
        "device": info.get("device"),
        "using_gpu": bool(info.get("using_gpu")),
        "model": info.get("model"),
        "score_meaning": SCORE_MEANING,
        "disclaimer": MATCH_DISCLAIMER,
        "indicator_disclaimer": INDICATOR_DISCLAIMER,
        "note": note,
        "results": results,
    }


def _preview_bytes(image: Image.Image) -> bytes:
    copy = image.convert("RGB")
    copy.thumbnail((640, 640))
    out = io.BytesIO()
    copy.save(out, "JPEG", quality=82)
    return out.getvalue()


def _case_name(name: str) -> str:
    cleaned = display_filename(name or "Evidence case", 0)
    return cleaned[:80] or "Evidence case"


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _error_text(exc: AnalysisError) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        return str(detail.get("message") or "This image was rejected.")
    return str(detail)

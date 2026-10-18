import os
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.analyze import (
    MAX_BYTES,
    MAX_UPLOAD_FILES,
    AnalysisError,
    analyze_bytes,
    decode_image_b64,
    object_list,
    parse_events,
    parse_sensors,
)
from app.batch import analyze_many, preview, scan_folder
from app import cases
from app.demo import build_demo_image, demo_case
from app.evidence import DEMO_ACTIVITY, build_evidence
from app.gemini import GeminiError, explain
from app import search_demo
from app import vision


def _cors_origins() -> list[str]:
    raw = os.environ.get("METADEX_CORS_ORIGINS", "")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _folder_scan_enabled() -> bool:
    """Server-path scans stay off unless this process was started for local use."""
    return os.environ.get("STILLFRAME_ALLOW_FOLDER_SCAN", "0") == "1"


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    cases.start_sweeper()
    if os.environ.get("METADEX_PRELOAD_MODEL", "0") == "1":
        try:
            vision.load()
        except vision.EncoderError:
            pass
    yield
    cases.stop_sweeper()


app = FastAPI(
    title="Stillframe",
    version="2.1.0",
    lifespan=_lifespan,
    description=(
        "Local image-forensics API. It looks for hidden-data indicators, ranks a folder of images by suspicion, "
        "correlates a submitted host timeline, and scores submitted device readings. Those conclusions stay separate. "
        "An evidence case can also be searched by visual similarity with a local OpenCLIP model. "
        "Nothing recovered is executed, and evidence files are opened read only."
    ),
)

_origins = _cors_origins()
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
else:
    # Local dashboard pages only, until METADEX_CORS_ORIGINS names the real frontend.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )


class AnalyzeJson(BaseModel):
    filename: Optional[str] = None
    image_base64: str = Field(..., description="PNG, JPEG, or BMP bytes as standard base64. A data: URL is accepted.")
    activity_events: Optional[list[dict[str, Any]]] = None
    sensor_samples: Optional[list[dict[str, Any]]] = None


class ScanFolder(BaseModel):
    path: str = Field(..., description="Folder on this computer, for example ~/Desktop/seized_images")
    recursive: bool = Field(False, description="Also scan subfolders (up to 6 levels)")
    activity_events: Optional[list[dict[str, Any]]] = None
    sensor_samples: Optional[list[dict[str, Any]]] = None


class ExplainFinding(BaseModel):
    level: str = Field(..., max_length=30)
    reasons: list[str] = Field(default_factory=list, max_length=5)
    sensor_notes: list[str] = Field(default_factory=list, max_length=5)


def _run(data: bytes, filename: str | None, events, sensors) -> dict:
    try:
        return analyze_bytes(data, filename, events, sensors)
    except AnalysisError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _slim(result: dict, include_reports: bool) -> dict:
    if not include_reports:
        for entry in result["ranking"]:
            entry.pop("report", None)
    return result


@app.get("/health")
def health():
    search = vision.status()
    return {
        "status": "degraded" if search["state"] == "failed" else "ok",
        "service": "stillframe",
        "version": app.version,
        "search": search,
    }


@app.get("/api/search/status")
def search_status():
    """Model readiness and the device that will actually run inference."""
    return vision.status()


@app.post("/api/explain")
async def explain_finding(body: ExplainFinding):
    """Explain finding labels on demand without uploading images or recovered text."""
    try:
        text = await run_in_threadpool(explain, body.level, body.reasons, body.sensor_notes)
    except GeminiError as exc:
        raise HTTPException(status_code=503, detail={"message": str(exc)}) from exc
    return {"text": text}


@app.get("/api/demo-case")
def get_demo_case():
    """Fixture image (base64), activity timeline, and sensor readings. Does not run analysis."""
    return demo_case()


@app.post("/api/demo-analyze")
def demo_analyze():
    """Build the exercise case, run the same analyzer as /api/analyze, return findings as JSON."""
    case = demo_case()
    report = _run(build_demo_image(), case["filename"], case["activity_events"], case["sensor_samples"])
    report["case"] = {
        "id": case["case_id"],
        "title": case["title"],
        "filename": case["filename"],
        "fixture": True,
        "scenario": case["scenario"],
    }
    return report


@app.post("/api/analyze")
async def analyze(
    image: UploadFile = File(...),
    activity_events: Optional[str] = Form(None),
    sensor_samples: Optional[str] = Form(None),
):
    """Multipart upload of one image. Use /api/analyze-json if the client already has a JSON body."""
    try:
        events = parse_events(activity_events)
        sensors = parse_sensors(sensor_samples)
    except AnalysisError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    data = await image.read(MAX_BYTES + 1)
    return _run(data, image.filename, events, sensors)


@app.post("/api/analyze-json")
def analyze_json(body: AnalyzeJson):
    """Same analyzer as /api/analyze. Image, events, and sensors all travel as JSON."""
    try:
        events = object_list(body.activity_events, "activity_events")
        sensors = object_list(body.sensor_samples, "sensor_samples")
        data = decode_image_b64(body.image_base64)
    except AnalysisError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return _run(data, body.filename, events, sensors)


@app.post("/api/scan-folder")
def scan_folder_endpoint(body: ScanFolder, include_reports: bool = Query(True)):
    """Scan a folder on this computer. Disabled unless the server is the local workbench."""
    if not _folder_scan_enabled():
        raise HTTPException(
            status_code=403,
            detail={
                "message": (
                    "Folder scanning is disabled on this server. Upload the images you want checked. "
                    "This endpoint is only available when Metadex is running on your own computer."
                )
            },
        )
    try:
        events = object_list(body.activity_events, "activity_events")
        sensors = object_list(body.sensor_samples, "sensor_samples")
        result = scan_folder(body.path, body.recursive, events, sensors)
    except AnalysisError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return _slim(result, include_reports)


@app.post("/api/analyze-batch")
async def analyze_batch(
    images: list[UploadFile] = File(...),
    activity_events: Optional[str] = Form(None),
    sensor_samples: Optional[str] = Form(None),
    include_reports: bool = Query(True),
):
    """Several files in one multipart request, for a browser folder picker. Same response as /api/scan-folder."""
    if len(images) > MAX_UPLOAD_FILES:
        raise HTTPException(status_code=413, detail={"message": f"At most {MAX_UPLOAD_FILES} files per request"})
    try:
        events = parse_events(activity_events)
        sensors = parse_sensors(sensor_samples)
    except AnalysisError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    items = []
    for upload in images:
        items.append((upload.filename or "", await upload.read(MAX_BYTES + 1)))
    result = await run_in_threadpool(analyze_many, items, events, sensors, {"type": "upload", "count": len(items)})
    return _slim(result, include_reports)


@app.post("/api/demo-batch")
def demo_batch(include_reports: bool = Query(True)):
    """Rank the built in evidence set (a pretend seized laptop folder) with its prepared activity timeline."""
    evidence = build_evidence()
    items = [(item["filename"], item["data"]) for item in evidence]
    result = analyze_many(
        items, DEMO_ACTIVITY, None, {"type": "demo", "title": "Seized laptop, Pictures folder", "count": len(items)}, keep_previews=True
    )
    return _slim(result, include_reports)


@app.get("/api/preview/{scan_id}/{item_id}")
def preview_image(scan_id: str, item_id: str):
    """The image itself, for display. Only files from one of the last 10 folder or demo scans. Read only."""
    found = preview(scan_id, item_id)
    if not found:
        raise HTTPException(status_code=404, detail={"message": "No preview for that scan and file. Previews last for the 10 most recent scans."})
    data, media_type = found
    return Response(content=data, media_type=media_type, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@app.get("/api/demo-answers")
def demo_answers():
    """Answer key for the demo evidence set: what was planted in each file and the expected level."""
    return {
        "files": [
            {"filename": item["filename"], "planted": item["planted"], "expected": item["expected"]}
            for item in build_evidence()
        ]
    }


class SearchQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=400)


def _case_error(exc: cases.CaseError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"message": exc.message})


async def _collect_uploads(images: list[UploadFile]) -> tuple[list[dict], list[dict]]:
    """Read uploads up to the existing file and byte limits. Extra files become per-file errors."""
    kept: list[dict] = []
    rejected: list[dict] = []
    total = 0
    budget = cases.max_total_bytes()
    for index, upload in enumerate(images):
        filename = cases.display_filename(upload.filename, index)
        if len(kept) >= MAX_UPLOAD_FILES:
            rejected.append(
                {
                    "filename": filename,
                    "reason": f"This case accepts at most {MAX_UPLOAD_FILES} images.",
                }
            )
            await upload.close()
            continue
        data = await upload.read(MAX_BYTES + 1)
        await upload.close()
        if total + len(data) > budget:
            rejected.append({"filename": filename, "reason": "This file would exceed the case size limit."})
            continue
        total += len(data)
        kept.append({"filename": upload.filename or filename, "data": data, "index": index})
    return kept, rejected


@app.get("/api/cases")
def read_cases():
    """List open cases. An empty list is a normal response, not a missing route."""
    return cases.list_cases()


@app.post("/api/cases")
async def create_case(images: list[UploadFile] = File(...), name: str = Form("")):
    """Index uploaded images and run the same forensic analyzer as a manual scan."""
    if not images:
        raise HTTPException(status_code=400, detail={"message": "Choose at least one image."})
    kept, rejected = await _collect_uploads(images)
    try:
        return cases.start_case(name, kept, source="upload", rejected=rejected)
    except cases.CaseError as exc:
        raise _case_error(exc) from exc


@app.post("/api/cases/demo")
def create_demo_case():
    """Index the built-in demo images. Nothing is downloaded."""
    try:
        return cases.start_case(
            "Technica demo case",
            search_demo.build_items(),
            source="demo",
            suggested=search_demo.SUGGESTED_QUERIES,
        )
    except cases.CaseError as exc:
        raise _case_error(exc) from exc


@app.get("/api/cases/{case_id}")
def read_case(case_id: str):
    try:
        return cases.get_case(case_id)
    except cases.CaseError as exc:
        raise _case_error(exc) from exc


@app.delete("/api/cases/{case_id}", status_code=204)
def remove_case(case_id: str):
    try:
        cases.delete_case(case_id)
    except cases.CaseError as exc:
        raise _case_error(exc) from exc
    return Response(status_code=204)


@app.post("/api/cases/{case_id}/search")
def search_case(case_id: str, body: SearchQuery):
    try:
        return cases.search(case_id, body.query)
    except cases.CaseError as exc:
        raise _case_error(exc) from exc


@app.get("/api/cases/{case_id}/items/{item_id}")
def read_case_item(case_id: str, item_id: str):
    try:
        return cases.item_detail(case_id, item_id)
    except cases.CaseError as exc:
        raise _case_error(exc) from exc


@app.get("/api/cases/{case_id}/items/{item_id}/preview")
def read_case_preview(case_id: str, item_id: str):
    try:
        data = cases.preview_bytes(case_id, item_id)
    except cases.CaseError as exc:
        raise _case_error(exc) from exc
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )

from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.analyze import (
    MAX_BYTES,
    AnalysisError,
    analyze_bytes,
    decode_image_b64,
    object_list,
    parse_events,
    parse_sensors,
)
from app.batch import analyze_many, preview, scan_folder
from app.demo import build_demo_image, demo_case
from app.evidence import DEMO_ACTIVITY, build_evidence
from app.gemini import GeminiError, explain

MAX_UPLOAD_FILES = 200

app = FastAPI(
    title="Stillframe",
    version="2.0.0",
    description=(
        "Local image-forensics API. It looks for hidden-data indicators, ranks a folder of images by suspicion, "
        "correlates a submitted host timeline, and scores submitted device readings. Those conclusions stay separate. "
        "Nothing recovered is executed or written to disk, and evidence files are opened read only."
    ),
)

# Only local dashboard pages may call this service from a browser. In particular,
# other websites must not be able to spend the configured Gemini key.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
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
    return {"status": "ok", "service": "stillframe", "version": app.version}


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
    """Scan every PNG, JPEG, and BMP in a folder on this computer and rank them. Files are opened read only."""
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

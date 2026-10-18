"""Fixed exercise case. The image is built in memory and analyzed by the normal pipeline."""
import base64
import io

from PIL import Image, ImageDraw

from app.recovery import embed_demo

CASE_ID = "1042"
FILENAME = "invoice-scan.png"
MESSAGE = "DEMO-CASE-1042 check-in. Fixture message for the forensics exercise. Not a live channel."
TRAILER = b"DEMO-TRAILER"

ACTIVITY = [
    {
        "timestamp": "2026-10-17T14:02:11Z",
        "host_id": "ws-14.corp.example",
        "user": "j.okonkwo",
        "event_type": "file_write",
        "process_name": "msedge.exe",
        "file_path": "C:\\Users\\j.okonkwo\\Downloads\\invoice-scan.png",
        "detail": "Browser saved the download",
    },
    {
        "timestamp": "2026-10-17T14:04:02Z",
        "host_id": "ws-14.corp.example",
        "user": "j.okonkwo",
        "event_type": "file_read",
        "process_name": "ImageDecodeHost.exe",
        "file_path": "C:\\Users\\j.okonkwo\\Downloads\\invoice-scan.png",
        "command_line": "ImageDecodeHost.exe --open invoice-scan.png",
        "detail": "A different process opened the image",
    },
    {
        "timestamp": "2026-10-17T14:04:19Z",
        "host_id": "ws-14.corp.example",
        "user": "j.okonkwo",
        "event_type": "network_send",
        "process_name": "ImageDecodeHost.exe",
        "destination": "203.0.113.50:443",
        "bytes_sent": 428,
        "detail": "Outbound send from the process that had just read the image",
    },
    {
        "timestamp": "2026-10-17T14:10:00Z",
        "host_id": "ws-14.corp.example",
        "user": "j.okonkwo",
        "event_type": "process_start",
        "process_name": "SearchIndexer.exe",
        "detail": "Later process with no path back to the image. Included so the timeline is not only the sequence under review.",
    },
]

SENSORS = [
    {
        "timestamp": "2026-10-17T14:04:05Z",
        "host_id": "ws-14.corp.example",
        "sensor_type": "cpu_temperature",
        "value": 91,
        "unit": "celsius",
    },
    {
        "timestamp": "2026-10-17T14:04:05Z",
        "host_id": "ws-14.corp.example",
        "sensor_type": "accelerometer",
        "value": 0.8,
        "unit": "m/s^2",
    },
]


def build_demo_image() -> bytes:
    canvas = Image.new("RGB", (420, 280), (244, 241, 232))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((16, 16, 403, 263), outline=(36, 44, 38), width=2)
    draw.rectangle((16, 16, 403, 68), fill=(36, 44, 38))
    draw.text((32, 28), "INVOICE  1042", fill=(244, 241, 232))
    draw.text((32, 44), "Northwind Supplies", fill=(198, 204, 190))
    draw.text((32, 92), "Scan copy", fill=(36, 44, 38))
    draw.text((32, 114), "Demonstration fixture — not a customer document", fill=(96, 102, 92))
    draw.line((32, 150, 388, 150), fill=(190, 184, 170), width=1)
    for index, label in enumerate(("Paper stock", "Print run", "Archive copy")):
        y = 168 + index * 24
        draw.text((32, y), label, fill=(70, 76, 68))
        draw.line((140, y + 8, 388, y + 8), fill=(210, 204, 192))
    stamped = embed_demo(canvas, MESSAGE)
    out = io.BytesIO()
    stamped.save(out, format="PNG")
    return out.getvalue() + TRAILER


def demo_case() -> dict:
    image = build_demo_image()
    return {
        "case_id": CASE_ID,
        "title": "Invoice scan",
        "filename": FILENAME,
        "media_type": "image/png",
        "image_base64": base64.b64encode(image).decode("ascii"),
        "scenario": (
            "Exercise hypothesis: a payload or check-in was hidden in an invoice image. "
            "The prepared timeline has the browser save the file, another process read it, "
            "and that process open an outbound connection. Sensor readings are a separate device-health note."
        ),
        "activity_events": ACTIVITY,
        "sensor_samples": SENSORS,
        "prepared_note": (
            "Fixture data. The image, timeline, and sensor readings are sent through POST /api/analyze, "
            "the same path as an analyst upload. The verdict is not hard-coded."
        ),
    }

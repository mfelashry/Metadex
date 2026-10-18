"""Score sensor readings the analyst chose to submit.

The readings are a safety note for the person holding the device and the place
around it: heat, a hard jolt, a fast spin, darkness, or something against the
sensor. Nothing here opens a device, samples hardware, or decides that an
image is hostile. Thresholds are demonstration values for the exercise.
"""
from __future__ import annotations

ALLOWED = {"accelerometer", "gyroscope", "cpu_temperature", "battery_temperature", "light", "proximity"}
TEMP_THRESHOLD = 85
ACCEL_THRESHOLD = 30
GYRO_THRESHOLD = 8
LIGHT_DARK = 5
PROXIMITY_NEAR = 1


def assess(samples, strain: dict) -> dict:
    strain = dict(strain or {})
    strain["note"] = _strain_note(strain)
    if not samples:
        return {
            "status": "not_assessed",
            "headline": "Device health not assessed",
            "samples": [],
            "observations": [],
            "ignored": 0,
            "strain": strain,
            "explanation": "No sensor samples were submitted. This workbench does not read CPU, battery, or motion hardware.",
        }
    observations = []
    ignored = 0
    for index, sample in enumerate(samples):
        kind = sample.get("sensor_type")
        value = sample.get("value")
        if kind not in ALLOWED or isinstance(value, bool) or not isinstance(value, (int, float)) or not -1e6 <= value <= 1e6:
            ignored += 1
            continue
        condition, reason = _condition(kind, value)
        if condition:
            observations.append(
                {
                    "index": index,
                    "condition": condition,
                    "reason": reason,
                    "sample": sample,
                }
            )
    if observations:
        status, headline = "condition_observed", "Person or place needs a look"
    else:
        status, headline = "no_condition_noted", "No safety condition noted"
    link = _link_note(observations, strain)
    explanation = (
        "Readings describe the device at the times the analyst supplied. "
        "They are not an attack verdict, and they do not show that the image hid a command. "
        + link
    )
    return {
        "status": status,
        "headline": headline,
        "samples": samples,
        "observations": observations,
        "ignored": ignored,
        "strain": strain,
        "thresholds": {
            "cpu_or_battery_celsius": TEMP_THRESHOLD,
            "accelerometer_magnitude": ACCEL_THRESHOLD,
            "gyroscope_magnitude": GYRO_THRESHOLD,
            "light_lux_at_or_below": LIGHT_DARK,
            "proximity_cm_at_or_below": PROXIMITY_NEAR,
            "note": "Demonstration thresholds for a person or a place. They are not intrusion indicators.",
        },
        "explanation": explanation.strip(),
    }


def _strain_note(strain: dict) -> str:
    if strain.get("rejected"):
        reason = strain.get("reason") or "a hard limit"
        return f"The file was refused ({reason}). A temperature reading taken while a scanner rejects an oversized or malformed image can reflect scanner strain."
    byte_ratio = strain.get("bytes_ratio")
    pixel_ratio = strain.get("pixel_ratio")
    if byte_ratio is None and pixel_ratio is None:
        return "Scanner budget was not computed for this file."
    near = strain.get("near_limit")
    size_txt = _pct(byte_ratio)
    pixel_txt = _pct(pixel_ratio)
    if near:
        return f"The image uses {size_txt} of the {strain.get('max_bytes')} byte budget and {pixel_txt} of the pixel budget. It is close to a hard limit."
    return (
        f"The image uses {size_txt} of the byte budget and {pixel_txt} of the pixel budget. "
        "It is well inside the scanner limits, so a high temperature should not be blamed on this file's size."
    )


def _condition(kind: str, value: float) -> tuple[str | None, str]:
    label = kind.replace("_", " ")
    if kind in ("cpu_temperature", "battery_temperature") and value >= TEMP_THRESHOLD:
        return "Elevated temperature", f"{label} is {value:g}, at or above the demonstration threshold of {TEMP_THRESHOLD}."
    if kind == "accelerometer" and abs(value) >= ACCEL_THRESHOLD:
        return "Large acceleration", f"Accelerometer magnitude is {value:g}, at or above the demonstration threshold of {ACCEL_THRESHOLD}."
    if kind == "gyroscope" and abs(value) >= GYRO_THRESHOLD:
        return "Fast rotation", f"Gyroscope magnitude is {value:g}, at or above the demonstration threshold of {GYRO_THRESHOLD}."
    if kind == "light" and value <= LIGHT_DARK:
        return "Very little light", f"Light is {value:g} lux, at or below the demonstration threshold of {LIGHT_DARK}. The place may be dark, or the sensor may be covered."
    if kind == "proximity" and value <= PROXIMITY_NEAR:
        return "Something is against the device", f"Proximity is {value:g} cm, at or below the demonstration threshold of {PROXIMITY_NEAR}. Something is very close to the device."
    return None, ""


def _link_note(observations: list, strain: dict) -> str:
    temps = [item for item in observations if item["condition"] == "Elevated temperature"]
    if not temps:
        if any(item["condition"] in ("Large acceleration", "Fast rotation") for item in observations):
            return "Motion is recorded as a safety note for the person holding the device. It is not tied to the image contents."
        if any(item["condition"] in ("Very little light", "Something is against the device") for item in observations):
            return "Light and proximity describe the place around the device. They are not tied to the image contents."
        return ""
    if strain.get("rejected") or strain.get("near_limit"):
        return "Elevated temperature overlaps a file that strained or was refused by the scanner. Record both. Do not upgrade either one into an intrusion finding."
    return "Elevated temperature does not line up with scanner strain for this file. Keep it in the device-health panel only."


def _pct(ratio) -> str:
    if ratio is None:
        return "n/a"
    return f"{ratio * 100:.2f}%"

"""Turn the hidden-data rules into one suspicion score for ranking.

The score only uses image evidence. Activity and device health stay in their
own panels, so a hot CPU or a busy timeline can never push an image up the list.
The score is a triage order for the examiner, not proof of anything.
"""

# Points each rule adds when it fires. Tune here.
WEIGHTS = {
    "SF-APP-001": 35,  # bytes after the end of the image
    "SF-MAG-001": 30,  # those bytes start with another file's signature (a second file is hidden)
    "SF-ENT-001": 15,  # those bytes look compressed or encrypted
    "SF-LSB-001": 40,  # pixel least-significant-bit statistics
    "SF-META-001": 10,  # known carrier key or long PNG text / JPEG comment
    "SF-REC-001": 20,  # readable hidden content was recovered (30 when it came out of the pixels)
    "SF-TYPE-001": 20,  # extension does not match the real file type
    "SF-STRUCT-002": 10,  # broken checksums or headers
}
PIXEL_RECOVERY_WEIGHT = 30
# SF-META-002 uses the weight of its strongest field (25 to 45), set in metadata_messages.py.

LEVELS = (
    (60, "high", "High"),
    (35, "suspicious", "Suspicious"),
    (1, "low", "Low"),
    (0, "none", "No indicators"),
)
LEVEL_ORDER = {"high": 3, "suspicious": 2, "low": 1, "none": 0}


def level_for(score: int) -> tuple[str, str]:
    for floor, key, label in LEVELS:
        if score >= floor:
            return key, label
    return "none", "No indicators"


def score_rules(rules: list, meta_weight: int, pixel_message: bool = False) -> dict:
    contributions = []
    for rule in rules:
        rid = rule["id"]
        fired = rule["result"] in ("indicator", "recovered", "anomaly")
        if not fired:
            continue
        if rid == "SF-META-002":
            points = meta_weight
        elif rid == "SF-REC-001" and pixel_message:
            points = PIXEL_RECOVERY_WEIGHT
        else:
            points = WEIGHTS.get(rid, 0)
        if points:
            contributions.append({"rule_id": rid, "name": rule["name"], "points": points, "detail": rule["detail"]})
    contributions.sort(key=lambda c: c["points"], reverse=True)
    score = min(100, sum(c["points"] for c in contributions))
    key, label = level_for(score)
    return {
        "score": score,
        "level": key,
        "level_label": label,
        "thresholds": {"high": 60, "suspicious": 35, "low": 1},
        "contributions": contributions,
        "top_reasons": [c["detail"] for c in contributions[:3]],
        "statement": "Suspicion level for triage. It ranks which images to examine first. It is not proof of hidden data or intent.",
    }

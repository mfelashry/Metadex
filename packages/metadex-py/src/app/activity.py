"""Correlate a submitted host timeline with the image filename.

The workbench does not collect process, file, or network telemetry. It only
orders events the analyst pasted in and looks for one sequence: the image
arrives, a process reads it, and that process later makes an outbound connection.
"""
import ipaddress
from datetime import datetime, timezone
from pathlib import PurePath

ARRIVAL = {"file_write", "file_create", "file_download"}
READ = {"file_open", "file_read", "file_access"}
NETWORK = {"network", "network_connection", "network_send", "dns_query", "socket_connect"}
SEQUENCE_WINDOW_SECONDS = 15 * 60

DOC_NETS = (
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
)


def classify_destination(destination) -> dict | None:
    if not destination:
        return None
    raw = str(destination).strip()
    host = raw
    if host.startswith("[") and "]" in host:
        host = host[1 : host.index("]")]
    elif host.count(":") == 1 and not host.endswith(":"):
        left, right = host.rsplit(":", 1)
        if right.isdigit():
            host = left
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return {"value": raw, "host": host, "class": "hostname", "note": "Name was not resolved. This workbench does not perform DNS lookups."}
    if any(ip in net for net in DOC_NETS):
        kind, note = "documentation", "TEST-NET documentation address (RFC 5737). Not a production destination."
    elif ip.is_loopback:
        kind, note = "loopback", "Loopback address."
    elif ip.is_private or ip.is_link_local:
        kind, note = "private", "Private or link-local address."
    elif ip.is_global:
        kind, note = "public", "Public address. No allow-list was supplied, so “unexpected” is an analyst judgment."
    else:
        kind, note = "special", "Special-purpose address."
    return {"value": raw, "host": str(ip), "class": kind, "note": note}


def _parse_time(value):
    if value is None or value == "":
        return None, "missing timestamp"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None, "unparseable timestamp"
    if parsed.tzinfo is None:
        return None, "timestamp has no timezone"
    return parsed.astimezone(timezone.utc), "ok"


def _basename(path: str) -> str:
    return PurePath(str(path).replace("\\", "/")).name.lower()


def correlate(events, filename: str) -> dict:
    if not events:
        return {
            "status": "not_assessed",
            "headline": "Activity not assessed",
            "sequence": None,
            "related_events": [],
            "timeline": [],
            "data_quality": [],
            "explanation": "No host events were submitted. Endpoint activity was not collected or assessed.",
        }
    target = _basename(filename or "")
    timeline = []
    quality = []
    for index, event in enumerate(events):
        when, q = _parse_time(event.get("timestamp"))
        if q != "ok":
            quality.append(f"Event {index}: {q}")
        path = str(event.get("file_path") or "")
        matched = bool(target) and bool(path) and _basename(path) == target
        destination = classify_destination(event.get("destination"))
        timeline.append(
            {
                "index": index,
                "timestamp": when.isoformat() if when else None,
                "time_quality": q,
                "sort_key": when,
                "host_id": event.get("host_id"),
                "user": event.get("user"),
                "event_type": event.get("event_type"),
                "process_name": event.get("process_name"),
                "file_path": path or None,
                "filename_match": matched,
                "destination": destination,
                "bytes_sent": event.get("bytes_sent"),
                "command_line": event.get("command_line"),
                "detail": event.get("detail"),
                "event": event,
                "sequence_role": None,
                "related": False,
                "reasons": [],
            }
        )
    file_hits = [row for row in timeline if row["filename_match"]]
    if not file_hits:
        ordered = _ordered(timeline)
        _strip(ordered)
        return {
            "status": "no_indicator_found",
            "headline": "No related activity",
            "sequence": None,
            "related_events": [],
            "timeline": ordered,
            "data_quality": quality,
            "explanation": "No submitted event names this image. That does not rule out activity under another filename.",
        }

    arrivals = [row for row in file_hits if row["event_type"] in ARRIVAL and row["sort_key"] is not None]
    reads = [row for row in file_hits if row["event_type"] in READ and row["process_name"] and row["sort_key"] is not None]
    arrival = min(arrivals, key=lambda row: row["sort_key"]) if arrivals else None
    read = None
    if arrival:
        later = [row for row in reads if row["sort_key"] >= arrival["sort_key"] and row["index"] != arrival["index"]]
        read = min(later, key=lambda row: row["sort_key"]) if later else None
    elif reads:
        read = min(reads, key=lambda row: row["sort_key"])
    network = None
    if read and read["sort_key"] is not None and read.get("host_id"):
        candidates = []
        for row in timeline:
            if row["event_type"] not in NETWORK or row["sort_key"] is None:
                continue
            if row["sort_key"] < read["sort_key"]:
                continue
            if row["host_id"] != read["host_id"]:
                continue
            if row["process_name"] != read["process_name"]:
                continue
            delta = (row["sort_key"] - read["sort_key"]).total_seconds()
            if delta <= SEQUENCE_WINDOW_SECONDS:
                candidates.append(row)
        if candidates:
            network = min(candidates, key=lambda row: row["sort_key"])

    steps = []
    if arrival:
        arrival["sequence_role"] = "file_arrival"
        arrival["related"] = True
        arrival["reasons"].append("File path basename matches the uploaded image, and the event records the file arriving")
        steps.append(_step("file_arrival", arrival, None))
    if read:
        read["sequence_role"] = "process_read"
        read["related"] = True
        read["reasons"].append("A process opened or read the image")
        delta = (read["sort_key"] - arrival["sort_key"]).total_seconds() if arrival else None
        steps.append(_step("process_read", read, delta))
    if network:
        network["sequence_role"] = "outbound"
        network["related"] = True
        network["reasons"].append("Same process and host made an outbound connection within 15 minutes of the read")
        delta = (network["sort_key"] - read["sort_key"]).total_seconds() if read else None
        steps.append(_step("outbound", network, delta))

    complete = bool(arrival and read and network)
    handoff = None
    if arrival and read and arrival.get("process_name") and read.get("process_name"):
        if arrival["process_name"] != read["process_name"]:
            handoff = f"{arrival['process_name']} wrote the file and {read['process_name']} read it"
        else:
            handoff = f"The same process ({read['process_name']}) both wrote and read the file"

    if complete:
        status, headline = "correlated", "Activity correlated"
        explanation = (
            "The submitted timeline contains the sequence this workbench looks for: the image arrives, a process reads it, "
            "and that process makes an outbound connection. The link is filename, host, process, and time. "
            "It does not prove the image caused the connection or identify a person."
        )
    elif file_hits:
        status, headline = "partial", "Filename overlap only"
        explanation = (
            "At least one event names this image, but the arrival → process read → outbound sequence is incomplete. "
            "Treat the overlap as context, not as a confirmed handoff."
        )
    else:
        status, headline = "no_indicator_found", "No related activity"
        explanation = "No submitted event names this image."

    related = []
    for row in timeline:
        if row["related"]:
            related.append({"index": row["index"], "reasons": list(row["reasons"]), "event": row["event"]})
    sequence = None
    if steps:
        sequence = {"complete": complete, "window_seconds": SEQUENCE_WINDOW_SECONDS, "steps": steps, "handoff": handoff}
    ordered = _ordered(timeline)
    _strip(ordered)
    return {
        "status": status,
        "headline": headline,
        "sequence": sequence,
        "related_events": related,
        "timeline": ordered,
        "data_quality": quality,
        "explanation": explanation,
    }


def _step(role: str, row: dict, delta: float | None) -> dict:
    return {
        "role": role,
        "index": row["index"],
        "timestamp": row["timestamp"],
        "event_type": row["event_type"],
        "process_name": row["process_name"],
        "host_id": row["host_id"],
        "delta_seconds_from_previous": None if delta is None else round(delta, 3),
        "destination": row["destination"],
    }


def _ordered(timeline: list) -> list:
    def key(row):
        return (row["sort_key"] is None, row["sort_key"] or datetime.min.replace(tzinfo=timezone.utc), row["index"])

    return sorted(timeline, key=key)


def _strip(timeline: list) -> None:
    for row in timeline:
        row.pop("sort_key", None)
        row.pop("event", None)

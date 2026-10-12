"""Parse CloudTrail envelopes without making AWS calls."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Any


class EventValidationError(ValueError):
    """The input cannot be safely interpreted as CloudTrail events."""


@dataclass(frozen=True)
class NormalizedEvent:
    event_id: str
    timestamp: str
    source: str
    action: str
    region: str | None
    identity: dict[str, Any] | None
    source_ip: str | None
    error_code: str | None
    error_message: str | None
    source_reference: str


def _text(
    record: dict[str, Any], location: str, field: str, *, required: bool = False
) -> str | None:
    value = record.get(field)
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        expectation = "a nonempty string" if required else "a string or null"
        raise EventValidationError(f"{location}.{field}: expected {expectation}")
    return value


def normalize_events(payload: object, *, source_reference: str) -> list[NormalizedEvent]:
    """Validate a complete envelope; preserve its provenance (path or object URI).

    Optional null fields are accepted. Unknown fields are ignored. Source IP is
    preserved as text because CloudTrail can also record service names there.
    """
    if not isinstance(source_reference, str) or not source_reference.strip():
        raise EventValidationError("source_reference must be a nonempty string")
    if not isinstance(payload, dict) or not isinstance(payload.get("Records"), list):
        raise EventValidationError(f"{source_reference}: expected an object with a Records list")
    events = []
    for index, record in enumerate(payload["Records"]):
        location = f"{source_reference}: Records[{index}]"
        if not isinstance(record, dict):
            raise EventValidationError(f"{location}: expected an event object")

        text = partial(_text, record, location)

        event_id = text("eventID", required=True)
        timestamp = text("eventTime", required=True)
        source = text("eventSource", required=True)
        action = text("eventName", required=True)
        try:
            parsed_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed_time.utcoffset() is None:
                raise ValueError("missing timezone")
        except ValueError as exc:
            raise EventValidationError(
                f"{location}.eventTime: expected an ISO 8601 timestamp with timezone"
            ) from exc
        identity = record.get("userIdentity")
        if identity is not None and not isinstance(identity, dict):
            raise EventValidationError(f"{location}.userIdentity: expected an object or null")
        events.append(
            NormalizedEvent(
                event_id=event_id,
                timestamp=timestamp,
                source=source,
                action=action,
                region=text("awsRegion"),
                identity=deepcopy(identity),
                source_ip=text("sourceIPAddress"),
                error_code=text("errorCode"),
                error_message=text("errorMessage"),
                source_reference=source_reference,
            )
        )
    return events

"""Payload schema validation and construction.

Mirrors firmware/include/mqtt_client.h's inbound validation: check
schema_version, required fields, and types before anything downstream
acts on a payload. Range/plausibility validation of the humidity/
temperature values themselves is the rule engine's job (rules.py),
matching the firmware split between MQTT-layer and controller-layer
validation - see docs/security.md "Command validation".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

SCHEMA_VERSION = 1
MAX_PAYLOAD_BYTES = 2048


def validate_telemetry(payload: Any) -> Tuple[bool, Optional[str]]:
    if not isinstance(payload, dict):
        return False, "payload is not a JSON object"

    if payload.get("schema_version") != SCHEMA_VERSION:
        return False, f"unsupported schema_version: {payload.get('schema_version')!r}"

    required_types = {
        "device_id": str,
        "humidity_percent": (int, float),
        "temperature_celsius": (int, float),
        "sensor_valid": bool,
        "timestamp": str,
    }
    for field, expected_type in required_types.items():
        if field not in payload:
            return False, f"missing required field: {field}"
        if not isinstance(payload[field], expected_type):
            return False, f"field {field} has wrong type"

    if not parse_iso8601(payload["timestamp"]):
        return False, "timestamp is not valid ISO-8601"

    return True, None


def parse_iso8601(value: str) -> Optional[datetime]:
    try:
        v = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def now_iso8601() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_fan_desired_payload(desired_on: bool, reason: str, source: str = "automation") -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "desired_relay_on": desired_on,
        "reason": reason,
        "source": source,
        "issued_at": now_iso8601(),
    }

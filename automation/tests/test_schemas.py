from automation_service.schemas import (
    build_fan_desired_payload,
    parse_iso8601,
    validate_telemetry,
)

VALID_TELEMETRY = {
    "schema_version": 1,
    "device_id": "bathroom-vent-01",
    "seq": 1,
    "humidity_percent": 65.0,
    "temperature_celsius": 22.5,
    "sensor_valid": True,
    "timestamp": "2026-09-09T15:30:00Z",
}


def test_valid_telemetry_passes():
    ok, err = validate_telemetry(VALID_TELEMETRY)
    assert ok is True
    assert err is None


def test_non_object_payload_rejected():
    ok, err = validate_telemetry([1, 2, 3])
    assert ok is False
    assert "not a JSON object" in err


def test_wrong_schema_version_rejected():
    payload = dict(VALID_TELEMETRY, schema_version=99)
    ok, err = validate_telemetry(payload)
    assert ok is False
    assert "schema_version" in err


def test_missing_field_rejected():
    payload = dict(VALID_TELEMETRY)
    del payload["humidity_percent"]
    ok, err = validate_telemetry(payload)
    assert ok is False
    assert "humidity_percent" in err


def test_wrong_type_rejected():
    payload = dict(VALID_TELEMETRY, sensor_valid="yes")  # should be bool
    ok, err = validate_telemetry(payload)
    assert ok is False
    assert "sensor_valid" in err


def test_bad_timestamp_rejected():
    payload = dict(VALID_TELEMETRY, timestamp="not-a-date")
    ok, err = validate_telemetry(payload)
    assert ok is False
    assert "timestamp" in err


def test_boundary_humidity_values_are_schema_valid():
    # Schema validation only checks type, not physical plausibility -
    # range/plausibility checks are the rule engine's job (see
    # docs/security.md "Command validation"). 0 and 100 (and even
    # out-of-range 150) must pass *schema* validation; rules.py is what
    # rejects the impossible 150 value.
    for value in (0.0, 100.0, 150.0):
        payload = dict(VALID_TELEMETRY, humidity_percent=value)
        ok, _ = validate_telemetry(payload)
        assert ok is True


def test_parse_iso8601_accepts_zulu_suffix():
    dt = parse_iso8601("2026-09-09T15:30:00Z")
    assert dt is not None
    assert dt.year == 2026 and dt.hour == 15


def test_parse_iso8601_rejects_garbage():
    assert parse_iso8601("garbage") is None


def test_build_fan_desired_payload_shape():
    payload = build_fan_desired_payload(True, "humidity_above_threshold")
    assert payload["schema_version"] == 1
    assert payload["desired_relay_on"] is True
    assert payload["reason"] == "humidity_above_threshold"
    assert payload["source"] == "automation"
    assert parse_iso8601(payload["issued_at"]) is not None

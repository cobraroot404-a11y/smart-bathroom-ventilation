import json
from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock

from automation_service.config import AppConfig, MqttConfig, RuleConfig
from automation_service.mqtt_handler import (
    TOPIC_FAN_DESIRED,
    TOPIC_TELEMETRY,
    MqttHandler,
)
from automation_service.state import StateStore


def make_rule_config(**overrides) -> RuleConfig:
    defaults = dict(
        fan_on_percent=70.0,
        fan_off_percent=60.0,
        humidity_min_valid_percent=0.0,
        humidity_max_valid_percent=100.0,
        temperature_min_valid_celsius=-10.0,
        temperature_max_valid_celsius=60.0,
        min_fan_on_seconds=120,
        min_fan_off_seconds=30,
        max_continuous_runtime_seconds=1800,
        stale_telemetry_timeout_seconds=60,
        sensor_consecutive_failure_limit=3,
        sensor_invalid_hold_last_state=False,
        rise_rate_detection_enabled=False,
        rise_rate_threshold_percent_per_minute=3.0,
        rise_rate_window_seconds=60,
        rise_rate_min_valid_samples=4,
    )
    defaults.update(overrides)
    return RuleConfig(**defaults)


def make_app_config(**mqtt_overrides) -> AppConfig:
    mqtt_defaults = dict(
        host="localhost",
        port=1883,
        keepalive_seconds=30,
        username=None,
        password=None,
        use_tls=False,
        device_id="bathroom-vent-01",
        qos_telemetry=1,
        qos_state=1,
        reconnect_backoff_initial_seconds=1,
        reconnect_backoff_max_seconds=60,
        max_payload_bytes=2048,
    )
    mqtt_defaults.update(mqtt_overrides)
    return AppConfig(rule=make_rule_config(), mqtt=MqttConfig(**mqtt_defaults), fan_power_watts=25.0)


def make_handler(clock=lambda: 1000.0) -> MqttHandler:
    config = make_app_config()
    state = StateStore(config.rule)
    handler = MqttHandler(config, state, clock=clock)
    handler._client.publish = MagicMock()
    return handler


def telemetry_payload(**overrides):
    payload = {
        "schema_version": 1,
        "device_id": "bathroom-vent-01",
        "seq": 1,
        "humidity_percent": 75.0,
        "temperature_celsius": 23.0,
        "sensor_valid": True,
        "timestamp": "2026-09-09T15:30:00Z",
    }
    payload.update(overrides)
    return payload


def msg(topic, payload_dict=None, raw: Optional[bytes] = None):
    body = raw if raw is not None else json.dumps(payload_dict).encode("utf-8")
    return SimpleNamespace(topic=topic, payload=body)


def test_valid_telemetry_publishes_fan_desired():
    handler = make_handler()
    handler._on_message(None, None, msg(TOPIC_TELEMETRY, telemetry_payload()))

    handler._client.publish.assert_called_once()
    args, kwargs = handler._client.publish.call_args
    assert args[0] == TOPIC_FAN_DESIRED
    published = json.loads(args[1])
    assert published["schema_version"] == 1
    assert "desired_relay_on" in published
    assert kwargs["retain"] is True


def test_invalid_schema_version_is_discarded():
    handler = make_handler()
    handler._on_message(None, None,
                         msg(TOPIC_TELEMETRY, telemetry_payload(schema_version=99)))
    handler._client.publish.assert_not_called()


def test_malformed_json_is_discarded():
    handler = make_handler()
    handler._on_message(None, None, msg(TOPIC_TELEMETRY, raw=b"{not json"))
    handler._client.publish.assert_not_called()


def test_oversized_payload_is_discarded():
    handler = make_handler()
    handler._on_message(
        None, None,
        msg(TOPIC_TELEMETRY, raw=b"x" * (handler.config.mqtt.max_payload_bytes + 1)),
    )
    handler._client.publish.assert_not_called()


def test_duplicate_seq_is_not_reprocessed():
    handler = make_handler()
    handler._on_message(None, None, msg(TOPIC_TELEMETRY, telemetry_payload(seq=42)))
    handler._client.publish.assert_called_once()

    handler._client.publish.reset_mock()
    handler._on_message(None, None, msg(TOPIC_TELEMETRY, telemetry_payload(seq=42)))
    handler._client.publish.assert_not_called()


def test_boundary_humidity_values_do_not_crash_and_are_range_checked():
    handler = make_handler()
    # 150% is schema-valid but physically impossible - the rule engine
    # (not the MQTT layer) must reject it without raising.
    handler._on_message(None, None,
                         msg(TOPIC_TELEMETRY, telemetry_payload(seq=1, humidity_percent=150.0)))
    handler._client.publish.assert_called_once()
    args, _ = handler._client.publish.call_args
    published = json.loads(args[1])
    assert published["desired_relay_on"] is False  # no valid reading yet -> safe default

"""Configuration loading.

Reads config/defaults.yaml (the canonical, documented set of tunables -
see docs/architecture.md "Configuration as a single source of truth")
and layers environment variables (from .env / the process environment)
on top for secrets and deployment-specific overrides (broker host,
credentials).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional at import time
    load_dotenv = None


def repo_root() -> Path:
    # automation/automation_service/config.py -> repo root
    return Path(__file__).resolve().parents[2]


def default_config_path() -> Path:
    override = os.environ.get("BATHROOM_VENT_CONFIG_PATH")
    if override:
        return Path(override)
    return repo_root() / "config" / "defaults.yaml"


@dataclass(frozen=True)
class RuleConfig:
    fan_on_percent: float
    fan_off_percent: float
    humidity_min_valid_percent: float
    humidity_max_valid_percent: float
    temperature_min_valid_celsius: float
    temperature_max_valid_celsius: float
    min_fan_on_seconds: float
    min_fan_off_seconds: float
    max_continuous_runtime_seconds: float
    stale_telemetry_timeout_seconds: float
    sensor_consecutive_failure_limit: int
    sensor_invalid_hold_last_state: bool
    rise_rate_detection_enabled: bool
    rise_rate_threshold_percent_per_minute: float
    rise_rate_window_seconds: float
    rise_rate_min_valid_samples: int


@dataclass(frozen=True)
class MqttConfig:
    host: str
    port: int
    keepalive_seconds: int
    username: Optional[str]
    password: Optional[str]
    use_tls: bool
    device_id: str
    qos_telemetry: int
    qos_state: int
    reconnect_backoff_initial_seconds: float
    reconnect_backoff_max_seconds: float
    max_payload_bytes: int


@dataclass(frozen=True)
class AppConfig:
    rule: RuleConfig
    mqtt: MqttConfig
    fan_power_watts: float


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_config(config_path: Optional[Path] = None,
                 env_file: Optional[Path] = None) -> AppConfig:
    if load_dotenv is not None:
        load_dotenv(dotenv_path=env_file)

    path = config_path or default_config_path()
    raw = _load_yaml(path)

    thresholds = raw["thresholds"]
    timing = raw["timing"]
    sensor = raw["sensor"]
    relay = raw["relay"]
    rise = raw["rise_rate_detection"]
    device = raw["device"]
    mqtt_defaults = raw["mqtt"]
    energy = raw["energy"]

    rule = RuleConfig(
        fan_on_percent=float(thresholds["fan_on_percent"]),
        fan_off_percent=float(thresholds["fan_off_percent"]),
        humidity_min_valid_percent=float(thresholds["humidity_min_valid_percent"]),
        humidity_max_valid_percent=float(thresholds["humidity_max_valid_percent"]),
        temperature_min_valid_celsius=float(thresholds["temperature_min_valid_celsius"]),
        temperature_max_valid_celsius=float(thresholds["temperature_max_valid_celsius"]),
        min_fan_on_seconds=float(timing["min_fan_on_seconds"]),
        min_fan_off_seconds=float(timing["min_fan_off_seconds"]),
        max_continuous_runtime_seconds=float(timing["max_continuous_runtime_seconds"]),
        stale_telemetry_timeout_seconds=float(timing["stale_telemetry_timeout_seconds"]),
        sensor_consecutive_failure_limit=int(sensor["consecutive_failure_limit"]),
        sensor_invalid_hold_last_state=(relay["sensor_invalid_safe_state"] == "hold_last_state"),
        rise_rate_detection_enabled=bool(rise["enabled"]),
        rise_rate_threshold_percent_per_minute=float(rise["rise_threshold_percent_per_minute"]),
        rise_rate_window_seconds=float(rise["window_seconds"]),
        rise_rate_min_valid_samples=int(rise["min_valid_samples"]),
    )

    mqtt = MqttConfig(
        host=os.environ.get("MQTT_HOST", mqtt_defaults["broker_host"]),
        port=int(os.environ.get("MQTT_PORT", mqtt_defaults["broker_port"])),
        keepalive_seconds=int(mqtt_defaults["keepalive_seconds"]),
        username=os.environ.get("MQTT_AUTOMATION_USERNAME"),
        password=os.environ.get("MQTT_AUTOMATION_PASSWORD"),
        use_tls=os.environ.get("MQTT_USE_TLS", "false").lower() == "true",
        device_id=os.environ.get("MQTT_DEVICE_ID", device["device_id"]),
        qos_telemetry=int(mqtt_defaults["qos_telemetry"]),
        qos_state=int(mqtt_defaults["qos_state"]),
        reconnect_backoff_initial_seconds=float(mqtt_defaults["reconnect_backoff_initial_seconds"]),
        reconnect_backoff_max_seconds=float(mqtt_defaults["reconnect_backoff_max_seconds"]),
        max_payload_bytes=int(mqtt_defaults["max_payload_bytes"]),
    )

    fan_power_watts = float(os.environ.get("ENERGY_FAN_WATTS", energy["fan_power_watts"]))

    return AppConfig(rule=rule, mqtt=mqtt, fan_power_watts=fan_power_watts)

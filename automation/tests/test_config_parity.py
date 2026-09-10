"""Guards against config/defaults.yaml and firmware/include/config.h
drifting apart - see docs/architecture.md "Configuration as a single
source of truth". This does not compile the firmware; it just extracts
the compiled-in constexpr values with a small regex parser and compares
them to the canonical YAML.
"""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULTS_YAML = REPO_ROOT / "config" / "defaults.yaml"
FIRMWARE_CONFIG_H = REPO_ROOT / "firmware" / "include" / "config.h"

CONSTEXPR_RE = re.compile(
    r"constexpr\s+[\w:]+\s+(k\w+)\s*=\s*([^;]+);"
)


def parse_config_h(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    values = {}
    for name, raw_value in CONSTEXPR_RE.findall(text):
        raw_value = raw_value.strip().rstrip("fF")
        if raw_value in ("true", "false"):
            values[name] = raw_value == "true"
        else:
            try:
                values[name] = float(raw_value) if "." in raw_value else int(raw_value)
            except ValueError:
                values[name] = raw_value.strip('"')
    return values


def load_yaml_defaults() -> dict:
    with open(DEFAULTS_YAML, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_firmware_config_parses():
    values = parse_config_h(FIRMWARE_CONFIG_H)
    assert "kFanOnPercent" in values
    assert "kFanOffPercent" in values


def test_threshold_defaults_match():
    yaml_cfg = load_yaml_defaults()
    fw = parse_config_h(FIRMWARE_CONFIG_H)

    assert fw["kFanOnPercent"] == yaml_cfg["thresholds"]["fan_on_percent"]
    assert fw["kFanOffPercent"] == yaml_cfg["thresholds"]["fan_off_percent"]


def test_timing_defaults_match():
    yaml_cfg = load_yaml_defaults()
    fw = parse_config_h(FIRMWARE_CONFIG_H)

    assert fw["kMinFanOnSeconds"] == yaml_cfg["timing"]["min_fan_on_seconds"]
    assert fw["kMinFanOffSeconds"] == yaml_cfg["timing"]["min_fan_off_seconds"]
    assert fw["kMaxContinuousRuntimeSeconds"] == yaml_cfg["timing"]["max_continuous_runtime_seconds"]
    assert fw["kStaleCommandTimeoutSeconds"] == yaml_cfg["timing"]["stale_command_timeout_seconds"]


def test_relay_defaults_match():
    yaml_cfg = load_yaml_defaults()
    fw = parse_config_h(FIRMWARE_CONFIG_H)

    assert fw["kRelayActiveLow"] == yaml_cfg["relay"]["active_low"]
    assert fw["kRelayGpioPin"] == yaml_cfg["relay"]["gpio_pin"]
    assert fw["kRelayStartupOn"] is False  # must always be false regardless of YAML


def test_rise_rate_disabled_by_default_in_both():
    yaml_cfg = load_yaml_defaults()
    fw = parse_config_h(FIRMWARE_CONFIG_H)

    assert yaml_cfg["rise_rate_detection"]["enabled"] is False
    assert fw["kRiseRateDetectionEnabled"] is False

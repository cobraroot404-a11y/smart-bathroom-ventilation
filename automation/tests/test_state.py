from automation_service.config import RuleConfig
from automation_service.rules import HysteresisRule
from automation_service.state import DeviceState, StateStore


def make_config(**overrides) -> RuleConfig:
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


def test_get_or_create_returns_same_instance():
    store = StateStore(make_config())
    a = store.get_or_create("dev-1")
    b = store.get_or_create("dev-1")
    assert a is b


def test_different_devices_get_independent_state():
    store = StateStore(make_config())
    a = store.get_or_create("dev-1")
    b = store.get_or_create("dev-2")
    assert a is not b
    assert store.known_devices() == ["dev-1", "dev-2"]


def test_is_stale_when_never_seen():
    state = DeviceState(rule=HysteresisRule(make_config()))
    assert state.is_stale(now=1000, timeout_seconds=60) is True


def test_is_stale_after_timeout():
    state = DeviceState(rule=HysteresisRule(make_config()))
    state.last_telemetry_time = 0
    assert state.is_stale(now=61, timeout_seconds=60) is True
    assert state.is_stale(now=59, timeout_seconds=60) is False


def test_duplicate_seq_detected():
    state = DeviceState(rule=HysteresisRule(make_config()))
    assert state.is_duplicate(5) is False  # no prior seq yet
    state.last_seq = 5
    assert state.is_duplicate(5) is True
    assert state.is_duplicate(6) is False


def test_duplicate_detection_ignores_missing_seq():
    state = DeviceState(rule=HysteresisRule(make_config()))
    assert state.is_duplicate(None) is False

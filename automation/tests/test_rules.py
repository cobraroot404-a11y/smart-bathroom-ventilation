"""Unit tests for HysteresisRule.

Timing note: min_fan_off_seconds (default 30s) is enforced on *every*
off->on transition, including the very first one after the rule object
is created (last_change_time starts at 0) - this mirrors
firmware/src/controller.cpp's documented boot behavior (see
docs/safety.md "Restart behavior": a restart never assumes an in-progress
min-off timer is already satisfied). Tests that want an immediate "first"
ON transition therefore evaluate at t >= min_fan_off_seconds; the boundary
itself is verified explicitly in test_startup_high_humidity_is_held_until_min_off_elapses.
"""

from automation_service.config import RuleConfig
from automation_service.rules import (
    REASON_ABOVE,
    REASON_BELOW,
    REASON_HOLD,
    REASON_MAX_RUNTIME,
    REASON_MIN_OFF_HOLD,
    REASON_MIN_ON_HOLD,
    REASON_RISE_RATE,
    REASON_SENSOR_INVALID,
    HysteresisRule,
)


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


def turn_on(rule: HysteresisRule, at: float = 31, humidity: float = 75.0):
    """Helper: drive the rule ON, past the boot-time min-off window."""
    rule.on_reading(humidity, 24.0, True, now=at)
    d = rule.evaluate(at)
    assert d.desired_on is True, "helper precondition failed: rule did not turn on"
    return d


def test_below_lower_threshold_keeps_fan_off():
    rule = HysteresisRule(make_config())
    rule.on_reading(40.0, 24.0, True, now=0)
    d = rule.evaluate(0)
    assert d.desired_on is False
    assert d.reason == REASON_BELOW


def test_startup_high_humidity_is_held_until_min_off_elapses():
    rule = HysteresisRule(make_config())
    rule.on_reading(80.0, 24.0, True, now=0)
    held = rule.evaluate(0)
    assert held.desired_on is False
    assert held.reason == REASON_MIN_OFF_HOLD

    rule.on_reading(80.0, 24.0, True, now=30)
    released = rule.evaluate(30)
    assert released.desired_on is True
    assert released.reason == REASON_ABOVE


def test_crossing_upper_threshold_turns_fan_on():
    rule = HysteresisRule(make_config())
    turn_on(rule, at=31, humidity=75.0)


def test_band_preserves_state_while_off():
    rule = HysteresisRule(make_config())
    rule.on_reading(65.0, 24.0, True, now=0)
    d = rule.evaluate(0)
    assert d.desired_on is False
    assert d.reason == REASON_HOLD


def test_band_preserves_state_while_on():
    rule = HysteresisRule(make_config())
    turn_on(rule, at=31)
    rule.on_reading(65.0, 24.0, True, now=161)
    d = rule.evaluate(161)
    assert d.desired_on is True
    assert d.reason == REASON_HOLD


def test_crossing_lower_threshold_turns_fan_off_after_min_on():
    rule = HysteresisRule(make_config())
    turn_on(rule, at=31)
    rule.on_reading(55.0, 24.0, True, now=161)  # 130s after turn-on (>120s min-on)
    d = rule.evaluate(161)
    assert d.desired_on is False
    assert d.reason == REASON_BELOW


def test_min_on_time_enforced():
    rule = HysteresisRule(make_config())
    turn_on(rule, at=31)

    rule.on_reading(40.0, 24.0, True, now=41)  # only 10s after turn-on
    held = rule.evaluate(41)
    assert held.desired_on is True
    assert held.reason == REASON_MIN_ON_HOLD

    rule.on_reading(40.0, 24.0, True, now=152)  # 121s after turn-on
    released = rule.evaluate(152)
    assert released.desired_on is False


def test_min_off_time_enforced():
    rule = HysteresisRule(make_config())
    rule.on_reading(40.0, 24.0, True, now=0)
    assert rule.evaluate(0).desired_on is False

    rule.on_reading(80.0, 24.0, True, now=5)  # only 5s since boot
    held = rule.evaluate(5)
    assert held.desired_on is False
    assert held.reason == REASON_MIN_OFF_HOLD

    rule.on_reading(80.0, 24.0, True, now=31)
    released = rule.evaluate(31)
    assert released.desired_on is True


def test_max_runtime_cutoff():
    rule = HysteresisRule(make_config())
    turn_on(rule, at=31)

    rule.on_reading(80.0, 24.0, True, now=31 + 1800)
    d = rule.evaluate(31 + 1800)
    assert d.desired_on is False
    assert d.reason == REASON_MAX_RUNTIME


def test_invalid_reading_below_failure_limit_holds_last_valid_state():
    rule = HysteresisRule(make_config())
    rule.on_reading(40.0, 24.0, True, now=0)
    rule.evaluate(0)

    rule.on_reading(150.0, 24.0, True, now=5)  # out of range
    d = rule.evaluate(5)
    assert d.desired_on is False  # unchanged


def test_sensor_failure_beyond_limit_forces_off():
    rule = HysteresisRule(make_config())
    turn_on(rule, at=31, humidity=80.0)
    rule.on_reading(80.0, 24.0, True, now=161)
    rule.evaluate(161)  # still on, well past min-on

    t = 161
    for _ in range(3):
        t += 5
        rule.on_reading(0.0, 24.0, False, now=t)
    d = rule.evaluate(t)
    assert d.desired_on is False
    assert d.reason == REASON_SENSOR_INVALID


def test_sensor_failure_hold_last_state_when_configured():
    rule = HysteresisRule(make_config(sensor_invalid_hold_last_state=True))
    turn_on(rule, at=31, humidity=80.0)
    rule.on_reading(80.0, 24.0, True, now=161)
    rule.evaluate(161)

    t = 161
    for _ in range(3):
        t += 5
        rule.on_reading(0.0, 24.0, False, now=t)
    d = rule.evaluate(t)
    assert d.desired_on is True


def test_rise_rate_triggers_below_absolute_threshold():
    rule = HysteresisRule(make_config(
        rise_rate_detection_enabled=True,
        rise_rate_threshold_percent_per_minute=3.0,
        rise_rate_window_seconds=60,
        rise_rate_min_valid_samples=3,
    ))
    # All samples start well after the boot min-off window so the ON
    # transition below is caused by the rise-rate rule, not by the
    # min-off boundary happening to clear at the same instant. The rule
    # needs rise_rate_min_valid_samples (3) samples in its window before
    # it evaluates a rate at all, so the trigger fires exactly on the 3rd
    # sample: 8%/20s = 24%/min, well above the 3%/min threshold.
    base = 100
    rule.on_reading(50.0, 24.0, True, now=base)
    rule.evaluate(base)
    rule.on_reading(54.0, 24.0, True, now=base + 10)
    rule.evaluate(base + 10)
    rule.on_reading(58.0, 24.0, True, now=base + 20)
    d = rule.evaluate(base + 20)
    assert d.desired_on is True
    assert d.reason == REASON_RISE_RATE

    # Anti-cycling still applies: holds ON afterward.
    rule.on_reading(58.0, 24.0, True, now=base + 25)
    held = rule.evaluate(base + 25)
    assert held.desired_on is True


def test_rise_rate_disabled_by_default_does_not_trigger():
    rule = HysteresisRule(make_config())
    rule.on_reading(50.0, 24.0, True, now=100)
    rule.evaluate(100)
    rule.on_reading(65.0, 24.0, True, now=110)
    d = rule.evaluate(110)
    assert d.desired_on is False


def test_rise_rate_requires_minimum_sample_count():
    rule = HysteresisRule(make_config(
        rise_rate_detection_enabled=True,
        rise_rate_min_valid_samples=10,  # more samples than we will feed
    ))
    rule.on_reading(50.0, 24.0, True, now=100)
    rule.evaluate(100)
    rule.on_reading(65.0, 24.0, True, now=110)
    d = rule.evaluate(110)
    assert d.desired_on is False

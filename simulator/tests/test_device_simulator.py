import dataclasses

from simulator.device_controller import (
    MODE_AUTOMATIC,
    MODE_LOCAL_FALLBACK,
    REASON_ABOVE,
    REASON_BELOW,
    REASON_MAX_RUNTIME,
    REASON_SENSOR_INVALID,
    DeviceController,
)
from simulator.device_simulator import run_headless
from simulator.humidity_profiles import (
    generate_steady_profile,
    inject_invalid_burst,
)


def make_controller(**overrides) -> DeviceController:
    defaults = dict(
        fan_on_percent=70.0,
        fan_off_percent=60.0,
        humidity_min_valid=0.0,
        humidity_max_valid=100.0,
        min_fan_on_seconds=120,
        min_fan_off_seconds=30,
        max_continuous_runtime_seconds=1800,
        stale_command_timeout_seconds=60,
        sensor_consecutive_failure_limit=3,
    )
    defaults.update(overrides)
    return DeviceController(**defaults)


def test_steady_low_humidity_never_turns_on():
    samples = generate_steady_profile(300, 5, humidity_percent=40.0)
    records = run_headless(samples, make_controller())
    assert records == []  # no transitions at all


def test_steady_high_humidity_turns_on_once_past_boot_window():
    samples = generate_steady_profile(300, 5, humidity_percent=80.0)
    records = run_headless(samples, make_controller())
    assert len(records) == 1
    assert records[0].relay_on is True
    assert records[0].reason == REASON_ABOVE
    assert records[0].time_seconds >= 30  # min_fan_off_seconds boot window


def test_deterministic_for_same_input():
    samples = generate_steady_profile(300, 5, humidity_percent=80.0)
    r1 = run_headless(samples, make_controller())
    r2 = run_headless(samples, make_controller())
    assert r1 == r2


def test_full_cycle_on_then_off():
    on_phase = generate_steady_profile(150, 5, humidity_percent=80.0)
    off_phase = [
        s for s in generate_steady_profile(200, 5, humidity_percent=50.0)
    ]
    # shift off_phase times to continue after on_phase
    offset = on_phase[-1].time_seconds + 5
    off_phase = [
        dataclasses.replace(s, time_seconds=s.time_seconds + offset)
        for s in off_phase
    ]
    samples = on_phase + off_phase

    records = run_headless(samples, make_controller())
    assert len(records) == 2
    assert records[0].relay_on is True and records[0].reason == REASON_ABOVE
    assert records[1].relay_on is False and records[1].reason == REASON_BELOW
    # min_fan_on_seconds (120) must have elapsed between on and off
    assert records[1].time_seconds - records[0].time_seconds >= 120


def test_max_runtime_cutoff_forces_off_eventually():
    # Humidity stays high for the whole run, so after the max-runtime
    # cutoff forces the fan off, it is expected to turn back on again
    # once min_fan_off_seconds clears - this is the correct, intentional
    # cyclical safety behavior (see docs/safety.md), not a bug.
    samples = generate_steady_profile(2200, 5, humidity_percent=85.0)
    records = run_headless(samples, make_controller())
    assert len(records) >= 2
    assert records[0].relay_on is True
    assert records[1].relay_on is False
    assert records[1].reason == REASON_MAX_RUNTIME


def test_invalid_burst_forces_safe_off_state():
    base = generate_steady_profile(400, 5, humidity_percent=80.0)
    samples = inject_invalid_burst(base, start_seconds=200, duration_seconds=30)
    records = run_headless(samples, make_controller())
    reasons = [r.reason for r in records]
    assert REASON_ABOVE in reasons  # turned on initially
    assert REASON_SENSOR_INVALID in reasons  # forced off after sensor failure
    off_after_invalid = [r for r in records if r.reason == REASON_SENSOR_INVALID]
    assert off_after_invalid[0].relay_on is False


def test_mqtt_command_takes_precedence_over_local_reading():
    # now=31 clears the boot-time min_fan_off_seconds window (see
    # docs/safety.md "Restart behavior") - min-off/min-on timing is
    # enforced on every transition regardless of source, MQTT included.
    controller = make_controller()
    controller.on_sensor_reading(40.0, True)  # would be OFF locally
    controller.on_mqtt_desired(True, issued_at_age_seconds=0, now=31)
    decision = controller.tick(31)
    assert decision.relay_on is True
    assert decision.mode == MODE_AUTOMATIC


def test_stale_mqtt_command_falls_back_to_local():
    controller = make_controller()
    controller.on_mqtt_desired(True, issued_at_age_seconds=0, now=0)
    controller.on_sensor_reading(40.0, True)
    assert controller.tick(0).mode == MODE_AUTOMATIC

    controller.on_sensor_reading(40.0, True)
    decision = controller.tick(61)  # command now stale (>60s)
    assert decision.mode == MODE_LOCAL_FALLBACK
    assert decision.fallback_active is True

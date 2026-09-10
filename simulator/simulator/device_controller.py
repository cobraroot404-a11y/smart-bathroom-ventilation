"""DeviceController: a Python port of firmware/src/controller.cpp's
precedence and anti-cycling logic, used only by the software simulator
(simulator/simulator/device_simulator.py) to emulate ESP32 behavior
without real hardware - see docs/testing.md "simulation mode".

This intentionally mirrors the C++ implementation's structure (including
its reason codes) rather than delegating to
automation/automation_service/rules.HysteresisRule, because the real
firmware's precedence between a fresh MQTT command and local fallback
hysteresis is something HysteresisRule does not model at all (the
automation service only ever computes the "automatic" side). Any change
to the anti-cycling/precedence algorithm in controller.cpp should be
mirrored here too - see docs/architecture.md "Configuration as a single
source of truth" for the equivalent guarantee on tunable values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

REASON_STARTUP = "startup_safe_state"
REASON_ABOVE = "humidity_above_threshold"
REASON_BELOW = "humidity_below_threshold"
REASON_HOLD = "hysteresis_hold"
REASON_MIN_ON_HOLD = "min_on_time_hold"
REASON_MIN_OFF_HOLD = "min_off_time_hold"
REASON_MAX_RUNTIME = "max_runtime_cutoff"
REASON_SENSOR_INVALID = "sensor_invalid_safe_state"
REASON_MQTT_COMMAND = "mqtt_command"

MODE_AUTOMATIC = "automatic"
MODE_LOCAL_FALLBACK = "local_fallback"


@dataclass
class DeviceDecision:
    relay_on: bool
    changed: bool
    mode: str
    reason: str
    fallback_active: bool


class DeviceController:
    def __init__(self, *, fan_on_percent: float, fan_off_percent: float,
                 humidity_min_valid: float, humidity_max_valid: float,
                 min_fan_on_seconds: float, min_fan_off_seconds: float,
                 max_continuous_runtime_seconds: float,
                 stale_command_timeout_seconds: float,
                 sensor_consecutive_failure_limit: int,
                 sensor_invalid_hold_last_state: bool = False):
        self.fan_on_percent = fan_on_percent
        self.fan_off_percent = fan_off_percent
        self.humidity_min_valid = humidity_min_valid
        self.humidity_max_valid = humidity_max_valid
        self.min_fan_on_seconds = min_fan_on_seconds
        self.min_fan_off_seconds = min_fan_off_seconds
        self.max_continuous_runtime_seconds = max_continuous_runtime_seconds
        self.stale_command_timeout_seconds = stale_command_timeout_seconds
        self.sensor_consecutive_failure_limit = sensor_consecutive_failure_limit
        self.sensor_invalid_hold_last_state = sensor_invalid_hold_last_state

        self.relay_on = False
        self.last_change_time = 0.0
        self.relay_on_since: Optional[float] = None

        self.has_valid_reading = False
        self.last_valid_humidity: Optional[float] = None
        self.consecutive_failures = 0

        self.mqtt_received = False
        self.mqtt_desired_on = False
        self.mqtt_issued_at: Optional[float] = None

    def on_sensor_reading(self, humidity_percent: float, sensor_valid: bool) -> None:
        in_range = sensor_valid and self.humidity_min_valid <= humidity_percent <= self.humidity_max_valid
        if in_range:
            self.consecutive_failures = 0
            self.has_valid_reading = True
            self.last_valid_humidity = humidity_percent
        else:
            self.consecutive_failures += 1

    def on_mqtt_desired(self, desired_on: bool, issued_at_age_seconds: float, now: float) -> None:
        self.mqtt_received = True
        self.mqtt_desired_on = desired_on
        # Clamped to 0 (never negative) so an `age` that is inflated by
        # whole-second timestamp truncation (docs/mqtt-api.md payloads use
        # second-precision ISO-8601, so up to ~1s of apparent age is
        # expected) can never push the issued time before the start of
        # this controller's own clock - mirrors
        # firmware/src/controller.cpp's SaturatingSub().
        self.mqtt_issued_at = max(0.0, now - max(0.0, issued_at_age_seconds))

    def _mqtt_fresh(self, now: float) -> bool:
        if not self.mqtt_received or self.mqtt_issued_at is None:
            return False
        return (now - self.mqtt_issued_at) <= self.stale_command_timeout_seconds

    def _compute_candidate(self, now: float):
        if self._mqtt_fresh(now):
            return self.mqtt_desired_on, MODE_AUTOMATIC, REASON_MQTT_COMMAND

        sensor_failed = (not self.has_valid_reading or
                          self.consecutive_failures >= self.sensor_consecutive_failure_limit)
        if sensor_failed:
            candidate = self.relay_on if self.sensor_invalid_hold_last_state else False
            return candidate, MODE_LOCAL_FALLBACK, REASON_SENSOR_INVALID

        humidity = self.last_valid_humidity
        if humidity >= self.fan_on_percent:
            return True, MODE_LOCAL_FALLBACK, REASON_ABOVE
        if humidity <= self.fan_off_percent:
            return False, MODE_LOCAL_FALLBACK, REASON_BELOW
        return self.relay_on, MODE_LOCAL_FALLBACK, REASON_HOLD

    def tick(self, now: float) -> DeviceDecision:
        candidate_on, mode, reason = self._compute_candidate(now)
        final_on, final_reason = candidate_on, reason

        max_runtime_exceeded = (
            self.relay_on and self.relay_on_since is not None and
            (now - self.relay_on_since) >= self.max_continuous_runtime_seconds
        )

        if max_runtime_exceeded:
            final_on, final_reason = False, REASON_MAX_RUNTIME
        elif candidate_on != self.relay_on:
            elapsed = now - self.last_change_time
            if self.relay_on and not candidate_on and elapsed < self.min_fan_on_seconds:
                final_on, final_reason = True, REASON_MIN_ON_HOLD
            elif not self.relay_on and candidate_on and elapsed < self.min_fan_off_seconds:
                final_on, final_reason = False, REASON_MIN_OFF_HOLD

        changed = final_on != self.relay_on
        if changed:
            self.relay_on = final_on
            self.last_change_time = now
            self.relay_on_since = now if final_on else None

        return DeviceDecision(
            relay_on=self.relay_on,
            changed=changed,
            mode=mode,
            reason=final_reason,
            fallback_active=(mode == MODE_LOCAL_FALLBACK),
        )

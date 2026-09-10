"""HysteresisRule: the automation service's humidity-controlled ventilation
rule.

This mirrors the logic in firmware/src/controller.cpp's local-fallback
path (hysteresis, anti-cycling timers, max-runtime cutoff, sensor-invalid
safe state, optional rise-rate detection) so both sides of the system
reach the same decision from the same telemetry, and the device's own
local fallback is a true drop-in replacement if this service or MQTT
becomes unavailable - see docs/architecture.md.

All times are POSIX-style seconds (float), monotonic within a given
process; callers pass `now` explicitly so this class is fully
deterministic and unit-testable without real time or MQTT.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Tuple

from .config import RuleConfig

# Reason strings match firmware/include/controller.h's Reason enum
# (ReasonToString) so logs and the `reason` field in fan/desired payloads
# are consistent across the two implementations - see docs/mqtt-api.md.
REASON_STARTUP = "startup_safe_state"
REASON_ABOVE = "humidity_above_threshold"
REASON_BELOW = "humidity_below_threshold"
REASON_HOLD = "hysteresis_hold"
REASON_MIN_ON_HOLD = "min_on_time_hold"
REASON_MIN_OFF_HOLD = "min_off_time_hold"
REASON_MAX_RUNTIME = "max_runtime_cutoff"
REASON_SENSOR_INVALID = "sensor_invalid_safe_state"
REASON_RISE_RATE = "rise_rate_trigger"


@dataclass
class Decision:
    desired_on: bool
    reason: str
    changed: bool


@dataclass
class _RiseSample:
    timestamp: float
    humidity_percent: float


class HysteresisRule:
    def __init__(self, cfg: RuleConfig):
        self.cfg = cfg
        self.relay_on = False
        self.last_change_time: float = 0.0
        self.relay_on_since: Optional[float] = None
        self.has_valid_reading = False
        self.last_valid_humidity: Optional[float] = None
        self.consecutive_failures = 0
        self._rise_buffer: Deque[_RiseSample] = deque(maxlen=64)

    def on_reading(self, humidity_percent: float, temperature_celsius: float,
                    sensor_valid: bool, now: float) -> None:
        in_range = (
            sensor_valid
            and self.cfg.humidity_min_valid_percent
            <= humidity_percent
            <= self.cfg.humidity_max_valid_percent
            and self.cfg.temperature_min_valid_celsius
            <= temperature_celsius
            <= self.cfg.temperature_max_valid_celsius
        )
        if in_range:
            self.consecutive_failures = 0
            self.has_valid_reading = True
            self.last_valid_humidity = humidity_percent
            if self.cfg.rise_rate_detection_enabled:
                self._rise_buffer.append(_RiseSample(now, humidity_percent))
        else:
            self.consecutive_failures += 1

    def _rise_rate_triggered(self, now: float) -> bool:
        if not self.cfg.rise_rate_detection_enabled:
            return False
        window_start = now - self.cfg.rise_rate_window_seconds
        in_window = [s for s in self._rise_buffer if s.timestamp >= window_start]
        if len(in_window) < self.cfg.rise_rate_min_valid_samples:
            return False
        oldest, newest = in_window[0], in_window[-1]
        elapsed_minutes = (newest.timestamp - oldest.timestamp) / 60.0
        if elapsed_minutes <= 0:
            return False
        rate = (newest.humidity_percent - oldest.humidity_percent) / elapsed_minutes
        return rate >= self.cfg.rise_rate_threshold_percent_per_minute

    def _compute_candidate(self, now: float) -> Tuple[bool, str]:
        sensor_failed = (
            not self.has_valid_reading
            or self.consecutive_failures >= self.cfg.sensor_consecutive_failure_limit
        )
        if sensor_failed:
            candidate = self.relay_on if self.cfg.sensor_invalid_hold_last_state else False
            return candidate, REASON_SENSOR_INVALID

        humidity = self.last_valid_humidity
        if humidity >= self.cfg.fan_on_percent:
            candidate, reason = True, REASON_ABOVE
        elif humidity <= self.cfg.fan_off_percent:
            candidate, reason = False, REASON_BELOW
        else:
            candidate, reason = self.relay_on, REASON_HOLD

        # Applied after every branch above (not just the hysteresis-hold
        # band) so a rapid rise is caught even while still below
        # fan_off_percent - mirrors firmware/src/controller.cpp's
        # ComputeCandidate, which runs this check unconditionally
        # whenever the humidity-based candidate isn't already ON.
        if not candidate and self._rise_rate_triggered(now):
            return True, REASON_RISE_RATE
        return candidate, reason

    def evaluate(self, now: float) -> Decision:
        candidate_on, reason = self._compute_candidate(now)
        final_on = candidate_on
        final_reason = reason

        max_runtime_exceeded = (
            self.relay_on
            and self.relay_on_since is not None
            and (now - self.relay_on_since) >= self.cfg.max_continuous_runtime_seconds
        )

        if max_runtime_exceeded:
            final_on = False
            final_reason = REASON_MAX_RUNTIME
        elif candidate_on != self.relay_on:
            elapsed = now - self.last_change_time
            if self.relay_on and not candidate_on:
                if elapsed < self.cfg.min_fan_on_seconds:
                    final_on = True
                    final_reason = REASON_MIN_ON_HOLD
            elif not self.relay_on and candidate_on:
                if elapsed < self.cfg.min_fan_off_seconds:
                    final_on = False
                    final_reason = REASON_MIN_OFF_HOLD

        changed = final_on != self.relay_on
        if changed:
            self.relay_on = final_on
            self.last_change_time = now
            if final_on:
                self.relay_on_since = now
            else:
                self.relay_on_since = None

        return Decision(desired_on=self.relay_on, reason=final_reason, changed=changed)

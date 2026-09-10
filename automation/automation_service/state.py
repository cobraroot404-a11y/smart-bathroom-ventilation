"""Per-device state tracking: telemetry freshness and duplicate detection.

Kept entirely in memory. On process restart, all state is rebuilt from
scratch from the next telemetry messages received - this is the
documented, deterministic restart behavior (see docs/mqtt-api.md /
docs/testing.md "restart-state tests"): the service never assumes a
device is still in whatever state it was in before the restart, and does
not publish a `fan/desired` command until it has received at least one
valid telemetry reading for that device.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .config import RuleConfig
from .rules import HysteresisRule


@dataclass
class DeviceState:
    rule: HysteresisRule
    last_telemetry_time: Optional[float] = None
    last_seq: Optional[int] = None

    def is_stale(self, now: float, timeout_seconds: float) -> bool:
        if self.last_telemetry_time is None:
            return True
        return (now - self.last_telemetry_time) > timeout_seconds

    def is_duplicate(self, seq: Optional[int]) -> bool:
        if seq is None or self.last_seq is None:
            return False
        return seq == self.last_seq


class StateStore:
    def __init__(self, rule_cfg: RuleConfig):
        self._rule_cfg = rule_cfg
        self._devices: Dict[str, DeviceState] = {}

    def get_or_create(self, device_id: str) -> DeviceState:
        if device_id not in self._devices:
            self._devices[device_id] = DeviceState(rule=HysteresisRule(self._rule_cfg))
        return self._devices[device_id]

    def known_devices(self):
        return list(self._devices.keys())

"""Deterministic humidity profile generators for the software-only
simulation (see docs/testing.md "Simulation mode" / requirement 14).

Every generator takes an explicit `seed` and produces the same sequence
of samples every time for the same arguments - required so
`run_e2e_demo.py` can assert on exact expected transitions.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class HumiditySample:
    time_seconds: float
    humidity_percent: float
    temperature_celsius: float
    valid: bool = True


def _noisy(rng: random.Random, value: float, amplitude: float) -> float:
    return value + rng.uniform(-amplitude, amplitude)


def generate_shower_profile(
    total_seconds: float,
    sample_interval_seconds: float,
    seed: int = 42,
    baseline_percent: float = 45.0,
    peak_percent: float = 85.0,
    rise_start_seconds: float = 20.0,
    rise_duration_seconds: float = 120.0,
    plateau_duration_seconds: float = 90.0,
    decay_time_constant_seconds: float = 300.0,
    noise_amplitude_percent: float = 0.4,
    temperature_celsius: float = 23.0,
) -> List[HumiditySample]:
    """A gradual shower-related rise followed by a decay after ventilation
    - see requirement 14 ("represent a gradual shower-related rise" /
    "represent decreasing humidity after ventilation")."""
    rng = random.Random(seed)
    samples: List[HumiditySample] = []
    rise_end = rise_start_seconds + rise_duration_seconds
    plateau_end = rise_end + plateau_duration_seconds

    t = 0.0
    while t <= total_seconds:
        if t < rise_start_seconds:
            value = baseline_percent
        elif t < rise_end:
            frac = (t - rise_start_seconds) / rise_duration_seconds
            value = baseline_percent + frac * (peak_percent - baseline_percent)
        elif t < plateau_end:
            value = peak_percent
        else:
            decay_t = t - plateau_end
            value = baseline_percent + (peak_percent - baseline_percent) * math.exp(
                -decay_t / decay_time_constant_seconds
            )
        value = _noisy(rng, value, noise_amplitude_percent)
        value = max(0.0, min(100.0, value))
        samples.append(HumiditySample(t, value, temperature_celsius, True))
        t += sample_interval_seconds

    return samples


def generate_steady_profile(
    total_seconds: float,
    sample_interval_seconds: float,
    humidity_percent: float,
    temperature_celsius: float = 23.0,
) -> List[HumiditySample]:
    """Constant humidity - used for boundary/hysteresis/max-runtime tests."""
    samples = []
    t = 0.0
    while t <= total_seconds:
        samples.append(HumiditySample(t, humidity_percent, temperature_celsius, True))
        t += sample_interval_seconds
    return samples


def generate_multi_shower_profile(
    total_seconds: float,
    sample_interval_seconds: float,
    shower_start_times_seconds: List[float],
    seed: int = 42,
    baseline_percent: float = 45.0,
    shower_duration_seconds: float = 1200.0,
    temperature_celsius: float = 23.0,
) -> List[HumiditySample]:
    """A baseline-humidity timeline with one or more independent shower
    events overlaid at the given start times. Used by
    energy/energy_report.py to build a realistic multi-event comparison
    period; `shower_start_times_seconds` should be multiples of
    `sample_interval_seconds` so the overlay aligns exactly.
    """
    baseline = generate_steady_profile(
        total_seconds, sample_interval_seconds, baseline_percent, temperature_celsius
    )
    by_time = {round(s.time_seconds, 3): s for s in baseline}

    for i, start in enumerate(shower_start_times_seconds):
        local = generate_shower_profile(
            shower_duration_seconds,
            sample_interval_seconds,
            seed=seed + i,
            baseline_percent=baseline_percent,
            temperature_celsius=temperature_celsius,
        )
        for s in local:
            absolute_t = round(start + s.time_seconds, 3)
            if 0 <= absolute_t <= total_seconds:
                by_time[absolute_t] = HumiditySample(
                    absolute_t, s.humidity_percent, s.temperature_celsius, s.valid
                )

    return [by_time[t] for t in sorted(by_time.keys())]


def inject_invalid_burst(
    samples: List[HumiditySample],
    start_seconds: float,
    duration_seconds: float,
    invalid_value: Optional[float] = 150.0,
) -> List[HumiditySample]:
    """Marks samples within [start, start+duration) as invalid - simulates
    a sensor fault / out-of-range reading burst (requirement 14: "support
    invalid readings")."""
    out = []
    for s in samples:
        if start_seconds <= s.time_seconds < start_seconds + duration_seconds:
            value = invalid_value if invalid_value is not None else s.humidity_percent
            out.append(HumiditySample(s.time_seconds, value, s.temperature_celsius, False))
        else:
            out.append(s)
    return out

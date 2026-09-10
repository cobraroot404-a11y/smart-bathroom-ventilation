#!/usr/bin/env python3
"""Energy-efficiency comparison: continuous vs. fixed-time vs.
humidity-controlled ventilation (requirement 15).

This is a *simulated estimate*, not a measurement of any physical fan.
It models a configurable number of shower events over a configurable
duration using the same deterministic humidity profile generator and the
same hysteresis/timer control algorithm used elsewhere in this repository
(simulator/simulator/device_controller.py, itself a Python port of
firmware/src/controller.cpp), so the "humidity-controlled" runtime
reflects the actual control logic this project implements - not a
simplified stand-in for it.

    Energy (kWh) = Power (W) x Runtime (hours) / 1000

Usage:
    python energy/energy_report.py
    python energy/energy_report.py --duration-hours 24 --fan-watts 25 --showers-per-day 3
    python energy/energy_report.py --output energy/output/report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "simulator"))

import yaml
from simulator.device_controller import DeviceController
from simulator.humidity_profiles import generate_multi_shower_profile


@dataclass
class StrategyResult:
    name: str
    runtime_seconds: float
    runtime_hours: float
    energy_kwh: float
    percent_of_continuous: float
    energy_saved_vs_continuous_kwh: float


def load_defaults() -> dict:
    with open(REPO_ROOT / "config" / "defaults.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def continuous_runtime_seconds(total_seconds: float) -> float:
    return total_seconds


def fixed_time_runtime_seconds(shower_start_times: List[float], fixed_run_seconds: float,
                                total_seconds: float) -> float:
    total = 0.0
    for start in shower_start_times:
        run = min(fixed_run_seconds, max(0.0, total_seconds - start))
        total += run
    return total


def humidity_controlled_runtime_seconds(samples, controller: DeviceController,
                                         sample_interval_seconds: float) -> float:
    on_seconds = 0.0
    for s in samples:
        controller.on_sensor_reading(s.humidity_percent, s.valid)
        decision = controller.tick(s.time_seconds)
        if decision.relay_on:
            on_seconds += sample_interval_seconds
    return on_seconds


def make_result(name: str, runtime_seconds: float, fan_watts: float,
                 continuous_seconds: float) -> StrategyResult:
    runtime_hours = runtime_seconds / 3600.0
    energy_kwh = fan_watts * runtime_hours / 1000.0
    continuous_hours = continuous_seconds / 3600.0
    continuous_kwh = fan_watts * continuous_hours / 1000.0
    percent = (runtime_seconds / continuous_seconds * 100.0) if continuous_seconds > 0 else 0.0
    saved = continuous_kwh - energy_kwh
    return StrategyResult(name, runtime_seconds, runtime_hours, energy_kwh, percent, saved)


def run_comparison(*, duration_hours: float, fan_watts: float, showers_per_day: int,
                    shower_duration_seconds: float, fixed_run_minutes: float,
                    sample_interval_seconds: float, seed: int,
                    fan_on_percent: float, fan_off_percent: float,
                    min_fan_on_seconds: float, min_fan_off_seconds: float,
                    max_continuous_runtime_seconds: float) -> List[StrategyResult]:
    total_seconds = duration_hours * 3600.0
    day_seconds = 24 * 3600.0
    num_days = max(1, round(duration_hours / 24.0))

    shower_start_times = []
    for day in range(num_days):
        day_offset = day * day_seconds
        for i in range(showers_per_day):
            # Evenly spaced across the day, snapped to the sample grid.
            offset = day_offset + (i + 1) * day_seconds / (showers_per_day + 1)
            offset = round(offset / sample_interval_seconds) * sample_interval_seconds
            if offset < total_seconds:
                shower_start_times.append(offset)

    samples = generate_multi_shower_profile(
        total_seconds=total_seconds,
        sample_interval_seconds=sample_interval_seconds,
        shower_start_times_seconds=shower_start_times,
        seed=seed,
        shower_duration_seconds=shower_duration_seconds,
    )

    continuous_seconds = continuous_runtime_seconds(total_seconds)
    fixed_seconds = fixed_time_runtime_seconds(
        shower_start_times, fixed_run_minutes * 60.0, total_seconds
    )

    controller = DeviceController(
        fan_on_percent=fan_on_percent,
        fan_off_percent=fan_off_percent,
        humidity_min_valid=0.0,
        humidity_max_valid=100.0,
        min_fan_on_seconds=min_fan_on_seconds,
        min_fan_off_seconds=min_fan_off_seconds,
        max_continuous_runtime_seconds=max_continuous_runtime_seconds,
        stale_command_timeout_seconds=60,
        sensor_consecutive_failure_limit=3,
    )
    humidity_seconds = humidity_controlled_runtime_seconds(samples, controller, sample_interval_seconds)

    return [
        make_result("continuous", continuous_seconds, fan_watts, continuous_seconds),
        make_result("fixed_time", fixed_seconds, fan_watts, continuous_seconds),
        make_result("humidity_controlled", humidity_seconds, fan_watts, continuous_seconds),
    ]


def print_report(results: List[StrategyResult], assumptions: dict) -> None:
    print("Energy-efficiency comparison (SIMULATED ESTIMATE, not a physical measurement)")
    print("=" * 78)
    print(f"{'Strategy':<22}{'Runtime (h)':>14}{'Energy (kWh)':>16}{'% of continuous':>18}")
    for r in results:
        print(f"{r.name:<22}{r.runtime_hours:>14.2f}{r.energy_kwh:>16.3f}{r.percent_of_continuous:>17.1f}%")
    print()
    print("Estimated energy saved vs. continuous operation:")
    for r in results:
        if r.name != "continuous":
            print(f"  {r.name:<20} {r.energy_saved_vs_continuous_kwh:.3f} kWh "
                  f"({100 - r.percent_of_continuous:.1f}% less runtime)")
    print()
    print("Assumptions:")
    for k, v in assumptions.items():
        print(f"  {k}: {v}")
    print()
    print("Limitations: this is a control-policy simulation against a synthetic")
    print("humidity profile, not a measurement of a real fan, room, or occupancy")
    print("pattern. Actual savings depend on real household shower frequency/")
    print("duration, room volume and ventilation rate, sensor placement, and the")
    print("thresholds actually calibrated for the room - see docs/testing.md and")
    print("docs/physical-commissioning.md.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    defaults = load_defaults()
    parser.add_argument("--duration-hours", type=float, default=24.0)
    parser.add_argument("--fan-watts", type=float, default=defaults["energy"]["fan_power_watts"])
    parser.add_argument("--showers-per-day", type=int, default=3)
    parser.add_argument("--shower-duration-seconds", type=float, default=1200.0)
    parser.add_argument("--fixed-run-minutes", type=float, default=15.0,
                         help="Fixed-time strategy: minutes the fan runs per triggered event")
    parser.add_argument("--sample-interval-seconds", type=float, default=30.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=None,
                         help="Optional path to write the report as JSON")
    args = parser.parse_args()

    thresholds = defaults["thresholds"]
    timing = defaults["timing"]

    results = run_comparison(
        duration_hours=args.duration_hours,
        fan_watts=args.fan_watts,
        showers_per_day=args.showers_per_day,
        shower_duration_seconds=args.shower_duration_seconds,
        fixed_run_minutes=args.fixed_run_minutes,
        sample_interval_seconds=args.sample_interval_seconds,
        seed=args.seed,
        fan_on_percent=thresholds["fan_on_percent"],
        fan_off_percent=thresholds["fan_off_percent"],
        min_fan_on_seconds=timing["min_fan_on_seconds"],
        min_fan_off_seconds=timing["min_fan_off_seconds"],
        max_continuous_runtime_seconds=timing["max_continuous_runtime_seconds"],
    )

    assumptions = {
        "duration_hours": args.duration_hours,
        "fan_watts": args.fan_watts,
        "showers_per_day": args.showers_per_day,
        "shower_duration_seconds": args.shower_duration_seconds,
        "fixed_run_minutes": args.fixed_run_minutes,
        "fan_on_percent": thresholds["fan_on_percent"],
        "fan_off_percent": thresholds["fan_off_percent"],
        "seed": args.seed,
    }

    print_report(results, assumptions)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump({
                "results": [asdict(r) for r in results],
                "assumptions": assumptions,
            }, fh, indent=2)
        print(f"\nWrote JSON report to {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

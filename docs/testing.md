# Testing

This document records what was actually run and what its result was.
"Not tested" is stated explicitly wherever hardware was required and
unavailable - see `docs/requirements-traceability.md` for the full
per-requirement table.

## Test layers

1. **Firmware native unit tests** (`firmware/test/test_controller/`,
   PlatformIO `native` environment): the hardware-independent
   `VentilationController` compiled and run as a desktop binary with
   Unity, covering hysteresis, min-on/min-off timing, max-runtime cutoff,
   sensor-invalid safe state, local-fallback entry/exit, manual override
   (on/off/auto/expiry), stale-command rejection, and rise-rate detection.
2. **Firmware compilation** (`firmware`, PlatformIO `esp32dev`
   environment): compiles the full firmware including hardware drivers
   against the ESP32 toolchain. This validates the code compiles for real
   hardware; it does not run on real hardware (see
   `docs/requirements-traceability.md`).

> **Toolchain note**: the machine this prototype was built on has no
> native C/C++ compiler installed, so `pio test -e native` itself could
> not run there (PlatformIO's `native` platform still needs a system
> gcc/clang/MSVC). `firmware/src/controller.cpp`, `firmware/src/sensor.cpp`,
> and `firmware/test/test_controller/test_main.cpp` were instead compiled
> and executed with the same standard (`-std=gnu++17`), the same
> `-DUNIT_TEST` flag, and the same Unity test framework version
> (`v2.6.0`) inside a `gcc:13` Docker container (`scripts/run_full_check.py`
> falls back to this automatically when PlatformIO isn't on `PATH`).
>
> **This fallback build does not validate `firmware/platformio.ini`
> itself** - it invokes `g++`/`ld` directly rather than going through
> PlatformIO's own project-config-driven test build, so a misconfigured
> `[env:native]` (for example, a missing `test_build_src = true`, which
> caused PlatformIO's real test runner to link only `test_main.cpp` +
> Unity and fail with "undefined reference" errors for every
> `VentilationController` method, even though this Docker fallback
> passed) can go undetected locally. `.github/workflows/ci.yml` runs the
> real `pio test -e native` on a machine with an actual compiler and is
> the authoritative check for the PlatformIO configuration; treat a
> green Docker-fallback run as evidence the *controller logic* is
> correct, not as proof `pio test -e native` itself will succeed.
3. **Automation service unit tests** (`automation/tests/`, `pytest`):
   `HysteresisRule` logic (mirrors the firmware controller's automatic-mode
   behavior), payload schema validation, boundary values, stale-telemetry
   handling, restart/state-reload behavior, invalid-command rejection,
   retained-message handling, duplicate-message idempotency.
4. **Simulator unit tests** (`simulator/tests/`, `pytest`): humidity
   profile generation, deterministic seeding, simulated relay/controller
   bookkeeping.
5. **End-to-end simulation** (`simulator/simulator/run_e2e_demo.py`):
   brings up Mosquitto (via `docker compose`), runs the automation service
   and a simulated device against a scripted humidity profile, and asserts
   on the resulting MQTT transition log. Exits non-zero if an expected
   transition does not occur - see the assertions listed in
   "End-to-end scenario checklist" below.
6. **Energy comparison** (`energy/energy_report.py`): deterministic,
   config-driven simulation comparing continuous/fixed-time/humidity-
   controlled ventilation strategies (see `README.md` "Energy-efficiency
   evaluation").

## How to run everything

```bash
# Firmware native unit tests (no ESP32 required)
cd firmware
pio test -e native

# Firmware compile check (no flashing)
pio run -e esp32dev

# Automation service + simulator unit tests
cd ../automation && pip install -r requirements.txt && pytest
cd ../simulator && pip install -r requirements.txt && pytest

# Full end-to-end simulated demonstration (starts Mosquitto via Docker)
cd ..
python scripts/run_full_check.py
```

`scripts/run_full_check.py` runs every layer above in sequence and prints
a pass/fail summary; it is what was actually executed to produce the
results recorded in `docs/requirements-traceability.md`.

## End-to-end scenario checklist

The simulated end-to-end demonstration (`simulator/simulator/run_e2e_demo.py`)
scripts a humidity profile and asserts each of the following occurs, in
this order, against the real automation service and Mosquitto broker
(not mocked):

1. Mosquitto, the automation service, and the simulated device all start
   and connect successfully.
2. The automation service receives telemetry from the simulated device.
3. Humidity below `fan_on_percent` keeps the simulated relay OFF.
4. Humidity crossing `fan_on_percent` turns the simulated relay ON.
5. Humidity inside the hysteresis band (between `fan_off_percent` and
   `fan_on_percent`) preserves the current relay state.
6. Humidity crossing `fan_off_percent` turns the simulated relay OFF
   (after `min_fan_on_seconds` has elapsed).
7. `min_fan_on_seconds` / `min_fan_off_seconds` are enforced (a forced
   early state-change attempt within the simulation is shown to be held).
8. `max_continuous_runtime_seconds` is enforced (a scripted long-duration
   high-humidity period is forced off at the cutoff).
9. Invalid/out-of-range simulated readings do not cause an unsafe or
   spurious relay switch.
10. Simulated MQTT loss activates the device's local fallback mode
    (`mode` topic shows `fallback_active: true`).
11. Recovery from the simulated outage does not cause rapid toggling
    (the min-on/min-off timers carry through the outage).
12. `fan/actual` is published correctly and matches the simulated relay's
    real state at every transition.
13. The energy report script runs and produces a comparison table.
14. All started processes (broker container, automation service,
    simulator) shut down cleanly with exit code 0.

Each assertion failure causes `run_e2e_demo.py` to exit non-zero with a
message identifying which step failed, so it is safe to use as a CI gate.

## What physical hardware testing this prototype has and has not received

- Software simulation: **verified** (see `scripts/run_full_check.py`
  output referenced in the completion report).
- Firmware compilation for `esp32dev`: **verified**, subject to
  PlatformIO/toolchain availability in the build environment (see
  `docs/requirements-traceability.md` for the exact result).
- Firmware native unit tests: **verified**.
- Physical SHT31/SHT40 or DHT22 sensor: **not tested** - no physical
  sensor was connected during this build.
- Physical relay module: **not tested** - no physical relay was
  connected during this build.
- Real fan/lamp/LED load: **not tested**.
- Mains-voltage installation: **out of scope**, not attempted, not
  supported by this prototype - see `docs/safety.md`.

Physical commissioning steps remain in `docs/physical-commissioning.md`
as an unchecked checklist for whoever assembles the real hardware.

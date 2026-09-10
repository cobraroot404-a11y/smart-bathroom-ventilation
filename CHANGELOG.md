# Changelog

All notable changes to this project are documented in this file.
This project does not yet follow a formal release/versioning scheme;
entries are grouped by development milestone.

## [Unreleased]

### Changed

- Relicensed from MIT to a proprietary source-visible license. The
  project is public for educational review only; copying, modification,
  redistribution, and reuse now require prior written permission from
  Gautham - see [LICENSE](LICENSE) and the notice at the top of
  [README.md](README.md).
- Republished as a fresh repository with a clean history.

## [0.1.0] - 2026-09-10

### Added

- ESP32 firmware (PlatformIO, `esp32dev`): SHT31/SHT40 sensor abstraction
  with a documented DHT22 extension point, active-high/active-low relay
  driver with fail-safe startup ordering, Wi-Fi and MQTT connection
  management with bounded exponential backoff, and a hardware-independent
  `VentilationController` implementing hysteresis, anti-cycling timers,
  maximum-runtime protection, local fallback control, manual override,
  and structured diagnostic logging.
- Python automation service (`automation/`): MQTT-driven humidity rule
  engine (`HysteresisRule`) mirroring the firmware's control algorithm,
  payload schema validation, per-device telemetry freshness/duplicate
  tracking, and clean-shutdown signal handling.
- Software-only device simulator (`simulator/`): deterministic humidity
  profile generators (shower rise/decay, steady-state, invalid-reading
  bursts, multi-event days), a `DeviceController` port of the firmware's
  precedence/anti-cycling logic, an MQTT-connected `SimulatedDevice`, and
  a scripted end-to-end demonstration (`run_e2e_demo.py`) that exercises
  a real Mosquitto broker and the real automation service.
- Energy-efficiency comparison report (`energy/energy_report.py`):
  continuous vs. fixed-time vs. humidity-controlled ventilation, using
  the same control algorithm and a configurable fan wattage/duration.
- Eclipse Mosquitto broker configuration (authenticated, ACL template,
  TLS guidance) and Docker Compose stack for local development.
- Full documentation set: architecture, hardware/wiring, MQTT API,
  security, safety, testing, physical commissioning checklist, and
  requirements traceability.
- Test suites: 25 firmware native unit tests, 42 Python unit tests
  (automation service + simulator), and a full scripted end-to-end
  simulation - see `docs/testing.md`.

### Known limitations

- No physical ESP32, sensor, relay, or load has been tested - see
  `docs/requirements-traceability.md` and `docs/physical-commissioning.md`.

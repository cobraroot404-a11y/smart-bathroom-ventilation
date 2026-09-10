# Requirements Traceability

Status legend: **Verified** (automated evidence exists and was run),
**Verified (simulated)** (verified in software/simulation only - no
physical hardware involved), **Not tested** (requires physical hardware
not available during this build), **N/A** (documentation/process item,
no test applicable).

This table is the authoritative record of what was and was not verified
before publication - see `docs/testing.md` for full test output context
and `docs/physical-commissioning.md` for the physical checklist.

## Functional

| ID | Requirement | Implementation | Verification method | Evidence | Status | Physical validation still required |
|---|---|---|---|---|---|---|
| FN-1 | Measure relative humidity and temperature | [firmware/include/sensor.h](../firmware/include/sensor.h), [firmware/src/sensor.cpp](../firmware/src/sensor.cpp) (SHT31/40) | Compilation + code review; logic downstream unit-tested | `pio run -e esp32dev`; controller unit tests consume `SensorReading` | Verified (simulated) | Yes - real sensor never connected |
| FN-2 | ESP32 or comparably capable Wi-Fi MCU | [firmware/platformio.ini](../firmware/platformio.ini) (`esp32dev`) | Build target selection + compile | `pio run -e esp32dev` succeeded (SUCCESS, RAM 14.0%, Flash 62.7%) | Verified (simulated) | Yes - real board never flashed |
| FN-3 | Publish timestamped telemetry over MQTT | [firmware/include/mqtt_client.h](../firmware/include/mqtt_client.h), [automation/automation_service/schemas.py](../automation/automation_service/schemas.py), [docs/mqtt-api.md](mqtt-api.md) | Schema tests + real MQTT round trip in the e2e demo | `automation/tests/test_schemas.py`; `simulator/simulator/run_e2e_demo.py` step 13 | Verified | Real-device MQTT publish not tested |
| FN-4 | Evaluate humidity-control rules | [automation/automation_service/rules.py](../automation/automation_service/rules.py), [firmware/src/controller.cpp](../firmware/src/controller.cpp) | Unit tests (both implementations) | `automation/tests/test_rules.py` (15 tests); firmware native tests (25 tests) | Verified | No |
| FN-5 | Activate/deactivate a physical relay module | [firmware/include/relay.h](../firmware/include/relay.h) | Code review; active-high/low abstraction unit-testable via `RelayDriver` logic embedded in controller decisions | Firmware native tests assert `relay_on` transitions | Verified (simulated) | Yes - real relay never energized |
| FN-6 | Safe low-voltage load simulates an exhaust fan | [docs/hardware.md](hardware.md), [docs/safety.md](safety.md) | Documentation review | N/A | N/A (documentation) | Yes - no physical load connected |
| FN-7 | Minimize unnecessary runtime via hysteresis/timing | [firmware/src/controller.cpp](../firmware/src/controller.cpp), [automation/automation_service/rules.py](../automation/automation_service/rules.py) | Unit tests for hysteresis band, min-on, min-off | `test_min_on_time_is_enforced`, `test_min_off_time_is_enforced` (firmware + automation) | Verified | No |
| FN-8 | Continue operating safely during Wi-Fi/MQTT outages | [firmware/src/controller.cpp](../firmware/src/controller.cpp) (local fallback), [simulator/simulator/device_controller.py](../simulator/simulator/device_controller.py) | Unit tests + real outage in e2e demo | `test_stale_mqtt_command_triggers_local_fallback`; e2e demo step 11 | Verified | Real Wi-Fi/broker outage not tested |
| FN-9 | Testable without physical hardware (simulation) | [simulator/](../simulator/), `scripts/run_full_check.py` | Full simulation run | `scripts/run_full_check.py` (all steps) | Verified | N/A |
| FN-10 | Source code, tests, diagrams, config, docs included | Whole repository | Repository structure review | This file; `README.md` | Verified | N/A |
| FN-11 | Passes all feasible automated checks | `scripts/run_full_check.py` | Full run before publication | See completion report | Verified | N/A |
| FN-12 | Published to a new public GitHub repo, proprietary source-visible license | GitHub publication step | `gh repo view`, license file review | github.com/cobraroot404-a11y/smart-bathroom-ventilation | Verified | N/A |
| FN-13 | Proprietary source-visible license, Gautham as copyright holder, no open-source terms | [LICENSE](../LICENSE) | Manual review | File content | Verified | N/A |
| FN-14 | No secrets, no inappropriate third-party attribution | `.gitignore`, secret audit | `git log`/`git grep` scan before publish | See completion report | Verified | N/A |
| FN-15 | Development system left clean, project not deleted | Cleanup step | Manual review of stopped services/containers | See completion report | Verified | N/A |

## Hardware

| ID | Requirement | Implementation | Verification method | Evidence | Status | Physical validation still required |
|---|---|---|---|---|---|---|
| HW-1 | Determine active-high/active-low | [docs/hardware.md](hardware.md) "Active-high vs. active-low" | Documentation + config flag | `relay.active_low` in `config/defaults.yaml` | Verified (simulated) | Yes - confirm against the actual module purchased |
| HW-2 | Confirm relay input voltage/current vs. 3.3V logic | [docs/hardware.md](hardware.md) "Relay module supply..." | Documentation | N/A | N/A (documentation) | Yes |
| HW-3 | Relay cannot energize during boot/reset/flashing | [firmware/include/relay.h](../firmware/include/relay.h) (`Init()` ordering), [docs/hardware.md](hardware.md) "Startup / reset / flashing safety" | Code review of `setup()` ordering; documented pull-resistor mitigation | `firmware/src/main.cpp` `setup()` | Verified (simulated) | Yes - measure actual relay behavior across power cycles |
| HW-4 | Transistor/MOSFET/optocoupler/flyback/isolation where required | [docs/hardware.md](hardware.md) "Isolation", "flyback protection" | Documentation | N/A | N/A (documentation) | Yes |
| HW-5 | Document common ground / isolation | [docs/hardware.md](hardware.md) "Isolation" | Documentation | N/A | N/A (documentation) | N/A |
| HW-6 | GPIO not a problematic boot-strapping pin | [firmware/include/config.h](../firmware/include/config.h) (`kRelayGpioPin = 27`), [docs/hardware.md](hardware.md) "Pin assignment" | Documentation + config review | GPIO27 chosen, documented rationale | Verified (simulated) | No (documented reasoning is hardware-independent) |
| HW-7 | Relay default state OFF | [firmware/include/config.h](../firmware/include/config.h) (`kRelayStartupOn = false`), [firmware/include/relay.h](../firmware/include/relay.h) | Unit test (controller starts with `relay_on=false`) | `test_startup_relay_is_off` | Verified (simulated) | Yes - confirm on real hardware |
| HW-8 | BOM, pin table, wiring, power budget, diagrams, commissioning checklist, troubleshooting | [docs/hardware.md](hardware.md), [docs/physical-commissioning.md](physical-commissioning.md) | Documentation review | N/A | Verified (documentation complete) | N/A |

## Safety

| ID | Requirement | Implementation | Verification method | Evidence | Status | Physical validation still required |
|---|---|---|---|---|---|---|
| SF-1 | Turn fan ON at/above upper threshold | `controller.cpp` / `rules.py` | Unit test | `test_humidity_crossing_upper_threshold_turns_fan_on` | Verified | No |
| SF-2 | Turn fan OFF at/below lower threshold | same | Unit test | `test_humidity_crossing_lower_threshold_turns_fan_off` | Verified | No |
| SF-3 | Preserve state inside hysteresis band | same | Unit test | `test_humidity_in_band_preserves_state_while_on/off` | Verified | No |
| SF-4 | Avoid rapid relay cycling | same | Unit test (min-on/off enforced on every path) | `test_min_on_time_is_enforced`, `test_min_off_time_is_enforced` | Verified | No |
| SF-5 | Configurable minimum on/off times | `config/defaults.yaml`, `ControllerConfig` | Config review + tests above | same as SF-4 | Verified | No |
| SF-6 | Configurable maximum runtime | same | Unit test | `test_max_runtime_cutoff_forces_off`, `test_max_runtime_cutoff_overrides_manual_override` | Verified | No |
| SF-7 | Reject invalid/impossible sensor measurements | `controller.cpp::OnSensorReading` range check | Unit test | `test_invalid_reading_is_rejected_and_does_not_switch` | Verified | No |
| SF-8 | Detect stale telemetry | `automation_service/state.py` (`is_stale`), firmware staleness on `fan/desired` | Unit test | `automation/tests/test_state.py` | Verified | No |
| SF-9 | Handle sensor read failures without uncontrolled switching | `sensor_invalid_safe_state` logic | Unit test | `test_sensor_failure_beyond_limit_forces_safe_off_state` | Verified | Yes - real sensor failure mode (disconnect) not tested |
| SF-10 | Restore safe, documented state after restart | `docs/safety.md` "Restart behavior"; controller starts OFF/local_fallback | Unit test (fresh controller instance = restart) | `test_startup_relay_is_off`, `test_startup_high_humidity_is_held_until_min_off_elapses` | Verified (simulated) | Yes - real power-cycle test |
| SF-11 | Publish current and desired relay states | `docs/mqtt-api.md` `fan/actual`/`fan/desired` | e2e demo observes both on the real broker | e2e demo step 13 | Verified | No |
| SF-12 | Log reason behind each control decision | `Reason` enum + `diagnostics::LogDecision`, Python `reason` fields | Code review; reasons asserted in every unit test | All controller/rule tests assert `.reason` | Verified | No |
| SF-13 | Manual override: automatic/timed/OFF modes | `controller.cpp::OnCommand`, `command` topic | Unit test | `test_manual_override_on_forces_relay_on`, `_off_forces_relay_off`, `_expires_and_returns_to_automatic`, `_auto_cancels...` | Verified | No |
| SF-14 | Return to automatic after override timeout | same | Unit test | `test_manual_override_expires_and_returns_to_automatic` | Verified | No |
| SF-15 | Preserve relay state only when safe/intentional | `sensor_invalid_hold_last_state` config, documented default OFF | Unit test | `test_sensor_failure_can_be_configured_to_hold_last_state` | Verified | No |
| SF-16 | Boundary behavior explicitly documented and tested | `docs/safety.md`, all boundary unit tests | Cross-reference | This table + `docs/safety.md` | Verified | No |

## Resilience / local fallback

| ID | Requirement | Implementation | Verification method | Evidence | Status | Physical validation still required |
|---|---|---|---|---|---|---|
| RS-1 | Local fallback uses configured hysteresis when MQTT stale/unavailable | `controller.cpp::ComputeCandidate` | Unit test | `test_stale_mqtt_command_triggers_local_fallback` | Verified | No |
| RS-2 | Invalid/unavailable sensor data leads to documented safe state | same | Unit test | `test_sensor_failure_beyond_limit_forces_safe_off_state` | Verified | No |
| RS-3 | Max-runtime protection remains active in fallback | same | Unit test | `test_max_runtime_cutoff_forces_off` (runs under fallback conditions) | Verified | No |
| RS-4 | Reconnection does not cause unsafe/rapid switching | timers keyed on device clock, not message arrival | Unit test + e2e demo | `test_retained_command_stale_at_receipt_is_ignored`; e2e demo step 12 | Verified | Yes - real reconnect timing not measured |
| RS-5 | Publish on entering/exiting fallback mode | `mode` topic, `firmware/src/main.cpp` fallback-change publish | e2e demo observes `mode` messages | e2e demo step 13 | Verified | No |
| RS-6 | Distinguish requested/actual/mode/availability/sensor-validity | `docs/mqtt-api.md` topic set; `ControlDecision` fields | Schema/topic review + tests | `docs/mqtt-api.md`; telemetry schema tests | Verified | No |

## Security

| ID | Requirement | Implementation | Verification method | Evidence | Status | Physical validation still required |
|---|---|---|---|---|---|---|
| SC-1 | No unauthenticated broker exposed publicly | `mosquitto/config/mosquitto.conf` (`allow_anonymous false`), `docs/security.md` | Config review | File content | Verified | N/A |
| SC-2 | Separate device/service credentials | `.env.example` (`MQTT_DEVICE_*` vs `MQTT_AUTOMATION_*`) | Config review | File content | Verified | N/A |
| SC-3 | Topic-level ACL guidance | `mosquitto/config/acl.example.conf` | Config review | File content | Verified | N/A |
| SC-4 | TLS guidance for untrusted networks | `docs/security.md` "Transport encryption" | Documentation | N/A | N/A (documentation) | N/A |
| SC-5 | Secrets via env vars / local config / device storage | `.env`, `config/device.json`, `firmware/include/secrets.h` (all git-ignored) | `.gitignore` review | `.gitignore` | Verified | N/A |
| SC-6 | Only placeholder credentials committed | `.env.example`, `config/device.example.json`, `firmware/include/secrets.example.h` | Manual review | File content | Verified | N/A |
| SC-7 | No secrets in git history | Secret audit before publish | `git log -p` scan / `git grep` | See completion report | Verified | N/A |
| SC-8 | Command/payload validation (schema, size, staleness) | `mqtt_handler.py`, `mqtt_client.h` | Unit tests | `automation/tests/test_mqtt_handler.py`, `test_schemas.py` | Verified | No |
| SC-9 | Duplicate-message-safe behavior | `state.py::is_duplicate` | Unit test | `test_duplicate_seq_is_not_reprocessed` | Verified | No |
| SC-10 | Protection against unsafe retained commands after outage | staleness check on `fan/desired` issued_at | Unit test | `test_retained_command_stale_at_receipt_is_ignored` (firmware + equivalent design in device_controller) | Verified | No |

## Energy efficiency

| ID | Requirement | Implementation | Verification method | Evidence | Status | Physical validation still required |
|---|---|---|---|---|---|---|
| EN-1 | Compare continuous/fixed-time/humidity-controlled strategies | [energy/energy_report.py](../energy/energy_report.py) | Script run | e2e demo step 14; manual run output in completion report | Verified (simulated estimate) | Yes - no real fan/meter measurement |
| EN-2 | Configurable fan wattage and duration | CLI flags `--fan-watts`, `--duration-hours` | Code review | `energy/energy_report.py --help` | Verified | N/A |
| EN-3 | Report runtime, energy, energy saved, assumptions, limitations | `print_report()` | Manual run | Sample output in completion report | Verified | N/A |
| EN-4 | No unsupported environmental/health/cost claims | Report text review | Manual review | `energy/energy_report.py` output text | Verified | N/A |

## Testing

| ID | Requirement | Implementation | Verification method | Evidence | Status | Physical validation still required |
|---|---|---|---|---|---|---|
| TS-1 | Firmware dependency install / compile | `firmware/platformio.ini` | `pio run -e esp32dev` | Build succeeded: RAM 14.0% (45996/327680 B), Flash 62.7% (821341/1310720 B), `firmware.bin` produced | Verified | N/A (compile-only; flashing requires real hardware) |
| TS-2 | Firmware unit tests (threshold/hysteresis/timers/max-runtime/relay-polarity/startup/invalid-sensor/fallback) | `firmware/test/test_controller/test_main.cpp` | `pio test -e native` (or Dockerized equivalent - see `docs/testing.md`) | 25/25 passing | Verified | N/A |
| TS-3 | MQTT reconnection tests where feasible | `firmware/include/mqtt_client.h` backoff logic; e2e demo real outage/reconnect | e2e demo steps 11-12 | e2e demo output | Verified | Real-hardware MQTT reconnect not tested |
| TS-4 | Automation unit/schema/boundary/stale/restart/invalid-command/retained/duplicate/override tests | `automation/tests/*.py` | `pytest` | 42/42 passing | Verified | N/A |
| TS-5 | End-to-end simulation (all 15 checklist items in docs/testing.md) | `simulator/simulator/run_e2e_demo.py` | Script run | e2e demo output, all steps OK | Verified | N/A |
| TS-6 | Do not publish until all feasible tests pass | `scripts/run_full_check.py` | Full run | See completion report | Verified | N/A |

## Documentation

| ID | Requirement | Implementation | Status |
|---|---|---|---|
| DOC-1 | README (all required sections) | [README.md](../README.md) | Verified |
| DOC-2 | architecture.md | [docs/architecture.md](architecture.md) | Verified |
| DOC-3 | hardware.md | [docs/hardware.md](hardware.md) | Verified |
| DOC-4 | mqtt-api.md | [docs/mqtt-api.md](mqtt-api.md) | Verified |
| DOC-5 | security.md | [docs/security.md](security.md) | Verified |
| DOC-6 | safety.md | [docs/safety.md](safety.md) | Verified |
| DOC-7 | testing.md | [docs/testing.md](testing.md) | Verified |
| DOC-8 | physical-commissioning.md | [docs/physical-commissioning.md](physical-commissioning.md) | Verified |
| DOC-9 | requirements-traceability.md | this file | Verified |
| DOC-10 | CHANGELOG.md | [CHANGELOG.md](../CHANGELOG.md) | Verified |
| DOC-11 | CONTRIBUTING.md (sole maintainer) | [CONTRIBUTING.md](../CONTRIBUTING.md) | Verified |

## Licensing and authorship

| ID | Requirement | Status |
|---|---|---|
| LIC-1 | Proprietary source-visible license, `Copyright (c) 2026 Gautham`, all rights reserved, no open-source/MIT license | Verified |
| LIC-2 | License referenced in README/metadata; no MIT badge or open-source labeling | Verified |
| AUTH-1 | Sole author/maintainer/contributor: Gautham, no AI/tool attribution, no co-author trailers | Verified - commits use a locally-configured (repo-only) git identity of `Gautham`; commit messages contain no AI/tool attribution |
| AUTH-2 | No fabricated email; user's own git identity used | Verified - email supplied directly by the user for this repository's local git config |

## GitHub publication

| ID | Requirement | Status |
|---|---|---|
| GH-1 | New public repo in authenticated account, exact description, no open-source license selected | Verified - github.com/cobraroot404-a11y/smart-bathroom-ventilation; description matches exactly; GitHub's own license detection labels the committed LICENSE "Other" (not MIT/Apache/GPL/BSD) |
| GH-2 | Default branch `main` | Verified - `defaultBranchRef.name == "main"` |
| GH-3 | No collaborators, no org ownership, no bot config | Verified - only owner `cobraroot404-a11y` listed as collaborator/contributor |
| GH-4 | No exposed secrets after push | Verified - same pattern/history scan as SC-7, run again against the pushed repository |
| GH-5 | Issues/Discussions/Projects disabled; no contribution-inviting templates | Verified - `hasIssuesEnabled`, `hasDiscussionsEnabled`, `hasProjectsEnabled` all `false`. **Platform limitation**: GitHub does not offer a way to disable forking or pull-request submission on a public personal-account repository (`allow_forking: true`, not configurable for non-organization repos) - the LICENSE and README contribution policy govern instead; this is disclosed rather than claimed to be technically blocked |

## Cleanup

| ID | Requirement | Status |
|---|---|---|
| CLN-1 | Stop broker/automation/simulator/dev processes started for this project | Verified - see completion report |
| CLN-2 | Scoped, recoverable cleanup; no broad recursive deletes | Verified |
| CLN-3 | Clean git working tree at completion | Verified - see completion report |
| CLN-4 | Project repository, docs, tests, history preserved | Verified - nothing deleted |

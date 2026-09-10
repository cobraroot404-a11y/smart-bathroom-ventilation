# Physical Commissioning Checklist

None of the boxes below are checked in this repository. This prototype
was designed, implemented, and verified in software/simulation only - no
physical ESP32, sensor, relay, or load was connected during its build
(see `docs/requirements-traceability.md` and `docs/testing.md`). Whoever
assembles the real hardware must work through this checklist and record
the results (date, who performed it, measured values) before relying on
the system for real ventilation control, and **before any mains-connected
installation, which additionally requires a qualified electrician - see
`docs/safety.md`.**

## Power and electrical safety

- [ ] Verify the ESP32 supply voltage/current (USB 5V source) is stable under Wi-Fi TX load.
- [ ] Confirm the load-side DC power supply's voltage matches the fan/lamp/LED's rating.
- [ ] Confirm the load-side supply's current capacity exceeds the load's maximum draw.
- [ ] Confirm ESP32 GPIO logic level (3.3V) compatibility with the relay module's signal input - see `docs/hardware.md`.
- [ ] Identify whether the specific relay module is active-high or active-low from its datasheet/silkscreen, and set `RELAY_ACTIVE_LOW` / `relay.active_low` accordingly.
- [ ] Confirm the relay remains OFF (de-energized) through repeated power-on, reset, and reflash cycles (breadboard test procedure in `docs/hardware.md`).
- [ ] Verify which relay contact (NO vs. NC) the load is wired to, and confirm it is NO per this design's fail-safe requirement.
- [ ] Measure relay coil/trigger current draw and confirm the supply rail powering it can provide it.
- [ ] Measure actual load current with a multimeter and confirm it is within the relay's contact rating and the load supply's capacity.
- [ ] Check component temperatures (ESP32, relay module, any driver transistor) after an extended run under load.
- [ ] If substituting a DC motor/fan load, confirm flyback protection is present (on-module or an added diode) - see `docs/hardware.md`.

## Sensor

- [ ] Verify sensor readings (humidity and temperature) against a separate reference instrument, at more than one humidity level if possible.
- [ ] Confirm the I2C address and wiring (SDA/SCL) match `config/defaults.yaml`.
- [ ] Test invalid-sensor behavior: disconnect the sensor (or short/float its data line) and confirm `sensor/status` reports failure and the relay reaches the documented safe state.
- [ ] Confirm sensor placement follows `docs/hardware.md` / `docs/safety.md` guidance (not in direct shower spray, not on an exterior wall, not beside the exhaust inlet, not touching condensation-prone surfaces).

## Network and control behavior

- [ ] Test a Wi-Fi outage (disable the AP or move the device out of range) and confirm the device enters `local_fallback` mode and continues controlling the fan safely.
- [ ] Test an MQTT broker outage (stop Mosquitto) and confirm the same fallback behavior, independent of Wi-Fi.
- [ ] Confirm reconnection after an outage does not cause rapid relay cycling (watch `fan/actual` for at least the `min_fan_on_seconds`/`min_fan_off_seconds` window after reconnecting).
- [ ] Confirm `device/status` correctly reports `offline` (via the MQTT Last Will) when power or network is cut abruptly.
- [ ] Exercise a manual override command (`override_on`, `override_off`, `override_auto`) and confirm the device applies it and reverts to automatic mode after its timeout.

## Extended validation

- [ ] Run an extended soak test (multiple hours minimum) at the low-voltage bench setup, monitoring for unexpected relay chatter, sensor drift, memory leaks (device uptime/reconnect behavior), or MQTT disconnects.
- [ ] Calibrate `fan_on_percent`/`fan_off_percent` (and, if used, `rise_rate_detection` settings) against the actual room's humidity behavior during a real shower, not just the synthetic simulation profiles.

## Enclosure and installation

- [ ] Confirm the enclosure (if any) protects the ESP32/relay from moisture and condensation appropriate to a bathroom environment.
- [ ] For any mains-connected deployment: obtain installation by (or inspection from) a qualified, licensed electrician, per local building/electrical code - see `docs/safety.md`. This box cannot be checked by software testing.

---

**Record of completion** (fill in when performed):

| Item | Date | Performed by | Notes / measured values |
|---|---|---|---|
| | | | |

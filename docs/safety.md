# Safety

## Prototype electrical-safety boundary

> **This project is a low-voltage DC prototype and demonstration only.**
> Development and demonstration must use only a safe, current-limited
> low-voltage DC load: a 5 V or 12 V DC fan, a low-voltage lamp, or an LED
> with a suitable series resistor. **Never wire household mains voltage
> directly to a breadboard, an exposed relay module, or any part of this
> prototype.**
>
> A real bathroom exhaust-fan installation additionally involves:
> moisture and condensation exposure, electrical-code requirements,
> proper earthing/grounding, overcurrent and fault protection (fuses/
> breakers), electrical isolation appropriate to a wet location,
> appropriately IP-rated enclosures and cable glands, correctly rated
> relays/contactors for the actual fan's inrush and running current, and
> compliance with local building and electrical regulations. Installation
> of any mains-connected ventilation control in a bathroom **must be
> performed, or at minimum inspected and approved, by a qualified,
> licensed electrician** in your jurisdiction. **Passing this project's
> software tests does not certify any assembly for mains-voltage or
> bathroom use.**

## Fail-safe defaults

| Condition | Behavior | Reason |
|---|---|---|
| Relay power-up / reset / reflash | OFF (de-energized), NO contact open | A fan that could unexpectedly energize during boot is a safety and nuisance risk; OFF-by-default is the conventional fail-safe choice for a non-life-safety ventilation aid |
| Sensor invalid beyond `sensor.consecutive_failure_limit` (default 3) | Relay forced OFF (`relay.sensor_invalid_safe_state: "off"`), reason `sensor_invalid_safe_state` | See "Sensor-failure default" below |
| MQTT/Wi-Fi unavailable or `fan/desired` stale | Local fallback hysteresis control using the last valid local sensor reading | Ventilation must not depend on network availability (requirement 8 / section 5) |
| `max_continuous_runtime_seconds` exceeded | Relay forced OFF regardless of humidity, automatic mode, fallback mode, **or active manual override** | Bounds worst-case fan runtime/energy/noise even under a stuck-on command, a runaway automation bug, or an operator who forgets an override is active |
| Impossible sensor reading (outside configured min/max bounds) | Reading discarded, treated as a failure for consecutive-failure counting, last valid reading retained for control until the failure limit is hit | Prevents a single glitch reading from causing an unsafe or nonsensical switch |
| Startup after restart | Relay OFF, `operating_mode` starts in `local_fallback` until a fresh MQTT `fan/desired` is received, existing min-off timer *not* assumed satisfied (see below) | Documented, deterministic restart behavior; never assumes it is safe to immediately turn the fan on right after an unknown-length power interruption |

### Sensor-failure default: OFF, not "hold last state"

`relay.sensor_invalid_safe_state` defaults to `"off"` rather than holding
the relay at its last commanded state. Rationale: once the sensor is known
to be failing, the controller has no reliable basis for *any* humidity-based
decision, including "stay on." Leaving a fan running indefinitely on stale/
unverifiable justification wastes energy, adds noise and motor wear, and
provides no proven safety benefit, whereas the downside of stopping
ventilation during a genuine but undetected humidity event is bounded and
recoverable (a human in the room can open a door/window, and a manual
override remains available via MQTT even while the sensor is down since
override does not depend on sensor validity). `"hold_last_state"` is
implemented and available as a configuration alternative for deployments
that make a different risk tradeoff, but is not the default and has not
been the subject of the same design review here.

### Anti-cycling and timing

- `min_fan_on_seconds` (default 120 s) and `min_fan_off_seconds` (default
  30 s) are enforced on every code path that can change relay state
  (automatic, local fallback, and manual override transitions), preventing
  rapid relay cycling regardless of why a state change was requested.
- Reconnection after a network outage does **not** immediately reconcile
  to whatever the freshly-received `fan/desired` says if doing so would
  violate the min-on/min-off timer already in progress locally - the
  timers are tracked against wall-clock/monotonic device time, not MQTT
  message arrival, so a burst of catch-up messages after reconnecting
  cannot cause rapid toggling.
- The hysteresis band (`fan_on_percent` > `fan_off_percent`, default 70%/
  60%) guarantees the controller only changes state at the two threshold
  crossings and explicitly **holds** current state anywhere in between -
  this is a required, tested behavior, not an incidental one (see
  `docs/testing.md`).

## Operating modes and precedence

From highest to lowest precedence, the maximum-runtime cutoff is checked
independent of mode and always wins:

1. **Maximum-runtime cutoff** (always active, cannot be overridden)
2. **Manual override** (`manual_on`, `manual_off`, or `manual_timed`,
   received via the `command` topic) - reverts automatically to automatic
   mode after its configured/timed-out duration
3. **Automatic** (`fan/desired` from the automation service, while fresh)
4. **Local fallback** (device's own hysteresis logic, using its own last
   valid sensor reading), entered whenever `fan/desired` is stale or MQTT
   is unavailable

The system always distinguishes and separately reports (see
`docs/mqtt-api.md`):

- **Requested state** (`requested_relay_on` in telemetry / `fan/desired`)
- **Actual relay state** (`actual_relay_on` / `fan/actual`)
- **Operating mode** (`operating_mode` / `mode` topic)
- **Device availability** (`device/status`, via LWT)
- **Sensor validity** (`sensor_valid`, `sensor/status`)

## Optional humidity-rise-rate detection

Disabled by default (`rise_rate_detection.enabled: false`). When enabled,
it can trigger ventilation on a rapid humidity *rate of increase* even
before the absolute `fan_on_percent` threshold is crossed - intended to
catch a shower's humidity spike earlier. It:

- requires `rise_rate_detection.min_valid_samples` consecutive valid
  readings within `rise_rate_detection.window_seconds` before it will
  fire, so a single noisy reading cannot trigger it;
- is still subject to every anti-cycling and max-runtime protection above;
- has known limitations: ambient humidity can rise quickly for reasons
  unrelated to bathroom use (e.g. weather fronts, HVAC changes, a door
  opened to a humid outdoor climate), and its ideal threshold is seasonal
  and climate-dependent. It should only be enabled after being verified
  against your specific room's normal humidity variability, which this
  prototype has not done - see `docs/requirements-traceability.md`.

## Restart behavior

On restart (power loss, watchdog reset, or manual reset), the controller:

1. Immediately drives the relay to OFF (see hardware startup-safety
   measures in `docs/hardware.md`).
2. Starts `operating_mode` in `local_fallback` rather than assuming the
   last-known automation state is still valid or that any MQTT command
   received immediately after reconnecting is safe to apply without the
   usual staleness check.
3. Does **not** assume the just-completed min-off timer from before the
   restart is satisfied - the timer restarts at boot, so a restart can
   never be used to bypass the anti-cycling protection.
4. Publishes `device/status: online` and the current `mode`/`fan/actual`
   promptly so subscribers see accurate state rather than stale retained
   values from before the restart.

# MQTT API

All topics are namespaced under `bathroom/ventilation/` and use JSON
payloads with a `schema_version` field so future changes can be introduced
without breaking older subscribers. `{device_id}` defaults to
`bathroom-vent-01` (see `config/defaults.yaml`) but is configurable per
deployment; a home with multiple devices would give each a unique
`device_id` and, if desired, a unique topic prefix.

Payloads are capped at 2048 bytes (`mqtt.max_payload_bytes` in
`config/defaults.yaml`). Oversized or malformed payloads are logged and
discarded by both the firmware and the automation service rather than
acted upon.

## Topic reference

| Topic | Publisher | Subscriber(s) | QoS | Retained | Purpose |
|---|---|---|---|---|---|
| `bathroom/ventilation/telemetry` | ESP32 device | automation service, simulator, any dashboard | 1 | No | Full periodic telemetry snapshot (humidity, temperature, sensor/relay/mode state) |
| `bathroom/ventilation/sensor/humidity` | ESP32 device | dashboards / convenience subscribers | 0 | Yes | Latest humidity reading only, for lightweight subscribers that don't need the full telemetry object |
| `bathroom/ventilation/sensor/temperature` | ESP32 device | dashboards / convenience subscribers | 0 | Yes | Latest temperature reading only |
| `bathroom/ventilation/command` | automation service / operator tooling | ESP32 device | 1 | **No** | Manual override commands (see below) |
| `bathroom/ventilation/fan/desired` | automation service (and the device itself while in local fallback, so subscribers see the authoritative desired state regardless of source) | ESP32 device, dashboards | 1 | Yes, with staleness guard | Desired relay state computed by whichever controller is currently authoritative |
| `bathroom/ventilation/fan/actual` | ESP32 device | automation service, dashboards | 1 | Yes | Actual, physically-applied relay state and the reason for the last change |
| `bathroom/ventilation/mode` | ESP32 device | automation service, dashboards | 1 | Yes | Current operating mode, fallback/override status |
| `bathroom/ventilation/device/status` | ESP32 device (Last Will and Testament + birth message) | automation service, dashboards | 1 | Yes | Online/offline availability |
| `bathroom/ventilation/sensor/status` | ESP32 device | automation service, dashboards | 1 | Yes | Sensor validity / consecutive-failure state |
| `bathroom/ventilation/config` | ESP32 device | dashboards, operators | 1 | Yes | Effective configuration snapshot published on boot and on any local config change (read-only visibility; this prototype changes configuration via `config/device.json` and reflashing, not via MQTT, to avoid an additional unsafe-retained-command surface) |

### Why `command` is not retained but `fan/desired` is

`fan/desired` is retained so that a device reconnecting after a restart
immediately learns the last known desired state without waiting for the
automation service to republish. This is safe *only* because every
`fan/desired` payload carries an `issued_at` timestamp, and the firmware
treats a retained message older than `timing.stale_command_timeout_seconds`
(default 60 s) as stale and ignores it, falling back to local hysteresis
control instead (see `docs/safety.md`). This is the mitigation for
requirement "protection against unsafe retained commands after long
outages."

`command` (manual override) is intentionally **not** retained. A retained
override command replayed to a device after a long outage could silently
force the fan on/off against the operator's current intent. Since override
commands are infrequent, one-shot operator actions, non-retention is the
safer default: after an outage, the device simply resumes automatic
operation instead of replaying a stale override.

## Payload schemas

### `telemetry`

```json
{
  "schema_version": 1,
  "device_id": "bathroom-vent-01",
  "seq": 1234,
  "humidity_percent": 72.4,
  "temperature_celsius": 24.8,
  "sensor_valid": true,
  "sensor_status": "ok",
  "requested_relay_on": true,
  "actual_relay_on": true,
  "operating_mode": "automatic",
  "control_source": "mqtt",
  "fallback_active": false,
  "override_active": false,
  "uptime_seconds": 3600,
  "timestamp": "2026-09-09T15:30:00Z"
}
```

- `sensor_status`: `"ok"`, `"degraded"` (some recent failures, still within
  retry budget), or `"failed"` (consecutive-failure limit exceeded).
- `operating_mode`: `"automatic"`, `"manual_on"`, `"manual_off"`, or
  `"local_fallback"`. `manual_on`/`manual_off` are always timed (they carry
  an `override_expires_at` in the `mode` topic and always auto-revert to
  `automatic`); there is no separate untimed manual mode.
- `control_source`: `"mqtt"` (desired state came from a fresh MQTT command)
  or `"local"` (device is using its own hysteresis logic).

### `sensor/humidity` and `sensor/temperature`

```json
{ "schema_version": 1, "value": 72.4, "valid": true, "timestamp": "2026-09-09T15:30:00Z" }
```

These are convenience mirrors of the corresponding `telemetry` fields.
Control logic never reads these topics directly - they exist only for
lightweight external subscribers.

### `command`

```json
{
  "schema_version": 1,
  "command": "override_on",
  "duration_seconds": 1800,
  "issued_at": "2026-09-09T15:30:00Z"
}
```

- `command`: `"override_on"`, `"override_off"`, or `"override_auto"`
  (cancels any active override and returns to automatic control
  immediately).
- `duration_seconds`: optional; if omitted, defaults to
  `timing.manual_override_default_duration_seconds`. Clamped to
  `timing.manual_override_max_duration_seconds`. After this duration
  elapses the device automatically returns to `"automatic"` mode.
- Commands with `issued_at` older than `stale_command_timeout_seconds` at
  the time of receipt are rejected and logged, not applied.
- The maximum-continuous-runtime safety cutoff (`max_continuous_runtime_seconds`)
  still applies during `override_on` - see `docs/safety.md`.

### `fan/desired`

```json
{
  "schema_version": 1,
  "desired_relay_on": true,
  "reason": "humidity_above_threshold",
  "source": "automation",
  "issued_at": "2026-09-09T15:30:00Z"
}
```

- `source`: `"automation"` or `"local_fallback"`.
- `reason` is a short machine-readable enum documented in
  `docs/safety.md` / firmware source (e.g. `humidity_above_threshold`,
  `humidity_below_threshold`, `hysteresis_hold`, `min_on_time_hold`,
  `min_off_time_hold`, `max_runtime_cutoff`, `sensor_invalid_safe_state`,
  `manual_override`).

### `fan/actual`

```json
{
  "schema_version": 1,
  "actual_relay_on": true,
  "reason": "humidity_above_threshold",
  "timestamp": "2026-09-09T15:30:00Z"
}
```

### `mode`

```json
{
  "schema_version": 1,
  "operating_mode": "automatic",
  "fallback_active": false,
  "override_active": false,
  "override_expires_at": null,
  "timestamp": "2026-09-09T15:30:00Z"
}
```

Published immediately whenever the device enters or exits local fallback
mode, in addition to its normal periodic republish, per requirement
"publish when it enters or exits fallback mode."

### `device/status`

```json
{ "schema_version": 1, "device_id": "bathroom-vent-01", "status": "online", "timestamp": "2026-09-09T15:30:00Z" }
```

- Birth message: published retained, QoS 1, immediately after connecting.
- Will message: registered with the broker *before* connecting, so
  `status: "offline"` is published automatically by the broker if the
  device disconnects uncleanly.

### `sensor/status`

```json
{
  "schema_version": 1,
  "sensor_valid": true,
  "consecutive_failures": 0,
  "last_valid_reading_age_seconds": 5,
  "status": "ok",
  "timestamp": "2026-09-09T15:30:00Z"
}
```

### `config`

```json
{
  "schema_version": 1,
  "fan_on_percent": 70.0,
  "fan_off_percent": 60.0,
  "min_fan_on_seconds": 120,
  "min_fan_off_seconds": 30,
  "max_continuous_runtime_seconds": 1800,
  "stale_telemetry_timeout_seconds": 60,
  "rise_rate_detection_enabled": false,
  "timestamp": "2026-09-09T15:30:00Z"
}
```

## QoS and delivery notes

- QoS 1 is used for every state/command topic because at-most-once (QoS 0)
  delivery could silently drop a fan-on/fan-off transition, and QoS 2 is
  unnecessary overhead for a local network with idempotent, timestamped
  payloads.
- **Duplicate-message safety**: every state-changing payload is idempotent
  - applying the same `fan/desired` or `command` payload twice produces
  the same result (the controller compares against current state, not a
  delta). `telemetry` carries a monotonically increasing `seq` so
  duplicate telemetry can be detected and ignored by subscribers that
  care about counting messages.
- **Client IDs**: the device uses a unique MQTT client ID derived from
  `device_id` (e.g. `esp32-bathroom-vent-01`); the automation service uses
  `automation-<device_id>`. Unique client IDs prevent the broker from
  disconnecting one client when another connects with a colliding ID.
- **Reconnection**: both the firmware and the automation service use
  bounded exponential backoff (`mqtt.reconnect_backoff_initial_seconds`
  doubling up to `mqtt.reconnect_backoff_max_seconds`) rather than
  reconnecting in a tight loop.

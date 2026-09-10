# Security

## Broker exposure

**Do not expose the MQTT broker to the public internet without TLS and
authentication.** The default `docker-compose.yml` in this repository
binds Mosquitto to the local machine/network only and requires
authentication (anonymous access is disabled - see
`mosquitto/config/mosquitto.conf`). If you need remote access, put it
behind a VPN or a TLS-terminating reverse proxy with its own
authentication rather than forwarding port 1883/8883 directly from your
router.

## Authentication

- Mosquitto is configured with `allow_anonymous false` and a password file
  (`mosquitto/config/mosquitto.passwd`, generated locally, git-ignored -
  see `scripts/generate_mosquitto_passwd.sh` / `.ps1`).
- **Separate credentials are used for the automation service and the
  device** (`MQTT_AUTOMATION_USERNAME`/`MQTT_AUTOMATION_PASSWORD` vs.
  `MQTT_DEVICE_USERNAME`/`MQTT_DEVICE_PASSWORD` in `.env`), so either can
  be rotated or revoked independently without affecting the other.
- Topic-level access control: Mosquitto's ACL file
  (`mosquitto/config/acl.example.conf`) documents a recommended policy -
  the device account gets read access to `command` and `fan/desired`
  and write access to its own telemetry/status topics; the automation
  account gets read access to `telemetry`/`sensor/#`/`device/status` and
  write access to `fan/desired`/`command`. Copy it to
  `mosquitto/config/acl.conf` (git-ignored) and reference it from
  `mosquitto.conf` to enforce it; it ships disabled by default in this
  prototype's compose file so the quick-start demo works without extra
  setup, and enabling it is called out as a step in `README.md`.

## Transport encryption

MQTT traffic in this prototype's default `docker-compose.yml` setup stays
on the local Docker network / local machine and is unencrypted (plain
TCP on port 1883), which is an accepted tradeoff for a local development
and demonstration environment. **If MQTT traffic will ever cross a network
you do not fully trust** (e.g. a device on Wi-Fi talking to a broker
elsewhere, or any broker reachable from outside your LAN), enable TLS:

- Mosquitto: add a `listener 8883` block with `cafile`/`certfile`/
  `keyfile` directives (see comments in `mosquitto/config/mosquitto.conf`).
- Firmware: `PubSubClient`/`WiFiClientSecure` supports TLS; set
  `mqtt.use_tls: true` in `config/device.json` and provide the broker's CA
  certificate. This prototype ships TLS support as a documented,
  configurable option, not enabled in the default local demo, since it
  requires generating/managing certificates that are out of scope for a
  bench prototype.

## Secret handling

- Real secrets live only in `.env` (git-ignored) and
  `config/device.json` (git-ignored) and `firmware/include/secrets.h`
  (git-ignored, generated from `firmware/include/secrets.example.h`).
- Only placeholder values are committed, in `.env.example`,
  `config/device.example.json`, and `firmware/include/secrets.example.h`.
- The firmware reads Wi-Fi/MQTT credentials from `secrets.h`, which is
  never committed - see `.gitignore`.
- No Wi-Fi SSID/password, MQTT production credential, GitHub token,
  private key, certificate private material, or personal address is
  committed anywhere in this repository or its git history (see the
  secret audit performed before publication, recorded in
  `docs/requirements-traceability.md`).

## Command validation

- Every inbound MQTT payload (`fan/desired` consumed by the firmware in
  automatic mode; `command` consumed by the firmware for overrides;
  `telemetry` consumed by the automation service) is schema/type/range
  validated before being acted on. Malformed JSON, an unrecognized
  `schema_version`, a payload exceeding `mqtt.max_payload_bytes`, or an
  out-of-range value is logged and discarded rather than applied.
- Stale commands (see `docs/mqtt-api.md` "Why `command` is not retained")
  are rejected based on their `issued_at`/`timestamp` field, mitigating
  replay of an old retained message after a long outage.

## What is out of scope for this prototype

- Per-device X.509 client certificates (documented as a future
  improvement in `README.md`; username/password auth is used here for
  simplicity).
- A public-facing web dashboard or cloud relay (none is implemented;
  everything runs on the local network).

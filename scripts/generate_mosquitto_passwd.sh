#!/usr/bin/env bash
# Generates mosquitto/config/mosquitto.passwd (git-ignored) from the
# credentials in .env, using the mosquitto_passwd tool bundled in the
# eclipse-mosquitto Docker image so no local Mosquitto install is needed.
#
# Usage: ./scripts/generate_mosquitto_passwd.sh
# Requires: .env (copy from .env.example first), Docker.

set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "error: .env not found - copy .env.example to .env and fill in credentials first" >&2
  exit 1
fi

set -a
source .env
set +a

: "${MQTT_DEVICE_USERNAME:?MQTT_DEVICE_USERNAME not set in .env}"
: "${MQTT_DEVICE_PASSWORD:?MQTT_DEVICE_PASSWORD not set in .env}"
: "${MQTT_AUTOMATION_USERNAME:?MQTT_AUTOMATION_USERNAME not set in .env}"
: "${MQTT_AUTOMATION_PASSWORD:?MQTT_AUTOMATION_PASSWORD not set in .env}"

mkdir -p mosquitto/config
rm -f mosquitto/config/mosquitto.passwd

docker run --rm -v "$(pwd)/mosquitto/config:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -b -c /mosquitto/config/mosquitto.passwd "$MQTT_DEVICE_USERNAME" "$MQTT_DEVICE_PASSWORD"

docker run --rm -v "$(pwd)/mosquitto/config:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -b /mosquitto/config/mosquitto.passwd "$MQTT_AUTOMATION_USERNAME" "$MQTT_AUTOMATION_PASSWORD"

echo "Wrote mosquitto/config/mosquitto.passwd for users: $MQTT_DEVICE_USERNAME, $MQTT_AUTOMATION_USERNAME"

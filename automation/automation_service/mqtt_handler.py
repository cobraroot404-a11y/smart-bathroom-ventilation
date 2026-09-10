"""MQTT transport for the automation service (paho-mqtt wrapper).

Subscribes to telemetry, validates it, runs it through the per-device
HysteresisRule, and publishes fan/desired. See docs/mqtt-api.md for topic
names/QoS/retention and docs/security.md for the auth/TLS model.
"""

from __future__ import annotations

import json
import logging
import time

import paho.mqtt.client as mqtt

from .config import AppConfig
from .schemas import build_fan_desired_payload, validate_telemetry
from .state import StateStore

logger = logging.getLogger("automation_service")

TOPIC_TELEMETRY = "bathroom/ventilation/telemetry"
TOPIC_FAN_DESIRED = "bathroom/ventilation/fan/desired"


class MqttHandler:
    def __init__(self, config: AppConfig, state: StateStore,
                 clock=time.time):
        self.config = config
        self.state = state
        self.clock = clock
        self._client = mqtt.Client(
            client_id=f"automation-{config.mqtt.device_id}",
            clean_session=True,
        )
        if config.mqtt.username:
            self._client.username_pw_set(config.mqtt.username, config.mqtt.password)
        if config.mqtt.use_tls:
            self._client.tls_set()

        self._client.reconnect_delay_set(
            min_delay=config.mqtt.reconnect_backoff_initial_seconds,
            max_delay=config.mqtt.reconnect_backoff_max_seconds,
        )

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

    # --- lifecycle -----------------------------------------------------

    def connect(self) -> None:
        self._client.connect(
            self.config.mqtt.host,
            self.config.mqtt.port,
            keepalive=self.config.mqtt.keepalive_seconds,
        )

    def loop_forever(self) -> None:
        self._client.loop_forever()

    def loop_start(self) -> None:
        self._client.loop_start()

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    # --- callbacks -------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("connected to MQTT broker, subscribing to telemetry")
            client.subscribe(TOPIC_TELEMETRY, qos=self.config.mqtt.qos_telemetry)
        else:
            logger.warning("MQTT connect failed with rc=%s", rc)

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            logger.warning("unexpected MQTT disconnect (rc=%s); paho will "
                            "retry with the configured backoff", rc)

    def _on_message(self, client, userdata, msg):
        if len(msg.payload) > self.config.mqtt.max_payload_bytes:
            logger.warning("discarding oversized payload on %s (%d bytes)",
                            msg.topic, len(msg.payload))
            return

        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("discarding malformed JSON payload on %s", msg.topic)
            return

        if msg.topic == TOPIC_TELEMETRY:
            self._handle_telemetry(payload)

    def _handle_telemetry(self, payload: dict) -> None:
        ok, error = validate_telemetry(payload)
        if not ok:
            logger.warning("discarding invalid telemetry payload: %s", error)
            return

        device_id = payload["device_id"]
        device = self.state.get_or_create(device_id)

        seq = payload.get("seq")
        if device.is_duplicate(seq):
            logger.debug("duplicate telemetry seq=%s for %s, ignoring", seq, device_id)
            return
        device.last_seq = seq

        now = self.clock()
        was_stale = device.is_stale(now, self.config.rule.stale_telemetry_timeout_seconds)
        if was_stale and device.last_telemetry_time is not None:
            logger.info("device=%s telemetry resumed after a %.0fs gap",
                        device_id, now - device.last_telemetry_time)
        device.last_telemetry_time = now

        device.rule.on_reading(
            humidity_percent=payload["humidity_percent"],
            temperature_celsius=payload["temperature_celsius"],
            sensor_valid=payload["sensor_valid"],
            now=now,
        )
        decision = device.rule.evaluate(now)

        logger.info(
            "device=%s humidity=%.1f valid=%s -> desired_on=%s reason=%s changed=%s",
            device_id, payload["humidity_percent"], payload["sensor_valid"],
            decision.desired_on, decision.reason, decision.changed,
        )

        self._publish_fan_desired(decision.desired_on, decision.reason)

    def _publish_fan_desired(self, desired_on: bool, reason: str) -> None:
        payload = build_fan_desired_payload(desired_on, reason)
        self._client.publish(
            TOPIC_FAN_DESIRED,
            json.dumps(payload),
            qos=self.config.mqtt.qos_state,
            retain=True,
        )

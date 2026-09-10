"""Software-only ESP32 simulator (requirement 14: "simulation mode").

Two ways to use this module:

- `run_headless()`: feeds a list of HumiditySample into a DeviceController
  with no MQTT/network involved at all - fully deterministic, used by
  simulator/tests/test_device_simulator.py.
- `SimulatedDevice`: a real MQTT client (paho-mqtt) that behaves like the
  ESP32 firmware described in docs/mqtt-api.md - publishes telemetry,
  subscribes to fan/desired, and runs the same DeviceController - used by
  run_e2e_demo.py against a real Mosquitto broker and the real automation
  service, so the "end-to-end" demonstration exercises the real MQTT
  transport and the real automation_service code, not a mock of either.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

import paho.mqtt.client as mqtt

from .device_controller import DeviceController, DeviceDecision
from .humidity_profiles import HumiditySample

logger = logging.getLogger("simulator")

TOPIC_TELEMETRY = "bathroom/ventilation/telemetry"
TOPIC_FAN_DESIRED = "bathroom/ventilation/fan/desired"
TOPIC_FAN_ACTUAL = "bathroom/ventilation/fan/actual"
TOPIC_MODE = "bathroom/ventilation/mode"
TOPIC_DEVICE_STATUS = "bathroom/ventilation/device/status"
TOPIC_SENSOR_STATUS = "bathroom/ventilation/sensor/status"

SCHEMA_VERSION = 1


@dataclass
class TransitionRecord:
    time_seconds: float
    humidity_percent: float
    relay_on: bool
    mode: str
    reason: str


def run_headless(samples: List[HumiditySample], controller: DeviceController) -> List[TransitionRecord]:
    """Deterministic, no-MQTT simulation used for unit testing."""
    records: List[TransitionRecord] = []
    for s in samples:
        controller.on_sensor_reading(s.humidity_percent, s.valid)
        decision = controller.tick(s.time_seconds)
        if decision.changed:
            records.append(TransitionRecord(
                s.time_seconds, s.humidity_percent, decision.relay_on,
                decision.mode, decision.reason,
            ))
    return records


class SimulatedDevice:
    def __init__(self, *, device_id: str, mqtt_host: str, mqtt_port: int,
                 mqtt_username: Optional[str], mqtt_password: Optional[str],
                 controller: DeviceController,
                 on_transition: Optional[Callable[[TransitionRecord], None]] = None,
                 clock: Callable[[], float] = time.time):
        self.device_id = device_id
        self.controller = controller
        self.clock = clock
        self.on_transition = on_transition
        self.seq = 0
        self._last_fallback_active = True
        self._connected = False

        self._client = mqtt.Client(client_id=f"sim-{device_id}", clean_session=True)
        if mqtt_username:
            self._client.username_pw_set(mqtt_username, mqtt_password)

        will_payload = json.dumps({
            "schema_version": SCHEMA_VERSION, "device_id": device_id,
            "status": "offline", "timestamp": _now_iso(),
        })
        self._client.will_set(TOPIC_DEVICE_STATUS, will_payload, qos=1, retain=True)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

        self._mqtt_host = mqtt_host
        self._mqtt_port = mqtt_port

    def connect(self) -> None:
        self._client.connect(self._mqtt_host, self._mqtt_port, keepalive=30)
        self._client.loop_start()
        for _ in range(50):
            if self._connected:
                return
            time.sleep(0.1)
        raise RuntimeError("simulated device could not connect to MQTT broker")

    def disconnect(self, clean: bool = True) -> None:
        """Simulate a communication interruption (requirement 14) by
        dropping the MQTT connection. `clean=False` skips a graceful
        DISCONNECT so the broker's Last Will fires, matching a real
        power/Wi-Fi loss rather than an orderly shutdown."""
        if clean:
            self._client.disconnect()
        else:
            # Simulate an abrupt Wi-Fi/power loss (no clean MQTT
            # DISCONNECT) by closing the underlying socket directly, so
            # the broker only notices via keepalive timeout / the LWT.
            sock = self._client.socket()
            if sock is not None:
                sock.close()
        self._connected = False

    def reconnect(self) -> None:
        self._client.reconnect()
        for _ in range(50):
            if self._connected:
                return
            time.sleep(0.1)
        raise RuntimeError("simulated device could not reconnect to MQTT broker")

    def stop(self) -> None:
        self._client.loop_stop()
        try:
            self._client.disconnect()
        except Exception:
            pass

    def _on_connect(self, client, userdata, flags, rc):
        self._connected = (rc == 0)
        if rc == 0:
            client.subscribe(TOPIC_FAN_DESIRED, qos=1)
            self._publish_status("online")

    def _on_message(self, client, userdata, msg):
        if msg.topic != TOPIC_FAN_DESIRED:
            return
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if payload.get("schema_version") != SCHEMA_VERSION:
            return
        if "desired_relay_on" not in payload:
            return
        age = 0.0
        issued_at = payload.get("issued_at")
        if issued_at:
            from datetime import datetime, timezone
            try:
                dt = datetime.fromisoformat(issued_at.replace("Z", "+00:00"))
                age = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
            except ValueError:
                age = 0.0
        self.controller.on_mqtt_desired(payload["desired_relay_on"], age, self.clock())

    def _publish_status(self, status: str) -> None:
        self._client.publish(TOPIC_DEVICE_STATUS, json.dumps({
            "schema_version": SCHEMA_VERSION, "device_id": self.device_id,
            "status": status, "timestamp": _now_iso(),
        }), qos=1, retain=True)

    def tick_once(self) -> DeviceDecision:
        """Re-evaluate the controller against whatever sensor/MQTT state
        it already has, without a new sensor reading or telemetry
        publish. Real firmware re-evaluates every sensor_sample_interval
        regardless of whether a fresh MQTT command just arrived (see
        firmware/src/main.cpp's loop()); callers driving this simulator
        on a compressed/scripted timeline (e.g. run_e2e_demo.py) should
        call this while polling for an expected state change, not just
        read `controller.relay_on` directly, since that attribute is
        otherwise only updated inside tick()."""
        decision = self.controller.tick(self.clock())
        self._publish_state_updates(decision)
        if decision.changed and self.on_transition:
            humidity = self.controller.last_valid_humidity or 0.0
            self.on_transition(TransitionRecord(
                self.clock(), humidity, decision.relay_on, decision.mode, decision.reason,
            ))
        return decision

    def _publish_state_updates(self, decision: DeviceDecision) -> None:
        if not self._connected:
            return

        if decision.fallback_active != self._last_fallback_active:
            self._last_fallback_active = decision.fallback_active
            self._client.publish(TOPIC_MODE, json.dumps({
                "schema_version": SCHEMA_VERSION,
                "operating_mode": decision.mode,
                "fallback_active": decision.fallback_active,
                "override_active": False,
                "override_expires_at": None,
                "timestamp": _now_iso(),
            }), qos=1, retain=True)

        if decision.changed:
            self._client.publish(TOPIC_FAN_ACTUAL, json.dumps({
                "schema_version": SCHEMA_VERSION,
                "actual_relay_on": decision.relay_on,
                "reason": decision.reason,
                "timestamp": _now_iso(),
            }), qos=1, retain=True)

    def publish_reading(self, sample: HumiditySample) -> DeviceDecision:
        self.controller.on_sensor_reading(sample.humidity_percent, sample.valid)
        now = self.clock()
        decision = self.controller.tick(now)

        self.seq += 1
        telemetry = {
            "schema_version": SCHEMA_VERSION,
            "device_id": self.device_id,
            "seq": self.seq,
            "humidity_percent": sample.humidity_percent,
            "temperature_celsius": sample.temperature_celsius,
            "sensor_valid": sample.valid,
            "sensor_status": "ok" if sample.valid else "degraded",
            "requested_relay_on": decision.relay_on,
            "actual_relay_on": decision.relay_on,
            "operating_mode": decision.mode,
            "control_source": "mqtt" if decision.mode == "automatic" else "local",
            "fallback_active": decision.fallback_active,
            "override_active": False,
            "uptime_seconds": now,
            "timestamp": _now_iso(),
        }
        if self._connected:
            self._client.publish(TOPIC_TELEMETRY, json.dumps(telemetry), qos=1, retain=False)
            self._publish_state_updates(decision)

        if decision.changed and self.on_transition:
            self.on_transition(TransitionRecord(
                now, sample.humidity_percent, decision.relay_on,
                decision.mode, decision.reason,
            ))

        return decision


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

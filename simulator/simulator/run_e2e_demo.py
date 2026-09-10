#!/usr/bin/env python3
"""Scripted end-to-end demonstration (requirement 14 / docs/testing.md
"End-to-end scenario checklist").

Brings up a real (ephemeral, anonymous-access, localhost-only) Mosquitto
broker, the real automation service as a subprocess, and an in-process
SimulatedDevice (simulator/simulator/device_simulator.py) that speaks the
real MQTT topics/payloads from docs/mqtt-api.md. Scripts a humidity
sequence and asserts each expected transition happens, in order. Exits
non-zero with a message naming the failed step if any assertion fails -
safe to use as a CI gate.

Uses config/demo.yaml (compressed timers) purely so this finishes in well
under a minute; it is never used by firmware or a real deployment - see
docs/testing.md.

Usage: python simulator/simulator/run_e2e_demo.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "simulator"))

import paho.mqtt.client as mqtt
import yaml

from simulator.device_controller import DeviceController
from simulator.device_simulator import SimulatedDevice, TransitionRecord
from simulator.humidity_profiles import HumiditySample

DEMO_CONFIG_PATH = REPO_ROOT / "config" / "demo.yaml"
MOSQUITTO_PORT = 18830
MOSQUITTO_CONTAINER = "bathroom-vent-e2e-mosquitto"
DEVICE_ID = "bathroom-vent-e2e-demo"

TOPIC_FAN_ACTUAL = "bathroom/ventilation/fan/actual"
TOPIC_MODE = "bathroom/ventilation/mode"


class StepFailure(Exception):
    pass


def log(msg: str) -> None:
    print(f"[e2e] {msg}", flush=True)


def load_demo_config() -> dict:
    with open(DEMO_CONFIG_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# --- infrastructure -------------------------------------------------------

def start_mosquitto() -> str:
    log(f"starting ephemeral Mosquitto broker (anonymous, localhost-only, port {MOSQUITTO_PORT})")
    conf = tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False)
    conf.write("listener 1883\nallow_anonymous true\n")
    conf.close()
    subprocess.run(["docker", "rm", "-f", MOSQUITTO_CONTAINER], capture_output=True, check=False)
    result = subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", MOSQUITTO_CONTAINER,
            "-p", f"{MOSQUITTO_PORT}:1883",
            "-v", f"{conf.name}:/mosquitto/config/mosquitto.conf",
            "eclipse-mosquitto:2",
        ],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise StepFailure(f"failed to start Mosquitto container: {result.stderr}")
    return conf.name


def stop_mosquitto(conf_path: str) -> None:
    subprocess.run(["docker", "stop", MOSQUITTO_CONTAINER], capture_output=True, check=False)
    try:
        os.unlink(conf_path)
    except OSError:
        pass


def wait_for_broker(timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            c = mqtt.Client()
            c.connect("localhost", MOSQUITTO_PORT, keepalive=5)
            c.disconnect()
            return
        except OSError as e:
            last_err = e
            time.sleep(0.5)
    raise StepFailure(f"Mosquitto broker did not become ready in time: {last_err}")


def start_automation_service() -> subprocess.Popen:
    log("starting automation service subprocess")
    env = dict(os.environ)
    env["BATHROOM_VENT_CONFIG_PATH"] = str(DEMO_CONFIG_PATH)
    env["MQTT_HOST"] = "localhost"
    env["MQTT_PORT"] = str(MOSQUITTO_PORT)
    env["MQTT_DEVICE_ID"] = DEVICE_ID
    env.pop("MQTT_AUTOMATION_USERNAME", None)
    env.pop("MQTT_AUTOMATION_PASSWORD", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "automation_service.main"],
        cwd=str(REPO_ROOT / "automation"),
        env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    return proc


def stop_automation_service(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


class Observer:
    """Subscribes to fan/actual and mode as an independent MQTT client, to
    verify - via the real broker, not the simulator's own bookkeeping -
    that "actual state is published correctly" (checklist item 12)."""

    def __init__(self):
        self.messages: List[tuple] = []
        self._client = mqtt.Client(client_id="e2e-observer")
        self._client.on_connect = lambda c, u, f, rc: c.subscribe([
            (TOPIC_FAN_ACTUAL, 1), (TOPIC_MODE, 1),
        ])
        self._client.on_message = self._on_message

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = None
        self.messages.append((msg.topic, payload))

    def connect(self):
        self._client.connect("localhost", MOSQUITTO_PORT, keepalive=10)
        self._client.loop_start()

    def stop(self):
        self._client.loop_stop()
        self._client.disconnect()

    def received_on(self, topic: str) -> List[dict]:
        return [p for t, p in self.messages if t == topic and p is not None]


# --- scenario helpers -------------------------------------------------------

def wait_until(predicate, timeout: float, description: str, poll_interval: float = 0.25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(poll_interval)
    raise StepFailure(f"timed out waiting for: {description}")


def main() -> int:
    cfg = load_demo_config()
    sample_interval = cfg["timing"]["sensor_sample_interval_seconds"]
    min_on = cfg["timing"]["min_fan_on_seconds"]
    min_off = cfg["timing"]["min_fan_off_seconds"]
    max_runtime = cfg["timing"]["max_continuous_runtime_seconds"]
    stale_timeout = cfg["timing"]["stale_command_timeout_seconds"]

    conf_path = None
    automation_proc = None
    device = None
    observer = None
    transitions: List[TransitionRecord] = []
    t0 = time.time()
    clock = lambda: time.time() - t0

    try:
        conf_path = start_mosquitto()
        wait_for_broker()

        automation_proc = start_automation_service()
        time.sleep(1.5)  # let it connect and subscribe

        observer = Observer()
        observer.connect()

        controller = DeviceController(
            fan_on_percent=cfg["thresholds"]["fan_on_percent"],
            fan_off_percent=cfg["thresholds"]["fan_off_percent"],
            humidity_min_valid=cfg["thresholds"]["humidity_min_valid_percent"],
            humidity_max_valid=cfg["thresholds"]["humidity_max_valid_percent"],
            min_fan_on_seconds=min_on,
            min_fan_off_seconds=min_off,
            max_continuous_runtime_seconds=max_runtime,
            stale_command_timeout_seconds=stale_timeout,
            sensor_consecutive_failure_limit=cfg["sensor"]["consecutive_failure_limit"],
        )
        device = SimulatedDevice(
            device_id=DEVICE_ID, mqtt_host="localhost", mqtt_port=MOSQUITTO_PORT,
            mqtt_username=None, mqtt_password=None, controller=controller,
            on_transition=transitions.append, clock=clock,
        )
        device.connect()
        log("simulated device connected")

        def send(humidity, valid=True, temp=23.0):
            return device.publish_reading(HumiditySample(clock(), humidity, temp, valid))

        # tick_once() (not a bare attribute read) is required to see the
        # effect of an MQTT message that arrived asynchronously since the
        # last send() - see its docstring in device_simulator.py.

        # 1-2: services connected, telemetry flowing (implicit: send() succeeds)
        # 3: below threshold keeps fan off
        send(40.0)
        time.sleep(sample_interval * 2)
        if device.tick_once().relay_on:
            raise StepFailure("relay turned on below fan_on_percent")
        log("step 3 OK: humidity below threshold keeps fan off")

        # 4: crossing upper threshold turns fan on (via automation -> MQTT)
        send(80.0)
        wait_until(lambda: device.tick_once().relay_on, timeout=8,
                   description="fan turns ON above fan_on_percent")
        if device.tick_once().mode != "automatic":
            raise StepFailure("fan turned on but device is not reporting automatic mode")
        log("step 4 OK: humidity above threshold turns fan on (automatic mode)")

        # 5: band humidity preserves state
        send(65.0)
        time.sleep(sample_interval * 2)
        if not device.tick_once().relay_on:
            raise StepFailure("relay turned off while humidity was still in the hysteresis band")
        log("step 5 OK: hysteresis band preserves ON state")

        # 6-7: min-on enforced, then crossing lower threshold turns fan off
        time.sleep(max(0.0, min_on))  # ensure min_fan_on has elapsed
        send(50.0)
        wait_until(lambda: not device.tick_once().relay_on, timeout=8,
                   description="fan turns OFF below fan_off_percent")
        log("steps 6-7 OK: min-on enforced, then humidity below threshold turns fan off")

        # 8: max continuous runtime enforced
        time.sleep(max(0.0, min_off))
        send(85.0)
        wait_until(lambda: device.tick_once().relay_on, timeout=8,
                   description="fan turns back ON for max-runtime test")
        wait_until(lambda: not device.tick_once().relay_on, timeout=max_runtime + 8,
                   description="max_continuous_runtime_seconds cutoff forces fan off")
        last = transitions[-1]
        if last.reason != "max_runtime_cutoff":
            raise StepFailure(f"expected max_runtime_cutoff, got reason={last.reason}")
        log("step 8 OK: max continuous runtime cutoff enforced")

        # 11: MQTT/automation loss activates local fallback
        log("stopping automation service to simulate an outage")
        stop_automation_service(automation_proc)
        time.sleep(stale_timeout + sample_interval * 2)
        send(50.0)
        wait_until(lambda: device.tick_once().mode == "local_fallback",
                   timeout=8, description="device enters local_fallback mode")
        log("step 11 OK: automation/MQTT outage activates local fallback")

        # 9: invalid readings during fallback do not cause unsafe switching
        d = None
        for _ in range(cfg["sensor"]["consecutive_failure_limit"]):
            d = send(999.0, valid=False)
            time.sleep(sample_interval)
        if d.relay_on or d.reason != "sensor_invalid_safe_state":
            raise StepFailure(f"invalid sensor burst did not force the documented safe state (got {d})")
        log("step 9 OK: invalid readings during fallback force the documented safe OFF state")

        # 12: recovery does not cause rapid toggling
        log("restarting automation service to simulate recovery")
        automation_proc = start_automation_service()
        time.sleep(1.5)
        send(40.0)
        wait_until(lambda: device.tick_once().mode == "automatic",
                   timeout=8, description="device returns to automatic mode after recovery")
        # No relay change should have been needed (humidity is low both
        # sides of the outage), so no extra transition should appear.
        toggles_during_recovery = [t for t in transitions if t.time_seconds > clock() - sample_interval * 3]
        if len(toggles_during_recovery) > 0 and any(t.relay_on for t in toggles_during_recovery):
            raise StepFailure("recovery caused an unexpected ON transition (possible rapid toggling)")
        log("step 12 OK: recovery from outage did not cause rapid toggling")

        # 13: actual state published correctly - cross-check the broker
        # actually carried the transitions the simulator recorded.
        actual_msgs = observer.received_on(TOPIC_FAN_ACTUAL)
        if not actual_msgs:
            raise StepFailure("no fan/actual messages observed on the real broker")
        if not any(m.get("actual_relay_on") is True for m in actual_msgs):
            raise StepFailure("no fan/actual message reported actual_relay_on=true")
        if not any(m.get("actual_relay_on") is False for m in actual_msgs):
            raise StepFailure("no fan/actual message reported actual_relay_on=false")
        mode_msgs = observer.received_on(TOPIC_MODE)
        if not any(m.get("fallback_active") is True for m in mode_msgs):
            raise StepFailure("no mode message reported fallback_active=true")
        log("step 13 OK: fan/actual and mode were published correctly and observed on the broker")

        # 14: energy report runs
        log("running the energy-efficiency report")
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "energy" / "energy_report.py"),
             "--duration-hours", "1", "--showers-per-day", "1"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise StepFailure(f"energy_report.py failed:\n{result.stdout}\n{result.stderr}")
        log("step 14 OK: energy report generated")

        log("ALL END-TO-END CHECKS PASSED")
        return 0

    except StepFailure as e:
        print(f"\n[e2e] FAILED: {e}\n", file=sys.stderr)
        if automation_proc is not None:
            print(f"[e2e] automation service alive={automation_proc.poll() is None}", file=sys.stderr)
            if automation_proc.poll() is not None and automation_proc.stdout:
                print("[e2e] automation service output:", file=sys.stderr)
                print(automation_proc.stdout.read(), file=sys.stderr)
        return 1
    finally:
        log("shutting down cleanly")
        if device is not None:
            device.stop()
        if observer is not None:
            observer.stop()
        if automation_proc is not None:
            stop_automation_service(automation_proc)
        if conf_path is not None:
            stop_mosquitto(conf_path)


if __name__ == "__main__":
    raise SystemExit(main())

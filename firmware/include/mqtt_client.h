#pragma once

// VentMqttClient: MQTT transport for the ESP32, wrapping PubSubClient.
//
// Owns: connecting with unique client ID + LWT, bounded exponential
// backoff reconnection, publishing every topic in docs/mqtt-api.md, and
// dispatching validated inbound `fan/desired` / `command` payloads to
// the controller via callbacks. Payload validation (schema_version,
// size, required fields, value ranges) happens here, before anything
// reaches VentilationController - see docs/security.md "Command
// validation".

#include <Arduino.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <WiFi.h>

#include <cstring>
#include <functional>

#include "config.h"
#include "controller.h"
#include "time_utils.h"

namespace vent {

inline uint32_t MinU32(uint32_t a, uint32_t b) { return a < b ? a : b; }

using FanDesiredCallback =
    std::function<void(bool desired_on, uint32_t issued_at_age_ms)>;
using CommandCallback = std::function<void(
    OverrideType type, uint32_t duration_ms, uint32_t issued_at_age_ms)>;

class VentMqttClient {
 public:
  VentMqttClient(WiFiClient& net_client, const char* device_id)
      : client_(net_client), device_id_(device_id) {
    topic_telemetry_ = String("bathroom/ventilation/telemetry");
    topic_sensor_humidity_ = String("bathroom/ventilation/sensor/humidity");
    topic_sensor_temperature_ =
        String("bathroom/ventilation/sensor/temperature");
    topic_command_ = String("bathroom/ventilation/command");
    topic_fan_desired_ = String("bathroom/ventilation/fan/desired");
    topic_fan_actual_ = String("bathroom/ventilation/fan/actual");
    topic_mode_ = String("bathroom/ventilation/mode");
    topic_device_status_ = String("bathroom/ventilation/device/status");
    topic_sensor_status_ = String("bathroom/ventilation/sensor/status");
    topic_config_ = String("bathroom/ventilation/config");
  }

  void Init(const char* host, uint16_t port) {
    client_.setServer(host, port);
    client_.setBufferSize(config::kMqttMaxPayloadBytes);
    client_.setCallback([this](char* topic, uint8_t* payload,
                                unsigned int length) {
      HandleMessage(topic, payload, length);
    });
  }

  void SetFanDesiredCallback(FanDesiredCallback cb) { on_fan_desired_ = cb; }
  void SetCommandCallback(CommandCallback cb) { on_command_ = cb; }

  // Non-blocking; retries with bounded exponential backoff rather than a
  // tight reconnect loop. Returns true if currently connected.
  bool EnsureConnected(const char* username, const char* password) {
    if (client_.connected()) {
      backoff_ms_ = config::kMqttReconnectBackoffInitialSeconds * 1000UL;
      return true;
    }
    uint32_t now = millis();
    if (now - last_attempt_ms_ < backoff_ms_) return false;
    last_attempt_ms_ = now;

    String client_id = String("esp32-") + device_id_;
    String will_topic = topic_device_status_;
    String will_payload = BuildStatusPayload("offline");

    bool ok = client_.connect(client_id.c_str(), username, password,
                               will_topic.c_str(), config::kMqttQosState,
                               true, will_payload.c_str());
    if (ok) {
      backoff_ms_ = config::kMqttReconnectBackoffInitialSeconds * 1000UL;
      client_.subscribe(topic_fan_desired_.c_str(), config::kMqttQosState);
      client_.subscribe(topic_command_.c_str(), config::kMqttQosCommand);
      PublishRetained(topic_device_status_, BuildStatusPayload("online"),
                       config::kMqttQosState);
    } else {
      backoff_ms_ = MinU32(
          backoff_ms_ * 2, config::kMqttReconnectBackoffMaxSeconds * 1000UL);
    }
    return ok;
  }

  void Loop() { client_.loop(); }
  bool Connected() { return client_.connected(); }

  void PublishTelemetry(float humidity, float temperature, bool sensor_valid,
                         const char* sensor_status, bool requested_relay_on,
                         bool actual_relay_on, const char* operating_mode,
                         const char* control_source, bool fallback_active,
                         bool override_active, uint32_t uptime_seconds) {
    JsonDocument doc;
    doc["schema_version"] = config::kSchemaVersion;
    doc["device_id"] = device_id_;
    doc["seq"] = seq_++;
    doc["humidity_percent"] = humidity;
    doc["temperature_celsius"] = temperature;
    doc["sensor_valid"] = sensor_valid;
    doc["sensor_status"] = sensor_status;
    doc["requested_relay_on"] = requested_relay_on;
    doc["actual_relay_on"] = actual_relay_on;
    doc["operating_mode"] = operating_mode;
    doc["control_source"] = control_source;
    doc["fallback_active"] = fallback_active;
    doc["override_active"] = override_active;
    doc["uptime_seconds"] = uptime_seconds;
    doc["timestamp"] = NowIso8601();
    Publish(topic_telemetry_, doc, config::kMqttQosTelemetry, false);

    JsonDocument hdoc;
    hdoc["schema_version"] = config::kSchemaVersion;
    hdoc["value"] = humidity;
    hdoc["valid"] = sensor_valid;
    hdoc["timestamp"] = NowIso8601();
    Publish(topic_sensor_humidity_, hdoc, 0, true);

    JsonDocument tdoc;
    tdoc["schema_version"] = config::kSchemaVersion;
    tdoc["value"] = temperature;
    tdoc["valid"] = sensor_valid;
    tdoc["timestamp"] = NowIso8601();
    Publish(topic_sensor_temperature_, tdoc, 0, true);
  }

  void PublishFanActual(bool actual_relay_on, Reason reason) {
    JsonDocument doc;
    doc["schema_version"] = config::kSchemaVersion;
    doc["actual_relay_on"] = actual_relay_on;
    doc["reason"] = ReasonToString(reason);
    doc["timestamp"] = NowIso8601();
    Publish(topic_fan_actual_, doc, config::kMqttQosState, true);
  }

  void PublishLocalFanDesired(bool desired_on, Reason reason) {
    JsonDocument doc;
    doc["schema_version"] = config::kSchemaVersion;
    doc["desired_relay_on"] = desired_on;
    doc["reason"] = ReasonToString(reason);
    doc["source"] = "local_fallback";
    doc["issued_at"] = NowIso8601();
    Publish(topic_fan_desired_, doc, config::kMqttQosState, true);
  }

  void PublishMode(const char* operating_mode, bool fallback_active,
                    bool override_active, uint32_t override_expires_epoch) {
    JsonDocument doc;
    doc["schema_version"] = config::kSchemaVersion;
    doc["operating_mode"] = operating_mode;
    doc["fallback_active"] = fallback_active;
    doc["override_active"] = override_active;
    if (override_active) {
      char buf[32];
      time_utils::FormatIso8601(override_expires_epoch, buf, sizeof(buf));
      doc["override_expires_at"] = buf;
    } else {
      doc["override_expires_at"] = nullptr;
    }
    doc["timestamp"] = NowIso8601();
    Publish(topic_mode_, doc, config::kMqttQosState, true);
  }

  void PublishSensorStatus(bool sensor_valid, uint8_t consecutive_failures,
                            uint32_t last_valid_reading_age_seconds,
                            const char* status) {
    JsonDocument doc;
    doc["schema_version"] = config::kSchemaVersion;
    doc["sensor_valid"] = sensor_valid;
    doc["consecutive_failures"] = consecutive_failures;
    doc["last_valid_reading_age_seconds"] = last_valid_reading_age_seconds;
    doc["status"] = status;
    doc["timestamp"] = NowIso8601();
    Publish(topic_sensor_status_, doc, config::kMqttQosState, true);
  }

  void PublishConfigSnapshot(const ControllerConfig& cfg) {
    JsonDocument doc;
    doc["schema_version"] = config::kSchemaVersion;
    doc["fan_on_percent"] = cfg.fan_on_percent;
    doc["fan_off_percent"] = cfg.fan_off_percent;
    doc["min_fan_on_seconds"] = cfg.min_fan_on_ms / 1000;
    doc["min_fan_off_seconds"] = cfg.min_fan_off_ms / 1000;
    doc["max_continuous_runtime_seconds"] = cfg.max_continuous_runtime_ms / 1000;
    doc["stale_telemetry_timeout_seconds"] = config::kStaleTelemetryTimeoutSeconds;
    doc["rise_rate_detection_enabled"] = cfg.rise_rate_detection_enabled;
    doc["timestamp"] = NowIso8601();
    Publish(topic_config_, doc, config::kMqttQosState, true);
  }

 private:
  String NowIso8601() {
    char buf[32];
    time_utils::FormatIso8601(time(nullptr), buf, sizeof(buf));
    return String(buf);
  }

  String BuildStatusPayload(const char* status) {
    JsonDocument doc;
    doc["schema_version"] = config::kSchemaVersion;
    doc["device_id"] = device_id_;
    doc["status"] = status;
    doc["timestamp"] = NowIso8601();
    String out;
    serializeJson(doc, out);
    return out;
  }

  void Publish(const String& topic, JsonDocument& doc, uint8_t /*qos*/,
               bool retained) {
    // PubSubClient does not natively support QoS>0 publish acks in this
    // simple wrapper; QoS 1 subscription is still honored on the broker
    // side for inbound messages. Documented limitation - see
    // docs/mqtt-api.md.
    String out;
    if (measureJson(doc) > config::kMqttMaxPayloadBytes) {
      return;  // never publish an oversized payload
    }
    serializeJson(doc, out);
    client_.publish(topic.c_str(), out.c_str(), retained);
  }

  void PublishRetained(const String& topic, const String& payload,
                        uint8_t /*qos*/) {
    client_.publish(topic.c_str(), payload.c_str(), true);
  }

  void HandleMessage(char* topic, uint8_t* payload, unsigned int length) {
    if (length > config::kMqttMaxPayloadBytes) return;

    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, payload, length);
    if (err) return;

    int schema_version = doc["schema_version"] | -1;
    if (schema_version != config::kSchemaVersion) return;

    uint32_t age_ms = 0;
    const char* issued_field = nullptr;
    if (doc["issued_at"].is<const char*>()) {
      issued_field = doc["issued_at"];
    } else if (doc["timestamp"].is<const char*>()) {
      issued_field = doc["timestamp"];
    }
    if (issued_field != nullptr && TimeIsSynced()) {
      int64_t issued_epoch;
      if (time_utils::ParseIso8601(issued_field, &issued_epoch)) {
        int64_t now_epoch = time(nullptr);
        int64_t age_s = now_epoch - issued_epoch;
        if (age_s > 0) age_ms = static_cast<uint32_t>(age_s) * 1000UL;
      }
    }

    String t(topic);
    if (t == topic_fan_desired_ && on_fan_desired_) {
      if (!doc["desired_relay_on"].is<bool>()) return;
      on_fan_desired_(doc["desired_relay_on"].as<bool>(), age_ms);
    } else if (t == topic_command_ && on_command_) {
      const char* cmd = doc["command"] | "";
      OverrideType type = OverrideType::kNone;
      if (strcmp(cmd, "override_on") == 0) {
        type = OverrideType::kOn;
      } else if (strcmp(cmd, "override_off") == 0) {
        type = OverrideType::kOff;
      } else if (strcmp(cmd, "override_auto") == 0) {
        type = OverrideType::kAuto;
      } else {
        return;  // unrecognized command, discard
      }
      uint32_t duration_ms =
          (doc["duration_seconds"] | 0) * 1000UL;
      on_command_(type, duration_ms, age_ms);
    }
  }

  bool TimeIsSynced() { return time(nullptr) > 1609459200; }

  PubSubClient client_;
  const char* device_id_;
  uint32_t backoff_ms_ = config::kMqttReconnectBackoffInitialSeconds * 1000UL;
  uint32_t last_attempt_ms_ = 0;
  uint32_t seq_ = 0;

  FanDesiredCallback on_fan_desired_;
  CommandCallback on_command_;

  String topic_telemetry_;
  String topic_sensor_humidity_;
  String topic_sensor_temperature_;
  String topic_command_;
  String topic_fan_desired_;
  String topic_fan_actual_;
  String topic_mode_;
  String topic_device_status_;
  String topic_sensor_status_;
  String topic_config_;
};

}  // namespace vent

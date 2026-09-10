// Automated Energy-Efficient Bathroom Ventilation System - ESP32 firmware
// entry point. Wires the hardware-independent VentilationController (see
// controller.h/.cpp) to the real sensor, relay, Wi-Fi, and MQTT drivers.
//
// Not unit-tested directly (requires ESP32 hardware) - see
// docs/testing.md. The logic it depends on (VentilationController) is
// unit-tested in firmware/test/test_controller/.

#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>

#include "config.h"
#include "controller.h"
#include "diagnostics.h"
#include "mqtt_client.h"
#include "relay.h"
#include "secrets.h"
#include "sensor.h"
#include "wifi_manager.h"

using namespace vent;

namespace {

RelayDriver g_relay(config::kRelayGpioPin, config::kRelayActiveLow);
Sht3xSensor g_sensor;
WiFiClient g_net_client;
WifiManager g_wifi(WIFI_SSID, WIFI_PASSWORD,
                    config::kMqttReconnectBackoffInitialSeconds * 1000UL,
                    config::kMqttReconnectBackoffMaxSeconds * 1000UL);
VentMqttClient g_mqtt(g_net_client, config::kDeviceId);

ControllerConfig BuildControllerConfig() {
  ControllerConfig cfg;
  cfg.fan_on_percent = config::kFanOnPercent;
  cfg.fan_off_percent = config::kFanOffPercent;
  cfg.humidity_min_valid_percent = config::kHumidityMinValidPercent;
  cfg.humidity_max_valid_percent = config::kHumidityMaxValidPercent;
  cfg.temperature_min_valid_celsius = config::kTemperatureMinValidCelsius;
  cfg.temperature_max_valid_celsius = config::kTemperatureMaxValidCelsius;
  cfg.min_fan_on_ms = config::kMinFanOnSeconds * 1000UL;
  cfg.min_fan_off_ms = config::kMinFanOffSeconds * 1000UL;
  cfg.max_continuous_runtime_ms = config::kMaxContinuousRuntimeSeconds * 1000UL;
  cfg.stale_command_timeout_ms = config::kStaleCommandTimeoutSeconds * 1000UL;
  cfg.manual_override_default_duration_ms =
      config::kManualOverrideDefaultDurationSeconds * 1000UL;
  cfg.manual_override_max_duration_ms =
      config::kManualOverrideMaxDurationSeconds * 1000UL;
  cfg.sensor_consecutive_failure_limit = config::kSensorConsecutiveFailureLimit;
  cfg.sensor_invalid_hold_last_state = config::kSensorInvalidHoldLastState;
  cfg.rise_rate_detection_enabled = config::kRiseRateDetectionEnabled;
  cfg.rise_rate_threshold_percent_per_minute =
      config::kRiseRateThresholdPercentPerMinute;
  cfg.rise_rate_window_ms = config::kRiseRateWindowSeconds * 1000UL;
  cfg.rise_rate_min_valid_samples = config::kRiseRateMinValidSamples;
  return cfg;
}

VentilationController g_controller(BuildControllerConfig());

uint32_t g_last_sample_ms = 0;
uint32_t g_last_telemetry_ms = 0;
bool g_last_fallback_active = true;  // starts true - see docs/safety.md
float g_last_humidity = 0.0f;
float g_last_temperature = 0.0f;
bool g_last_sensor_valid = false;
uint32_t g_last_valid_reading_ms = 0;
ControlDecision g_last_decision;

const char* SensorStatusToString(SensorStatus status) {
  switch (status) {
    case SensorStatus::kOk: return "ok";
    case SensorStatus::kDegraded: return "degraded";
    case SensorStatus::kFailed: return "failed";
  }
  return "unknown";
}

void OnFanDesired(bool desired_on, uint32_t issued_at_age_ms) {
  g_controller.OnMqttDesired(desired_on, issued_at_age_ms, millis());
}

void OnCommand(OverrideType type, uint32_t duration_ms,
                uint32_t issued_at_age_ms) {
  bool accepted =
      g_controller.OnCommand(type, duration_ms, issued_at_age_ms, millis());
  if (!accepted) {
    diagnostics::LogWarn("rejected stale command");
  }
}

}  // namespace

void setup() {
  // Relay must be driven to its safe (OFF) level before anything else -
  // see docs/hardware.md "Startup / reset / flashing safety".
  g_relay.Init();

  diagnostics::Init();
  diagnostics::LogInfo("booting bathroom ventilation controller");

  Wire.begin(config::kI2cSdaGpio, config::kI2cSclGpio);
  if (!g_sensor.Init()) {
    diagnostics::LogError("sensor init failed - check wiring/I2C address");
  }

  if (config::kStatusLedEnabled) {
    pinMode(config::kStatusLedGpioPin, OUTPUT);
    digitalWrite(config::kStatusLedGpioPin, LOW);
  }

  g_wifi.Begin();
  g_mqtt.Init(MQTT_HOST, MQTT_PORT);
  g_mqtt.SetFanDesiredCallback(OnFanDesired);
  g_mqtt.SetCommandCallback(OnCommand);
}

void loop() {
  uint32_t now = millis();

  g_wifi.EnsureConnected();
  if (g_wifi.IsConnected()) {
    if (g_mqtt.EnsureConnected(MQTT_USERNAME, MQTT_PASSWORD)) {
      g_mqtt.Loop();
    }
  }

  if (now - g_last_sample_ms >= config::kSensorSampleIntervalSeconds * 1000UL) {
    g_last_sample_ms = now;
    SensorReading reading = g_sensor.Read();
    g_last_sensor_valid = reading.valid;
    if (reading.valid) {
      g_last_humidity = reading.humidity_percent;
      g_last_temperature = reading.temperature_celsius;
      g_last_valid_reading_ms = now;
    }
    g_controller.OnSensorReading(reading, now);

    ControlDecision decision = g_controller.Tick(now);
    g_last_decision = decision;
    g_relay.Set(decision.relay_on);

    diagnostics::LogDecision(decision, g_last_humidity, g_last_temperature,
                              g_last_sensor_valid);

    if (config::kStatusLedEnabled) {
      digitalWrite(config::kStatusLedGpioPin,
                    decision.fallback_active ? HIGH : LOW);
    }

    if (decision.fallback_active != g_last_fallback_active) {
      g_last_fallback_active = decision.fallback_active;
      if (g_mqtt.Connected()) {
        g_mqtt.PublishMode(OperatingModeToString(decision.mode),
                            decision.fallback_active, decision.override_active,
                            0);
      }
      diagnostics::LogInfo(decision.fallback_active
                                ? "entered local fallback mode"
                                : "exited local fallback mode");
    }

    if (decision.relay_state_changed && g_mqtt.Connected()) {
      g_mqtt.PublishFanActual(decision.relay_on, decision.reason);
      if (decision.source == ControlSource::kLocal) {
        g_mqtt.PublishLocalFanDesired(decision.relay_on, decision.reason);
      }
    }
  }

  if (g_mqtt.Connected() &&
      now - g_last_telemetry_ms >=
          config::kTelemetryPublishIntervalSeconds * 1000UL) {
    g_last_telemetry_ms = now;
    SensorStatus sensor_status = g_controller.GetSensorStatus();
    const ControlDecision& decision = g_last_decision;

    g_mqtt.PublishTelemetry(
        g_last_humidity, g_last_temperature, g_last_sensor_valid,
        SensorStatusToString(sensor_status), decision.relay_on,
        decision.relay_on, OperatingModeToString(decision.mode),
        decision.source == ControlSource::kMqtt ? "mqtt" : "local",
        decision.fallback_active, decision.override_active,
        now / 1000);

    g_mqtt.PublishSensorStatus(
        g_last_sensor_valid, g_controller.GetConsecutiveFailures(),
        (now - g_last_valid_reading_ms) / 1000,
        SensorStatusToString(sensor_status));
  }
}

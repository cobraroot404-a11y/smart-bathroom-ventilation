#pragma once

// Compiled-in default configuration for the ESP32 firmware.
//
// This mirrors config/defaults.yaml (the canonical, documented set of
// tunables - see docs/architecture.md "Configuration as a single source
// of truth"). Keep the two in sync when changing a default. Per-device
// overrides (Wi-Fi/MQTT credentials, and optionally threshold overrides)
// come from config/device.json at provisioning time via
// firmware/include/secrets.h (see secrets.example.h) - this file only
// holds values safe to compile into every build.

#include <stdint.h>

namespace config {

// --- Device identity ---
constexpr const char* kDeviceId = "bathroom-vent-01";
constexpr uint8_t kSchemaVersion = 1;

// --- Humidity/temperature thresholds ---
constexpr float kFanOnPercent = 70.0f;
constexpr float kFanOffPercent = 60.0f;
constexpr float kHumidityMinValidPercent = 0.0f;
constexpr float kHumidityMaxValidPercent = 100.0f;
constexpr float kTemperatureMinValidCelsius = -10.0f;
constexpr float kTemperatureMaxValidCelsius = 60.0f;

// --- Timing (all in seconds; converted to ms where used) ---
constexpr uint32_t kSensorSampleIntervalSeconds = 5;
constexpr uint32_t kTelemetryPublishIntervalSeconds = 10;
constexpr uint32_t kMinFanOnSeconds = 120;
constexpr uint32_t kMinFanOffSeconds = 30;
constexpr uint32_t kMaxContinuousRuntimeSeconds = 1800;
constexpr uint32_t kStaleTelemetryTimeoutSeconds = 60;
constexpr uint32_t kStaleCommandTimeoutSeconds = 60;
constexpr uint32_t kManualOverrideDefaultDurationSeconds = 1800;
constexpr uint32_t kManualOverrideMaxDurationSeconds = 7200;

// --- Relay ---
constexpr bool kRelayActiveLow = true;   // see docs/hardware.md
constexpr uint8_t kRelayGpioPin = 27;    // not an ESP32 boot-strapping pin
constexpr bool kRelayStartupOn = false;  // must always be false (fail-safe)
constexpr bool kSensorInvalidHoldLastState = false;  // "off" is the safe default

// --- Sensor ---
constexpr uint8_t kI2cSdaGpio = 21;
constexpr uint8_t kI2cSclGpio = 22;
constexpr uint8_t kSensorConsecutiveFailureLimit = 3;
constexpr uint8_t kSensorReadRetryAttempts = 2;

// --- Optional status indicator ---
constexpr uint8_t kStatusLedGpioPin = 4;
constexpr bool kStatusLedEnabled = true;

// --- Optional rise-rate detection (disabled by default) ---
constexpr bool kRiseRateDetectionEnabled = false;
constexpr float kRiseRateThresholdPercentPerMinute = 3.0f;
constexpr uint32_t kRiseRateWindowSeconds = 60;
constexpr uint8_t kRiseRateMinValidSamples = 4;

// --- MQTT ---
constexpr uint16_t kMqttKeepaliveSeconds = 30;
constexpr uint8_t kMqttQosTelemetry = 1;
constexpr uint8_t kMqttQosState = 1;
constexpr uint8_t kMqttQosCommand = 1;
constexpr uint32_t kMqttReconnectBackoffInitialSeconds = 1;
constexpr uint32_t kMqttReconnectBackoffMaxSeconds = 60;
constexpr size_t kMqttMaxPayloadBytes = 2048;

}  // namespace config

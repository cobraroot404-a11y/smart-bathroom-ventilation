#pragma once

// VentilationController: the hardware-independent core control logic.
//
// Deliberately has no dependency on Arduino/ESP32/WiFi/MQTT headers so it
// can be compiled and unit-tested as a plain desktop binary (PlatformIO
// `native` environment - see firmware/test/test_controller/). All time
// values are caller-supplied monotonic milliseconds (e.g. millis() on
// real hardware) so tests can drive time deterministically.
//
// See docs/architecture.md "Control flow" and docs/safety.md for the
// behavior this class implements and why.

#include <stdint.h>

namespace vent {

enum class OperatingMode {
  kAutomatic,
  kLocalFallback,
  kManualOn,
  kManualOff,
};

enum class ControlSource {
  kMqtt,
  kLocal,
};

enum class SensorStatus {
  kOk,
  kDegraded,
  kFailed,
};

enum class Reason {
  kStartupSafeState,
  kHumidityAboveThreshold,
  kHumidityBelowThreshold,
  kHysteresisHold,
  kMinOnTimeHold,
  kMinOffTimeHold,
  kMaxRuntimeCutoff,
  kSensorInvalidSafeState,
  kManualOverride,
  kRiseRateTrigger,
  kMqttCommand,
};

const char* ReasonToString(Reason reason);
const char* OperatingModeToString(OperatingMode mode);

struct SensorReading {
  bool valid = false;
  float humidity_percent = 0.0f;
  float temperature_celsius = 0.0f;
};

enum class OverrideType {
  kNone,
  kOn,
  kOff,
  kAuto,
};

struct ControllerConfig {
  float fan_on_percent = 70.0f;
  float fan_off_percent = 60.0f;
  float humidity_min_valid_percent = 0.0f;
  float humidity_max_valid_percent = 100.0f;
  float temperature_min_valid_celsius = -10.0f;
  float temperature_max_valid_celsius = 60.0f;

  uint32_t min_fan_on_ms = 120000;
  uint32_t min_fan_off_ms = 30000;
  uint32_t max_continuous_runtime_ms = 1800000;
  uint32_t stale_command_timeout_ms = 60000;
  uint32_t manual_override_default_duration_ms = 1800000;
  uint32_t manual_override_max_duration_ms = 7200000;

  uint8_t sensor_consecutive_failure_limit = 3;
  bool sensor_invalid_hold_last_state = false;  // false => safe state is OFF

  bool rise_rate_detection_enabled = false;
  float rise_rate_threshold_percent_per_minute = 3.0f;
  uint32_t rise_rate_window_ms = 60000;
  uint8_t rise_rate_min_valid_samples = 4;
};

struct ControlDecision {
  bool relay_on = false;
  bool relay_state_changed = false;
  OperatingMode mode = OperatingMode::kLocalFallback;
  ControlSource source = ControlSource::kLocal;
  Reason reason = Reason::kStartupSafeState;
  bool fallback_active = true;
  bool override_active = false;
  uint32_t override_expires_at_ms = 0;
};

class VentilationController {
 public:
  explicit VentilationController(const ControllerConfig& cfg);

  // Feed a new local sensor reading. `now_ms` is the monotonic time the
  // reading was taken. Applies range validation and consecutive-failure
  // tracking; out-of-range readings are treated as invalid.
  void OnSensorReading(const SensorReading& reading, uint32_t now_ms);

  // Feed a freshly-received `fan/desired` MQTT payload. `issued_at_age_ms`
  // is how old the payload's `issued_at` timestamp already was when
  // received (0 for a just-issued command); this lets a stale retained
  // message delivered right after reconnecting be recognized as stale
  // immediately, rather than only after it sits unrefreshed locally for
  // the timeout - see docs/mqtt-api.md "Why `command` is not retained".
  void OnMqttDesired(bool desired_on, uint32_t issued_at_age_ms,
                      uint32_t now_ms);

  // Feed a manual override command (see docs/mqtt-api.md `command` topic).
  // `issued_at_age_ms` is how old the command already was when received
  // (e.g. computed from its `issued_at` timestamp vs. current wall time);
  // pass 0 for a command known to be fresh. Returns false and makes no
  // change if the command is rejected as stale.
  bool OnCommand(OverrideType type, uint32_t duration_ms,
                 uint32_t issued_at_age_ms, uint32_t now_ms);

  // Advance the controller and get the current control decision. Must be
  // called periodically (e.g. once per sensor sample interval). This is
  // where hysteresis, timing, max-runtime, and precedence rules are all
  // applied.
  ControlDecision Tick(uint32_t now_ms);

  SensorStatus GetSensorStatus() const;
  uint8_t GetConsecutiveFailures() const { return consecutive_failures_; }
  bool HasValidReading() const { return has_valid_reading_; }

 private:
  bool IsMqttFresh(uint32_t now_ms) const;
  bool IsOverrideActive(uint32_t now_ms) const;
  void ComputeCandidate(uint32_t now_ms, bool* candidate_on,
                         OperatingMode* mode, ControlSource* source,
                         Reason* reason);
  void UpdateRiseRateBuffer(const SensorReading& reading, uint32_t now_ms);
  bool RiseRateTriggered(uint32_t now_ms) const;

  ControllerConfig cfg_;

  bool relay_on_ = false;
  uint32_t last_relay_change_ms_ = 0;
  uint32_t relay_on_since_ms_ = 0;

  bool has_valid_reading_ = false;
  SensorReading last_valid_reading_{};
  uint8_t consecutive_failures_ = 0;

  bool mqtt_command_received_ = false;
  bool mqtt_desired_on_ = false;
  uint32_t mqtt_issued_at_ms_ = 0;

  OverrideType override_type_ = OverrideType::kNone;
  uint32_t override_expires_at_ms_ = 0;

  static constexpr uint8_t kRiseRateBufferSize = 16;
  struct RiseSample {
    uint32_t timestamp_ms;
    float humidity_percent;
  };
  RiseSample rise_buffer_[kRiseRateBufferSize]{};
  uint8_t rise_buffer_count_ = 0;
  uint8_t rise_buffer_head_ = 0;
};

}  // namespace vent

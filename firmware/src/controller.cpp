#include "controller.h"

namespace vent {

const char* ReasonToString(Reason reason) {
  switch (reason) {
    case Reason::kStartupSafeState: return "startup_safe_state";
    case Reason::kHumidityAboveThreshold: return "humidity_above_threshold";
    case Reason::kHumidityBelowThreshold: return "humidity_below_threshold";
    case Reason::kHysteresisHold: return "hysteresis_hold";
    case Reason::kMinOnTimeHold: return "min_on_time_hold";
    case Reason::kMinOffTimeHold: return "min_off_time_hold";
    case Reason::kMaxRuntimeCutoff: return "max_runtime_cutoff";
    case Reason::kSensorInvalidSafeState: return "sensor_invalid_safe_state";
    case Reason::kManualOverride: return "manual_override";
    case Reason::kRiseRateTrigger: return "rise_rate_trigger";
    case Reason::kMqttCommand: return "mqtt_command";
  }
  return "unknown";
}

const char* OperatingModeToString(OperatingMode mode) {
  switch (mode) {
    case OperatingMode::kAutomatic: return "automatic";
    case OperatingMode::kLocalFallback: return "local_fallback";
    case OperatingMode::kManualOn: return "manual_on";
    case OperatingMode::kManualOff: return "manual_off";
  }
  return "unknown";
}

VentilationController::VentilationController(const ControllerConfig& cfg)
    : cfg_(cfg) {}

static uint32_t SaturatingSub(uint32_t a, uint32_t b) {
  return (a > b) ? (a - b) : 0;
}

void VentilationController::OnSensorReading(const SensorReading& reading,
                                             uint32_t now_ms) {
  const bool in_range =
      reading.valid &&
      reading.humidity_percent >= cfg_.humidity_min_valid_percent &&
      reading.humidity_percent <= cfg_.humidity_max_valid_percent &&
      reading.temperature_celsius >= cfg_.temperature_min_valid_celsius &&
      reading.temperature_celsius <= cfg_.temperature_max_valid_celsius;

  if (in_range) {
    consecutive_failures_ = 0;
    has_valid_reading_ = true;
    last_valid_reading_ = reading;
    UpdateRiseRateBuffer(reading, now_ms);
  } else {
    if (consecutive_failures_ < 255) {
      consecutive_failures_++;
    }
  }
}

void VentilationController::OnMqttDesired(bool desired_on,
                                           uint32_t issued_at_age_ms,
                                           uint32_t now_ms) {
  mqtt_command_received_ = true;
  mqtt_desired_on_ = desired_on;
  mqtt_issued_at_ms_ = SaturatingSub(now_ms, issued_at_age_ms);
}

bool VentilationController::OnCommand(OverrideType type, uint32_t duration_ms,
                                       uint32_t issued_at_age_ms,
                                       uint32_t now_ms) {
  if (issued_at_age_ms > cfg_.stale_command_timeout_ms) {
    return false;  // rejected as stale - see docs/mqtt-api.md
  }

  if (type == OverrideType::kAuto || type == OverrideType::kNone) {
    override_type_ = OverrideType::kNone;
    override_expires_at_ms_ = 0;
    return true;
  }

  uint32_t effective_duration =
      (duration_ms == 0) ? cfg_.manual_override_default_duration_ms
                          : duration_ms;
  if (effective_duration > cfg_.manual_override_max_duration_ms) {
    effective_duration = cfg_.manual_override_max_duration_ms;
  }

  override_type_ = type;
  override_expires_at_ms_ = now_ms + effective_duration;
  return true;
}

bool VentilationController::IsMqttFresh(uint32_t now_ms) const {
  if (!mqtt_command_received_) return false;
  return (now_ms - mqtt_issued_at_ms_) <= cfg_.stale_command_timeout_ms;
}

bool VentilationController::IsOverrideActive(uint32_t now_ms) const {
  return override_type_ != OverrideType::kNone && now_ms < override_expires_at_ms_;
}

void VentilationController::UpdateRiseRateBuffer(const SensorReading& reading,
                                                   uint32_t now_ms) {
  if (!cfg_.rise_rate_detection_enabled) return;
  rise_buffer_[rise_buffer_head_] = {now_ms, reading.humidity_percent};
  rise_buffer_head_ = (rise_buffer_head_ + 1) % kRiseRateBufferSize;
  if (rise_buffer_count_ < kRiseRateBufferSize) rise_buffer_count_++;
}

bool VentilationController::RiseRateTriggered(uint32_t now_ms) const {
  if (!cfg_.rise_rate_detection_enabled) return false;
  if (rise_buffer_count_ < cfg_.rise_rate_min_valid_samples) return false;

  // Find the oldest sample within the configured window and the newest
  // sample overall; a simple two-point slope is sufficient here since
  // UpdateRiseRateBuffer only stores samples that already passed range
  // validation (see OnSensorReading), which filters single-sample noise.
  const RiseSample& newest =
      rise_buffer_[(rise_buffer_head_ + kRiseRateBufferSize - 1) %
                   kRiseRateBufferSize];

  const RiseSample* oldest_in_window = nullptr;
  uint8_t samples_in_window = 0;
  for (uint8_t i = 0; i < rise_buffer_count_; i++) {
    uint8_t idx =
        (rise_buffer_head_ + kRiseRateBufferSize - 1 - i) % kRiseRateBufferSize;
    const RiseSample& s = rise_buffer_[idx];
    if (SaturatingSub(now_ms, s.timestamp_ms) > cfg_.rise_rate_window_ms) break;
    oldest_in_window = &s;
    samples_in_window++;
  }

  if (oldest_in_window == nullptr ||
      samples_in_window < cfg_.rise_rate_min_valid_samples) {
    return false;
  }

  uint32_t elapsed_ms = SaturatingSub(newest.timestamp_ms, oldest_in_window->timestamp_ms);
  if (elapsed_ms == 0) return false;

  float elapsed_minutes = static_cast<float>(elapsed_ms) / 60000.0f;
  float rate_per_minute =
      (newest.humidity_percent - oldest_in_window->humidity_percent) /
      elapsed_minutes;

  return rate_per_minute >= cfg_.rise_rate_threshold_percent_per_minute;
}

void VentilationController::ComputeCandidate(uint32_t now_ms,
                                              bool* candidate_on,
                                              OperatingMode* mode,
                                              ControlSource* source,
                                              Reason* reason) {
  if (IsOverrideActive(now_ms)) {
    *source = ControlSource::kLocal;
    *reason = Reason::kManualOverride;
    if (override_type_ == OverrideType::kOn) {
      *mode = OperatingMode::kManualOn;
      *candidate_on = true;
    } else {
      *mode = OperatingMode::kManualOff;
      *candidate_on = false;
    }
    return;
  }

  if (IsMqttFresh(now_ms)) {
    *mode = OperatingMode::kAutomatic;
    *source = ControlSource::kMqtt;
    *candidate_on = mqtt_desired_on_;
    *reason = Reason::kMqttCommand;
    return;
  }

  // Local fallback: MQTT desired state is stale/unavailable.
  *mode = OperatingMode::kLocalFallback;
  *source = ControlSource::kLocal;

  const bool sensor_failed =
      !has_valid_reading_ ||
      consecutive_failures_ >= cfg_.sensor_consecutive_failure_limit;

  if (sensor_failed) {
    *candidate_on =
        cfg_.sensor_invalid_hold_last_state ? relay_on_ : false;
    *reason = Reason::kSensorInvalidSafeState;
    return;
  }

  const float humidity = last_valid_reading_.humidity_percent;
  if (humidity >= cfg_.fan_on_percent) {
    *candidate_on = true;
    *reason = Reason::kHumidityAboveThreshold;
  } else if (humidity <= cfg_.fan_off_percent) {
    *candidate_on = false;
    *reason = Reason::kHumidityBelowThreshold;
  } else {
    *candidate_on = relay_on_;
    *reason = Reason::kHysteresisHold;
  }

  if (!*candidate_on && RiseRateTriggered(now_ms)) {
    *candidate_on = true;
    *reason = Reason::kRiseRateTrigger;
  }
}

ControlDecision VentilationController::Tick(uint32_t now_ms) {
  // Expire a finished manual override before computing the candidate so
  // precedence naturally falls through to automatic/fallback.
  if (override_type_ != OverrideType::kNone && now_ms >= override_expires_at_ms_) {
    override_type_ = OverrideType::kNone;
  }

  bool candidate_on = relay_on_;
  OperatingMode mode = OperatingMode::kLocalFallback;
  ControlSource source = ControlSource::kLocal;
  Reason reason = Reason::kStartupSafeState;
  ComputeCandidate(now_ms, &candidate_on, &mode, &source, &reason);

  bool final_on = candidate_on;
  Reason final_reason = reason;

  // Maximum-runtime safety cutoff: always wins, bypasses min-on gating,
  // cannot be overridden by mode (including an active manual override).
  const bool max_runtime_exceeded =
      relay_on_ &&
      SaturatingSub(now_ms, relay_on_since_ms_) >= cfg_.max_continuous_runtime_ms;

  if (max_runtime_exceeded) {
    final_on = false;
    final_reason = Reason::kMaxRuntimeCutoff;
  } else if (candidate_on != relay_on_) {
    // Anti-cycling: enforce minimum on/off dwell time on every transition
    // attempt, regardless of what requested it.
    uint32_t elapsed = SaturatingSub(now_ms, last_relay_change_ms_);
    if (relay_on_ && !candidate_on) {
      if (elapsed < cfg_.min_fan_on_ms) {
        final_on = true;
        final_reason = Reason::kMinOnTimeHold;
      }
    } else if (!relay_on_ && candidate_on) {
      if (elapsed < cfg_.min_fan_off_ms) {
        final_on = false;
        final_reason = Reason::kMinOffTimeHold;
      }
    }
  }

  const bool changed = (final_on != relay_on_);
  if (changed) {
    relay_on_ = final_on;
    last_relay_change_ms_ = now_ms;
    if (final_on) {
      relay_on_since_ms_ = now_ms;
    }
  }

  ControlDecision decision;
  decision.relay_on = relay_on_;
  decision.relay_state_changed = changed;
  decision.mode = mode;
  decision.source = source;
  decision.reason = final_reason;
  decision.fallback_active = (mode == OperatingMode::kLocalFallback);
  decision.override_active = IsOverrideActive(now_ms);
  decision.override_expires_at_ms =
      decision.override_active ? override_expires_at_ms_ : 0;
  return decision;
}

SensorStatus VentilationController::GetSensorStatus() const {
  if (consecutive_failures_ >= cfg_.sensor_consecutive_failure_limit) {
    return SensorStatus::kFailed;
  }
  if (consecutive_failures_ > 0) {
    return SensorStatus::kDegraded;
  }
  return SensorStatus::kOk;
}

}  // namespace vent

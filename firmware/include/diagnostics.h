#pragma once

// Structured serial logging. Every control decision is logged with its
// reason (see controller.h Reason enum) so the "log the reason behind
// each control decision" requirement is satisfiable by reading the serial
// monitor, independent of MQTT connectivity.

#include <Arduino.h>

#include "controller.h"

namespace vent {

namespace diagnostics {

inline void Init() {
  Serial.begin(115200);
  unsigned long start = millis();
  while (!Serial && millis() - start < 2000) {
    delay(10);
  }
}

inline void LogDecision(const ControlDecision& decision, float humidity,
                         float temperature, bool sensor_valid) {
  Serial.printf(
      "[decision] relay=%s mode=%s reason=%s humidity=%.1f%% "
      "temp=%.1fC sensor_valid=%s fallback=%s override=%s\n",
      decision.relay_on ? "ON" : "OFF",
      OperatingModeToString(decision.mode), ReasonToString(decision.reason),
      humidity, temperature, sensor_valid ? "true" : "false",
      decision.fallback_active ? "true" : "false",
      decision.override_active ? "true" : "false");
}

inline void LogInfo(const char* message) {
  Serial.printf("[info] %s\n", message);
}

inline void LogWarn(const char* message) {
  Serial.printf("[warn] %s\n", message);
}

inline void LogError(const char* message) {
  Serial.printf("[error] %s\n", message);
}

}  // namespace diagnostics

}  // namespace vent

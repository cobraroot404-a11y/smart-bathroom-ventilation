#pragma once

// WifiManager: connection + bounded exponential backoff reconnection, and
// NTP time sync (required so MQTT payload timestamps and staleness
// comparisons are meaningful - see time_utils.h).

#include <Arduino.h>
#include <WiFi.h>
#include <time.h>

namespace vent {

class WifiManager {
 public:
  WifiManager(const char* ssid, const char* password,
              uint32_t backoff_initial_ms, uint32_t backoff_max_ms)
      : ssid_(ssid),
        password_(password),
        backoff_initial_ms_(backoff_initial_ms),
        backoff_max_ms_(backoff_max_ms),
        backoff_ms_(backoff_initial_ms) {}

  void Begin() {
    WiFi.mode(WIFI_STA);
    configTime(0, 0, "pool.ntp.org", "time.nist.gov");
    Connect();
  }

  // Call every loop iteration. Non-blocking; retries with exponential
  // backoff rather than a tight reconnect loop.
  bool EnsureConnected() {
    if (WiFi.status() == WL_CONNECTED) {
      backoff_ms_ = backoff_initial_ms_;
      return true;
    }
    uint32_t now = millis();
    if (now - last_attempt_ms_ >= backoff_ms_) {
      Connect();
      last_attempt_ms_ = now;
      backoff_ms_ = min(backoff_ms_ * 2, backoff_max_ms_);
    }
    return WiFi.status() == WL_CONNECTED;
  }

  bool IsConnected() const { return WiFi.status() == WL_CONNECTED; }

  bool TimeIsSynced() const { return time(nullptr) > 1609459200; }  // > 2021-01-01

 private:
  void Connect() { WiFi.begin(ssid_, password_); }

  const char* ssid_;
  const char* password_;
  uint32_t backoff_initial_ms_;
  uint32_t backoff_max_ms_;
  uint32_t backoff_ms_;
  uint32_t last_attempt_ms_ = 0;
};

}  // namespace vent

#pragma once

// RelayDriver: thin active-high/active-low abstraction over a single GPIO.
//
// Safety-critical ordering lives in Init(): the pin is configured as an
// OUTPUT and immediately driven to its inactive level as the very first
// hardware action the firmware takes (called first thing in setup(),
// before Wi-Fi/MQTT/sensor init) - see docs/hardware.md "Startup / reset
// / flashing safety".

#include <Arduino.h>

namespace vent {

class RelayDriver {
 public:
  RelayDriver(uint8_t gpio_pin, bool active_low)
      : gpio_pin_(gpio_pin), active_low_(active_low) {}

  void Init() {
    pinMode(gpio_pin_, OUTPUT);
    digitalWrite(gpio_pin_, InactiveLevel());
    is_on_ = false;
  }

  void Set(bool on) {
    digitalWrite(gpio_pin_, on ? ActiveLevel() : InactiveLevel());
    is_on_ = on;
  }

  bool IsOn() const { return is_on_; }

 private:
  int ActiveLevel() const { return active_low_ ? LOW : HIGH; }
  int InactiveLevel() const { return active_low_ ? HIGH : LOW; }

  uint8_t gpio_pin_;
  bool active_low_;
  bool is_on_ = false;
};

}  // namespace vent

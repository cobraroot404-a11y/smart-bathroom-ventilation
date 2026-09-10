#pragma once

// SensorReader: abstraction over the physical humidity/temperature
// sensor so firmware/src/controller.* never depends on a specific part.
//
// Sht3xSensor is the primary, recommended implementation (SHT31/SHT40,
// both I2C-compatible and supported by the same Adafruit_SHT31 driver at
// the default 0x44 address). A DHT22 implementation is not included by
// default - see "DHT22 extension point" below - because docs/hardware.md
// documents its slower response time, coarser accuracy, and higher
// condensation sensitivity as reasons it is not the recommended primary
// sensor for this project; sites that still want it can implement
// Dht22Sensor against this same interface with the `DHT sensor library`
// (Adafruit), which is a drop-in three-pin (VCC/GND/DATA) alternative to
// the I2C wiring documented for the SHT31/40.

#include "controller.h"

namespace vent {

class SensorReader {
 public:
  virtual ~SensorReader() = default;
  virtual SensorReading Read() = 0;
};

#ifndef UNIT_TEST

class Sht3xSensor : public SensorReader {
 public:
  explicit Sht3xSensor(uint8_t i2c_address = 0x44)
      : i2c_address_(i2c_address) {}

  bool Init();
  SensorReading Read() override;

 private:
  uint8_t i2c_address_;
};

// DHT22 extension point (not implemented by default - see file comment
// above and docs/hardware.md). To add support:
//   1. Add `adafruit/DHT sensor library` to firmware/platformio.ini
//      lib_deps.
//   2. Implement Dht22Sensor : public SensorReader wrapping `DHT::begin()`
//      / `DHT::readHumidity()` / `DHT::readTemperature()`, applying the
//      same NaN-checking Adafruit's DHT library returns on a failed read.
//   3. Respect the DHT22's minimum ~2 second interval between reads -
//      do not sample it faster than that even if
//      config::kSensorSampleIntervalSeconds is set lower.
//   4. Select it in firmware/src/main.cpp in place of Sht3xSensor.
// class Dht22Sensor : public SensorReader { ... };

#endif  // UNIT_TEST

}  // namespace vent

#include "sensor.h"

#ifndef UNIT_TEST

#include <Adafruit_SHT31.h>
#include <cmath>

namespace vent {

namespace {
Adafruit_SHT31 g_sht31;
}

bool Sht3xSensor::Init() { return g_sht31.begin(i2c_address_); }

SensorReading Sht3xSensor::Read() {
  SensorReading reading;
  float humidity = g_sht31.readHumidity();
  float temperature = g_sht31.readTemperature();

  // Adafruit_SHT31 returns NaN on a failed/CRC-mismatched read.
  if (isnan(humidity) || isnan(temperature)) {
    reading.valid = false;
    return reading;
  }

  reading.valid = true;
  reading.humidity_percent = humidity;
  reading.temperature_celsius = temperature;
  return reading;
}

}  // namespace vent

#endif  // UNIT_TEST

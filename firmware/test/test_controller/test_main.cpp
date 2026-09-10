// Native (no-hardware) unit tests for VentilationController.
// Run with: pio test -e native   (from firmware/)
//
// Timing note: min_fan_off_ms (default 30000) is enforced on *every*
// off->on transition, including the very first one after the controller
// is constructed (last_relay_change_ms_ starts at 0) - this is the
// documented boot behavior in docs/safety.md "Restart behavior": a
// restart never assumes an in-progress min-off timer is already
// satisfied. Tests that want an immediate "first" ON transition
// therefore call Tick() at now_ms >= min_fan_off_ms; the boundary itself
// is verified explicitly in
// test_startup_high_humidity_is_held_until_min_off_elapses.

#include <unity.h>

#include "controller.h"

using namespace vent;

namespace {

ControllerConfig DefaultTestConfig() {
  ControllerConfig cfg;
  cfg.fan_on_percent = 70.0f;
  cfg.fan_off_percent = 60.0f;
  cfg.humidity_min_valid_percent = 0.0f;
  cfg.humidity_max_valid_percent = 100.0f;
  cfg.temperature_min_valid_celsius = -10.0f;
  cfg.temperature_max_valid_celsius = 60.0f;
  cfg.min_fan_on_ms = 120000;
  cfg.min_fan_off_ms = 30000;
  cfg.max_continuous_runtime_ms = 1800000;
  cfg.stale_command_timeout_ms = 60000;
  cfg.manual_override_default_duration_ms = 1800000;
  cfg.manual_override_max_duration_ms = 7200000;
  cfg.sensor_consecutive_failure_limit = 3;
  cfg.sensor_invalid_hold_last_state = false;
  cfg.rise_rate_detection_enabled = false;
  return cfg;
}

SensorReading Reading(float humidity, float temperature = 24.0f) {
  SensorReading r;
  r.valid = true;
  r.humidity_percent = humidity;
  r.temperature_celsius = temperature;
  return r;
}

// Drives the controller ON, past the boot-time min-off window, and
// fails the test immediately if that precondition doesn't hold.
void TurnOn(VentilationController* c, uint32_t at_ms = 31000,
            float humidity = 75.0f) {
  c->OnSensorReading(Reading(humidity), at_ms);
  ControlDecision d = c->Tick(at_ms);
  TEST_ASSERT_TRUE_MESSAGE(d.relay_on, "TurnOn() helper precondition failed");
}

}  // namespace

void setUp(void) {}
void tearDown(void) {}

// --- Startup ---

void test_startup_relay_is_off(void) {
  VentilationController c(DefaultTestConfig());
  ControlDecision d = c.Tick(0);
  TEST_ASSERT_FALSE(d.relay_on);
  TEST_ASSERT_EQUAL(static_cast<int>(OperatingMode::kLocalFallback),
                     static_cast<int>(d.mode));
}

void test_startup_high_humidity_is_held_until_min_off_elapses(void) {
  VentilationController c(DefaultTestConfig());
  c.OnSensorReading(Reading(80.0f), 0);
  ControlDecision held = c.Tick(0);
  TEST_ASSERT_FALSE(held.relay_on);
  TEST_ASSERT_EQUAL(static_cast<int>(Reason::kMinOffTimeHold),
                     static_cast<int>(held.reason));

  c.OnSensorReading(Reading(80.0f), 30000);
  ControlDecision released = c.Tick(30000);
  TEST_ASSERT_TRUE(released.relay_on);
  TEST_ASSERT_EQUAL(static_cast<int>(Reason::kHumidityAboveThreshold),
                     static_cast<int>(released.reason));
}

// --- Hysteresis ---

void test_humidity_below_lower_threshold_keeps_fan_off(void) {
  VentilationController c(DefaultTestConfig());
  c.OnSensorReading(Reading(40.0f), 0);
  ControlDecision d = c.Tick(0);
  TEST_ASSERT_FALSE(d.relay_on);
  TEST_ASSERT_EQUAL(static_cast<int>(Reason::kHumidityBelowThreshold),
                     static_cast<int>(d.reason));
}

void test_humidity_crossing_upper_threshold_turns_fan_on(void) {
  VentilationController c(DefaultTestConfig());
  TurnOn(&c, 31000, 75.0f);
}

void test_humidity_in_band_preserves_state_while_off(void) {
  VentilationController c(DefaultTestConfig());
  c.OnSensorReading(Reading(65.0f), 0);
  ControlDecision d = c.Tick(0);
  TEST_ASSERT_FALSE(d.relay_on);
  TEST_ASSERT_EQUAL(static_cast<int>(Reason::kHysteresisHold),
                     static_cast<int>(d.reason));
}

void test_humidity_in_band_preserves_state_while_on(void) {
  VentilationController c(DefaultTestConfig());
  TurnOn(&c, 31000, 75.0f);
  c.OnSensorReading(Reading(65.0f), 161000);
  ControlDecision d = c.Tick(161000);
  TEST_ASSERT_TRUE(d.relay_on);
  TEST_ASSERT_EQUAL(static_cast<int>(Reason::kHysteresisHold),
                     static_cast<int>(d.reason));
}

void test_humidity_crossing_lower_threshold_turns_fan_off(void) {
  VentilationController c(DefaultTestConfig());
  TurnOn(&c, 31000, 75.0f);
  c.OnSensorReading(Reading(55.0f), 161000);  // 130s after turn-on (>120s min-on)
  ControlDecision d = c.Tick(161000);
  TEST_ASSERT_FALSE(d.relay_on);
  TEST_ASSERT_EQUAL(static_cast<int>(Reason::kHumidityBelowThreshold),
                     static_cast<int>(d.reason));
}

// --- Timers ---

void test_min_on_time_is_enforced(void) {
  VentilationController c(DefaultTestConfig());
  TurnOn(&c, 31000, 75.0f);

  // Humidity drops below off-threshold after only 10s (< 120s min-on).
  c.OnSensorReading(Reading(50.0f), 41000);
  ControlDecision held = c.Tick(41000);
  TEST_ASSERT_TRUE(held.relay_on);
  TEST_ASSERT_EQUAL(static_cast<int>(Reason::kMinOnTimeHold),
                     static_cast<int>(held.reason));

  // After min-on elapses (121s after turn-on), it is allowed to turn off.
  c.OnSensorReading(Reading(50.0f), 152000);
  ControlDecision released = c.Tick(152000);
  TEST_ASSERT_FALSE(released.relay_on);
}

void test_min_off_time_is_enforced(void) {
  VentilationController c(DefaultTestConfig());
  c.OnSensorReading(Reading(40.0f), 0);
  ControlDecision off = c.Tick(0);
  TEST_ASSERT_FALSE(off.relay_on);

  // Humidity rises above on-threshold after only 5s (< 30s min-off).
  c.OnSensorReading(Reading(80.0f), 5000);
  ControlDecision held = c.Tick(5000);
  TEST_ASSERT_FALSE(held.relay_on);
  TEST_ASSERT_EQUAL(static_cast<int>(Reason::kMinOffTimeHold),
                     static_cast<int>(held.reason));

  c.OnSensorReading(Reading(80.0f), 31000);
  ControlDecision released = c.Tick(31000);
  TEST_ASSERT_TRUE(released.relay_on);
}

void test_max_runtime_cutoff_forces_off(void) {
  VentilationController c(DefaultTestConfig());
  TurnOn(&c, 31000, 80.0f);

  // Still high humidity, but max runtime (1800s) has elapsed since turn-on.
  c.OnSensorReading(Reading(80.0f), 31000 + 1800000);
  ControlDecision d = c.Tick(31000 + 1800000);
  TEST_ASSERT_FALSE(d.relay_on);
  TEST_ASSERT_EQUAL(static_cast<int>(Reason::kMaxRuntimeCutoff),
                     static_cast<int>(d.reason));
}

void test_max_runtime_cutoff_overrides_manual_override(void) {
  VentilationController c(DefaultTestConfig());
  TEST_ASSERT_TRUE(c.OnCommand(OverrideType::kOn, 3600000, 0, 31000));
  ControlDecision on = c.Tick(31000);  // relay on via override
  TEST_ASSERT_TRUE(on.relay_on);

  ControlDecision d = c.Tick(31000 + 1800000);  // max runtime elapsed
  TEST_ASSERT_FALSE(d.relay_on);
  TEST_ASSERT_EQUAL(static_cast<int>(Reason::kMaxRuntimeCutoff),
                     static_cast<int>(d.reason));
}

// --- Sensor failure handling ---

void test_invalid_reading_is_rejected_and_does_not_switch(void) {
  VentilationController c(DefaultTestConfig());
  c.OnSensorReading(Reading(40.0f), 0);
  c.Tick(0);  // established: off, valid reading

  SensorReading bad;
  bad.valid = true;
  bad.humidity_percent = 150.0f;  // impossible value
  bad.temperature_celsius = 24.0f;
  c.OnSensorReading(bad, 6000);
  ControlDecision d = c.Tick(6000);
  // One bad reading alone (below failure limit) keeps last valid state.
  TEST_ASSERT_FALSE(d.relay_on);
  TEST_ASSERT_EQUAL(static_cast<int>(SensorStatus::kDegraded),
                     static_cast<int>(c.GetSensorStatus()));
}

void test_sensor_failure_beyond_limit_forces_safe_off_state(void) {
  ControllerConfig cfg = DefaultTestConfig();
  VentilationController c(cfg);
  TurnOn(&c, 31000, 80.0f);

  c.OnSensorReading(Reading(80.0f), 161000);
  c.Tick(161000);  // still on, well past min-on

  SensorReading bad;
  bad.valid = false;
  uint32_t t = 161000;
  for (int i = 0; i < 3; i++) {
    t += 5000;
    c.OnSensorReading(bad, t);
  }
  ControlDecision d = c.Tick(t);
  TEST_ASSERT_FALSE(d.relay_on);
  TEST_ASSERT_EQUAL(static_cast<int>(Reason::kSensorInvalidSafeState),
                     static_cast<int>(d.reason));
  TEST_ASSERT_EQUAL(static_cast<int>(SensorStatus::kFailed),
                     static_cast<int>(c.GetSensorStatus()));
}

void test_sensor_failure_can_be_configured_to_hold_last_state(void) {
  ControllerConfig cfg = DefaultTestConfig();
  cfg.sensor_invalid_hold_last_state = true;
  VentilationController c(cfg);
  TurnOn(&c, 31000, 80.0f);
  c.OnSensorReading(Reading(80.0f), 161000);
  c.Tick(161000);

  SensorReading bad;
  bad.valid = false;
  uint32_t t = 161000;
  for (int i = 0; i < 3; i++) {
    t += 5000;
    c.OnSensorReading(bad, t);
  }
  ControlDecision d = c.Tick(t);
  TEST_ASSERT_TRUE(d.relay_on);  // held, not forced off
}

// --- MQTT automatic mode / staleness ---

void test_fresh_mqtt_command_drives_automatic_mode(void) {
  VentilationController c(DefaultTestConfig());
  c.OnSensorReading(Reading(40.0f), 31000);  // would be OFF locally
  c.OnMqttDesired(true, 0, 31000);
  ControlDecision d = c.Tick(31000);
  TEST_ASSERT_TRUE(d.relay_on);
  TEST_ASSERT_EQUAL(static_cast<int>(OperatingMode::kAutomatic),
                     static_cast<int>(d.mode));
  TEST_ASSERT_EQUAL(static_cast<int>(ControlSource::kMqtt),
                     static_cast<int>(d.source));
}

void test_stale_mqtt_command_triggers_local_fallback(void) {
  VentilationController c(DefaultTestConfig());
  c.OnMqttDesired(true, 0, 0);
  c.OnSensorReading(Reading(40.0f), 0);
  TEST_ASSERT_EQUAL(static_cast<int>(OperatingMode::kAutomatic),
                     static_cast<int>(c.Tick(0).mode));

  // No new MQTT message arrives; 61s later the command is stale.
  c.OnSensorReading(Reading(40.0f), 61000);
  ControlDecision d = c.Tick(61000);
  TEST_ASSERT_EQUAL(static_cast<int>(OperatingMode::kLocalFallback),
                     static_cast<int>(d.mode));
  TEST_ASSERT_TRUE(d.fallback_active);
}

void test_retained_command_stale_at_receipt_is_ignored(void) {
  VentilationController c(DefaultTestConfig());
  c.OnSensorReading(Reading(40.0f), 100000);
  // A retained message arrives at t=100000 that was actually issued 90s
  // earlier (age_ms=90000), i.e. older than the 60s staleness window.
  c.OnMqttDesired(true, 90000, 100000);
  ControlDecision d = c.Tick(100000);
  TEST_ASSERT_EQUAL(static_cast<int>(OperatingMode::kLocalFallback),
                     static_cast<int>(d.mode));
  TEST_ASSERT_FALSE(d.relay_on);
}

// --- Manual override ---

void test_manual_override_on_forces_relay_on(void) {
  VentilationController c(DefaultTestConfig());
  c.OnSensorReading(Reading(40.0f), 31000);
  TEST_ASSERT_TRUE(c.OnCommand(OverrideType::kOn, 600000, 0, 31000));
  ControlDecision d = c.Tick(31000);
  TEST_ASSERT_TRUE(d.relay_on);
  TEST_ASSERT_TRUE(d.override_active);
  TEST_ASSERT_EQUAL(static_cast<int>(OperatingMode::kManualOn),
                     static_cast<int>(d.mode));
}

void test_manual_override_off_forces_relay_off(void) {
  VentilationController c(DefaultTestConfig());
  c.OnSensorReading(Reading(80.0f), 0);
  TEST_ASSERT_TRUE(c.OnCommand(OverrideType::kOff, 600000, 0, 0));
  ControlDecision d = c.Tick(0);
  TEST_ASSERT_FALSE(d.relay_on);
  TEST_ASSERT_EQUAL(static_cast<int>(OperatingMode::kManualOff),
                     static_cast<int>(d.mode));
}

void test_manual_override_expires_and_returns_to_automatic(void) {
  VentilationController c(DefaultTestConfig());
  c.OnSensorReading(Reading(40.0f), 0);
  TEST_ASSERT_TRUE(c.OnCommand(OverrideType::kOn, 60000, 0, 0));
  TEST_ASSERT_TRUE(c.Tick(0).override_active);

  c.OnSensorReading(Reading(40.0f), 60001);
  ControlDecision d = c.Tick(60001);
  TEST_ASSERT_FALSE(d.override_active);
  TEST_ASSERT_EQUAL(static_cast<int>(OperatingMode::kLocalFallback),
                     static_cast<int>(d.mode));
}

void test_override_auto_cancels_active_override_immediately(void) {
  VentilationController c(DefaultTestConfig());
  c.OnSensorReading(Reading(40.0f), 0);
  c.OnCommand(OverrideType::kOn, 600000, 0, 0);
  TEST_ASSERT_TRUE(c.Tick(0).override_active);

  c.OnCommand(OverrideType::kAuto, 0, 0, 1000);
  ControlDecision d = c.Tick(1000);
  TEST_ASSERT_FALSE(d.override_active);
}

void test_stale_command_is_rejected(void) {
  VentilationController c(DefaultTestConfig());
  // Command claims to have been issued 90s before receipt (> 60s timeout).
  bool accepted = c.OnCommand(OverrideType::kOn, 600000, 90000, 0);
  TEST_ASSERT_FALSE(accepted);
  ControlDecision d = c.Tick(0);
  TEST_ASSERT_FALSE(d.override_active);
}

// --- Rise-rate detection (optional feature) ---

void test_rise_rate_detection_triggers_below_absolute_threshold(void) {
  ControllerConfig cfg = DefaultTestConfig();
  cfg.rise_rate_detection_enabled = true;
  cfg.rise_rate_threshold_percent_per_minute = 3.0f;
  cfg.rise_rate_window_ms = 60000;
  cfg.rise_rate_min_valid_samples = 3;
  VentilationController c(cfg);

  // All samples start well after the boot min-off window so the ON
  // transition below is caused by the rise-rate rule, not by the min-off
  // boundary happening to clear at the same instant. Humidity rises
  // 50% -> 54% -> 58%, staying under both the 70% absolute threshold and
  // (until the 3rd sample) even the 60% lower threshold. The rule needs
  // rise_rate_min_valid_samples (3) samples in its window before it will
  // evaluate a rate at all, so the trigger fires exactly on the 3rd
  // sample: 8%/20s = 24%/min, well above the 3%/min threshold.
  uint32_t base = 100000;
  c.OnSensorReading(Reading(50.0f), base);
  c.Tick(base);
  c.OnSensorReading(Reading(54.0f), base + 10000);
  c.Tick(base + 10000);
  c.OnSensorReading(Reading(58.0f), base + 20000);
  ControlDecision d = c.Tick(base + 20000);

  TEST_ASSERT_TRUE(d.relay_on);
  TEST_ASSERT_EQUAL(static_cast<int>(Reason::kRiseRateTrigger),
                     static_cast<int>(d.reason));

  // Anti-cycling still applies: it holds ON afterward rather than
  // re-evaluating from scratch every tick.
  c.OnSensorReading(Reading(58.0f), base + 25000);
  ControlDecision held = c.Tick(base + 25000);
  TEST_ASSERT_TRUE(held.relay_on);
}

void test_rise_rate_detection_disabled_by_default_does_not_trigger(void) {
  VentilationController c(DefaultTestConfig());  // disabled by default
  c.OnSensorReading(Reading(50.0f), 100000);
  c.Tick(100000);
  c.OnSensorReading(Reading(65.0f), 110000);  // fast rise, still under 70%
  ControlDecision d = c.Tick(110000);
  TEST_ASSERT_FALSE(d.relay_on);
}

void test_rise_rate_requires_minimum_sample_count(void) {
  ControllerConfig cfg = DefaultTestConfig();
  cfg.rise_rate_detection_enabled = true;
  cfg.rise_rate_min_valid_samples = 10;  // more samples than we will feed
  VentilationController c(cfg);
  c.OnSensorReading(Reading(50.0f), 100000);
  c.Tick(100000);
  c.OnSensorReading(Reading(65.0f), 110000);
  ControlDecision d = c.Tick(110000);
  TEST_ASSERT_FALSE(d.relay_on);  // not enough samples to trust the rate
}

int main(int argc, char** argv) {
  (void)argc;
  (void)argv;
  UNITY_BEGIN();

  RUN_TEST(test_startup_relay_is_off);
  RUN_TEST(test_startup_high_humidity_is_held_until_min_off_elapses);

  RUN_TEST(test_humidity_below_lower_threshold_keeps_fan_off);
  RUN_TEST(test_humidity_crossing_upper_threshold_turns_fan_on);
  RUN_TEST(test_humidity_in_band_preserves_state_while_off);
  RUN_TEST(test_humidity_in_band_preserves_state_while_on);
  RUN_TEST(test_humidity_crossing_lower_threshold_turns_fan_off);

  RUN_TEST(test_min_on_time_is_enforced);
  RUN_TEST(test_min_off_time_is_enforced);
  RUN_TEST(test_max_runtime_cutoff_forces_off);
  RUN_TEST(test_max_runtime_cutoff_overrides_manual_override);

  RUN_TEST(test_invalid_reading_is_rejected_and_does_not_switch);
  RUN_TEST(test_sensor_failure_beyond_limit_forces_safe_off_state);
  RUN_TEST(test_sensor_failure_can_be_configured_to_hold_last_state);

  RUN_TEST(test_fresh_mqtt_command_drives_automatic_mode);
  RUN_TEST(test_stale_mqtt_command_triggers_local_fallback);
  RUN_TEST(test_retained_command_stale_at_receipt_is_ignored);

  RUN_TEST(test_manual_override_on_forces_relay_on);
  RUN_TEST(test_manual_override_off_forces_relay_off);
  RUN_TEST(test_manual_override_expires_and_returns_to_automatic);
  RUN_TEST(test_override_auto_cancels_active_override_immediately);
  RUN_TEST(test_stale_command_is_rejected);

  RUN_TEST(test_rise_rate_detection_triggers_below_absolute_threshold);
  RUN_TEST(test_rise_rate_detection_disabled_by_default_does_not_trigger);
  RUN_TEST(test_rise_rate_requires_minimum_sample_count);

  return UNITY_END();
}

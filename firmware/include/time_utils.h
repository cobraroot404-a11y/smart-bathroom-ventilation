#pragma once

// Minimal UTC ISO-8601 <-> epoch-seconds helpers. Avoids depending on
// timegm() (not available in all ESP32 toolchains) by computing the
// UTC epoch manually. Requires NTP time sync (see wifi_manager.h) for
// the resulting timestamps to be meaningful; if the clock has not
// synced yet, epoch will be small and payload timestamps will reflect
// that - callers should treat freshness comparisons made before NTP
// sync as unreliable, which is why the firmware also tracks a
// millis()-based "received_at" fallback for staleness decisions rather
// than depending solely on wall-clock timestamps.

#include <stdint.h>
#include <stdio.h>
#include <time.h>

namespace vent {
namespace time_utils {

inline int64_t DaysFromCivil(int y, int m, int d) {
  y -= m <= 2;
  int64_t era = (y >= 0 ? y : y - 399) / 400;
  int yoe = static_cast<int>(y - era * 400);
  int doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
  int doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return era * 146097 + doe - 719468;
}

inline int64_t TmToEpochUtc(const struct tm& t) {
  int64_t days = DaysFromCivil(t.tm_year + 1900, t.tm_mon + 1, t.tm_mday);
  return days * 86400 + t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec;
}

inline void FormatIso8601(time_t epoch_seconds, char* out, size_t out_len) {
  struct tm tm_utc;
  gmtime_r(&epoch_seconds, &tm_utc);
  snprintf(out, out_len, "%04d-%02d-%02dT%02d:%02d:%02dZ",
           tm_utc.tm_year + 1900, tm_utc.tm_mon + 1, tm_utc.tm_mday,
           tm_utc.tm_hour, tm_utc.tm_min, tm_utc.tm_sec);
}

// Returns true and fills *epoch_seconds on success.
inline bool ParseIso8601(const char* str, int64_t* epoch_seconds) {
  struct tm t {};
  int year, month, day, hour, minute, second;
  if (sscanf(str, "%d-%d-%dT%d:%d:%dZ", &year, &month, &day, &hour, &minute,
             &second) != 6) {
    return false;
  }
  t.tm_year = year - 1900;
  t.tm_mon = month - 1;
  t.tm_mday = day;
  t.tm_hour = hour;
  t.tm_min = minute;
  t.tm_sec = second;
  *epoch_seconds = TmToEpochUtc(t);
  return true;
}

}  // namespace time_utils
}  // namespace vent

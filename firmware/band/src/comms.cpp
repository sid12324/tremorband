#include "comms.h"

#include "config.h"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>

namespace {

char g_queue[8][768];
volatile int g_head = 0;
volatile int g_tail = 0;
char g_commands[8][96];
volatile int g_cmd_head = 0;
volatile int g_cmd_tail = 0;
BandContext* g_bound = nullptr;

bool token_ok(const char* text) {
  if (text == nullptr || text[0] == '\0') {
    return false;
  }
  for (const char* cursor = text; *cursor != '\0'; ++cursor) {
    const unsigned char c = static_cast<unsigned char>(*cursor);
    const bool ok = (c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == '.' ||
                    c == '_' || c == ':' || c == '-';
    if (!ok) {
      return false;
    }
  }
  return true;
}

void lower_copy(const char* text, char* dest, int capacity) {
  int i = 0;
  for (; text[i] != '\0' && i + 1 < capacity; ++i) {
    char c = text[i];
    if (c >= 'A' && c <= 'Z') {
      c = static_cast<char>(c - 'A' + 'a');
    }
    dest[i] = c;
  }
  dest[i] = '\0';
}

bool extract_json_cmd(const char* text, char* dest, int capacity) {
  const char* key = std::strstr(text, "\"cmd\"");
  if (key == nullptr) {
    return false;
  }
  const char* colon = std::strchr(key, ':');
  if (colon == nullptr) {
    return false;
  }
  const char* open = std::strchr(colon, '"');
  if (open == nullptr) {
    return false;
  }
  const char* close = std::strchr(open + 1, '"');
  if (close == nullptr || close - (open + 1) >= capacity) {
    return false;
  }
  const int length = static_cast<int>(close - (open + 1));
  std::memcpy(dest, open + 1, static_cast<size_t>(length));
  dest[length] = '\0';
  return true;
}

HapticPattern pattern_from_name(const char* name) {
  if (std::strcmp(name, "prompt") == 0) {
    return HapticPattern::Prompt;
  }
  if (std::strcmp(name, "countdown") == 0) {
    return HapticPattern::Countdown;
  }
  if (std::strcmp(name, "start") == 0) {
    return HapticPattern::Start;
  }
  if (std::strcmp(name, "done") == 0) {
    return HapticPattern::Done;
  }
  if (std::strcmp(name, "alert") == 0) {
    return HapticPattern::Alert;
  }
  if (std::strcmp(name, "error") == 0) {
    return HapticPattern::Error;
  }
  if (std::strcmp(name, "connected") == 0) {
    return HapticPattern::Connected;
  }
  return HapticPattern::Alert;
}

bool mode_ok(const char* mode) {
  return std::strcmp(mode, "passive") == 0 || std::strcmp(mode, "test") == 0 || std::strcmp(mode, "raw") == 0 ||
         std::strcmp(mode, "ms_mode") == 0 || std::strcmp(mode, "forward") == 0;
}

}  // namespace

ParsedCommand parse_command(const char* text) {
  ParsedCommand command{};
  command.kind = CommandKind::None;
  command.test = TestType::None;
  command.pattern = HapticPattern::Alert;
  command.mode[0] = '\0';
  command.name[0] = '\0';
  command.value = 0.0;
  if (text == nullptr) {
    return command;
  }
  while (*text == ' ' || *text == '\t') {
    ++text;
  }
  char raw[96];
  if (text[0] == '{') {
    if (!extract_json_cmd(text, raw, static_cast<int>(sizeof(raw)))) {
      command.kind = CommandKind::Unknown;
      return command;
    }
  } else {
    std::snprintf(raw, sizeof(raw), "%s", text);
  }
  char line[96];
  lower_copy(raw, line, static_cast<int>(sizeof(line)));
  if (line[0] == '\0') {
    return command;
  }
  if (std::strcmp(line, "selftest") == 0) {
    command.kind = CommandKind::SelfTest;
    return command;
  }
  if (std::strcmp(line, "cancel_test") == 0) {
    command.kind = CommandKind::CancelTest;
    return command;
  }
  if (std::strcmp(line, "calibrate_still") == 0) {
    command.kind = CommandKind::CalibrateStill;
    return command;
  }
  if (std::strcmp(line, "identify") == 0) {
    command.kind = CommandKind::Identify;
    return command;
  }
  if (std::strcmp(line, "reboot") == 0) {
    command.kind = CommandKind::Reboot;
    return command;
  }
  if (std::strncmp(line, "run_test:", 9) == 0) {
    command.test = test_type_from_name(line + 9);
    command.kind = command.test == TestType::None ? CommandKind::Unknown : CommandKind::RunTest;
    return command;
  }
  if (std::strncmp(line, "vibrate:", 8) == 0) {
    command.pattern = pattern_from_name(line + 8);
    command.kind = CommandKind::Vibrate;
    return command;
  }
  if (std::strncmp(line, "set_mode:", 9) == 0) {
    if (!mode_ok(line + 9)) {
      command.kind = CommandKind::Unknown;
      return command;
    }
    std::memcpy(command.mode, line + 9, std::strlen(line + 9) + 1);
    command.kind = CommandKind::SetMode;
    return command;
  }
  if (std::strncmp(line, "set_threshold:", 14) == 0) {
    const char* name = line + 14;
    const char* colon = std::strrchr(name, ':');
    if (colon == nullptr || colon == name) {
      command.kind = CommandKind::Unknown;
      return command;
    }
    const int length = static_cast<int>(colon - name);
    if (length <= 0 || length >= static_cast<int>(sizeof(command.name))) {
      command.kind = CommandKind::Unknown;
      return command;
    }
    std::memcpy(command.name, name, static_cast<size_t>(length));
    command.name[length] = '\0';
    char* end = nullptr;
    command.value = std::strtod(colon + 1, &end);
    if (end == colon + 1 || !std::isfinite(command.value)) {
      command.kind = CommandKind::Unknown;
      return command;
    }
    command.kind = CommandKind::SetThreshold;
    return command;
  }
  command.kind = CommandKind::Unknown;
  return command;
}

bool apply_command(const ParsedCommand& command, BandContext& band, uint32_t now_ms) {
  switch (command.kind) {
    case CommandKind::RunTest:
      return band.test != nullptr && band.test->start(command.test, now_ms, *band.haptics);
    case CommandKind::CancelTest:
      if (band.test == nullptr) {
        return false;
      }
      band.test->cancel(now_ms, *band.haptics);
      return true;
    case CommandKind::Vibrate:
      if (band.haptics == nullptr) {
        return false;
      }
      band.haptics->play(command.pattern, now_ms);
      return true;
    case CommandKind::SetMode:
      std::snprintf(band.mode, sizeof(band.mode), "%s", command.mode);
      return true;
    case CommandKind::SetThreshold:
      if (std::strcmp(command.name, "still_acc_rms") == 0) {
        threshold_overrides().still_acc_rms = command.value;
        return true;
      }
      if (std::strcmp(command.name, "still_gyro_rms") == 0) {
        threshold_overrides().still_gyro_rms = command.value;
        return true;
      }
      if (std::strcmp(command.name, "tremor_sharpness") == 0) {
        threshold_overrides().tremor_sharpness = command.value;
        return true;
      }
      return false;
    case CommandKind::CalibrateStill:
      if (band.calibrator == nullptr) {
        return false;
      }
      band.calibrator->begin(now_ms);
      return true;
    case CommandKind::Identify:
      band.identify = true;
      if (band.haptics != nullptr) {
        band.haptics->play(HapticPattern::Alert, now_ms);
      }
      return true;
    case CommandKind::SelfTest:
      return true;
    case CommandKind::Reboot:
      band.reboot = true;
      return true;
    case CommandKind::None:
    case CommandKind::Unknown:
      break;
  }
  return false;
}

void wifi_schedule_init(WifiSchedule& schedule, uint32_t now_ms) {
  schedule.next_command_ms = now_ms;
  schedule.next_heartbeat_ms = now_ms;
  schedule.blocked_until_ms = now_ms;
  schedule.backoff_ms = 0;
  schedule.failures = 0;
}

bool wifi_command_due(const WifiSchedule& schedule, uint32_t now_ms) {
  return now_ms >= schedule.blocked_until_ms && now_ms >= schedule.next_command_ms;
}

bool wifi_heartbeat_due(const WifiSchedule& schedule, uint32_t now_ms) {
  return now_ms >= schedule.blocked_until_ms && now_ms >= schedule.next_heartbeat_ms;
}

void wifi_note_success(WifiSchedule& schedule, uint32_t now_ms, bool command) {
  schedule.failures = 0;
  schedule.backoff_ms = 0;
  schedule.blocked_until_ms = now_ms;
  if (command) {
    schedule.next_command_ms = now_ms + 2000;
  } else {
    schedule.next_heartbeat_ms = now_ms + 15000;
  }
}

void wifi_note_failure(WifiSchedule& schedule, uint32_t now_ms) {
  if (schedule.failures < 1000) {
    schedule.failures += 1;
  }
  schedule.backoff_ms = wifi_retry_delay_ms(schedule.failures);
  schedule.blocked_until_ms = now_ms + schedule.backoff_ms;
}

uint32_t wifi_retry_delay_ms(int failures) {
  if (failures <= 1) {
    return 1000;
  }
  if (failures >= 6) {
    return 30000;
  }
  return 1000u << (failures - 1);
}

int format_commands_path(char* dest, int capacity, const char* device_id) {
  if (dest == nullptr || !token_ok(device_id)) {
    return -1;
  }
  return std::snprintf(dest, static_cast<size_t>(capacity), "/api/device/%s/commands", device_id);
}

int format_heartbeat_path(char* dest, int capacity, const char* device_id) {
  if (dest == nullptr || !token_ok(device_id)) {
    return -1;
  }
  return std::snprintf(dest, static_cast<size_t>(capacity), "/api/device/%s/heartbeat", device_id);
}

int format_window_object(char* dest, int capacity, const char* ts_iso, const WindowFeatures& row,
                         const ActivityLabel& label, bool vibrating, const char* test_type) {
  if (dest == nullptr || capacity < 2 || ts_iso == nullptr || label.label == nullptr) {
    return -1;
  }
  char extra[80] = "";
  if (test_type != nullptr && token_ok(test_type)) {
    std::snprintf(extra, sizeof(extra), ",\"test_type\":\"%s\"", test_type);
  }
  const int wrote = std::snprintf(
      dest, static_cast<size_t>(capacity),
      "{\"ts\":\"%s\",\"peak_hz\":%.6f,\"band_power\":%.6f,\"rms\":%.6f,\"sharpness\":%.6f,"
      "\"amp_deg\":%.6f,\"disp_mm\":%.6f,\"log_amp\":%.6f,\"label\":\"%s\",\"p_tremor\":%.6f,"
      "\"vibrating\":%s%s}",
      ts_iso, row.gyro.peak_hz, row.gyro.band_power, row.gyro.rms, row.gyro.sharpness, row.amp_deg, row.disp_mm,
      row.log_amp, label.label, label.p_tremor, vibrating ? "true" : "false", extra);
  if (wrote < 0 || wrote >= capacity) {
    return -1;
  }
  return wrote;
}

int format_session_object(char* dest, int capacity, const char* ts_start, const char* ts_end,
                          const SessionSummary& summary) {
  if (dest == nullptr || ts_start == nullptr || ts_end == nullptr) {
    return -1;
  }
  const int wrote = std::snprintf(
      dest, static_cast<size_t>(capacity),
      "{\"ts_start\":\"%s\",\"ts_end\":\"%s\",\"test_type\":\"%s\",\"quality\":%.4f,\"is_synthetic\":false,"
      "\"summary\":{\"median_hz\":%.4f,\"median_log_amp\":%.4f,\"mean_p_tremor\":%.4f,\"tremor_pct\":%.2f,"
      "\"taps_per_s\":%.4f,\"tap_decrement\":%.4f,\"tap_interval_cv\":%.4f,\"intention_ratio\":%.4f,"
      "\"cadence_spm\":%.2f,\"stride_cv\":%.4f,\"asymmetry_pct\":%.2f}}",
      ts_start, ts_end, test_type_name(summary.type), summary.quality, summary.median_hz, summary.median_log_amp,
      summary.mean_p_tremor, summary.tremor_pct, summary.taps_per_s, summary.tap_decrement, summary.tap_interval_cv,
      summary.intention_ratio, summary.cadence_spm, summary.stride_cv, summary.asymmetry_pct);
  if (wrote < 0 || wrote >= capacity) {
    return -1;
  }
  return wrote;
}

int format_http_ingest(char* dest, int capacity, const char* device_id, const char* window_object,
                       const char* session_object) {
  if (dest == nullptr || !token_ok(device_id)) {
    return -1;
  }
  int wrote = -1;
  if (window_object != nullptr && session_object != nullptr) {
    wrote = std::snprintf(dest, static_cast<size_t>(capacity),
                          "{\"device_id\":\"%s\",\"windows\":[%s],\"sessions\":[%s]}", device_id, window_object,
                          session_object);
  } else if (window_object != nullptr) {
    wrote = std::snprintf(dest, static_cast<size_t>(capacity), "{\"device_id\":\"%s\",\"windows\":[%s]}", device_id,
                          window_object);
  } else if (session_object != nullptr) {
    wrote = std::snprintf(dest, static_cast<size_t>(capacity), "{\"device_id\":\"%s\",\"sessions\":[%s]}", device_id,
                          session_object);
  }
  if (wrote < 0 || wrote >= capacity) {
    return -1;
  }
  return wrote;
}

int format_heartbeat_body(char* dest, int capacity, float battery, float rssi, float uptime_s, float buffer_fill,
                          const char* fw_version, const char* mode) {
  if (dest == nullptr || fw_version == nullptr || mode == nullptr) {
    return -1;
  }
  const int wrote = std::snprintf(
      dest, static_cast<size_t>(capacity),
      "{\"fw_version\":\"%s\",\"mode\":\"%s\",\"battery\":%.1f,\"rssi\":%.0f,\"uptime_s\":%.1f,\"buffer_fill\":%.2f}",
      fw_version, mode, battery, rssi, uptime_s, buffer_fill);
  if (wrote < 0 || wrote >= capacity) {
    return -1;
  }
  return wrote;
}

int format_session_line(char* dest, int capacity, const char* device_id, const char* ts_start, const char* ts_end,
                        const SessionSummary& summary) {
  if (dest == nullptr || !token_ok(device_id) || ts_start == nullptr || ts_end == nullptr) {
    return -1;
  }
  const int wrote = std::snprintf(
      dest, static_cast<size_t>(capacity),
      "{\"type\":\"session\",\"device_id\":\"%s\",\"ts_start\":\"%s\",\"ts_end\":\"%s\",\"test_type\":\"%s\","
      "\"quality\":%.4f,\"summary\":{\"median_hz\":%.4f,\"median_log_amp\":%.4f,\"mean_p_tremor\":%.4f,"
      "\"tremor_pct\":%.2f,\"taps_per_s\":%.4f,\"tap_decrement\":%.4f,\"tap_interval_cv\":%.4f,"
      "\"intention_ratio\":%.4f,\"cadence_spm\":%.2f,\"stride_cv\":%.4f,\"asymmetry_pct\":%.2f}}",
      device_id, ts_start, ts_end, test_type_name(summary.type), summary.quality, summary.median_hz,
      summary.median_log_amp, summary.mean_p_tremor, summary.tremor_pct, summary.taps_per_s, summary.tap_decrement,
      summary.tap_interval_cv, summary.intention_ratio, summary.cadence_spm, summary.stride_cv,
      summary.asymmetry_pct);
  if (wrote < 0 || wrote >= capacity) {
    return -1;
  }
  return wrote;
}

void comms_bind(BandContext* band) { g_bound = band; }

BandContext* comms_band() { return g_bound; }

bool comms_enqueue_command(const char* command) {
  if (command == nullptr || command[0] == '\0') {
    return false;
  }
  const int next = (g_cmd_head + 1) % 8;
  if (next == g_cmd_tail) {
    g_cmd_tail = (g_cmd_tail + 1) % 8;
  }
  std::snprintf(g_commands[g_cmd_head], sizeof(g_commands[g_cmd_head]), "%s", command);
  g_cmd_head = next;
  return true;
}

bool comms_pop_command(char* dest, int capacity) {
  if (dest == nullptr || capacity < 2 || g_cmd_tail == g_cmd_head) {
    return false;
  }
  std::snprintf(dest, static_cast<size_t>(capacity), "%s", g_commands[g_cmd_tail]);
  g_cmd_tail = (g_cmd_tail + 1) % 8;
  return true;
}

bool comms_enqueue_line(const char* json) {
  if (json == nullptr) {
    return false;
  }
  const int next = (g_head + 1) % 8;
  if (next == g_tail) {
    g_tail = (g_tail + 1) % 8;
  }
  std::snprintf(g_queue[g_head], sizeof(g_queue[g_head]), "%s", json);
  g_head = next;
  return true;
}

bool comms_pop_line(char* dest, int capacity) {
  if (dest == nullptr || capacity < 2 || g_tail == g_head) {
    return false;
  }
  std::snprintf(dest, static_cast<size_t>(capacity), "%s", g_queue[g_tail]);
  g_tail = (g_tail + 1) % 8;
  return true;
}

bool wall_time_iso(char* dest, int capacity) {
  if (dest == nullptr || capacity < 21) {
    return false;
  }
  time_t now = std::time(nullptr);
  if (now < 0) {
    now = 0;
  }
  struct tm parts {};
  gmtime_r(&now, &parts);
  return std::strftime(dest, static_cast<size_t>(capacity), "%Y-%m-%dT%H:%M:%SZ", &parts) > 0;
}

float battery_percent(float volts) {
  if (volts <= 3.3f) {
    return 0.0f;
  }
  if (volts >= 4.2f) {
    return 100.0f;
  }
  return (volts - 3.3f) / 0.9f * 100.0f;
}

bool battery_is_low(float percent) { return percent >= 0.0f && percent < 15.0f; }

bool status_led_on(LinkState state, uint32_t now_ms) {
  if (state == LinkState::Online) {
    return true;
  }
  if (state == LinkState::Recording) {
    return ((now_ms / 100) % 2) == 0;
  }
  return ((now_ms / 500) % 2) == 0;
}

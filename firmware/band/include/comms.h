#pragma once

#include "haptics.h"
#include "window_features.h"
#include "tests.h"

#include <stdint.h>

// Wi-Fi HTTP schedule and the command language. The Arduino transport lives
// in comms_wifi.cpp. This file has no sockets, so the host test can run it.

enum class CommandKind {
  None,
  RunTest,
  CancelTest,
  Vibrate,
  SetMode,
  SetThreshold,
  CalibrateStill,
  Identify,
  SelfTest,
  Reboot,
  Unknown,
};

enum class LinkState { Offline, Online, Recording };

struct ParsedCommand {
  CommandKind kind;
  TestType test;
  HapticPattern pattern;
  char mode[16];
  char name[32];
  double value;
};

struct WifiSchedule {
  uint32_t next_command_ms;
  uint32_t next_heartbeat_ms;
  uint32_t blocked_until_ms;
  uint32_t backoff_ms;
  int failures;
};

struct BandContext {
  GuidedTest* test;
  Haptics* haptics;
  StillCalibrator* calibrator;
  char mode[16];
  bool identify;
  bool reboot;
};

ParsedCommand parse_command(const char* text);
bool apply_command(const ParsedCommand& command, BandContext& band, uint32_t now_ms);

void wifi_schedule_init(WifiSchedule& schedule, uint32_t now_ms);
bool wifi_command_due(const WifiSchedule& schedule, uint32_t now_ms);
bool wifi_heartbeat_due(const WifiSchedule& schedule, uint32_t now_ms);
void wifi_note_success(WifiSchedule& schedule, uint32_t now_ms, bool command);
void wifi_note_failure(WifiSchedule& schedule, uint32_t now_ms);
uint32_t wifi_retry_delay_ms(int failures);

int format_commands_path(char* dest, int capacity, const char* device_id);
int format_heartbeat_path(char* dest, int capacity, const char* device_id);
int format_window_object(char* dest, int capacity, const char* ts_iso, const WindowFeatures& row,
                         const ActivityLabel& label, bool vibrating, const char* test_type);
int format_session_object(char* dest, int capacity, const char* ts_start, const char* ts_end,
                          const SessionSummary& summary);
int format_http_ingest(char* dest, int capacity, const char* device_id, const char* window_object,
                       const char* session_object);
int format_heartbeat_body(char* dest, int capacity, float battery, float rssi, float uptime_s, float buffer_fill,
                          const char* fw_version, const char* mode);
int format_session_line(char* dest, int capacity, const char* device_id, const char* ts_start, const char* ts_end,
                        const SessionSummary& summary);

bool comms_enqueue_line(const char* json);
bool comms_pop_line(char* dest, int capacity);

bool wall_time_iso(char* dest, int capacity);
float battery_percent(float volts);
bool battery_is_low(float percent);
bool status_led_on(LinkState state, uint32_t now_ms);

void comms_bind(BandContext* band);
BandContext* comms_band();
bool comms_enqueue_command(const char* command);
bool comms_pop_command(char* dest, int capacity);

void start_wifi_transport();
LinkState current_link_state();

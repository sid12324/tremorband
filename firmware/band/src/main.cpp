#include "comms.h"
#include "config.h"
#include "haptics.h"
#include "imu.h"
#include "signal.h"
#include "tests.h"

#include <Arduino.h>
#include <esp_timer.h>

#include <cstdio>
#include <cmath>

static volatile bool g_sample_due = false;
static ImuDriver* g_imu = nullptr;
static char g_cmd[96];
static size_t g_cmd_len = 0;
static uint32_t g_read_failures = 0;
static Haptics g_haptics;
static GuidedTest g_test;
static ButtonTracker g_button;
static StillCalibrator g_calibrator;
static BandContext g_band{&g_test, &g_haptics, &g_calibrator, "passive", false, false};

static void on_sample_timer(void* /*arg*/) { g_sample_due = true; }

static void set_led(bool on) { digitalWrite(TB_LED_PIN, on ? LOW : HIGH); }

static void write_motor(int pwm) { analogWrite(TB_MOTOR_PIN, pwm); }

static void print_window(long long ts_us, const WindowFeatures& row, const ActivityLabel& label, bool vibrating,
                         const char* test_type) {
  char line[640];
  if (format_window_json(line, sizeof(line), TB_DEVICE_ID, ts_us, row, label, vibrating, test_type) > 0) {
    Serial.println(line);
  }
  char stamp[32];
  if (!wall_time_iso(stamp, static_cast<int>(sizeof(stamp)))) {
    std::snprintf(stamp, sizeof(stamp), "1970-01-01T00:00:00Z");
  }
  char object[640];
  char body[900];
  if (format_window_object(object, sizeof(object), stamp, row, label, vibrating, test_type) > 0 &&
      format_http_ingest(body, sizeof(body), TB_DEVICE_ID, object, nullptr) > 0) {
    comms_enqueue_line(body);
  }
}

static void dispatch(const char* text, uint32_t now_ms) {
  const ParsedCommand command = parse_command(text);
  if (command.kind == CommandKind::SelfTest) {
    const WindowFeatures row = run_selftest();
    const ActivityLabel label = rule_label(row);
    Serial.printf("selftest acc_peak_hz=%.6f gyro_peak_hz=%.6f label=%s\n", row.acc.peak_hz, row.gyro.peak_hz,
                  label.label);
    print_window(0, row, label, false, nullptr);
    return;
  }
  if (!apply_command(command, g_band, now_ms)) {
    Serial.printf("{\"type\":\"log\",\"device_id\":\"%s\",\"message\":\"unknown command\"}\n", TB_DEVICE_ID);
    return;
  }
  if (command.kind == CommandKind::Reboot && g_band.reboot) {
    ESP.restart();
  }
}

static void poll_serial(uint32_t now_ms) {
  while (Serial.available() > 0) {
    const char c = static_cast<char>(Serial.read());
    if (c == '\n' || c == '\r') {
      if (g_cmd_len > 0) {
        g_cmd[g_cmd_len] = '\0';
        dispatch(g_cmd, now_ms);
        g_cmd_len = 0;
      }
      continue;
    }
    if (g_cmd_len + 1 < sizeof(g_cmd)) {
      g_cmd[g_cmd_len++] = c;
    }
  }
}

static void sample_task(void* /*arg*/) {
  WindowPipeline pipeline;
  uint32_t windows = 0;
  while (true) {
    const uint32_t now_ms = millis();
    poll_serial(now_ms);
    char queued[96];
    while (comms_pop_command(queued, static_cast<int>(sizeof(queued)))) {
      dispatch(queued, now_ms);
    }
    g_haptics.update(now_ms);
    const bool pressed = digitalRead(TB_BUTTON_PIN) == LOW;
    const PressKind press = g_button.update(pressed, now_ms);
    if (press == PressKind::Long) {
      g_test.cycle_and_start(now_ms, g_haptics);
    } else if (press == PressKind::Double) {
      g_test.cancel(now_ms, g_haptics);
    }
    g_test.update(now_ms, g_haptics);
    if (g_calibrator.finished(now_ms)) {
      threshold_overrides().still_acc_rms = g_calibrator.suggested_acc_rms();
      g_calibrator.clear();
    }
    write_motor(g_haptics.pwm());
    if (!g_sample_due) {
      vTaskDelay(pdMS_TO_TICKS(1));
      continue;
    }
    g_sample_due = false;
    ImuSample sample{};
    if (g_imu == nullptr || !g_imu->read(sample)) {
      ++g_read_failures;
      if (g_read_failures == 1 || (g_read_failures % 104) == 0) {
        Serial.printf("{\"type\":\"log\",\"device_id\":\"%s\",\"message\":\"imu read failed\",\"count\":%lu}\n",
                      TB_DEVICE_ID, static_cast<unsigned long>(g_read_failures));
      }
      if (g_read_failures >= 104 && g_imu != nullptr) {
        g_imu->begin();
        g_read_failures = 0;
      }
      continue;
    }
    sample.t_us = esp_timer_get_time();
    const double gyro_mag =
        sqrt(static_cast<double>(sample.gx) * sample.gx + static_cast<double>(sample.gy) * sample.gy +
             static_cast<double>(sample.gz) * sample.gz);
    g_test.on_sample(gyro_mag, now_ms);
    WindowFeatures row;
    ActivityLabel label{"still", 0.0};
    bool window_vibrating = false;
    if (!pipeline.push(sample.ax, sample.ay, sample.az, sample.gx, sample.gy, sample.gz, row, label,
                       g_haptics.vibrating(), window_vibrating)) {
      continue;
    }
    if (g_calibrator.active()) {
      g_calibrator.add(row.acc.rms);
    }
    const char* test_type = g_test.phase() == TestPhase::Record ? test_type_name(g_test.type()) : nullptr;
    g_test.on_window(row, label, window_vibrating);
    print_window(sample.t_us, row, label, window_vibrating, test_type);
    SessionSummary summary{};
    if (g_test.take_upload(summary)) {
      char stamp[32];
      if (!wall_time_iso(stamp, static_cast<int>(sizeof(stamp)))) {
        std::snprintf(stamp, sizeof(stamp), "1970-01-01T00:00:00Z");
      }
      char line[700];
      if (format_session_line(line, sizeof(line), TB_DEVICE_ID, stamp, stamp, summary) > 0) {
        Serial.println(line);
      }
      char object[640];
      char body[900];
      if (format_session_object(object, sizeof(object), stamp, stamp, summary) > 0 &&
          format_http_ingest(body, sizeof(body), TB_DEVICE_ID, nullptr, object) > 0) {
        comms_enqueue_line(body);
      }
    }
    ++windows;
    if (windows % 12 == 0) {
      Serial.printf("{\"type\":\"heartbeat\",\"device_id\":\"%s\",\"fw_version\":\"%s\",\"mode\":\"%s\"}\n",
                    TB_DEVICE_ID, TB_FW_VERSION, g_band.mode);
    }
  }
}

void setup() {
  Serial.begin(TB_SERIAL_BAUD);
  pinMode(TB_LED_PIN, OUTPUT);
  pinMode(TB_BUTTON_PIN, INPUT_PULLUP);
  pinMode(TB_MOTOR_PIN, OUTPUT);
  set_led(false);
  comms_bind(&g_band);
  g_haptics.set_intensity(0.7f);
  g_imu = make_imu();
  while (g_imu == nullptr || !g_imu->begin()) {
    Serial.printf("{\"type\":\"log\",\"device_id\":\"%s\",\"message\":\"imu begin failed\"}\n", TB_DEVICE_ID);
    set_led(true);
    delay(200);
    set_led(false);
    delay(800);
  }
  set_led(true);
  Serial.printf("{\"type\":\"log\",\"device_id\":\"%s\",\"message\":\"imu %s fs=%.1f\"}\n", TB_DEVICE_ID, g_imu->name(),
                static_cast<double>(TB_FS_HZ));
  Serial.printf("{\"type\":\"heartbeat\",\"device_id\":\"%s\",\"fw_version\":\"%s\",\"mode\":\"serial\"}\n",
                TB_DEVICE_ID, TB_FW_VERSION);
  start_wifi_transport();

  const uint64_t period_us = static_cast<uint64_t>(1000000.0f / TB_FS_HZ + 0.5f);
  esp_timer_handle_t timer = nullptr;
  esp_timer_create_args_t args{};
  args.callback = &on_sample_timer;
  args.name = "tb_sample";
  esp_timer_create(&args, &timer);
  esp_timer_start_periodic(timer, period_us);
  xTaskCreatePinnedToCore(sample_task, "imu", 12288, nullptr, 5, nullptr, 1);
}

void loop() {
  const bool recording = g_test.phase() == TestPhase::Record;
  const LinkState link = recording ? LinkState::Recording : current_link_state();
  set_led(status_led_on(link, millis()));
  vTaskDelay(pdMS_TO_TICKS(50));
}

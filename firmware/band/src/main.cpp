#include "config.h"
#include "imu.h"
#include "signal.h"

#include <Arduino.h>
#include <esp_timer.h>

static volatile bool g_sample_due = false;
static ImuDriver* g_imu = nullptr;
static char g_cmd[32];
static size_t g_cmd_len = 0;
static uint32_t g_read_failures = 0;

static void on_sample_timer(void* /*arg*/) { g_sample_due = true; }

static bool command_is_selftest(const char* text) {
  const char expected[] = "selftest";
  for (size_t i = 0; i < sizeof(expected); ++i) {
    char c = text[i];
    if (c >= 'A' && c <= 'Z') {
      c = static_cast<char>(c - 'A' + 'a');
    }
    if (c != expected[i]) {
      return false;
    }
  }
  return true;
}

static void handle_command(const char* text) {
  if (command_is_selftest(text)) {
    const WindowFeatures row = run_selftest();
    Serial.printf("selftest acc_peak_hz=%.6f gyro_peak_hz=%.6f\n", row.acc.peak_hz, row.gyro.peak_hz);
    return;
  }
  Serial.printf("unknown command\n");
}

static void poll_serial() {
  while (Serial.available() > 0) {
    const char c = static_cast<char>(Serial.read());
    if (c == '\n' || c == '\r') {
      if (g_cmd_len > 0) {
        g_cmd[g_cmd_len] = '\0';
        handle_command(g_cmd);
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
  while (true) {
    poll_serial();
    if (!g_sample_due) {
      vTaskDelay(pdMS_TO_TICKS(1));
      continue;
    }
    g_sample_due = false;
    ImuSample sample{};
    if (g_imu == nullptr || !g_imu->read(sample)) {
      ++g_read_failures;
      if (g_read_failures == 1 || (g_read_failures % 104) == 0) {
        Serial.printf("imu read failed count=%lu\n", static_cast<unsigned long>(g_read_failures));
      }
      continue;
    }
    sample.t_us = esp_timer_get_time();
    Serial.printf("%lld,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f\n", static_cast<long long>(sample.t_us), sample.ax,
                  sample.ay, sample.az, sample.gx, sample.gy, sample.gz);
  }
}

static void set_led(bool on) {
  digitalWrite(TB_LED_PIN, on ? LOW : HIGH);
}

void setup() {
  Serial.begin(TB_SERIAL_BAUD);
  pinMode(TB_LED_PIN, OUTPUT);
  set_led(false);
  g_imu = make_imu();
  while (g_imu == nullptr || !g_imu->begin()) {
    Serial.printf("imu begin failed\n");
    set_led(true);
    delay(200);
    set_led(false);
    delay(800);
  }
  set_led(true);
  Serial.printf("imu %s fs=%.1f\n", g_imu->name(), static_cast<double>(TB_FS_HZ));
  Serial.printf("ts_us,ax,ay,az,gx,gy,gz\n");

  const uint64_t period_us = static_cast<uint64_t>(1000000.0f / TB_FS_HZ + 0.5f);
  esp_timer_handle_t timer = nullptr;
  esp_timer_create_args_t args{};
  args.callback = &on_sample_timer;
  args.name = "tb_sample";
  esp_timer_create(&args, &timer);
  esp_timer_start_periodic(timer, period_us);
  xTaskCreatePinnedToCore(sample_task, "imu", 8192, nullptr, 5, nullptr, 1);
}

void loop() { vTaskDelay(pdMS_TO_TICKS(1000)); }

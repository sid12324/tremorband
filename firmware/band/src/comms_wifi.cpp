#include "comms.h"

#include "config.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
#define TB_WIFI_SSID ""
#define TB_WIFI_PASSWORD ""
#endif

#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <cstdio>
#include <cstring>
#include <esp_mac.h>
#include <time.h>

namespace {

LinkState g_link = LinkState::Offline;
const char* g_device_id = TB_DEVICE_ID;
char g_mac_id[24] = TB_DEVICE_ID;

void refresh_device_id() {
  uint8_t mac[6] = {};
  if (esp_read_mac(mac, ESP_MAC_WIFI_STA) != ESP_OK) {
    g_device_id = TB_DEVICE_ID;
    return;
  }
  std::snprintf(g_mac_id, sizeof(g_mac_id), "band-%02x%02x%02x%02x%02x%02x", mac[0], mac[1], mac[2], mac[3], mac[4],
                mac[5]);
  g_device_id = g_mac_id;
}

bool post_json(const char* path, const char* body) {
  HTTPClient http;
  const String url = String(TB_SERVER_URL) + path;
  if (!http.begin(url)) {
    return false;
  }
  http.addHeader("Content-Type", "application/json");
  const int status = http.POST(String(body));
  http.end();
  return status >= 200 && status < 300;
}

bool poll_commands() {
  char path[80];
  if (format_commands_path(path, static_cast<int>(sizeof(path)), g_device_id) < 0) {
    return false;
  }
  HTTPClient http;
  const String url = String(TB_SERVER_URL) + path;
  if (!http.begin(url)) {
    return false;
  }
  const int status = http.GET();
  if (status != 200) {
    http.end();
    return false;
  }
  JsonDocument doc;
  const DeserializationError error = deserializeJson(doc, http.getString());
  http.end();
  if (error) {
    return false;
  }
  for (JsonObject item : doc.as<JsonArray>()) {
    const char* cmd = item["cmd"] | "";
    if (cmd[0] != '\0') {
      comms_enqueue_command(cmd);
    }
  }
  return true;
}

float read_battery_percent() {
  const int raw = analogRead(TB_BATTERY_PIN);
  const float volts = (static_cast<float>(raw) / 4095.0f) * 3.3f * 2.0f;
  return battery_percent(volts);
}

}  // namespace

LinkState current_link_state() { return g_link; }

void start_wifi_transport() {
  if (TB_WIFI_SSID[0] == '\0') {
    return;
  }
  refresh_device_id();
  xTaskCreatePinnedToCore(
      [](void* /*arg*/) {
        WifiSchedule schedule{};
        wifi_schedule_init(schedule, millis());
        configTime(0, 0, "pool.ntp.org");
        int failures = 0;
        bool announced = false;
        for (;;) {
          if (WiFi.status() != WL_CONNECTED) {
            g_link = LinkState::Offline;
            announced = false;
            if (millis() >= schedule.blocked_until_ms) {
              WiFi.mode(WIFI_STA);
              WiFi.begin(TB_WIFI_SSID, TB_WIFI_PASSWORD);
              failures += 1;
              schedule.blocked_until_ms = millis() + wifi_retry_delay_ms(failures);
            }
            vTaskDelay(pdMS_TO_TICKS(200));
            continue;
          }
          g_link = LinkState::Online;
          if (!announced) {
            announced = true;
            failures = 0;
            BandContext* band = comms_band();
            if (band != nullptr && band->haptics != nullptr) {
              band->haptics->request(HapticPattern::Connected);
            }
          }
          if (wifi_command_due(schedule, millis())) {
            if (poll_commands()) {
              wifi_note_success(schedule, millis(), true);
            } else {
              wifi_note_failure(schedule, millis());
            }
          }
          if (wifi_heartbeat_due(schedule, millis())) {
            char path[80];
            char body[192];
            const float battery = read_battery_percent();
            format_heartbeat_path(path, static_cast<int>(sizeof(path)), g_device_id);
            format_heartbeat_body(body, static_cast<int>(sizeof(body)), battery, static_cast<float>(WiFi.RSSI()),
                                  static_cast<float>(millis()) / 1000.0f, 0.0f, TB_FW_VERSION, "wifi");
            if (post_json(path, body)) {
              wifi_note_success(schedule, millis(), false);
              BandContext* band = comms_band();
              if (battery_is_low(battery) && band != nullptr && band->haptics != nullptr) {
                band->haptics->request(HapticPattern::Alert);
              }
            } else {
              wifi_note_failure(schedule, millis());
            }
          }
          char line[768];
          if (comms_pop_line(line, static_cast<int>(sizeof(line)))) {
            if (!post_json("/api/ingest", line)) {
              wifi_note_failure(schedule, millis());
            }
          }
          vTaskDelay(pdMS_TO_TICKS(100));
        }
      },
      "wifi", 12288, nullptr, 3, nullptr, 0);
}

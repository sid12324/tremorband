// Calibration rig. Servo signal on TB_RIG_SERVO_PIN, common ground with the
// controller, and a separate 5 V supply for the SG90. theta = center + A*sin(2*pi*f*t).
// Serial commands at 115200: "f <hz>", "a <deg>", "stop", "sweep".

#include "rig_control.h"

#include <Servo.h>

#ifndef TB_RIG_SERVO_PIN
#define TB_RIG_SERVO_PIN 9
#endif

#ifndef TB_RIG_UPDATE_US
#define TB_RIG_UPDATE_US 20000
#endif

static Servo g_servo;
static RigController g_rig;
static uint32_t g_last_us = 0;
static char g_line[64];
static size_t g_line_len = 0;

static void handle_line(const char* text) {
  const RigCommand command = parse_rig_command(text);
  const uint32_t now_us = micros();
  const uint32_t now_ms = millis();
  if (command.kind == RigCommand::Frequency) {
    g_rig.set_frequency(command.value, now_us);
  } else if (command.kind == RigCommand::Amplitude) {
    g_rig.set_amplitude(command.value);
  } else if (command.kind == RigCommand::Stop) {
    g_rig.stop();
    g_servo.write(static_cast<int>(RigController::kCenterDeg));
  } else if (command.kind == RigCommand::Sweep) {
    g_rig.start_sweep(now_ms, now_us);
  } else if (command.kind == RigCommand::Unknown) {
    Serial.println("{\"type\":\"log\",\"message\":\"unknown command\"}");
    return;
  } else {
    return;
  }
  if (g_rig.take_warning()) {
    char warning[180];
    if (format_speed_warning(warning, static_cast<int>(sizeof(warning)), g_rig.status()) > 0) {
      Serial.println(warning);
    }
  }
}

static void poll_serial() {
  while (Serial.available() > 0) {
    const char c = static_cast<char>(Serial.read());
    if (c == '\n' || c == '\r') {
      if (g_line_len > 0) {
        g_line[g_line_len] = '\0';
        handle_line(g_line);
        g_line_len = 0;
      }
      continue;
    }
    if (g_line_len + 1 < sizeof(g_line)) {
      g_line[g_line_len++] = c;
    }
  }
}

void setup() {
  Serial.begin(115200);
  g_servo.attach(TB_RIG_SERVO_PIN);
  g_servo.write(static_cast<int>(RigController::kCenterDeg));
  g_last_us = micros();
  Serial.println("{\"type\":\"log\",\"message\":\"rig ready\"}");
}

void loop() {
  poll_serial();
  const uint32_t now_us = micros();
  if (now_us - g_last_us < TB_RIG_UPDATE_US) {
    return;
  }
  g_last_us = now_us;
  RigOutput output{};
  const bool cycle =
      g_rig.update(now_us, millis(), static_cast<float>(TB_RIG_UPDATE_US) / 1000000.0f, output);
  g_servo.write(static_cast<int>(output.theta_deg + 0.5f));
  if (g_rig.take_warning()) {
    char warning[180];
    if (format_speed_warning(warning, static_cast<int>(sizeof(warning)), g_rig.status()) > 0) {
      Serial.println(warning);
    }
  }
  if (cycle) {
    char line[160];
    const RigStatus& status = g_rig.status();
    if (format_rig_json(line, static_cast<int>(sizeof(line)), status.set_hz, output.measured_hz, status.amp_deg) > 0) {
      Serial.println(line);
    }
  }
}

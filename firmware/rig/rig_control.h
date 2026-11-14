#pragma once

#include <stdint.h>

// SG90 sine drive. Peak speed is 2*pi*f*A in degrees per second.
// Above the speed limit the amplitude is reduced. This is a motion
// setpoint, not a clinical measurement.

struct RigStatus {
  float set_hz;
  float requested_amp_deg;
  float amp_deg;
  float peak_deg_s;
  bool limited;
  bool running;
  bool sweeping;
};

struct RigOutput {
  float theta_deg;
  float measured_hz;
  bool cycle_done;
};

struct RigCommand {
  enum Kind { None, Frequency, Amplitude, Stop, Sweep, Unknown } kind;
  float value;
};

class RigController {
 public:
  static constexpr float kCenterDeg = 90.0f;
  static constexpr float kSpeedLimitDps = 600.0f;
  static constexpr float kMinDeg = 0.0f;
  static constexpr float kMaxDeg = 180.0f;
  static constexpr uint32_t kSweepStepMs = 15000;

  RigController();

  void set_frequency(float hz, uint32_t now_us);
  void set_amplitude(float deg);
  void stop();
  void start_sweep(uint32_t now_ms, uint32_t now_us);
  bool update(uint32_t now_us, uint32_t now_ms, float nominal_dt_s, RigOutput& out);
  bool take_warning();
  const RigStatus& status() const;

 private:
  void apply_limit();
  void begin_motion(uint32_t now_us);

  RigStatus status_;
  double phase_;
  uint32_t cycle_start_us_;
  bool cycle_open_;
  bool warning_pending_;
  int sweep_index_;
  uint32_t sweep_started_ms_;
};

RigCommand parse_rig_command(const char* text);
float rig_angle(float center_deg, float amp_deg, double phase);
int format_rig_json(char* dest, int capacity, float set_hz, float measured_hz, float amp_deg);
int format_speed_warning(char* dest, int capacity, const RigStatus& status);

#include "rig_control.h"

#include <cmath>
#include <cstdio>
#include <cstring>

namespace {

constexpr double kPi = 3.141592653589793;
constexpr float kSweepHz[] = {3.0f, 4.0f, 5.0f, 6.0f, 7.0f, 8.0f};

float clampf(float value, float low, float high) {
  if (value < low) {
    return low;
  }
  if (value > high) {
    return high;
  }
  return value;
}

}  // namespace

RigController::RigController()
    : phase_(0.0),
      cycle_start_us_(0),
      cycle_open_(false),
      warning_pending_(false),
      sweep_index_(0),
      sweep_started_ms_(0) {
  status_.set_hz = 0.0f;
  status_.requested_amp_deg = 10.0f;
  status_.amp_deg = 10.0f;
  status_.peak_deg_s = 0.0f;
  status_.limited = false;
  status_.running = false;
  status_.sweeping = false;
}

void RigController::apply_limit() {
  const float peak = static_cast<float>(2.0 * kPi * status_.set_hz * status_.requested_amp_deg);
  status_.peak_deg_s = peak;
  if (status_.set_hz > 0.0f && peak > kSpeedLimitDps) {
    status_.amp_deg = kSpeedLimitDps / static_cast<float>(2.0 * kPi * status_.set_hz);
    status_.limited = true;
    warning_pending_ = true;
    return;
  }
  status_.amp_deg = status_.requested_amp_deg;
  status_.limited = false;
  warning_pending_ = false;
}

void RigController::begin_motion(uint32_t now_us) {
  phase_ = 0.0;
  cycle_start_us_ = now_us;
  cycle_open_ = true;
}

void RigController::set_frequency(float hz, uint32_t now_us) {
  if (hz < 0.0f) {
    hz = 0.0f;
  }
  status_.sweeping = false;
  status_.set_hz = hz;
  status_.running = hz > 0.0f;
  apply_limit();
  if (status_.running) {
    begin_motion(now_us);
  }
}

void RigController::set_amplitude(float deg) {
  if (deg < 0.0f) {
    deg = 0.0f;
  }
  status_.requested_amp_deg = deg;
  apply_limit();
}

void RigController::stop() {
  status_.running = false;
  status_.sweeping = false;
  status_.set_hz = 0.0f;
  phase_ = 0.0;
  cycle_open_ = false;
  apply_limit();
}

void RigController::start_sweep(uint32_t now_ms, uint32_t now_us) {
  if (status_.requested_amp_deg <= 0.0f) {
    status_.requested_amp_deg = 10.0f;
  }
  sweep_index_ = 0;
  sweep_started_ms_ = now_ms;
  status_.sweeping = true;
  status_.set_hz = kSweepHz[0];
  status_.running = true;
  apply_limit();
  begin_motion(now_us);
}

bool RigController::update(uint32_t now_us, uint32_t now_ms, float nominal_dt_s, RigOutput& out) {
  if (status_.sweeping && now_ms - sweep_started_ms_ >= kSweepStepMs) {
    sweep_index_ += 1;
    sweep_started_ms_ = now_ms;
    if (sweep_index_ >= static_cast<int>(sizeof(kSweepHz) / sizeof(kSweepHz[0]))) {
      stop();
    } else {
      status_.set_hz = kSweepHz[sweep_index_];
      apply_limit();
      begin_motion(now_us);
    }
  }
  out.measured_hz = status_.set_hz;
  out.cycle_done = false;
  if (!status_.running || status_.set_hz <= 0.0f || nominal_dt_s <= 0.0f) {
    out.theta_deg = kCenterDeg;
    return false;
  }
  if (!cycle_open_) {
    begin_motion(now_us);
  }
  phase_ += 2.0 * kPi * static_cast<double>(status_.set_hz) * static_cast<double>(nominal_dt_s);
  if (phase_ + 1e-6 >= 2.0 * kPi) {
    const double cycles = phase_ / (2.0 * kPi);
    const uint32_t elapsed_us = now_us - cycle_start_us_;
    if (elapsed_us > 0) {
      out.measured_hz = static_cast<float>(cycles / (static_cast<double>(elapsed_us) / 1000000.0));
    }
    phase_ = std::fmod(phase_, 2.0 * kPi);
    cycle_start_us_ = now_us;
    out.cycle_done = true;
  }
  const float theta = rig_angle(kCenterDeg, status_.amp_deg, phase_);
  out.theta_deg = clampf(theta, kMinDeg, kMaxDeg);
  return out.cycle_done;
}

bool RigController::take_warning() {
  if (!warning_pending_) {
    return false;
  }
  warning_pending_ = false;
  return status_.limited;
}

const RigStatus& RigController::status() const { return status_; }

RigCommand parse_rig_command(const char* text) {
  RigCommand command{RigCommand::None, 0.0f};
  if (text == nullptr) {
    return command;
  }
  while (*text == ' ' || *text == '\t') {
    ++text;
  }
  char line[64];
  int length = 0;
  for (; text[length] != '\0' && length + 1 < static_cast<int>(sizeof(line)); ++length) {
    char c = text[length];
    if (c >= 'A' && c <= 'Z') {
      c = static_cast<char>(c - 'A' + 'a');
    }
    line[length] = c;
  }
  line[length] = '\0';
  if (std::strcmp(line, "stop") == 0) {
    command.kind = RigCommand::Stop;
    return command;
  }
  if (std::strcmp(line, "sweep") == 0) {
    command.kind = RigCommand::Sweep;
    return command;
  }
  char name[16] = {};
  float value = 0.0f;
  if (std::sscanf(line, "%15s %f", name, &value) != 2) {
    command.kind = line[0] == '\0' ? RigCommand::None : RigCommand::Unknown;
    return command;
  }
  if (std::strcmp(name, "f") == 0) {
    command.kind = RigCommand::Frequency;
    command.value = value;
    return command;
  }
  if (std::strcmp(name, "a") == 0) {
    command.kind = RigCommand::Amplitude;
    command.value = value;
    return command;
  }
  command.kind = RigCommand::Unknown;
  return command;
}

float rig_angle(float center_deg, float amp_deg, double phase) {
  return center_deg + amp_deg * static_cast<float>(std::sin(phase));
}

int format_rig_json(char* dest, int capacity, float set_hz, float measured_hz, float amp_deg) {
  if (dest == nullptr || capacity < 2) {
    return -1;
  }
  const int wrote = std::snprintf(dest, static_cast<size_t>(capacity),
                                  "{\"type\":\"rig\",\"set_hz\":%.4f,\"measured_hz\":%.4f,\"amp_deg\":%.3f}",
                                  set_hz, measured_hz, amp_deg);
  if (wrote < 0 || wrote >= capacity) {
    return -1;
  }
  return wrote;
}

int format_speed_warning(char* dest, int capacity, const RigStatus& status) {
  if (dest == nullptr || capacity < 2) {
    return -1;
  }
  const int wrote = std::snprintf(
      dest, static_cast<size_t>(capacity),
      "{\"type\":\"log\",\"message\":\"SG90 speed limit\",\"set_hz\":%.4f,\"requested_amp_deg\":%.3f,"
      "\"amp_deg\":%.3f,\"peak_deg_s\":%.1f}",
      status.set_hz, status.requested_amp_deg, status.amp_deg, status.peak_deg_s);
  if (wrote < 0 || wrote >= capacity) {
    return -1;
  }
  return wrote;
}

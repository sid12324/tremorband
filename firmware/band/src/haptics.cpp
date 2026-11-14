#include "haptics.h"

namespace {

const Haptics::Phase kPrompt[] = {{80, 1}, {80, 0}, {80, 1}, {80, 0}};
const Haptics::Phase kCountdown[] = {{40, 1}, {1000, 0}, {40, 1}, {1000, 0}, {40, 1}};
const Haptics::Phase kStart[] = {{200, 1}};
const Haptics::Phase kDone[] = {{500, 1}};
const Haptics::Phase kAlert[] = {{60, 1}, {60, 0}, {60, 1}, {60, 0}, {60, 1}};
const Haptics::Phase kError[] = {{400, 1}, {120, 0}, {80, 1}, {120, 0}, {400, 1}};
const Haptics::Phase kConnected[] = {{50, 1}};

struct Script {
  const Haptics::Phase* phases;
  int count;
  float scale;
};

Script script_for(HapticPattern pattern) {
  switch (pattern) {
    case HapticPattern::Prompt:
      return {kPrompt, 4, 1.0f};
    case HapticPattern::Countdown:
      return {kCountdown, 5, 1.0f};
    case HapticPattern::Start:
      return {kStart, 1, 1.0f};
    case HapticPattern::Done:
      return {kDone, 1, 1.0f};
    case HapticPattern::Alert:
      return {kAlert, 5, 1.0f};
    case HapticPattern::Error:
      return {kError, 5, 1.0f};
    case HapticPattern::Connected:
      return {kConnected, 1, 0.35f};
  }
  return {kPrompt, 4, 1.0f};
}

}  // namespace

Haptics::Haptics()
    : script_(nullptr),
      script_len_(0),
      index_(0),
      phase_started_ms_(0),
      intensity_(0.7f),
      scale_(1.0f),
      pwm_(0),
      running_(false),
      pending_(-1) {}

void Haptics::set_intensity(float intensity) {
  if (intensity < 0.0f) {
    intensity = 0.0f;
  }
  if (intensity > 1.0f) {
    intensity = 1.0f;
  }
  intensity_ = intensity;
}

void Haptics::begin(const Phase* phases, int count, uint32_t now_ms, float scale) {
  script_ = phases;
  script_len_ = count;
  index_ = 0;
  phase_started_ms_ = now_ms;
  scale_ = scale;
  running_ = count > 0;
  pwm_ = 0;
  update(now_ms);
}

void Haptics::play(HapticPattern pattern, uint32_t now_ms) {
  const Script script = script_for(pattern);
  begin(script.phases, script.count, now_ms, script.scale);
}

void Haptics::play_pulses(int count, uint16_t on_ms, uint16_t off_ms, uint32_t now_ms) {
  if (count < 1) {
    count = 1;
  }
  if (count > 5) {
    count = 5;
  }
  int written = 0;
  for (int i = 0; i < count; ++i) {
    custom_[written++] = Phase{on_ms, 1};
    custom_[written++] = Phase{off_ms, 0};
  }
  begin(custom_, written, now_ms, 1.0f);
}

void Haptics::request(HapticPattern pattern) { pending_ = static_cast<int>(pattern); }

void Haptics::stop() {
  running_ = false;
  pwm_ = 0;
  pending_ = -1;
}

void Haptics::update(uint32_t now_ms) {
  if (pending_ >= 0) {
    const int requested = pending_;
    pending_ = -1;
    play(static_cast<HapticPattern>(requested), now_ms);
  }
  if (!running_ || script_ == nullptr) {
    pwm_ = 0;
    return;
  }
  while (running_ && now_ms - phase_started_ms_ >= script_[index_].ms) {
    phase_started_ms_ += script_[index_].ms;
    index_ += 1;
    if (index_ >= script_len_) {
      running_ = false;
      pwm_ = 0;
      return;
    }
  }
  if (script_[index_].on == 0) {
    pwm_ = 0;
    return;
  }
  float duty = intensity_ * scale_ * 255.0f;
  if (duty < 0.0f) {
    duty = 0.0f;
  }
  if (duty > 255.0f) {
    duty = 255.0f;
  }
  pwm_ = static_cast<int>(duty + 0.5f);
}

bool Haptics::vibrating() const { return pwm_ > 0; }

int Haptics::pwm() const { return pwm_; }

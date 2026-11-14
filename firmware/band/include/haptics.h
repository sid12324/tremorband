#pragma once

#include <stdint.h>

// Non-blocking vibration patterns. Samples taken while vibrating() is true
// are flagged and left out of session features.

enum class HapticPattern {
  Prompt,
  Countdown,
  Start,
  Done,
  Alert,
  Error,
  Connected,
};

class Haptics {
 public:
  struct Phase {
    uint16_t ms;
    uint8_t on;
  };

  Haptics();
  void set_intensity(float intensity);
  void play(HapticPattern pattern, uint32_t now_ms);
  void play_pulses(int count, uint16_t on_ms, uint16_t off_ms, uint32_t now_ms);
  void request(HapticPattern pattern);
  void stop();
  void update(uint32_t now_ms);
  bool vibrating() const;
  int pwm() const;

 private:
  void begin(const Phase* phases, int count, uint32_t now_ms, float scale);

  Phase custom_[16];
  const Phase* script_;
  int script_len_;
  int index_;
  uint32_t phase_started_ms_;
  float intensity_;
  float scale_;
  int pwm_;
  bool running_;
  volatile int pending_;
};

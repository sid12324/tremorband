#pragma once

#include "haptics.h"
#include "window_features.h"

#include <stdint.h>
#include <vector>

// Guided test: idle, prompt, countdown, record, done, upload.
// A measurement sequence, not a diagnosis.

enum class TestType { None, Rest, Postural, FingerNose, Tapping, Gait };
enum class TestPhase { Idle, Prompt, Countdown, Record, Done, Upload };
enum class PressKind { None, Long, Double };

const char* test_type_name(TestType type);
int test_duration_ms(TestType type);
TestType test_type_from_name(const char* name);

struct SessionSummary {
  TestType type;
  int windows;
  int included;
  double median_hz;
  double median_log_amp;
  double mean_p_tremor;
  double tremor_pct;
  double quality;
  double taps_per_s;
  double tap_decrement;
  double tap_interval_cv;
  double intention_ratio;
  double cadence_spm;
  double stride_cv;
  double asymmetry_pct;
};

class GuidedTest {
 public:
  GuidedTest();
  TestPhase phase() const;
  TestType type() const;
  bool start(TestType type, uint32_t now_ms, Haptics& haptics);
  bool cycle_and_start(uint32_t now_ms, Haptics& haptics);
  void cancel(uint32_t now_ms, Haptics& haptics);
  void update(uint32_t now_ms, Haptics& haptics);
  void on_sample(double gyro_mag, uint32_t now_ms);
  void on_window(const WindowFeatures& row, const ActivityLabel& label, bool vibrating);
  bool take_upload(SessionSummary& summary);

 private:
  void clear();
  void enter(TestPhase phase, uint32_t now_ms, Haptics& haptics);

  TestPhase phase_;
  TestType type_;
  int cycle_index_;
  uint32_t phase_started_ms_;
  int prompt_ms_;
  std::vector<double> hz_;
  std::vector<double> log_amp_;
  std::vector<double> p_tremor_;
  std::vector<double> amp_deg_;
  std::vector<double> intervals_ms_;
  std::vector<double> peak_amp_;
  int windows_;
  int tremor_windows_;
  double prev_;
  double prev2_;
  uint32_t last_peak_ms_;
  bool have_peak_;
  bool primed_;
};

class ButtonTracker {
 public:
  ButtonTracker();
  PressKind update(bool down, uint32_t now_ms);

 private:
  bool down_;
  bool long_sent_;
  bool release_armed_;
  uint32_t down_at_ms_;
  uint32_t last_release_ms_;
};

class StillCalibrator {
 public:
  StillCalibrator();
  void begin(uint32_t now_ms);
  void add(double acc_rms);
  bool active() const;
  bool finished(uint32_t now_ms) const;
  double suggested_acc_rms() const;
  void clear();

 private:
  bool active_;
  uint32_t started_ms_;
  double sum_;
  int count_;
};

#include "tests.h"

#include "config.h"

#include <algorithm>
#include <cmath>
#include <cstring>

namespace {

double median_of(std::vector<double> values) {
  if (values.empty()) {
    return 0.0;
  }
  std::sort(values.begin(), values.end());
  const size_t n = values.size();
  if ((n % 2) == 1) {
    return values[n / 2];
  }
  return 0.5 * (values[n / 2 - 1] + values[n / 2]);
}

double mean_of(const std::vector<double>& values, size_t begin, size_t end) {
  if (end <= begin) {
    return 0.0;
  }
  double sum = 0.0;
  for (size_t i = begin; i < end; ++i) {
    sum += values[i];
  }
  return sum / static_cast<double>(end - begin);
}

double variation_of(const std::vector<double>& values) {
  if (values.size() < 2) {
    return 0.0;
  }
  const double mean = mean_of(values, 0, values.size());
  if (std::fabs(mean) < 1e-9) {
    return 0.0;
  }
  double square = 0.0;
  for (double value : values) {
    const double delta = value - mean;
    square += delta * delta;
  }
  const double sd = std::sqrt(square / static_cast<double>(values.size()));
  return sd / mean;
}

}  // namespace

const char* test_type_name(TestType type) {
  switch (type) {
    case TestType::Rest:
      return "rest";
    case TestType::Postural:
      return "postural";
    case TestType::FingerNose:
      return "finger_nose";
    case TestType::Tapping:
      return "tapping";
    case TestType::Gait:
      return "gait";
    case TestType::None:
      break;
  }
  return "rest";
}

int test_duration_ms(TestType type) {
  switch (type) {
    case TestType::Rest:
    case TestType::Postural:
    case TestType::FingerNose:
      return 20000;
    case TestType::Tapping:
      return 10000;
    case TestType::Gait:
      return 30000;
    case TestType::None:
      break;
  }
  return 0;
}

TestType test_type_from_name(const char* name) {
  if (name == nullptr) {
    return TestType::None;
  }
  if (std::strcmp(name, "rest") == 0) {
    return TestType::Rest;
  }
  if (std::strcmp(name, "postural") == 0) {
    return TestType::Postural;
  }
  if (std::strcmp(name, "finger_nose") == 0) {
    return TestType::FingerNose;
  }
  if (std::strcmp(name, "tapping") == 0) {
    return TestType::Tapping;
  }
  if (std::strcmp(name, "gait") == 0) {
    return TestType::Gait;
  }
  return TestType::None;
}

GuidedTest::GuidedTest()
    : phase_(TestPhase::Idle),
      type_(TestType::None),
      cycle_index_(-1),
      phase_started_ms_(0),
      prompt_ms_(400),
      windows_(0),
      tremor_windows_(0),
      prev_(0.0),
      prev2_(0.0),
      last_peak_ms_(0),
      have_peak_(false),
      primed_(false) {}

TestPhase GuidedTest::phase() const { return phase_; }

TestType GuidedTest::type() const { return type_; }

void GuidedTest::clear() {
  hz_.clear();
  log_amp_.clear();
  p_tremor_.clear();
  amp_deg_.clear();
  intervals_ms_.clear();
  peak_amp_.clear();
  windows_ = 0;
  tremor_windows_ = 0;
  prev_ = 0.0;
  prev2_ = 0.0;
  last_peak_ms_ = 0;
  have_peak_ = false;
  primed_ = false;
}

void GuidedTest::enter(TestPhase phase, uint32_t now_ms, Haptics& haptics) {
  phase_ = phase;
  phase_started_ms_ = now_ms;
  if (phase == TestPhase::Countdown) {
    haptics.play(HapticPattern::Countdown, now_ms);
  } else if (phase == TestPhase::Record) {
    haptics.play(HapticPattern::Start, now_ms);
  } else if (phase == TestPhase::Done) {
    haptics.play(HapticPattern::Done, now_ms);
  }
}

bool GuidedTest::start(TestType type, uint32_t now_ms, Haptics& haptics) {
  if (phase_ != TestPhase::Idle || type == TestType::None) {
    return false;
  }
  clear();
  type_ = type;
  prompt_ms_ = 400;
  haptics.play(HapticPattern::Prompt, now_ms);
  phase_ = TestPhase::Prompt;
  phase_started_ms_ = now_ms;
  return true;
}

bool GuidedTest::cycle_and_start(uint32_t now_ms, Haptics& haptics) {
  if (phase_ != TestPhase::Idle) {
    return false;
  }
  static const TestType kOrder[] = {TestType::Rest, TestType::Postural, TestType::FingerNose, TestType::Tapping,
                                    TestType::Gait};
  cycle_index_ = (cycle_index_ + 1) % 5;
  const int pulses = cycle_index_ + 1;
  clear();
  type_ = kOrder[cycle_index_];
  prompt_ms_ = pulses * 160;
  haptics.play_pulses(pulses, 80, 80, now_ms);
  phase_ = TestPhase::Prompt;
  phase_started_ms_ = now_ms;
  return true;
}

void GuidedTest::cancel(uint32_t now_ms, Haptics& haptics) {
  if (phase_ == TestPhase::Idle) {
    return;
  }
  phase_ = TestPhase::Idle;
  type_ = TestType::None;
  clear();
  haptics.play(HapticPattern::Error, now_ms);
}

void GuidedTest::update(uint32_t now_ms, Haptics& haptics) {
  if (phase_ == TestPhase::Prompt && now_ms - phase_started_ms_ >= static_cast<uint32_t>(prompt_ms_)) {
    enter(TestPhase::Countdown, now_ms, haptics);
  }
  if (phase_ == TestPhase::Countdown && now_ms - phase_started_ms_ >= 3000) {
    enter(TestPhase::Record, now_ms, haptics);
  }
  if (phase_ == TestPhase::Record && now_ms - phase_started_ms_ >= static_cast<uint32_t>(test_duration_ms(type_))) {
    enter(TestPhase::Done, now_ms, haptics);
  }
  if (phase_ == TestPhase::Done && now_ms - phase_started_ms_ >= 500) {
    phase_ = TestPhase::Upload;
    phase_started_ms_ = now_ms;
  }
}

void GuidedTest::on_sample(double gyro_mag, uint32_t now_ms) {
  if (!primed_) {
    prev2_ = gyro_mag;
    prev_ = gyro_mag;
    primed_ = true;
    return;
  }
  const bool local_peak = prev_ > prev2_ && prev_ > gyro_mag && prev_ > 5.0;
  const uint32_t refractory = type_ == TestType::Gait ? 250u : 180u;
  if (phase_ == TestPhase::Record && (type_ == TestType::Tapping || type_ == TestType::Gait) && local_peak &&
      (!have_peak_ || now_ms - last_peak_ms_ >= refractory)) {
    if (have_peak_) {
      intervals_ms_.push_back(static_cast<double>(now_ms - last_peak_ms_));
    }
    peak_amp_.push_back(prev_);
    last_peak_ms_ = now_ms;
    have_peak_ = true;
  }
  prev2_ = prev_;
  prev_ = gyro_mag;
}

void GuidedTest::on_window(const WindowFeatures& row, const ActivityLabel& label, bool vibrating) {
  if (phase_ != TestPhase::Record) {
    return;
  }
  windows_ += 1;
  if (vibrating) {
    return;
  }
  hz_.push_back(row.gyro.peak_hz);
  log_amp_.push_back(row.log_amp);
  p_tremor_.push_back(label.p_tremor);
  amp_deg_.push_back(row.amp_deg);
  if (std::strcmp(label.label, "tremor") == 0) {
    tremor_windows_ += 1;
  }
}

bool GuidedTest::take_upload(SessionSummary& summary) {
  if (phase_ != TestPhase::Upload) {
    return false;
  }
  summary = SessionSummary{};
  summary.type = type_;
  summary.windows = windows_;
  summary.included = static_cast<int>(hz_.size());
  summary.median_hz = median_of(hz_);
  summary.median_log_amp = median_of(log_amp_);
  summary.mean_p_tremor = mean_of(p_tremor_, 0, p_tremor_.size());
  summary.quality = windows_ > 0 ? static_cast<double>(summary.included) / static_cast<double>(windows_) : 0.0;
  summary.tremor_pct =
      summary.included > 0 ? (100.0 * static_cast<double>(tremor_windows_) / static_cast<double>(summary.included))
                           : 0.0;
  const double duration_s = static_cast<double>(test_duration_ms(type_)) / 1000.0;
  if (type_ == TestType::Tapping) {
    summary.taps_per_s = duration_s > 0.0 ? static_cast<double>(peak_amp_.size()) / duration_s : 0.0;
    if (peak_amp_.size() >= 6) {
      summary.tap_decrement = mean_of(peak_amp_, 0, 3) - mean_of(peak_amp_, peak_amp_.size() - 3, peak_amp_.size());
    }
    summary.tap_interval_cv = variation_of(intervals_ms_);
  }
  if (type_ == TestType::FingerNose && !amp_deg_.empty()) {
    const size_t split = (amp_deg_.size() * 7) / 10;
    const double early = mean_of(amp_deg_, 0, split);
    const double late = mean_of(amp_deg_, split, amp_deg_.size());
    summary.intention_ratio = early > 1e-9 ? late / early : 0.0;
  }
  if (type_ == TestType::Gait && !intervals_ms_.empty()) {
    summary.cadence_spm = duration_s > 0.0 ? static_cast<double>(peak_amp_.size()) / duration_s * 60.0 : 0.0;
    double odd = 0.0;
    double even = 0.0;
    int odd_n = 0;
    int even_n = 0;
    for (size_t i = 0; i < intervals_ms_.size(); ++i) {
      if ((i % 2) == 0) {
        even += intervals_ms_[i];
        even_n += 1;
      } else {
        odd += intervals_ms_[i];
        odd_n += 1;
      }
    }
    const double mean_all = mean_of(intervals_ms_, 0, intervals_ms_.size());
    if (odd_n > 0 && even_n > 0 && mean_all > 1e-9) {
      summary.asymmetry_pct = std::fabs((odd / odd_n) - (even / even_n)) / mean_all * 100.0;
    }
    std::vector<double> strides;
    for (size_t i = 0; i + 1 < intervals_ms_.size(); i += 2) {
      strides.push_back(intervals_ms_[i] + intervals_ms_[i + 1]);
    }
    summary.stride_cv = variation_of(strides);
  }
  phase_ = TestPhase::Idle;
  type_ = TestType::None;
  return true;
}

ButtonTracker::ButtonTracker()
    : down_(false), long_sent_(false), release_armed_(false), down_at_ms_(0), last_release_ms_(0) {}

PressKind ButtonTracker::update(bool down, uint32_t now_ms) {
  if (down && !down_) {
    down_ = true;
    down_at_ms_ = now_ms;
    long_sent_ = false;
    return PressKind::None;
  }
  if (down && down_ && !long_sent_ && now_ms - down_at_ms_ >= 600) {
    long_sent_ = true;
    release_armed_ = false;
    return PressKind::Long;
  }
  if (!down && down_) {
    down_ = false;
    if (!long_sent_) {
      if (release_armed_ && now_ms - last_release_ms_ <= 350) {
        release_armed_ = false;
        return PressKind::Double;
      }
      last_release_ms_ = now_ms;
      release_armed_ = true;
    }
  }
  return PressKind::None;
}

StillCalibrator::StillCalibrator() : active_(false), started_ms_(0), sum_(0.0), count_(0) {}

void StillCalibrator::begin(uint32_t now_ms) {
  active_ = true;
  started_ms_ = now_ms;
  sum_ = 0.0;
  count_ = 0;
}

void StillCalibrator::add(double acc_rms) {
  if (!active_) {
    return;
  }
  sum_ += acc_rms;
  count_ += 1;
}

bool StillCalibrator::active() const { return active_; }

bool StillCalibrator::finished(uint32_t now_ms) const {
  return active_ && count_ > 0 && now_ms - started_ms_ >= 5000;
}

double StillCalibrator::suggested_acc_rms() const {
  if (count_ <= 0) {
    return static_cast<double>(TB_STILL_ACC_RMS);
  }
  return (sum_ / static_cast<double>(count_)) * 3.0;
}

void StillCalibrator::clear() { active_ = false; }

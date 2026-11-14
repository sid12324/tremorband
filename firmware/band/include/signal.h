#pragma once

#include <vector>

// Window features for one accel stream and one gyro stream.
// This is a measurement summary, not a diagnosis.

struct StreamFeatures {
  double peak_hz;
  double band_power;
  double rms;
  double sharpness;
  double spectral_entropy;
  double zero_crossing_rate;
  double band_ratio;
};

struct WindowFeatures {
  StreamFeatures acc;
  StreamFeatures gyro;
  double amp_deg;
  double disp_mm;
  double log_amp;
};

// Band-pass each magnitude stream, then emit one feature row per hop.
// Accel is m/s^2. Gyro is deg/s. hpf_hz and lpf_hz are Hertz.
std::vector<WindowFeatures> compute_windows(const std::vector<double>& ax,
                                            const std::vector<double>& ay,
                                            const std::vector<double>& az,
                                            const std::vector<double>& gx,
                                            const std::vector<double>& gy,
                                            const std::vector<double>& gz,
                                            double hpf_hz,
                                            double lpf_hz);

// Synthetic 5 Hz sine through the same pipeline. The last window is returned.
WindowFeatures run_selftest();

// Per-window rule: still, voluntary, or tremor. Not a diagnosis.
struct ActivityLabel {
  const char* label;
  double p_tremor;
};

ActivityLabel rule_label(const WindowFeatures& row);

// Still and voluntary stay as the rule called them. A tremor candidate is
// rescored by the exported model, which can reject it.
ActivityLabel classify_window(const WindowFeatures& row);

// Runtime copies of the rule thresholds. set_threshold updates these.
struct ThresholdOverrides {
  double still_acc_rms;
  double still_gyro_rms;
  double tremor_sharpness;
};

ThresholdOverrides& threshold_overrides();

// Majority of the last three raw labels. A new label is adopted only when it
// has at least two votes, so one odd window does not flip the displayed label.
class LabelSmoother {
 public:
  LabelSmoother();
  ActivityLabel push_raw(const char* label, double tremor_score);
  ActivityLabel update(const WindowFeatures& row);
  ActivityLabel hold() const;

 private:
  int raw_[3];
  int count_;
  int current_;
  double last_score_;
};

// Incremental magnitude, biquad, and hop. Completed windows match compute_windows.
class WindowPipeline {
 public:
  WindowPipeline();
  ~WindowPipeline();
  WindowPipeline(const WindowPipeline&) = delete;
  WindowPipeline& operator=(const WindowPipeline&) = delete;
  bool push(double ax, double ay, double az, double gx, double gy, double gz, WindowFeatures& row,
            ActivityLabel& label);
  // sample_vibrating is true while the motor is driven. The completed window is
  // flagged and does not move the smoothed label.
  bool push(double ax, double ay, double az, double gx, double gy, double gz, WindowFeatures& row,
            ActivityLabel& label, bool sample_vibrating, bool& window_vibrating);

 private:
  struct State;
  State* state_;
};

// One serial JSON object, without a newline. Returns the length, or -1.
int format_window_json(char* dest, int capacity, const char* device_id, long long ts_us,
                       const WindowFeatures& row, const ActivityLabel& label, bool vibrating,
                       const char* test_type);

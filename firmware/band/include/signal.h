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

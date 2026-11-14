#include "signal.h"

#include "config.h"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <stdexcept>

namespace {

constexpr double kPi = 3.141592653589793;

struct Biquad {
  double b0;
  double b1;
  double b2;
  double a1;
  double a2;
  double w0;
  double w1;

  double process(double x) {
    // Direct form II, matching esp-dsp dsps_biquad_f32_ansi (v1.8.2).
    const double d0 = x - a1 * w0 - a2 * w1;
    const double y = b0 * d0 + b1 * w0 + b2 * w1;
    w1 = w0;
    w0 = d0;
    return y;
  }
};

struct Coeff {
  double b0;
  double b1;
  double b2;
  double a1;
  double a2;
};

// esp-dsp dsps_biquad_gen_lpf_f32 / dsps_biquad_gen_hpf_f32.
// f_hz is absolute; the library takes f_hz / fs. Q is 1/sqrt(2) for Butterworth.
Coeff make_lpf(double f_hz, double fs) {
  const double q = 1.0 / std::sqrt(2.0);
  const double w0 = 2.0 * kPi * (f_hz / fs);
  const double c = std::cos(w0);
  const double s = std::sin(w0);
  const double alpha = s / (2.0 * q);
  const double b0 = (1.0 - c) / 2.0;
  const double b1 = 1.0 - c;
  const double b2 = b0;
  const double a0 = 1.0 + alpha;
  return Coeff{b0 / a0, b1 / a0, b2 / a0, (-2.0 * c) / a0, (1.0 - alpha) / a0};
}

Coeff make_hpf(double f_hz, double fs) {
  const double q = 1.0 / std::sqrt(2.0);
  const double w0 = 2.0 * kPi * (f_hz / fs);
  const double c = std::cos(w0);
  const double s = std::sin(w0);
  const double alpha = s / (2.0 * q);
  const double b0 = (1.0 + c) / 2.0;
  const double b1 = -(1.0 + c);
  const double b2 = b0;
  const double a0 = 1.0 + alpha;
  return Coeff{b0 / a0, b1 / a0, b2 / a0, (-2.0 * c) / a0, (1.0 - alpha) / a0};
}

Biquad make_biquad(const Coeff& coeff) {
  return Biquad{coeff.b0, coeff.b1, coeff.b2, coeff.a1, coeff.a2, 0.0, 0.0};
}

std::vector<double> magnitudes(const std::vector<double>& x, const std::vector<double>& y,
                               const std::vector<double>& z) {
  std::vector<double> out(x.size());
  for (size_t i = 0; i < x.size(); ++i) {
    out[i] = std::sqrt(x[i] * x[i] + y[i] * y[i] + z[i] * z[i]);
  }
  return out;
}

std::vector<double> bandpass(const std::vector<double>& input, double hpf_hz, double lpf_hz, double fs) {
  Biquad high = make_biquad(make_hpf(hpf_hz, fs));
  Biquad low = make_biquad(make_lpf(lpf_hz, fs));
  std::vector<double> output(input.size());
  for (size_t i = 0; i < input.size(); ++i) {
    output[i] = low.process(high.process(input[i]));
  }
  return output;
}

void forward_fft(const std::vector<double>& input, std::vector<double>& real, std::vector<double>& imag) {
  const int n = static_cast<int>(input.size());
  real = input;
  imag.assign(static_cast<size_t>(n), 0.0);
  int j = 0;
  for (int i = 1; i < n; ++i) {
    int bit = n >> 1;
    while ((j & bit) != 0) {
      j ^= bit;
      bit >>= 1;
    }
    j ^= bit;
    if (i < j) {
      std::swap(real[static_cast<size_t>(i)], real[static_cast<size_t>(j)]);
      std::swap(imag[static_cast<size_t>(i)], imag[static_cast<size_t>(j)]);
    }
  }
  for (int length = 2; length <= n; length <<= 1) {
    const double angle = -2.0 * kPi / static_cast<double>(length);
    const double wlen_re = std::cos(angle);
    const double wlen_im = std::sin(angle);
    const int half = length / 2;
    for (int start = 0; start < n; start += length) {
      double w_re = 1.0;
      double w_im = 0.0;
      for (int k = 0; k < half; ++k) {
        const size_t even = static_cast<size_t>(start + k);
        const size_t odd = static_cast<size_t>(start + k + half);
        const double v_re = real[odd] * w_re - imag[odd] * w_im;
        const double v_im = real[odd] * w_im + imag[odd] * w_re;
        const double u_re = real[even];
        const double u_im = imag[even];
        real[even] = u_re + v_re;
        imag[even] = u_im + v_im;
        real[odd] = u_re - v_re;
        imag[odd] = u_im - v_im;
        const double next_re = w_re * wlen_re - w_im * wlen_im;
        const double next_im = w_re * wlen_im + w_im * wlen_re;
        w_re = next_re;
        w_im = next_im;
      }
    }
  }
}

double hann_at(int index, int length) {
  // esp-dsp dsps_wind_hann_f32: 0.5 * (1 - cos(2*pi*i/(len-1))).
  const double scale = 1.0 / static_cast<double>(length - 1);
  return 0.5 * (1.0 - std::cos(static_cast<double>(index) * 2.0 * kPi * scale));
}

StreamFeatures features_for_window(const std::vector<double>& filtered, double fs) {
  const int n = static_cast<int>(filtered.size());
  double square_sum = 0.0;
  int crossings = 0;
  for (int i = 0; i < n; ++i) {
    square_sum += filtered[static_cast<size_t>(i)] * filtered[static_cast<size_t>(i)];
    if (i > 0) {
      const double previous = filtered[static_cast<size_t>(i - 1)];
      const double current = filtered[static_cast<size_t>(i)];
      if ((previous >= 0.0 && current < 0.0) || (previous < 0.0 && current >= 0.0)) {
        ++crossings;
      }
    }
  }
  const double rms = std::sqrt(square_sum / static_cast<double>(n));
  const double zcr = static_cast<double>(crossings) / static_cast<double>(n - 1);

  std::vector<double> windowed(static_cast<size_t>(n));
  for (int i = 0; i < n; ++i) {
    windowed[static_cast<size_t>(i)] = filtered[static_cast<size_t>(i)] * hann_at(i, n);
  }
  std::vector<double> real;
  std::vector<double> imag;
  forward_fft(windowed, real, imag);

  const int bins = n / 2;
  std::vector<double> power(static_cast<size_t>(bins + 1));
  for (int k = 0; k <= bins; ++k) {
    power[static_cast<size_t>(k)] =
        real[static_cast<size_t>(k)] * real[static_cast<size_t>(k)] +
        imag[static_cast<size_t>(k)] * imag[static_cast<size_t>(k)];
  }

  int peak_k = 0;
  double peak_power = -1.0;
  double band_power = 0.0;
  double sharp_den = 0.0;
  bool have_peak = false;
  for (int k = 0; k <= bins; ++k) {
    const double freq = static_cast<double>(k) * fs / static_cast<double>(n);
    const double p = power[static_cast<size_t>(k)];
    if (freq >= 2.0 && freq <= 12.0 && (!have_peak || p > peak_power)) {
      peak_power = p;
      peak_k = k;
      have_peak = true;
    }
    if (freq >= 3.0 && freq <= 12.0) {
      band_power += p;
    }
    if (freq >= 2.0 && freq <= 15.0) {
      sharp_den += p;
    }
  }

  double delta = 0.0;
  if (peak_k > 0 && peak_k < bins) {
    const double left = power[static_cast<size_t>(peak_k - 1)];
    const double center = power[static_cast<size_t>(peak_k)];
    const double right = power[static_cast<size_t>(peak_k + 1)];
    const double denom = left - 2.0 * center + right;
    if (std::fabs(denom) > 1e-20) {
      delta = 0.5 * (left - right) / denom;
    }
  }
  const double peak_hz = (static_cast<double>(peak_k) + delta) * fs / static_cast<double>(n);

  double sharp_num = 0.0;
  double total = 0.0;
  for (int k = 0; k <= bins; ++k) {
    const double freq = static_cast<double>(k) * fs / static_cast<double>(n);
    const double p = power[static_cast<size_t>(k)];
    if (std::fabs(freq - peak_hz) <= 0.5) {
      sharp_num += p;
    }
    if (k >= 1) {
      total += p;
    }
  }

  double entropy = 0.0;
  if (total > 0.0) {
    for (int k = 1; k <= bins; ++k) {
      const double p = power[static_cast<size_t>(k)];
      if (p > 0.0) {
        const double share = p / total;
        entropy -= share * std::log(share);
      }
    }
  }

  StreamFeatures features;
  features.peak_hz = peak_hz;
  features.band_power = band_power;
  features.rms = rms;
  features.sharpness = sharp_den > 0.0 ? sharp_num / sharp_den : 0.0;
  features.spectral_entropy = entropy;
  features.zero_crossing_rate = zcr;
  features.band_ratio = total > 0.0 ? band_power / total : 0.0;
  return features;
}

void require_same_length(const std::vector<double>& ax, const std::vector<double>& ay,
                         const std::vector<double>& az, const std::vector<double>& gx,
                         const std::vector<double>& gy, const std::vector<double>& gz) {
  const size_t n = ax.size();
  if (ay.size() != n || az.size() != n || gx.size() != n || gy.size() != n || gz.size() != n) {
    throw std::invalid_argument("IMU axes must have the same length");
  }
}

}  // namespace

std::vector<WindowFeatures> compute_windows(const std::vector<double>& ax, const std::vector<double>& ay,
                                            const std::vector<double>& az, const std::vector<double>& gx,
                                            const std::vector<double>& gy, const std::vector<double>& gz,
                                            double hpf_hz, double lpf_hz) {
  require_same_length(ax, ay, az, gx, gy, gz);
  const double fs = static_cast<double>(TB_FS_HZ);
  const int window_n = TB_WINDOW_N;
  const int hop = TB_HOP;
  const std::vector<double> acc = bandpass(magnitudes(ax, ay, az), hpf_hz, lpf_hz, fs);
  const std::vector<double> gyro = bandpass(magnitudes(gx, gy, gz), hpf_hz, lpf_hz, fs);
  std::vector<WindowFeatures> rows;
  if (static_cast<int>(acc.size()) < window_n) {
    return rows;
  }
  for (int start = 0; start + window_n <= static_cast<int>(acc.size()); start += hop) {
    const std::vector<double> acc_window(acc.begin() + start, acc.begin() + start + window_n);
    const std::vector<double> gyro_window(gyro.begin() + start, gyro.begin() + start + window_n);
    WindowFeatures row;
    row.acc = features_for_window(acc_window, fs);
    row.gyro = features_for_window(gyro_window, fs);
    const double gyro_peak = std::sqrt(2.0) * row.gyro.rms;
    const double acc_peak = std::sqrt(2.0) * row.acc.rms;
    if (row.gyro.peak_hz > 1e-6) {
      row.amp_deg = gyro_peak / (2.0 * kPi * row.gyro.peak_hz);
    } else {
      row.amp_deg = 0.0;
    }
    if (row.acc.peak_hz > 1e-6) {
      const double omega = 2.0 * kPi * row.acc.peak_hz;
      row.disp_mm = (acc_peak / (omega * omega)) * 1000.0;
    } else {
      row.disp_mm = 0.0;
    }
    row.log_amp = std::log10(std::max(row.amp_deg, 1e-12));
    rows.push_back(row);
  }
  return rows;
}

WindowFeatures run_selftest() {
  constexpr int kSamples = 1024;
  const double fs = static_cast<double>(TB_FS_HZ);
  std::vector<double> ax(kSamples, 0.0);
  std::vector<double> ay(kSamples, 0.0);
  std::vector<double> az(kSamples, 0.0);
  std::vector<double> gx(kSamples, 0.0);
  std::vector<double> gy(kSamples, 0.0);
  std::vector<double> gz(kSamples, 0.0);
  for (int i = 0; i < kSamples; ++i) {
    const double t = static_cast<double>(i) / fs;
    const double sine = std::sin(2.0 * kPi * 5.0 * t);
    az[static_cast<size_t>(i)] = 9.81 + 0.8 * sine;
    gx[static_cast<size_t>(i)] = 30.0 + 20.0 * sine;
  }
  const std::vector<WindowFeatures> rows =
      compute_windows(ax, ay, az, gx, gy, gz, static_cast<double>(TB_HPF_HZ), static_cast<double>(TB_LPF_HZ));
  if (rows.empty()) {
    throw std::runtime_error("selftest produced no windows");
  }
  return rows.back();
}

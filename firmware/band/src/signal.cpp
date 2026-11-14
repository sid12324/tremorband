#include "signal.h"

#include "config.h"

ThresholdOverrides& threshold_overrides() {
  static ThresholdOverrides values{static_cast<double>(TB_STILL_ACC_RMS), static_cast<double>(TB_STILL_GYRO_RMS),
                                   static_cast<double>(TB_TREMOR_SHARPNESS)};
  return values;
}

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <cstring>
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

void fill_amplitudes(WindowFeatures& row) {
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
}

bool in_tremor_band(double peak_hz) {
  const double low = static_cast<double>(TB_TREMOR_HZ_MIN) - static_cast<double>(TB_PEAK_TOL_HZ);
  const double high = static_cast<double>(TB_TREMOR_HZ_MAX) + static_cast<double>(TB_PEAK_TOL_HZ);
  return peak_hz >= low && peak_hz <= high;
}

bool stream_is_tremor(const StreamFeatures& stream) {
  return stream.sharpness >= threshold_overrides().tremor_sharpness && in_tremor_band(stream.peak_hz);
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
    fill_amplitudes(row);
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

namespace {

const char* label_name(int code) {
  if (code == 2) {
    return "tremor";
  }
  if (code == 1) {
    return "voluntary";
  }
  return "still";
}

int label_code(const char* label) {
  if (std::strcmp(label, "tremor") == 0) {
    return 2;
  }
  if (std::strcmp(label, "voluntary") == 0) {
    return 1;
  }
  return 0;
}

double clamp01(double value) {
  if (value < 0.0) {
    return 0.0;
  }
  if (value > 1.0) {
    return 1.0;
  }
  return value;
}

const StreamFeatures& display_stream(const WindowFeatures& row, const char* label) {
  if (std::strcmp(label, "tremor") == 0) {
    const bool acc = stream_is_tremor(row.acc);
    const bool gyro = stream_is_tremor(row.gyro);
    if (acc && !gyro) {
      return row.acc;
    }
    if (gyro && !acc) {
      return row.gyro;
    }
    if (acc && gyro) {
      return row.acc.sharpness > row.gyro.sharpness ? row.acc : row.gyro;
    }
  }
  if (std::strcmp(label, "voluntary") == 0 && row.acc.sharpness > row.gyro.sharpness) {
    return row.acc;
  }
  return row.gyro;
}

bool device_id_ok(const char* device_id) {
  if (device_id == nullptr || device_id[0] == '\0') {
    return false;
  }
  for (const char* cursor = device_id; *cursor != '\0'; ++cursor) {
    const unsigned char c = static_cast<unsigned char>(*cursor);
    const bool ok = (c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == '.' ||
                    c == '_' || c == ':' || c == '-';
    if (!ok) {
      return false;
    }
  }
  return true;
}

}  // namespace

ActivityLabel rule_label(const WindowFeatures& row) {
  ActivityLabel out{"still", 0.0};
  if (row.acc.rms < threshold_overrides().still_acc_rms && row.gyro.rms < threshold_overrides().still_gyro_rms) {
    return out;
  }
  const bool acc = stream_is_tremor(row.acc);
  const bool gyro = stream_is_tremor(row.gyro);
  if (acc || gyro) {
    double score = 0.0;
    if (acc) {
      score = row.acc.sharpness;
    }
    if (gyro && row.gyro.sharpness > score) {
      score = row.gyro.sharpness;
    }
    out.label = "tremor";
    out.p_tremor = clamp01(score);
    return out;
  }
  out.label = "voluntary";
  return out;
}

LabelSmoother::LabelSmoother() : raw_{0, 0, 0}, count_(0), current_(-1), last_score_(0.0) {}

ActivityLabel LabelSmoother::push_raw(const char* label, double tremor_score) {
  const int code = label_code(label);
  if (count_ < 3) {
    raw_[count_++] = code;
  } else {
    raw_[0] = raw_[1];
    raw_[1] = raw_[2];
    raw_[2] = code;
  }
  int votes[3] = {0, 0, 0};
  for (int i = 0; i < count_; ++i) {
    votes[raw_[i]] += 1;
  }
  int best = 0;
  for (int i = 1; i < 3; ++i) {
    if (votes[i] > votes[best]) {
      best = i;
    }
  }
  bool unique = true;
  for (int i = 0; i < 3; ++i) {
    if (i != best && votes[i] == votes[best]) {
      unique = false;
    }
  }
  if (current_ < 0) {
    current_ = code;
  } else if (unique && votes[best] >= 2 && best != current_) {
    current_ = best;
  }
  if (code == 2) {
    last_score_ = clamp01(tremor_score);
  }
  ActivityLabel out;
  out.label = label_name(current_);
  out.p_tremor = current_ == 2 ? last_score_ : 0.0;
  return out;
}

ActivityLabel LabelSmoother::update(const WindowFeatures& row) {
  const ActivityLabel raw = rule_label(row);
  return push_raw(raw.label, raw.p_tremor);
}

ActivityLabel LabelSmoother::hold() const {
  ActivityLabel out;
  out.label = current_ < 0 ? "still" : label_name(current_);
  out.p_tremor = current_ == 2 ? last_score_ : 0.0;
  return out;
}

struct WindowPipeline::State {
  Biquad acc_hp;
  Biquad acc_lp;
  Biquad gyro_hp;
  Biquad gyro_lp;
  std::vector<double> acc;
  std::vector<double> gyro;
  std::vector<char> vibrating;
  int count;
  LabelSmoother smoother;
};

WindowPipeline::WindowPipeline()
    : state_(new State{make_biquad(make_hpf(TB_HPF_HZ, TB_FS_HZ)), make_biquad(make_lpf(TB_LPF_HZ, TB_FS_HZ)),
                       make_biquad(make_hpf(TB_HPF_HZ, TB_FS_HZ)), make_biquad(make_lpf(TB_LPF_HZ, TB_FS_HZ)),
                       {},
                       {},
                       {},
                       0,
                       LabelSmoother()}) {
  state_->acc.reserve(static_cast<size_t>(TB_WINDOW_N));
  state_->gyro.reserve(static_cast<size_t>(TB_WINDOW_N));
}

WindowPipeline::~WindowPipeline() { delete state_; }

bool WindowPipeline::push(double ax, double ay, double az, double gx, double gy, double gz, WindowFeatures& row,
                          ActivityLabel& label) {
  bool ignored = false;
  return push(ax, ay, az, gx, gy, gz, row, label, false, ignored);
}

bool WindowPipeline::push(double ax, double ay, double az, double gx, double gy, double gz, WindowFeatures& row,
                          ActivityLabel& label, bool sample_vibrating, bool& window_vibrating) {
  const double acc_mag = std::sqrt(ax * ax + ay * ay + az * az);
  const double gyro_mag = std::sqrt(gx * gx + gy * gy + gz * gz);
  const double acc_filtered = state_->acc_lp.process(state_->acc_hp.process(acc_mag));
  const double gyro_filtered = state_->gyro_lp.process(state_->gyro_hp.process(gyro_mag));
  if (static_cast<int>(state_->acc.size()) == TB_WINDOW_N) {
    state_->acc.erase(state_->acc.begin());
    state_->gyro.erase(state_->gyro.begin());
    state_->vibrating.erase(state_->vibrating.begin());
  }
  state_->acc.push_back(acc_filtered);
  state_->gyro.push_back(gyro_filtered);
  state_->vibrating.push_back(sample_vibrating ? 1 : 0);
  state_->count += 1;
  if (state_->count < TB_WINDOW_N || ((state_->count - TB_WINDOW_N) % TB_HOP) != 0) {
    return false;
  }
  const double fs = static_cast<double>(TB_FS_HZ);
  row.acc = features_for_window(state_->acc, fs);
  row.gyro = features_for_window(state_->gyro, fs);
  fill_amplitudes(row);
  window_vibrating = false;
  for (char flag : state_->vibrating) {
    if (flag != 0) {
      window_vibrating = true;
      break;
    }
  }
  // A vibrating window is stored with the flag and left out of the label vote.
  label = window_vibrating ? state_->smoother.hold() : state_->smoother.update(row);
  return true;
}

int format_window_json(char* dest, int capacity, const char* device_id, long long ts_us, const WindowFeatures& row,
                       const ActivityLabel& label, bool vibrating, const char* test_type) {
  if (dest == nullptr || capacity < 2 || !device_id_ok(device_id) || label.label == nullptr) {
    return -1;
  }
  char extra[80] = "";
  if (test_type != nullptr && device_id_ok(test_type)) {
    std::snprintf(extra, sizeof(extra), ",\"test_type\":\"%s\"", test_type);
  }
  const StreamFeatures& shown = display_stream(row, label.label);
  const int wrote = std::snprintf(
      dest, static_cast<size_t>(capacity),
      "{\"type\":\"window\",\"device_id\":\"%s\",\"ts_us\":%lld,\"peak_hz\":%.6f,\"band_power\":%.6f,"
      "\"rms\":%.6f,\"sharpness\":%.6f,\"amp_deg\":%.6f,\"disp_mm\":%.6f,\"log_amp\":%.6f,"
      "\"label\":\"%s\",\"p_tremor\":%.6f,\"vibrating\":%s%s,"
      "\"peak_hz_acc\":%.6f,\"peak_hz_gyro\":%.6f}",
      device_id, ts_us, shown.peak_hz, shown.band_power, shown.rms, shown.sharpness, row.amp_deg, row.disp_mm,
      row.log_amp, label.label, label.p_tremor, vibrating ? "true" : "false", extra, row.acc.peak_hz,
      row.gyro.peak_hz);
  if (wrote < 0 || wrote >= capacity) {
    return -1;
  }
  return wrote;
}

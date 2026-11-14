#include "config.h"
#include "window_features.h"

#include <cmath>
#include <iostream>
#include <string>
#include <vector>

namespace {

bool expect(bool ok, const char* message) {
  if (!ok) {
    std::cerr << message << "\n";
  }
  return ok;
}

std::vector<double> zeros(int count) { return std::vector<double>(static_cast<size_t>(count), 0.0); }

}  // namespace

int main() {
  bool ok = true;
  const double fs = static_cast<double>(TB_FS_HZ);
  constexpr int kSamples = 768;

  {
    WindowPipeline pipeline;
    WindowFeatures last{};
    ActivityLabel label{"still", 0.0};
    int windows = 0;
    for (int i = 0; i < 1024; ++i) {
      const double sine = std::sin(2.0 * 3.141592653589793 * 5.0 * (static_cast<double>(i) / fs));
      WindowFeatures row;
      ActivityLabel next;
      if (pipeline.push(0.0, 0.0, 9.81 + 0.8 * sine, 30.0 + 20.0 * sine, 0.0, 0.0, row, next)) {
        last = row;
        label = next;
        ++windows;
      }
    }
    const WindowFeatures batch = run_selftest();
    ok &= expect(windows > 0, "stream produced no windows");
    ok &= expect(std::fabs(last.gyro.peak_hz - batch.gyro.peak_hz) < 1e-8, "stream and batch peaks differ");
    ok &= expect(std::string(label.label) == "tremor", "5 Hz stream was not tremor");
    ok &= expect(std::fabs(last.gyro.peak_hz - 5.0) < 0.05, "5 Hz peak missed");
    char json[640];
    const int wrote = format_window_json(json, sizeof(json), TB_DEVICE_ID, 1000, last, label, false, nullptr);
    ok &= expect(wrote > 0, "json format failed");
    ok &= expect(std::string(json).find("\"label\":\"tremor\"") != std::string::npos, "json missing tremor");
    std::cout << json << "\n";
  }

  {
    auto ax = zeros(kSamples);
    auto ay = zeros(kSamples);
    auto az = zeros(kSamples);
    auto gx = zeros(kSamples);
    auto gy = zeros(kSamples);
    auto gz = zeros(kSamples);
    for (int i = 0; i < kSamples; ++i) {
      az[static_cast<size_t>(i)] = 9.81;
      gx[static_cast<size_t>(i)] = 0.2;
    }
    const std::vector<WindowFeatures> rows =
        compute_windows(ax, ay, az, gx, gy, gz, TB_HPF_HZ, TB_LPF_HZ);
    ok &= expect(!rows.empty(), "still signal produced no windows");
    ok &= expect(std::string(rule_label(rows.back()).label) == "still", "rest was not still");
    ok &= expect(std::string(classify_window(rows.back()).label) == "still", "gate did not keep still");
    ok &= expect(classify_window(rows.back()).p_tremor == 0.0, "still score was not zero");
  }

  {
    auto ax = zeros(kSamples);
    auto ay = zeros(kSamples);
    auto az = zeros(kSamples);
    auto gx = zeros(kSamples);
    auto gy = zeros(kSamples);
    auto gz = zeros(kSamples);
    for (int i = 0; i < kSamples; ++i) {
      const double t = static_cast<double>(i) / fs;
      const double motion = 1.2 * std::sin(2.0 * 3.141592653589793 * 2.2 * t) +
                            0.9 * std::sin(2.0 * 3.141592653589793 * 6.5 * t) +
                            0.7 * std::sin(2.0 * 3.141592653589793 * 9.0 * t);
      const double spin = 40.0 * std::sin(2.0 * 3.141592653589793 * 1.8 * t) +
                          25.0 * std::sin(2.0 * 3.141592653589793 * 7.0 * t);
      az[static_cast<size_t>(i)] = 9.81 + motion;
      gx[static_cast<size_t>(i)] = spin;
    }
    const std::vector<WindowFeatures> rows =
        compute_windows(ax, ay, az, gx, gy, gz, TB_HPF_HZ, TB_LPF_HZ);
    ok &= expect(!rows.empty(), "voluntary signal produced no windows");
    ok &= expect(std::string(rule_label(rows.back()).label) == "voluntary", "mixed motion was not voluntary");
    ok &= expect(std::string(classify_window(rows.back()).label) == "voluntary", "gate did not keep voluntary");
  }

  {
    LabelSmoother smoother;
    const ActivityLabel first = smoother.push_raw("still", 0.0);
    const ActivityLabel flicker = smoother.push_raw("tremor", 0.9);
    const ActivityLabel held = smoother.push_raw("still", 0.0);
    ok &= expect(std::string(first.label) == "still", "first label was not still");
    ok &= expect(std::string(flicker.label) == "still", "one tremor window flipped the label");
    ok &= expect(std::string(held.label) == "still", "hysteresis did not hold still");
    LabelSmoother confirmed;
    confirmed.push_raw("tremor", 0.9);
    confirmed.push_raw("tremor", 0.91);
    const ActivityLabel stayed = confirmed.push_raw("still", 0.0);
    ok &= expect(std::string(stayed.label) == "tremor", "two tremor votes did not hold");
    ok &= expect(std::fabs(stayed.p_tremor - 0.91) < 1e-9, "held tremor score changed");
  }

  if (!ok) {
    return 1;
  }
  std::cout << "classifier ok\n";
  return 0;
}

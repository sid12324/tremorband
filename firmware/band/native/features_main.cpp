#include "signal.h"

#include "config.h"

#include <iostream>
#include <vector>

namespace {

void print_stream(const char* suffix, const StreamFeatures& row) {
  std::cout << "\"peak_hz_" << suffix << "\":" << row.peak_hz << ","
            << "\"band_power_" << suffix << "\":" << row.band_power << ","
            << "\"rms_" << suffix << "\":" << row.rms << ","
            << "\"sharpness_" << suffix << "\":" << row.sharpness << ","
            << "\"entropy_" << suffix << "\":" << row.spectral_entropy << ","
            << "\"zcr_" << suffix << "\":" << row.zero_crossing_rate << ","
            << "\"ratio_" << suffix << "\":" << row.band_ratio;
}

}  // namespace

int main() {
  std::ios::sync_with_stdio(false);
  std::cin.tie(nullptr);
  int count = 0;
  if (!(std::cin >> count) || count < 0) {
    std::cerr << "expected a sample count\n";
    return 2;
  }
  std::vector<double> ax(static_cast<size_t>(count));
  std::vector<double> ay(static_cast<size_t>(count));
  std::vector<double> az(static_cast<size_t>(count));
  std::vector<double> gx(static_cast<size_t>(count));
  std::vector<double> gy(static_cast<size_t>(count));
  std::vector<double> gz(static_cast<size_t>(count));
  for (int i = 0; i < count; ++i) {
    if (!(std::cin >> ax[static_cast<size_t>(i)] >> ay[static_cast<size_t>(i)] >> az[static_cast<size_t>(i)] >>
          gx[static_cast<size_t>(i)] >> gy[static_cast<size_t>(i)] >> gz[static_cast<size_t>(i)])) {
      std::cerr << "short sample list\n";
      return 2;
    }
  }
  const std::vector<WindowFeatures> rows =
      compute_windows(ax, ay, az, gx, gy, gz, static_cast<double>(TB_HPF_HZ), static_cast<double>(TB_LPF_HZ));
  std::cout.setf(std::ios::fmtflags(0), std::ios::floatfield);
  std::cout.precision(17);
  for (const WindowFeatures& row : rows) {
    std::cout << "{\"fs\":" << static_cast<double>(TB_FS_HZ) << ",\"n\":" << TB_WINDOW_N << ",\"hop\":" << TB_HOP
              << ",";
    print_stream("acc", row.acc);
    std::cout << ",";
    print_stream("gyro", row.gyro);
    const ActivityLabel activity = rule_label(row);
    std::cout << ",\"amp_deg\":" << row.amp_deg << ",\"disp_mm\":" << row.disp_mm << ",\"log_amp\":" << row.log_amp
              << ",\"label\":\"" << activity.label << "\"}\n";
  }
  return 0;
}

#include "window_features.h"

#include <cmath>
#include <cstdlib>
#include <iostream>

int main() {
  const WindowFeatures row = run_selftest();
  std::cout.setf(std::ios::fixed);
  std::cout.precision(6);
  std::cout << "selftest acc_peak_hz=" << row.acc.peak_hz << " gyro_peak_hz=" << row.gyro.peak_hz << "\n";
  const bool acc_ok = std::fabs(row.acc.peak_hz - 5.0) <= 0.05;
  const bool gyro_ok = std::fabs(row.gyro.peak_hz - 5.0) <= 0.05;
  return (acc_ok && gyro_ok) ? EXIT_SUCCESS : EXIT_FAILURE;
}

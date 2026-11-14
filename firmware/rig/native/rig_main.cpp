#include "rig_control.h"

#include <cmath>
#include <cstring>
#include <iostream>

namespace {

int g_failures = 0;

void expect(bool ok, const char* message) {
  if (!ok) {
    std::cerr << message << "\n";
    g_failures += 1;
  }
}

}  // namespace

int main() {
  const float mild = static_cast<float>(2.0 * 3.141592653589793 * 5.0 * 10.0);
  expect(std::fabs(mild - 314.159f) < 0.01f, "5 Hz at 10 deg is under the limit");

  RigController rig;
  rig.set_amplitude(10.0f);
  rig.set_frequency(5.0f, 0);
  expect(!rig.status().limited, "mild motion was limited");
  expect(std::fabs(rig.status().amp_deg - 10.0f) < 1e-3f, "amplitude changed");

  RigOutput output{};
  bool done = false;
  for (int step = 1; step <= 10 && !done; ++step) {
    done = rig.update(static_cast<uint32_t>(step) * 20000u, static_cast<uint32_t>(step) * 20u, 0.02f, output);
  }
  expect(done, "5 Hz cycle did not complete");
  expect(std::fabs(output.measured_hz - 5.0f) < 1e-3f, "on-time measured frequency");

  RigController slow;
  slow.set_amplitude(10.0f);
  slow.set_frequency(5.0f, 0);
  bool slow_done = false;
  for (int step = 1; step <= 10 && !slow_done; ++step) {
    slow_done =
        slow.update(static_cast<uint32_t>(step) * 21000u, static_cast<uint32_t>(step) * 21u, 0.02f, output);
  }
  expect(slow_done, "slow cycle did not complete");
  expect(std::fabs(output.measured_hz - (1000000.0f / 210000.0f)) < 1e-3f, "late loop measured frequency");

  RigController fast;
  fast.set_frequency(8.0f, 0);
  fast.set_amplitude(20.0f);
  expect(fast.status().limited, "8 Hz at 20 deg was not limited");
  const float reduced = 600.0f / static_cast<float>(2.0 * 3.141592653589793 * 8.0);
  expect(std::fabs(fast.status().amp_deg - reduced) < 1e-3f, "reduced amplitude");
  expect(fast.status().peak_deg_s > 600.0f, "warning peak");
  expect(fast.take_warning(), "warning was not pending");
  expect(!fast.take_warning(), "warning repeated");
  char warning[200];
  expect(format_speed_warning(warning, static_cast<int>(sizeof(warning)), fast.status()) > 0, "warning json");
  expect(std::strstr(warning, "SG90 speed limit") != nullptr, "warning text");

  char json[160];
  expect(format_rig_json(json, static_cast<int>(sizeof(json)), 5.0f, 4.99f, 10.0f) > 0, "rig json");
  expect(std::strstr(json, "\"set_hz\":5.0000") != nullptr, "set_hz field");
  expect(std::strstr(json, "\"measured_hz\":4.9900") != nullptr, "measured_hz field");

  expect(parse_rig_command("f 6").kind == RigCommand::Frequency, "f command");
  expect(std::fabs(parse_rig_command("F 6.5").value - 6.5f) < 1e-3f, "f value");
  expect(parse_rig_command("a 12").kind == RigCommand::Amplitude, "a command");
  expect(parse_rig_command("stop").kind == RigCommand::Stop, "stop command");
  expect(parse_rig_command("sweep").kind == RigCommand::Sweep, "sweep command");

  RigController sweep;
  sweep.set_amplitude(10.0f);
  sweep.start_sweep(0, 0);
  expect(std::fabs(sweep.status().set_hz - 3.0f) < 1e-3f, "sweep starts at 3 Hz");
  const float expect_hz[] = {3, 4, 5, 6, 7, 8};
  for (int i = 0; i < 6; ++i) {
    expect(std::fabs(sweep.status().set_hz - expect_hz[i]) < 1e-3f, "sweep frequency");
    sweep.update(1000, static_cast<uint32_t>((i + 1) * 15000), 0.02f, output);
  }
  expect(!sweep.status().running, "sweep did not stop");

  const float angle = rig_angle(90.0f, 10.0f, 3.141592653589793 / 2.0);
  expect(std::fabs(angle - 100.0f) < 1e-3f, "sine peak angle");

  if (g_failures != 0) {
    std::cerr << g_failures << " checks failed\n";
    return 1;
  }
  std::cout << "rig ok\n";
  return 0;
}

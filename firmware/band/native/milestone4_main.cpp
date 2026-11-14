#include "comms.h"
#include "config.h"
#include "haptics.h"
#include "signal.h"
#include "tests.h"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <string>

namespace {

int g_failures = 0;

void expect(bool ok, const char* message) {
  if (!ok) {
    std::cerr << message << "\n";
    g_failures += 1;
  }
}

void spike(GuidedTest& test, uint32_t at_ms, double height) {
  test.on_sample(0.0, at_ms);
  test.on_sample(height, at_ms + 5);
  test.on_sample(0.0, at_ms + 10);
}

}  // namespace

int main() {
  {
    Haptics haptics;
    haptics.set_intensity(1.0f);
    haptics.play(HapticPattern::Prompt, 0);
    haptics.update(0);
    expect(haptics.vibrating(), "prompt did not start the motor");
    haptics.update(80);
    expect(!haptics.vibrating(), "prompt gap still driving the motor");
    haptics.update(160);
    expect(haptics.vibrating(), "second prompt pulse missing");
    haptics.update(400);
    expect(!haptics.vibrating(), "prompt did not finish");
  }

  {
    WindowPipeline pipeline;
    WindowFeatures row{};
    ActivityLabel label{"still", 0.0};
    bool window_vibrating = false;
    bool ready = false;
    for (int i = 0; i < 256; ++i) {
      ready = pipeline.push(0.0, 0.0, 9.81, 0.2, 0.0, 0.0, row, label, i == 10, window_vibrating);
    }
    expect(ready && window_vibrating, "a vibrating sample did not flag the window");
    for (int i = 0; i < 128; ++i) {
      ready = pipeline.push(0.0, 0.0, 9.81, 0.2, 0.0, 0.0, row, label, false, window_vibrating);
    }
    expect(ready && !window_vibrating, "the next hop stayed flagged after the pulse left the window");
  }

  const WindowFeatures tremor = run_selftest();
  const ActivityLabel tremor_label = rule_label(tremor);
  expect(std::strcmp(tremor_label.label, "tremor") == 0, "selftest was not tremor");

  {
    GuidedTest test;
    Haptics haptics;
    expect(test.start(TestType::Rest, 0, haptics), "rest did not start");
    test.update(400, haptics);
    expect(test.phase() == TestPhase::Countdown, "prompt did not reach countdown");
    test.update(3400, haptics);
    expect(test.phase() == TestPhase::Record, "countdown did not reach record");
    test.on_window(tremor, tremor_label, false);
    test.on_window(tremor, tremor_label, false);
    test.on_window(tremor, tremor_label, false);
    test.on_window(tremor, tremor_label, true);
    test.update(23400, haptics);
    expect(test.phase() == TestPhase::Done, "record did not finish");
    test.update(23900, haptics);
    expect(test.phase() == TestPhase::Upload, "done did not upload");
    SessionSummary summary{};
    expect(test.take_upload(summary), "upload missing");
    expect(summary.windows == 4 && summary.included == 3, "vibrating window was included");
    expect(std::fabs(summary.quality - 0.75) < 1e-9, "quality was not the valid fraction");
    expect(std::fabs(summary.tremor_pct - 100.0) < 1e-6, "tremor percent skipped a clean window");
    expect(std::fabs(summary.median_hz - tremor.gyro.peak_hz) < 1e-6, "median peak changed");
    expect(test.phase() == TestPhase::Idle, "upload did not return to idle");
  }

  {
    GuidedTest test;
    Haptics haptics;
    ButtonTracker button;
    expect(button.update(true, 0) == PressKind::None, "press edge fired early");
    expect(button.update(true, 600) == PressKind::Long, "long press was not detected");
    expect(test.cycle_and_start(600, haptics), "long press did not start a test");
    expect(test.type() == TestType::Rest, "first long press was not rest");
    test.cancel(700, haptics);
    expect(test.phase() == TestPhase::Idle, "cancel did not return to idle");
    expect(button.update(false, 800) == PressKind::None, "release after long press looked like a tap");
    expect(button.update(true, 900) == PressKind::None, "second press edge fired");
    expect(button.update(true, 1500) == PressKind::Long, "second long press missing");
    expect(test.cycle_and_start(1500, haptics), "second long press did not cycle");
    expect(test.type() == TestType::Postural, "cycle did not reach postural");
    ButtonTracker cancel;
    expect(cancel.update(true, 0) == PressKind::None, "double setup");
    expect(cancel.update(false, 40) == PressKind::None, "first tap of a double fired");
    expect(cancel.update(true, 80) == PressKind::None, "second tap down fired");
    expect(cancel.update(false, 120) == PressKind::Double, "double press was not detected");
    test.cancel(120, haptics);
    expect(test.phase() == TestPhase::Idle, "double press did not cancel");
  }

  {
    GuidedTest test;
    Haptics haptics;
    expect(test.start(TestType::Tapping, 0, haptics), "tapping did not start");
    test.update(400, haptics);
    test.update(3400, haptics);
    const double heights[] = {30, 30, 30, 10, 10, 10};
    for (int i = 0; i < 6; ++i) {
      spike(test, 3600 + static_cast<uint32_t>(i) * 200, heights[i]);
    }
    test.update(13400, haptics);
    test.update(13900, haptics);
    SessionSummary summary{};
    expect(test.take_upload(summary), "tapping upload missing");
    expect(std::fabs(summary.taps_per_s - 0.6) < 1e-9, "taps per second");
    expect(std::fabs(summary.tap_decrement - 20.0) < 1e-6, "tap decrement");
    expect(summary.tap_interval_cv < 1e-6, "even taps reported rhythm variation");
  }

  {
    GuidedTest test;
    Haptics haptics;
    expect(test.start(TestType::FingerNose, 0, haptics), "finger nose did not start");
    test.update(400, haptics);
    test.update(3400, haptics);
    WindowFeatures row{};
    ActivityLabel label{"voluntary", 0.0};
    for (int i = 0; i < 10; ++i) {
      row.amp_deg = i < 7 ? 1.0 : 3.0;
      row.gyro.peak_hz = 2.0;
      row.log_amp = 0.0;
      test.on_window(row, label, false);
    }
    test.update(23400, haptics);
    test.update(23900, haptics);
    SessionSummary summary{};
    expect(test.take_upload(summary), "finger nose upload missing");
    expect(std::fabs(summary.intention_ratio - 3.0) < 1e-6, "intention ratio");
  }

  {
    GuidedTest test;
    Haptics haptics;
    expect(test.start(TestType::Gait, 0, haptics), "gait did not start");
    test.update(400, haptics);
    test.update(3400, haptics);
    const uint32_t gaps[] = {400, 600, 400, 600};
    uint32_t at = 3600;
    spike(test, at, 20);
    for (uint32_t gap : gaps) {
      at += gap;
      spike(test, at, 20);
    }
    test.update(33400, haptics);
    test.update(33900, haptics);
    SessionSummary summary{};
    expect(test.take_upload(summary), "gait upload missing");
    expect(std::fabs(summary.cadence_spm - 10.0) < 1e-6, "cadence");
    expect(std::fabs(summary.asymmetry_pct - 40.0) < 1e-6, "step asymmetry");
  }

  {
    const ParsedCommand run = parse_command("{\"type\":\"command\",\"cmd\":\"run_test:gait\"}");
    expect(run.kind == CommandKind::RunTest && run.test == TestType::Gait, "json run_test");
    expect(parse_command("cancel_test").kind == CommandKind::CancelTest, "cancel_test");
    expect(parse_command("vibrate:ALERT").pattern == HapticPattern::Alert, "vibrate alert");
    expect(parse_command("SELFTEST").kind == CommandKind::SelfTest, "selftest");
    expect(parse_command("set_mode:ms_mode").kind == CommandKind::SetMode, "ms mode");
    GuidedTest test;
    Haptics haptics;
    StillCalibrator calibrator;
    BandContext band{&test, &haptics, &calibrator, "passive", false, false};
    const ParsedCommand threshold = parse_command("set_threshold:still_acc_rms:0.5");
    const double saved = threshold_overrides().still_acc_rms;
    expect(apply_command(threshold, band, 0), "threshold command");
    expect(std::fabs(threshold_overrides().still_acc_rms - 0.5) < 1e-9, "threshold was not stored");
    threshold_overrides().still_acc_rms = saved;
    expect(apply_command(parse_command("calibrate_still"), band, 10), "calibrate");
    calibrator.add(0.02);
    expect(!calibrator.finished(4000), "calibration finished early");
    expect(calibrator.finished(5010), "calibration did not finish at 5 s");
    expect(std::fabs(calibrator.suggested_acc_rms() - 0.06) < 1e-9, "noise floor");
    expect(apply_command(parse_command("identify"), band, 20), "identify");
    expect(band.identify && haptics.vibrating(), "identify did not buzz");
  }

  {
    WifiSchedule schedule{};
    wifi_schedule_init(schedule, 1000);
    expect(wifi_command_due(schedule, 1000), "command poll should be due immediately");
    wifi_note_success(schedule, 1000, true);
    expect(!wifi_command_due(schedule, 2999), "command poll was early");
    expect(wifi_command_due(schedule, 3000), "command poll was not every 2 s");
    expect(wifi_heartbeat_due(schedule, 1000), "heartbeat should be due immediately");
    wifi_note_success(schedule, 1000, false);
    expect(!wifi_heartbeat_due(schedule, 14999), "heartbeat was early");
    expect(wifi_heartbeat_due(schedule, 16000), "heartbeat was not every 15 s");
    wifi_note_failure(schedule, 16000);
    expect(schedule.backoff_ms == 1000, "first backoff");
    expect(!wifi_command_due(schedule, 16500), "backoff did not hold the poll");
    expect(wifi_retry_delay_ms(3) == 4000, "backoff did not double");
    char path[80];
    expect(format_commands_path(path, static_cast<int>(sizeof(path)), "band-01") > 0, "command path");
    expect(std::strcmp(path, "/api/device/band-01/commands") == 0, "command path text");
    expect(format_heartbeat_path(path, static_cast<int>(sizeof(path)), "band-01") > 0, "heartbeat path");
    expect(std::strcmp(path, "/api/device/band-01/heartbeat") == 0, "heartbeat path text");
    expect(std::fabs(battery_percent(3.75f) - 50.0f) < 0.1f, "battery curve");
    expect(battery_is_low(10.0f) && !battery_is_low(40.0f), "low battery");
    expect(status_led_on(LinkState::Online, 250), "online LED");
    expect(status_led_on(LinkState::Offline, 0) && !status_led_on(LinkState::Offline, 500), "offline blink");
    expect(status_led_on(LinkState::Recording, 0) && !status_led_on(LinkState::Recording, 100), "record blink");
  }

  char window[640];
  char session[800];
  char body[2048];
  ActivityLabel posted = tremor_label;
  posted.p_tremor = tremor_label.p_tremor;
  expect(format_window_object(window, static_cast<int>(sizeof(window)), "2026-11-14T02:40:00Z", tremor, posted, true,
                              "rest") > 0,
         "window object");
  SessionSummary summary{};
  summary.type = TestType::Rest;
  summary.windows = 4;
  summary.included = 3;
  summary.median_hz = tremor.gyro.peak_hz;
  summary.median_log_amp = tremor.log_amp;
  summary.mean_p_tremor = tremor_label.p_tremor;
  summary.tremor_pct = 100.0;
  summary.quality = 0.75;
  expect(format_session_object(session, static_cast<int>(sizeof(session)), "2026-11-14T02:40:00Z",
                               "2026-11-14T02:40:20Z", summary) > 0,
         "session object");
  expect(format_http_ingest(body, static_cast<int>(sizeof(body)), "band-01", window, session) > 0, "ingest body");
  char queued[128];
  expect(comms_enqueue_line("{\"device_id\":\"band-01\"}") && comms_pop_line(queued, static_cast<int>(sizeof(queued))),
         "queue");
  std::cout << "INGEST " << body << "\n";

  if (g_failures != 0) {
    std::cerr << g_failures << " checks failed\n";
    return 1;
  }
  std::cout << "milestone4 ok\n";
  return 0;
}

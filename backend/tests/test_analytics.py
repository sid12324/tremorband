"""Baselines, z-scores, the adaptive line, and the synthetic demo seed."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.mkdtemp()) / 'analytics.db'}"

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, delete  # noqa: E402

from app.analytics import (  # noqa: E402
    DosePoint,
    SessionPoint,
    WindowPoint,
    above_threshold,
    adjust_threshold,
    baseline_from_points,
    data_quality,
    exclusion_reason,
    tremor_hours_by_day,
    wearing_off,
    z_score,
)
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Baseline  # noqa: E402
from scripts.seed_demo import seed_database  # noqa: E402


def _point(hours: float, log_amp: float, test_type: str = "rest") -> SessionPoint:
    return SessionPoint(
        session_id=None,
        test_type=test_type,
        ts=datetime(2026, 11, 14, tzinfo=timezone.utc) + timedelta(hours=hours),
        log_amp=log_amp,
        peak_hz=5.0,
    )


class AnalyticsMathTest(unittest.TestCase):
    def test_sample_sd_and_z_score(self) -> None:
        stats = baseline_from_points("rest", [_point(0, 1), _point(1, 2), _point(2, 3)])
        self.assertIsNotNone(stats)
        assert stats is not None
        self.assertAlmostEqual(stats.mean_log_amp, 2.0)
        self.assertAlmostEqual(stats.sd_log_amp, 1.0)
        self.assertEqual(stats.n_sessions, 3)
        self.assertAlmostEqual(z_score(4.0, stats.mean_log_amp, stats.sd_log_amp) or 0, 2.0)
        self.assertIsNone(z_score(4.0, 1.0, 0.0))
        self.assertFalse(above_threshold(2.0, 2.0))
        self.assertTrue(above_threshold(2.01, 2.0))

    def test_threshold_steps_and_limits(self) -> None:
        raised = adjust_threshold(2.0, "not_a_bad_day")
        lowered = adjust_threshold(2.0, "missed_symptoms")
        self.assertAlmostEqual(raised.new_threshold_z, 2.25)
        self.assertIn("raised", raised.reason)
        self.assertAlmostEqual(lowered.new_threshold_z, 1.75)
        self.assertIn("lowered", lowered.reason)
        capped = adjust_threshold(3.5, "not_a_bad_day")
        floored = adjust_threshold(1.0, "missed_symptoms")
        self.assertAlmostEqual(capped.new_threshold_z, 3.5)
        self.assertIn("limit", capped.reason)
        self.assertAlmostEqual(floored.new_threshold_z, 1.0)
        self.assertIn("limit", floored.reason)

    def test_wearing_off_bins_and_small_samples(self) -> None:
        dose = [DosePoint(ts=datetime(2026, 11, 14, tzinfo=timezone.utc))]
        late_edge = wearing_off([_point(5.0, 1.0), _point(4.9, 0.5)], dose)
        self.assertEqual(late_edge["bins"][3]["n"], 1)
        self.assertEqual(late_edge["bins"][2]["n"], 1)
        self.assertEqual(late_edge["confidence"], "insufficient")
        early = [_point(0.5, -0.5) for _ in range(3)]
        late = [_point(3.5, 0.0) for _ in range(3)]
        report = wearing_off(early + late, dose)
        self.assertEqual(report["confidence"], "low")
        self.assertAlmostEqual(report["median_difference"], 0.5)
        self.assertIn("not a diagnosis", str(report["finding"]))

    def test_quality_exclusion_order(self) -> None:
        vibrating = WindowPoint(vibrating=True, log_amp=None, peak_hz=None, label=None)
        self.assertEqual(exclusion_reason(vibrating), "vibration")
        missing = WindowPoint(log_amp=None, peak_hz=5, label="tremor", rms=0.2)
        empty = WindowPoint(log_amp=-0.2, peak_hz=0, label="still", rms=0)
        used = WindowPoint(log_amp=-0.2, peak_hz=5, label="tremor", rms=0.2)
        report = data_quality([used, used, vibrating, missing, empty])
        self.assertEqual(report["excluded_vibration"], 1)
        self.assertEqual(report["excluded_missing"], 1)
        self.assertEqual(report["excluded_low_quality"], 1)
        self.assertEqual(report["n_used"], 2)
        self.assertAlmostEqual(report["quality"], 0.4)

    def test_short_passive_gaps_do_not_count_as_full_hours(self) -> None:
        start = datetime(2026, 11, 14, 8, tzinfo=timezone.utc)
        hourly = [(start + timedelta(hours=index), 50.0) for index in range(2)]
        dense = [(start + timedelta(seconds=10 * index), 50.0) for index in range(6)]
        hourly_total = tremor_hours_by_day(hourly)[0]["tremor_hours"]
        dense_total = tremor_hours_by_day(dense)[0]["tremor_hours"]
        self.assertAlmostEqual(hourly_total, 1.0)
        self.assertLess(dense_total, 0.1)


class AnalyticsApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)

    def setUp(self) -> None:
        with Session(engine) as session:
            session.exec(delete(Baseline))
            session.commit()
            seed_database(session, reset=True)

    def test_seed_is_synthetic_and_rises_after_the_dose(self) -> None:
        metrics = self.client.get("/api/metrics?days=14").json()
        self.assertEqual(len(metrics), 28)
        self.assertTrue(all(row["is_synthetic"] for row in metrics))
        rest = [row for row in metrics if row["test_type"] == "rest"]
        self.assertAlmostEqual(min(row["hours_since_dose"] for row in rest), 0.5)
        self.assertAlmostEqual(max(row["hours_since_dose"] for row in rest), 3.5)
        self.assertLess(rest[0]["z"], 0)
        self.assertGreater(rest[-1]["z"], 0)
        self.assertFalse(rest[0]["above_threshold"])
        report = self.client.get("/api/analytics/wearing-off?days=14").json()
        self.assertEqual(report["confidence"], "moderate")
        self.assertGreater(report["median_difference"], 0.3)
        self.assertEqual(report["bins"][0]["n"], 14)
        self.assertEqual(report["bins"][2]["n"], 14)
        self.assertIn("not a diagnosis", report["finding"])
        self.assertNotIn("you should", report["finding"])
        doses = self.client.get("/api/medications").json()
        self.assertEqual(len(doses), 7)
        self.assertTrue(all(row["name"] == "Recorded dose" for row in doses))

    def test_feedback_moves_the_line_and_recompute_keeps_it(self) -> None:
        metrics = self.client.get("/api/metrics?test_type=rest&days=14").json()
        response = self.client.post(
            "/api/feedback",
            json={"kind": "not_a_bad_day", "session_id": metrics[0]["id"]},
        )
        self.assertEqual(response.status_code, 200)
        change = response.json()["changes"][0]
        self.assertAlmostEqual(change["old_threshold_z"], 2.0)
        self.assertAlmostEqual(change["new_threshold_z"], 2.25)
        self.assertIn("raised", change["reason"])
        baselines = {row["test_type"]: row for row in self.client.get("/api/baseline").json()}
        self.assertAlmostEqual(baselines["rest"]["threshold_z"], 2.25)
        self.assertAlmostEqual(baselines["postural"]["threshold_z"], 2.0)
        recomputed = {
            row["test_type"]: row for row in self.client.post("/api/baseline/recompute").json()
        }
        self.assertAlmostEqual(recomputed["rest"]["threshold_z"], 2.25)
        self.assertGreater(recomputed["rest"]["n_sessions"], 0)

    def test_tags_quality_and_tremor_hours(self) -> None:
        tags = {row["tag"]: row for row in self.client.get("/api/analytics/tags?days=14").json()}
        for name in ("stress", "caffeine", "poor sleep"):
            self.assertEqual(tags[name]["n_tagged"], 4)
            self.assertGreaterEqual(tags[name]["n_untagged"], 2)
            self.assertIn("not a diagnosis", tags[name]["finding"])
            self.assertIn("association", tags[name]["finding"])
        quality = self.client.get("/api/analytics/quality?days=14").json()
        self.assertEqual(quality["n_windows"], 112)
        self.assertEqual(quality["excluded_vibration"], 28)
        self.assertEqual(quality["n_used"], 84)
        self.assertAlmostEqual(quality["quality"], 0.75)
        hours = self.client.get("/api/analytics/tremor-hours?days=14").json()
        self.assertEqual(len(hours), 7)
        for day in hours:
            self.assertAlmostEqual(day["tremor_hours"], 3.45, places=6)
        reset = self.client.post("/api/demo/reset").json()
        self.assertEqual(reset["sessions"], 28)
        self.assertTrue(reset["is_synthetic"])
        self.assertEqual(len(self.client.get("/api/metrics?days=14").json()), 28)


if __name__ == "__main__":
    unittest.main()

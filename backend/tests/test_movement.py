"""Tapping and gait summaries, plus export and delete confirmation."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.mkdtemp()) / 'records.db'}"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.movement import gait_summary, intention_ratio, tapping_summary  # noqa: E402


def _taps() -> list[tuple[int, float]]:
    samples: list[tuple[int, float]] = []
    clock = 0
    for index in range(8):
        samples.extend([(clock, 1.0), (clock + 30, 10.0 - index * 0.5), (clock + 60, 1.0)])
        clock += 540 if index % 2 == 0 else 460
    return samples


class MovementTest(unittest.TestCase):
    def test_tapping_rate_and_decrement(self) -> None:
        summary = tapping_summary(_taps(), 10.0)
        self.assertAlmostEqual(summary["taps_per_s"], 0.8)
        self.assertGreater(summary["tap_decrement"], 0.0)
        self.assertGreater(summary["tap_interval_cv"], 0.0)

    def test_gait_asymmetry_and_intention_ratio(self) -> None:
        samples: list[tuple[int, float]] = []
        clock = 0
        for index in range(8):
            samples.extend([(clock, 1.0), (clock + 40, 9.0), (clock + 80, 1.0)])
            clock += 500 if index % 2 == 0 else (700 if index < 4 else 900)
        summary = gait_summary(samples, 30.0)
        self.assertAlmostEqual(summary["cadence_spm"], 16.0)
        self.assertGreater(summary["asymmetry_pct"], 0.0)
        self.assertGreater(summary["stride_cv"], 0.0)
        self.assertAlmostEqual(intention_ratio([1, 1, 1, 1, 1, 1, 1, 2, 2, 2]), 2.0)


class RecordsApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)

    def test_settings_export_and_delete_phrase(self) -> None:
        saved = self.client.put(
            "/api/settings",
            json={
                "transport": "simulator",
                "ms_mode": True,
                "sleep_start_hour": 22,
                "sleep_end_hour": 7,
                "haptic_intensity": 40,
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertTrue(saved.json()["ms_mode"])
        exported = self.client.get("/api/export.csv")
        self.assertEqual(exported.status_code, 200)
        self.assertIn("# sessions", exported.text)
        self.assertIn("care_settings", exported.text)
        refused = self.client.request("DELETE", "/api/data", json={"confirm": "no"})
        self.assertEqual(refused.status_code, 400)
        removed = self.client.request("DELETE", "/api/data", json={"confirm": "delete my data"})
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(self.client.get("/api/settings").json()["haptic_intensity"], 70)


if __name__ == "__main__":
    unittest.main()

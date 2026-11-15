"""The capture switch opens a session and tags windows ingested while it is on."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.mkdtemp()) / 'capture.db'}"
os.environ["TREMORBAND_MODEL"] = "mock"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _window(ts: str, session_id: int | None = None) -> dict:
    body = {
        "ts": ts,
        "peak_hz": 5.0,
        "band_power": 0.2,
        "rms": 0.1,
        "sharpness": 0.6,
        "amp_deg": 2.0,
        "disp_mm": 1.0,
        "log_amp": 0.3,
        "label": "tremor",
        "p_tremor": 0.8,
        "vibrating": False,
    }
    if session_id is not None:
        body["session_id"] = session_id
    return body


class CaptureSwitchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)

    def test_each_on_creates_a_session_and_windows_follow_it(self) -> None:
        idle = self.client.get("/api/capture")
        self.assertEqual(idle.status_code, 200)
        self.assertFalse(idle.json()["on"])

        first = self.client.post("/api/capture", json={"on": True})
        self.assertEqual(first.status_code, 200)
        first_id = first.json()["session_id"]
        self.assertIsNotNone(first_id)
        again = self.client.post("/api/capture", json={"on": True})
        self.assertEqual(again.json()["session_id"], first_id)

        stamp = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc).isoformat()
        ingested = self.client.post(
            "/api/ingest",
            json={
                "device_id": "band-01",
                "device_name": "Band",
                "windows": [_window(stamp)],
            },
        )
        self.assertEqual(ingested.status_code, 200)
        listed = self.client.get("/api/windows?device_id=band-01&limit=5")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[-1]["session_id"], first_id)

        stopped = self.client.post("/api/capture", json={"on": False})
        self.assertFalse(stopped.json()["on"])
        closed = stopped.json()["sessions"][0]
        self.assertEqual(closed["id"], first_id)
        self.assertIsNotNone(closed["ts_end"])
        self.assertEqual(closed["n_windows"], 1)

        later = datetime(2026, 11, 15, 12, 1, tzinfo=timezone.utc).isoformat()
        outside = self.client.post(
            "/api/ingest",
            json={"device_id": "band-01", "windows": [_window(later)]},
        )
        self.assertEqual(outside.status_code, 200)
        listed = self.client.get("/api/windows?device_id=band-01&limit=5")
        self.assertIsNone(listed.json()[-1]["session_id"])

        second = self.client.post("/api/capture", json={"on": True})
        second_id = second.json()["session_id"]
        self.assertNotEqual(second_id, first_id)
        third_stamp = datetime(2026, 11, 15, 12, 2, tzinfo=timezone.utc).isoformat()
        self.client.post(
            "/api/ingest",
            json={"device_id": "other-band", "windows": [_window(third_stamp)]},
        )
        other = self.client.get("/api/windows?device_id=other-band&limit=5")
        self.assertEqual(other.json()[-1]["session_id"], second_id)
        self.client.post("/api/capture", json={"on": False})

    def test_explicit_session_id_is_kept(self) -> None:
        opened = self.client.post(
            "/api/ingest",
            json={
                "device_id": "band-02",
                "sessions": [
                    {
                        "ts_start": datetime(2026, 11, 15, 13, 0, tzinfo=timezone.utc).isoformat(),
                        "test_type": "rest",
                        "is_synthetic": True,
                    }
                ],
            },
        )
        self.assertEqual(opened.status_code, 200)
        session_id = opened.json()["session_ids"][0]
        self.client.post("/api/capture", json={"on": True})
        posted = self.client.post(
            "/api/ingest",
            json={
                "device_id": "band-02",
                "windows": [
                    _window(datetime(2026, 11, 15, 13, 1, tzinfo=timezone.utc).isoformat(), session_id)
                ],
            },
        )
        self.assertEqual(posted.status_code, 200)
        listed = self.client.get("/api/windows?device_id=band-02&limit=5")
        self.assertEqual(listed.json()[-1]["session_id"], session_id)
        self.client.post("/api/capture", json={"on": False})

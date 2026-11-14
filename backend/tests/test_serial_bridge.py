"""Serial JSON lines go through the same ingest path as HTTP."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.mkdtemp()) / 'bridge.db'}"

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.serial_bridge import consume_line  # noqa: E402

NOW = datetime(2026, 11, 14, 2, 30, tzinfo=timezone.utc)
WINDOW = (
    '{"type":"window","device_id":"band-01","ts_us":1000,"peak_hz":4.953799,'
    '"band_power":12.5,"rms":13.8,"sharpness":0.994,"amp_deg":0.640000,'
    '"disp_mm":0.570000,"log_amp":-0.193820,"label":"tremor","p_tremor":0.994,'
    '"vibrating":false,"peak_hz_acc":4.953799,"peak_hz_gyro":4.953799}\n'
)


class SerialBridgeTest(unittest.TestCase):
    def test_window_line_is_stored_like_http_ingest(self) -> None:
        with TestClient(app) as client:
            with Session(engine) as session:
                self.assertEqual(consume_line(session, "not json\n", now=NOW), "ignored")
                self.assertEqual(consume_line(session, WINDOW, now=NOW), "window")
                self.assertEqual(
                    consume_line(
                        session,
                        '{"type":"heartbeat","device_id":"band-01","fw_version":"0.3.0","mode":"serial"}\n',
                        now=NOW,
                    ),
                    "heartbeat",
                )
                self.assertEqual(consume_line(session, '{"type":"window","label":"maybe"}\n', now=NOW), "rejected")
            windows = client.get("/api/windows", params={"device_id": "band-01"}).json()
            self.assertEqual(len(windows), 1)
            self.assertEqual(windows[0]["label"], "tremor")
            self.assertAlmostEqual(windows[0]["peak_hz"], 4.953799)
            self.assertEqual(windows[0]["device_id"], "band-01")
            device = client.get("/api/device/band-01").json()
            self.assertEqual(device["mode"], "serial")
            self.assertEqual(device["fw_version"], "0.3.0")
            self.assertNotIn("sim", device["fw_version"])
            with Session(engine) as session:
                self.assertEqual(
                    consume_line(
                        session,
                        '{"type":"session","device_id":"band-01","test_type":"rest",'
                        '"ts_start":"2026-11-14T02:40:00Z","ts_end":"2026-11-14T02:40:20Z",'
                        '"quality":0.75,"summary":{"tremor_pct":100}}\n',
                        now=NOW,
                    ),
                    "session",
                )
            listed = client.get("/api/windows", params={"device_id": "band-01"}).json()
            self.assertEqual(len(listed), 1)


if __name__ == "__main__":
    unittest.main()

"""Rig accuracy math and the host-side SG90 controller."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.mkdtemp()) / 'rig.db'}"

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.serial_bridge import consume_line  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


class RigAccuracyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        build = REPO / "firmware" / "rig" / "build-host"
        build.mkdir(parents=True, exist_ok=True)
        binary = build / "rig_test"
        compile_cmd = [
            "g++",
            "-std=c++17",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(REPO / "firmware" / "rig"),
            str(REPO / "firmware" / "rig" / "rig_control.cpp"),
            str(REPO / "firmware" / "rig" / "native" / "rig_main.cpp"),
            "-o",
            str(binary),
            "-lm",
        ]
        compiled = subprocess.run(compile_cmd, check=False, capture_output=True, text=True)
        if compiled.returncode != 0:
            raise AssertionError(compiled.stderr or compiled.stdout)
        ran = subprocess.run([str(binary)], check=False, capture_output=True, text=True)
        if ran.returncode != 0:
            raise AssertionError(ran.stderr + ran.stdout)
        if "rig ok" not in ran.stdout:
            raise AssertionError(ran.stdout)

    def test_accuracy_groups_band_measurements(self) -> None:
        with TestClient(app) as client:
            empty = client.get("/api/rig/accuracy")
            self.assertEqual(empty.status_code, 200)
            self.assertIsNone(empty.json()["mae_hz"])
            self.assertEqual(empty.json()["n"], 0)
            rejected = client.post("/api/rig/run", json={"set_hz": 0, "band_hz": 0})
            self.assertEqual(rejected.status_code, 422)
            posted = []
            for body in (
                {"set_hz": 5, "band_hz": 4.9, "amp_set": 10, "amp_band": 9},
                {"set_hz": 5, "band_hz": 5.1, "measured_hz": 5.0},
                {"set_hz": 8, "band_hz": 7.6},
            ):
                response = client.post("/api/rig/run", json=body)
                self.assertEqual(response.status_code, 200, response.text)
                posted.append(response.json())
            self.assertEqual(posted[0]["set_hz"], 5)
            report = client.get("/api/rig/accuracy").json()
            self.assertEqual(report["n"], 3)
            self.assertAlmostEqual(report["mae_hz"], 0.2)
            by_hz = {row["set_hz"]: row for row in report["rows"]}
            self.assertEqual(set(by_hz), {5.0, 8.0})
            self.assertEqual(by_hz[5.0]["n"], 2)
            self.assertAlmostEqual(by_hz[5.0]["mae_hz"], 0.1)
            self.assertAlmostEqual(by_hz[5.0]["mean_pct_error"], 0.0)
            self.assertAlmostEqual(by_hz[5.0]["mean_band_hz"], 5.0)
            self.assertAlmostEqual(by_hz[8.0]["mae_hz"], 0.4)
            self.assertAlmostEqual(by_hz[8.0]["mean_pct_error"], -5.0)
            self.assertEqual([point["compared_hz"] for point in report["points"]], [4.9, 5.1, 7.6])
            self.assertAlmostEqual(report["points"][2]["error_pct"], -5.0)
            with Session(engine) as session:
                self.assertEqual(
                    consume_line(
                        session,
                        '{"type":"rig","set_hz":5.0,"measured_hz":4.99,"amp_deg":10}\n',
                    ),
                    "rig",
                )
            after = client.get("/api/rig/accuracy").json()
            self.assertEqual(after["n"], 4)
            self.assertAlmostEqual(after["points"][-1]["compared_hz"], 4.99)
            self.assertAlmostEqual(after["points"][-1]["amp_set"], 10)
            self.assertIsNone(after["points"][-1]["band_hz"])


if __name__ == "__main__":
    unittest.main()

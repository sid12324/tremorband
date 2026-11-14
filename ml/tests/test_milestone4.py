"""Host checks for haptics, guided tests, and the Wi-Fi ingest body."""

from __future__ import annotations

import json
import subprocess
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INCLUDE = ROOT / "firmware" / "band" / "include"
SOURCES = [
    ROOT / "firmware" / "band" / "src" / "signal.cpp",
    ROOT / "firmware" / "band" / "src" / "haptics.cpp",
    ROOT / "firmware" / "band" / "src" / "tests.cpp",
    ROOT / "firmware" / "band" / "src" / "comms.cpp",
    ROOT / "firmware" / "band" / "native" / "milestone4_main.cpp",
]
BINARY = ROOT / "firmware" / "band" / "build-host" / "milestone4"


def _compile() -> None:
    BINARY.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{INCLUDE}",
            *[str(path) for path in SOURCES],
            "-o",
            str(BINARY),
            "-lm",
        ],
        check=True,
    )


class Milestone4Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _compile()
        completed = subprocess.run([str(BINARY)], text=True, capture_output=True, check=False)
        cls.completed = completed

    def test_host_checks_pass(self) -> None:
        self.assertEqual(self.completed.returncode, 0, self.completed.stdout + self.completed.stderr)
        self.assertIn("milestone4 ok", self.completed.stdout)

    def test_wifi_ingest_body_reaches_the_api(self) -> None:
        self.assertEqual(self.completed.returncode, 0, self.completed.stderr)
        line = next(item for item in self.completed.stdout.splitlines() if item.startswith("INGEST "))
        body = json.loads(line.removeprefix("INGEST "))
        self.assertTrue(body["windows"][0]["vibrating"])
        self.assertEqual(body["windows"][0]["test_type"], "rest")
        self.assertEqual(body["sessions"][0]["test_type"], "rest")
        self.assertEqual(body["sessions"][0]["quality"], 0.75)
        self.assertEqual(body["sessions"][0]["summary"]["tremor_pct"], 100.0)
        request = urllib.request.Request(
            "http://127.0.0.1:8000/api/ingest",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode())
        self.assertEqual(payload["device_id"], "band-01")
        self.assertEqual(len(payload["window_ids"]), 1)
        self.assertEqual(len(payload["session_ids"]), 1)
        window_id = payload["window_ids"][0]
        listed = urllib.request.urlopen(
            "http://127.0.0.1:8000/api/windows?device_id=band-01&limit=20",
            timeout=5,
        )
        windows = json.loads(listed.read().decode())
        match = next(item for item in windows if item["id"] == window_id)
        self.assertTrue(match["vibrating"])
        self.assertEqual(match["test_type"], "rest")
        self.assertEqual(match["label"], "tremor")


if __name__ == "__main__":
    unittest.main()

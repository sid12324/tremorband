"""Firmware signal.cpp and ml/features.py must agree on the same samples."""

from __future__ import annotations

import json
import math
import subprocess
import unittest
from pathlib import Path

from ml.features import FS_HZ, HOP, WINDOW_N, compute_windows, selftest_samples, synthetic_imu

ROOT = Path(__file__).resolve().parents[2]
INCLUDE = ROOT / "firmware" / "band" / "include"
SIGNAL = ROOT / "firmware" / "band" / "src" / "signal.cpp"
BUILD = ROOT / "firmware" / "band" / "build-host"
FEATURES_BIN = BUILD / "features_cli"
SELFTEST_BIN = BUILD / "selftest"
ABS_TOL = 1e-6
REL_TOL = 1e-6


def _compile(source: Path, output: Path) -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "g++",
            "-std=c++17",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{INCLUDE}",
            str(SIGNAL),
            str(source),
            "-o",
            str(output),
            "-lm",
        ],
        check=True,
    )


def _run_cli(samples: tuple[list[float], ...]) -> list[dict[str, float]]:
    if not FEATURES_BIN.exists():
        _compile(ROOT / "firmware" / "band" / "native" / "features_main.cpp", FEATURES_BIN)
    lines = [str(len(samples[0]))]
    for row in zip(*samples):
        lines.append(" ".join(f"{value:.17g}" for value in row))
    completed = subprocess.run(
        [str(FEATURES_BIN)],
        input="\n".join(lines) + "\n",
        text=True,
        capture_output=True,
        check=True,
    )
    return [json.loads(line) for line in completed.stdout.splitlines() if line]


class FeatureParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _compile(ROOT / "firmware" / "band" / "native" / "features_main.cpp", FEATURES_BIN)
        _compile(ROOT / "firmware" / "band" / "native" / "selftest_main.cpp", SELFTEST_BIN)

    def test_constants_match_firmware_header(self) -> None:
        header = (INCLUDE / "config.h").read_text()
        self.assertIn("constexpr float TB_FS_HZ = 104.0f;", header)
        self.assertEqual(FS_HZ, 104.0)
        self.assertEqual(WINDOW_N, 256)
        self.assertEqual(HOP, 128)

    def test_selftest_prints_five_hertz(self) -> None:
        completed = subprocess.run([str(SELFTEST_BIN)], text=True, capture_output=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        text = completed.stdout.strip()
        self.assertTrue(text.startswith("selftest "))
        fields = dict(part.split("=", 1) for part in text.split()[1:])
        acc = float(fields["acc_peak_hz"])
        gyro = float(fields["gyro_peak_hz"])
        self.assertAlmostEqual(acc, 5.0, delta=0.05)
        self.assertAlmostEqual(gyro, 5.0, delta=0.05)

    def test_selftest_samples_agree(self) -> None:
        self._assert_agree(selftest_samples())

    def test_sinusoids_with_noise_agree(self) -> None:
        for freq in (3.0, 5.0, 8.0):
            samples = synthetic_imu(freq, noise_a=0.02, noise_g=0.4, n=768, seed=int(freq))
            cpp_rows, py_rows = self._assert_agree(samples)
            self.assertAlmostEqual(py_rows[-1].acc.peak_hz, freq, delta=0.25)
            self.assertAlmostEqual(py_rows[-1].gyro.peak_hz, freq, delta=0.25)
            self.assertGreater(len(cpp_rows), 0)

    def _assert_agree(self, samples: tuple[list[float], ...]) -> tuple[list[dict[str, float]], list]:
        cpp_rows = _run_cli(samples)
        py_rows = compute_windows(*samples)
        self.assertEqual(len(cpp_rows), len(py_rows))
        self.assertGreater(len(py_rows), 0)
        for cpp, py in zip(cpp_rows, py_rows):
            self.assertEqual(cpp["fs"], FS_HZ)
            self.assertEqual(cpp["n"], WINDOW_N)
            self.assertEqual(cpp["hop"], HOP)
            for key, value in py.as_dict().items():
                self.assertTrue(
                    math.isclose(cpp[key], value, rel_tol=REL_TOL, abs_tol=ABS_TOL),
                    f"{key}: firmware {cpp[key]} python {value}",
                )
        return cpp_rows, py_rows


if __name__ == "__main__":
    unittest.main()

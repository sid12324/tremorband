#!/usr/bin/env python3
"""Post realistic feature windows from a simulated band.

The amplitude envelope is a demo waveform so the Live page moves. It is not a
clinical model and it is not medication guidance.

TremorBand is a monitoring aid, not a diagnostic device.
"""

from __future__ import annotations

import argparse
import logging
import math
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

FS_HZ = 104.0
WINDOW_SAMPLES = 256
HOP_SAMPLES = 128
HOP_S = HOP_SAMPLES / FS_HZ
BIN_HZ = FS_HZ / WINDOW_SAMPLES
HEARTBEAT_S = 15.0
COMMAND_POLL_S = 2.0
PASSIVE_S = 10.0
TEST_WINDOWS = {
    "rest": 16,
    "postural": 16,
    "finger_nose": 16,
    "tapping": 8,
    "gait": 24,
}
def _guided_metrics(test_type: str | None) -> dict[str, float]:
    """Synthetic gyro peaks so a simulated test still has tapping or gait numbers."""
    from app.movement import gait_summary, intention_ratio, tapping_summary

    if test_type == "tapping":
        samples = []
        for index in range(10):
            at = index * 400
            samples.extend([(at, 1.0), (at + 40, 12.0 - index * 0.4), (at + 80, 1.0)])
        return tapping_summary(samples, 10.0)
    if test_type == "gait":
        samples = []
        for index in range(20):
            gap = 520 if index % 2 == 0 else 560
            at = index * gap
            samples.extend([(at, 1.0), (at + 40, 8.0), (at + 80, 1.0)])
        return gait_summary(samples, 30.0)
    if test_type == "finger_nose":
        return {"intention_ratio": intention_ratio([1.0] * 7 + [1.4] * 3)}
    return {}


CYCLE = (
    ("tremor", 6),
    ("still", 4),
    ("voluntary", 4),
    ("tremor", 6),
)

logger = logging.getLogger("sim_device")


def utcnow() -> datetime:
    """Current UTC time."""
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    """ISO-8601 timestamp with milliseconds."""
    current = value or utcnow()
    return current.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def amplitude_envelope(simulated_hours: float) -> float:
    """Unitless gain over a repeating six-hour simulated clock.

    The gain stays lower for the first two hours, rises through hour five,
    then holds. Callers multiply tremor amplitude by this number.
    """
    since_mark = simulated_hours % 6.0
    if since_mark < 2.0:
        return 0.75
    if since_mark < 5.0:
        return 0.75 + (since_mark - 2.0) / 3.0 * 0.55
    return 1.30


def spectrum_for(kind: str, peak_hz: float, rng: random.Random) -> list[dict[str, float]]:
    """Build a 0–15 Hz display spectrum consistent with this window."""
    bins: list[dict[str, float]] = []
    limit = int(15.0 / BIN_HZ)
    for index in range(limit + 1):
        hz = index * BIN_HZ
        noise = abs(rng.gauss(0, 0.02))
        if kind == "tremor":
            peak = math.exp(-0.5 * ((hz - peak_hz) / 0.35) ** 2)
            power = noise * 0.25 + peak
        elif kind == "voluntary":
            broad = 0.45 * math.exp(-0.5 * ((hz - 2.2) / 2.4) ** 2)
            power = noise + broad
        else:
            power = noise
        bins.append({"hz": round(hz, 4), "power": round(max(0.0, power), 4)})
    return bins


def median(values: list[float]) -> float:
    """Median of a non-empty list."""
    return float(statistics.median(values))


class Simulator:
    """Stateful fake band."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.device_id = args.device_id
        self.name = args.name
        self.base_hz = args.peak_hz
        self.base_amp = args.amp_deg
        self.hour_seconds = args.hour_seconds
        self.rng = random.Random(args.seed)
        self.started = time.monotonic()
        self.battery = 86.0
        self.rssi = -54.0
        self.mode = "passive"
        self.kind = "tremor"
        self.kind_left = 0
        self.cycle_index = 0
        self.vibrating_left = 0
        self.test_type: str | None = None
        self.test_left = 0
        self.session_id: int | None = None
        self.test_windows: list[dict[str, Any]] = []
        self.passive_buffer: list[dict[str, Any]] = []
        self._advance_kind()

    def uptime_s(self) -> float:
        return time.monotonic() - self.started

    def simulated_hours(self) -> float:
        return self.uptime_s() / self.hour_seconds

    def _advance_kind(self) -> None:
        kind, count = CYCLE[self.cycle_index % len(CYCLE)]
        self.cycle_index += 1
        self.kind = kind
        self.kind_left = count

    def start_test(self, client: httpx.Client, test_type: str) -> None:
        """Open a synthetic session and hold the band in test mode."""
        if test_type not in TEST_WINDOWS:
            logger.info("ignored unknown test type %s", test_type)
            return
        if self.session_id is not None:
            self.finish_test(client, cancelled=True)
        response = client.post(
            "/api/ingest",
            json={
                "device_id": self.device_id,
                "device_name": self.name,
                "sessions": [
                    {
                        "ts_start": iso(),
                        "test_type": test_type,
                        "is_synthetic": True,
                    }
                ],
            },
        )
        response.raise_for_status()
        self.session_id = int(response.json()["session_ids"][0])
        self.test_type = test_type
        self.test_left = TEST_WINDOWS[test_type]
        self.test_windows = []
        self.mode = "test"
        logger.info("started synthetic %s session %s", test_type, self.session_id)

    def finish_test(self, client: httpx.Client, cancelled: bool) -> None:
        """Close the open session with a numeric summary."""
        if self.session_id is None or self.test_type is None:
            self.mode = "passive"
            return
        rows = self.test_windows
        tremor_rows = [row for row in rows if row["label"] == "tremor" and not row["vibrating"]]
        usable = tremor_rows or rows
        valid = [row for row in rows if not row["vibrating"]]
        summary = {
            "median_peak_hz": round(median([row["peak_hz"] for row in usable]), 3) if usable else None,
            "median_log_amp": round(median([row["log_amp"] for row in usable]), 3) if usable else None,
            "mean_p_tremor": round(
                sum(row["p_tremor"] for row in rows) / len(rows),
                3,
            )
            if rows
            else None,
            "tremor_pct": round(100.0 * len(tremor_rows) / len(rows), 1) if rows else 0.0,
            "n_windows": len(rows),
            "cancelled": cancelled,
            "is_synthetic": True,
            **_guided_metrics(self.test_type),
        }
        quality = (len(valid) / len(rows)) if rows else 0.0
        response = client.post(
            "/api/ingest",
            json={
                "device_id": self.device_id,
                "sessions": [
                    {
                        "id": self.session_id,
                        "test_type": self.test_type,
                        "ts_end": iso(),
                        "summary": summary,
                        "quality": round(quality, 3),
                        "is_synthetic": True,
                    }
                ],
            },
        )
        response.raise_for_status()
        logger.info("closed session %s cancelled=%s", self.session_id, cancelled)
        self.session_id = None
        self.test_type = None
        self.test_left = 0
        self.test_windows = []
        self.mode = "passive"

    def handle_command(self, client: httpx.Client, cmd: str) -> None:
        """Apply one command the API marked sent."""
        if cmd == "identify":
            logger.info("identify acknowledged")
            return
        if cmd == "cancel_test":
            self.finish_test(client, cancelled=True)
            return
        if cmd.startswith("vibrate:"):
            pattern = cmd.split(":", 1)[1]
            self.vibrating_left = 2
            logger.info("vibrate pattern=%s for the next two windows", pattern)
            return
        if cmd.startswith("run_test:"):
            self.start_test(client, cmd.split(":", 1)[1])
            return
        logger.info("ignored command %s", cmd)

    def poll_commands(self, client: httpx.Client) -> None:
        response = client.get(f"/api/device/{self.device_id}/commands")
        if response.status_code == 404:
            return
        response.raise_for_status()
        for item in response.json():
            self.handle_command(client, str(item["cmd"]))

    def heartbeat(self, client: httpx.Client) -> None:
        self.battery = min(100.0, max(15.0, self.battery + self.rng.uniform(-0.15, 0.05)))
        self.rssi = min(-40.0, max(-90.0, self.rssi + self.rng.uniform(-1.5, 1.5)))
        response = client.post(
            f"/api/device/{self.device_id}/heartbeat",
            json={
                "name": self.name,
                "battery": round(self.battery, 1),
                "rssi": round(self.rssi, 1),
                "fw_version": "0.1.0-sim",
                "mode": self.mode,
                "uptime_s": round(self.uptime_s(), 1),
            },
        )
        response.raise_for_status()

    def next_window(self) -> dict[str, Any]:
        """Sample one feature window from the current state."""
        if self.kind_left <= 0:
            self._advance_kind()
        self.kind_left -= 1
        kind = self.kind
        gain = amplitude_envelope(self.simulated_hours())
        vibrating = self.vibrating_left > 0
        if vibrating:
            self.vibrating_left -= 1

        if kind == "tremor":
            peak_hz = min(12.0, max(3.0, self.base_hz + self.rng.gauss(0, 0.08)))
            amp_deg = max(0.2, self.base_amp * gain * self.rng.uniform(0.92, 1.08))
            if vibrating:
                amp_deg *= 1.35
            sharpness = self.rng.uniform(0.58, 0.84) if not vibrating else self.rng.uniform(0.35, 0.6)
            band_power = 0.22 * amp_deg**2
            rms = 0.045 * amp_deg
            disp_mm = max(0.1, amp_deg * 0.9 + self.rng.gauss(0, 0.08))
            p_tremor = self.rng.uniform(0.78, 0.96)
            label = "tremor"
        elif kind == "voluntary":
            peak_hz = min(12.0, max(0.4, self.rng.uniform(1.2, 7.5)))
            amp_deg = max(0.3, self.rng.uniform(1.5, 8.0) * (0.85 + 0.15 * gain))
            sharpness = self.rng.uniform(0.08, 0.28)
            band_power = self.rng.uniform(0.15, 1.4)
            rms = self.rng.uniform(0.18, 0.75)
            disp_mm = self.rng.uniform(2.0, 18.0)
            p_tremor = self.rng.uniform(0.04, 0.22)
            label = "voluntary"
        else:
            peak_hz = self.rng.uniform(0.3, 2.2)
            amp_deg = self.rng.uniform(0.04, 0.25)
            sharpness = self.rng.uniform(0.02, 0.16)
            band_power = self.rng.uniform(0.001, 0.04)
            rms = self.rng.uniform(0.004, 0.03)
            disp_mm = self.rng.uniform(0.02, 0.2)
            p_tremor = self.rng.uniform(0.0, 0.06)
            label = "still"

        if vibrating:
            rms += 0.05
            band_power += 0.1

        window = {
            "ts": iso(),
            "session_id": self.session_id,
            "test_type": self.test_type,
            "peak_hz": round(peak_hz, 3),
            "band_power": round(max(0.0, band_power), 4),
            "rms": round(max(0.0, rms), 4),
            "sharpness": round(max(0.0, sharpness), 4),
            "amp_deg": round(max(0.0, amp_deg), 3),
            "disp_mm": round(max(0.0, disp_mm), 3),
            "log_amp": round(math.log10(max(amp_deg, 1e-3)), 4),
            "label": label,
            "p_tremor": round(min(1.0, max(0.0, p_tremor)), 3),
            "vibrating": vibrating,
            "spectrum": spectrum_for(kind, peak_hz, self.rng),
        }
        return window

    def post_window(self, client: httpx.Client) -> None:
        window = self.next_window()
        if self.test_left > 0:
            self.test_left -= 1
            self.test_windows.append(window)
        response = client.post(
            "/api/ingest",
            json={
                "device_id": self.device_id,
                "device_name": self.name,
                "windows": [window],
            },
        )
        response.raise_for_status()
        self.passive_buffer.append(window)
        logger.info(
            "window label=%s peak_hz=%s amp_deg=%s p_tremor=%s vibrating=%s",
            window["label"],
            window["peak_hz"],
            window["amp_deg"],
            window["p_tremor"],
            window["vibrating"],
        )
        if self.test_type is not None and self.test_left <= 0:
            self.finish_test(client, cancelled=False)

    def post_passive(self, client: httpx.Client) -> None:
        rows = self.passive_buffer
        self.passive_buffer = []
        if not rows:
            return
        tremor_rows = [row for row in rows if row["label"] == "tremor" and not row["vibrating"]]
        hz_source = tremor_rows or rows
        response = client.post(
            "/api/ingest",
            json={
                "device_id": self.device_id,
                "passive_summaries": [
                    {
                        "ts": iso(),
                        "tremor_pct": round(100.0 * len(tremor_rows) / len(rows), 1),
                        "median_hz": round(median([row["peak_hz"] for row in hz_source]), 3),
                        "median_log_amp": round(median([row["log_amp"] for row in hz_source]), 4),
                        "activity": round(sum(row["rms"] for row in rows) / len(rows), 4),
                    }
                ],
            },
        )
        response.raise_for_status()


def wait_for_api(client: httpx.Client) -> None:
    """Block until the health endpoint answers."""
    for _attempt in range(30):
        try:
            response = client.get("/api/health")
            if response.status_code == 200:
                logger.info("API ready at %s", client.base_url)
                return
        except httpx.HTTPError as exc:
            logger.info("waiting for API (%s)", exc.__class__.__name__)
        time.sleep(1)
    raise SystemExit(f"API did not become ready at {client.base_url}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post simulated TremorBand windows.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--device-id", default="sim-band-001")
    parser.add_argument("--name", default="Simulated Band")
    parser.add_argument("--peak-hz", type=float, default=5.0)
    parser.add_argument("--amp-deg", type=float, default=4.0)
    parser.add_argument(
        "--hour-seconds",
        type=float,
        default=20.0,
        help="Wall-clock seconds per simulated hour in the amplitude envelope.",
    )
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args(argv)
    if not 0.5 <= args.peak_hz <= 12.0:
        parser.error("--peak-hz must be between 0.5 and 12")
    if args.amp_deg <= 0:
        parser.error("--amp-deg must be positive")
    if args.hour_seconds <= 0:
        parser.error("--hour-seconds must be positive")
    return args


def main(argv: list[str] | None = None) -> None:
    """Run until interrupted."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(sys.argv[1:] if argv is None else argv)
    simulator = Simulator(args)
    next_window = time.monotonic()
    next_heartbeat = time.monotonic()
    next_command = time.monotonic() + 0.5
    next_passive = time.monotonic() + PASSIVE_S
    with httpx.Client(base_url=args.base_url, timeout=10.0) as client:
        wait_for_api(client)
        logger.info(
            "simulating device=%s peak_hz=%s amp_deg=%s hop_s=%.3f",
            args.device_id,
            args.peak_hz,
            args.amp_deg,
            HOP_S,
        )
        while True:
            now = time.monotonic()
            wait = min(next_window, next_heartbeat, next_command, next_passive) - now
            if wait > 0:
                time.sleep(wait)
            now = time.monotonic()
            try:
                if now >= next_heartbeat:
                    simulator.heartbeat(client)
                    next_heartbeat = now + HEARTBEAT_S
                if now >= next_command:
                    simulator.poll_commands(client)
                    next_command = now + COMMAND_POLL_S
                if now >= next_window:
                    simulator.post_window(client)
                    next_window = now + HOP_S
                if now >= next_passive:
                    simulator.post_passive(client)
                    next_passive = now + PASSIVE_S
            except httpx.HTTPError as exc:
                body = ""
                response = getattr(exc, "response", None)
                if response is not None:
                    body = response.text[:300]
                logger.error("request failed: %s %s", exc, body)
                time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("simulator stopped")

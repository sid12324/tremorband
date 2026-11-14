"""Record a labeled IMU session, or write the synthetic corpus.

A row is a measurement with a session label. It is not a diagnosis.
The band prints `ts,ax,ay,az,gx,gy,gz` after `set_mode:forward`.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import sys
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path

FS_HZ = 104.0
CSV_COLUMNS = (
    "person_id",
    "label",
    "wrist",
    "pose",
    "source",
    "synthetic",
    "ts_us",
    "ax",
    "ay",
    "az",
    "gx",
    "gy",
    "gz",
)
LABELS = ("still", "voluntary", "tremor")
SOURCES = ("human", "rig")

# Four made-up ids. Each file is marked synthetic=yes. Rig tremor is one
# session per person and human tremor is two, so rig stays under half.
SYNTHETIC_PEOPLE = (
    {"person_id": "p01", "wrist": "left", "rest_hz": 4.5, "postural_hz": 5.5, "rig_hz": 3.0},
    {"person_id": "p02", "wrist": "right", "rest_hz": 5.0, "postural_hz": 6.0, "rig_hz": 5.0},
    {"person_id": "p03", "wrist": "left", "rest_hz": 4.2, "postural_hz": 5.2, "rig_hz": 8.0},
    {"person_id": "p04", "wrist": "right", "rest_hz": 5.8, "postural_hz": 4.8, "rig_hz": 7.0},
)


def countdown(seconds: int, write: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep) -> None:
    """Print the seconds remaining before a capture starts."""
    for left in range(max(seconds, 0), 0, -1):
        write(str(left))
        sleep(1)


def metronome(
    hz: float,
    duration_s: float,
    write: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
    beep: bool = True,
) -> int:
    """Tick at `hz` for `duration_s`. Returns the number of ticks."""
    if hz <= 0 or duration_s <= 0:
        return 0
    count = int(duration_s * hz)
    interval = 1.0 / hz
    for _ in range(count):
        write("\a" if beep else "tick")
        sleep(interval)
    return count


def parse_forward_line(line: str) -> tuple[int, float, float, float, float, float, float] | None:
    """Parse one forwarder sample. JSON and other text are ignored."""
    text = line.strip()
    if not text or text.startswith("{"):
        return None
    parts = text.split(",")
    if len(parts) != 7:
        return None
    try:
        ts_us = int(float(parts[0]))
        ax, ay, az, gx, gy, gz = (float(part) for part in parts[1:])
    except ValueError:
        return None
    return ts_us, ax, ay, az, gx, gy, gz


def session_rows(
    samples: Iterable[tuple[int, float, float, float, float, float, float]],
    *,
    person_id: str,
    label: str,
    wrist: str,
    pose: str,
    source: str,
    synthetic: str,
) -> list[dict[str, str]]:
    """Attach session metadata to each sample."""
    if label not in LABELS:
        raise ValueError(f"label must be one of {LABELS}")
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}")
    if synthetic not in {"yes", "no"}:
        raise ValueError("synthetic must be yes or no")
    if source == "rig" and label != "tremor":
        raise ValueError("rig captures are tremor sessions")
    rows: list[dict[str, str]] = []
    for ts_us, ax, ay, az, gx, gy, gz in samples:
        rows.append(
            {
                "person_id": person_id,
                "label": label,
                "wrist": wrist,
                "pose": pose,
                "source": source,
                "synthetic": synthetic,
                "ts_us": str(ts_us),
                "ax": f"{ax:.6f}",
                "ay": f"{ay:.6f}",
                "az": f"{az:.6f}",
                "gx": f"{gx:.6f}",
                "gy": f"{gy:.6f}",
                "gz": f"{gz:.6f}",
            }
        )
    return rows


def write_session(path: Path, rows: list[dict[str, str]]) -> None:
    """Write one labeled session."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def load_sessions(directory: Path) -> list[dict[str, str]]:
    """Read every CSV session in a directory."""
    rows: list[dict[str, str]] = []
    for path in sorted(directory.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or tuple(reader.fieldnames) != CSV_COLUMNS:
                raise ValueError(f"{path.name} does not use the session columns")
            rows.extend(dict(row) for row in reader)
    return rows


def _sine(freq_hz: float, index: int) -> float:
    return math.sin(2.0 * math.pi * freq_hz * (index / FS_HZ))


def synthetic_samples(
    kind: str,
    freq_hz: float,
    n: int,
    seed: int,
) -> list[tuple[int, float, float, float, float, float, float]]:
    """IMU samples for one synthetic session. `kind` selects the motion."""
    rng = random.Random(seed)
    rows: list[tuple[int, float, float, float, float, float, float]] = []
    for i in range(n):
        ts_us = int(round(i * 1_000_000 / FS_HZ))
        if kind == "still":
            ax = rng.gauss(0.0, 0.004)
            ay = rng.gauss(0.0, 0.004)
            az = 9.81 + rng.gauss(0.0, 0.004)
            gx = rng.gauss(0.0, 0.02)
            gy = rng.gauss(0.0, 0.02)
            gz = rng.gauss(0.0, 0.02)
        elif kind == "tremor":
            tone = _sine(freq_hz, i)
            ax = rng.gauss(0.0, 0.02)
            ay = rng.gauss(0.0, 0.02)
            az = 9.81 + 0.8 * tone + rng.gauss(0.0, 0.02)
            gx = 30.0 + 20.0 * tone + rng.gauss(0.0, 0.4)
            gy = rng.gauss(0.0, 0.4)
            gz = rng.gauss(0.0, 0.4)
        elif kind == "rig":
            tone = _sine(freq_hz, i)
            ax = rng.gauss(0.0, 0.005)
            ay = rng.gauss(0.0, 0.005)
            az = 9.81 + 0.8 * tone + rng.gauss(0.0, 0.005)
            gx = 30.0 + 20.0 * tone + rng.gauss(0.0, 0.1)
            gy = rng.gauss(0.0, 0.1)
            gz = rng.gauss(0.0, 0.1)
        elif kind == "reaching":
            tone = _sine(0.4, i)
            ax = rng.gauss(0.0, 0.03)
            ay = 0.4 * tone
            az = 9.81 + 1.6 * tone + rng.gauss(0.0, 0.03)
            gx = 70.0 * tone
            gy = rng.gauss(0.0, 0.5)
            gz = 10.0 * _sine(0.25, i)
        elif kind == "walking":
            step = _sine(0.9, i)
            sway = _sine(1.7, i)
            ax = 0.2 * sway
            ay = 0.15 * step
            az = 9.81 + 0.55 * step + 0.25 * sway
            gx = 40.0 * step + 18.0 * sway
            gy = 8.0 * step
            gz = 6.0 * sway
        else:
            raise ValueError(f"unknown synthetic kind {kind}")
        rows.append((ts_us, ax, ay, az, gx, gy, gz))
    return rows


def write_synthetic_corpus(directory: Path, seconds: float = 8.0) -> list[Path]:
    """Write the stand-in corpus. Every row says synthetic=yes."""
    n = int(seconds * FS_HZ)
    paths: list[Path] = []
    for person_index, person in enumerate(SYNTHETIC_PEOPLE):
        plan = (
            ("still", "rest", "human", "still", 0.0),
            ("voluntary", "reaching", "human", "reaching", 0.4),
            ("voluntary", "walking", "human", "walking", 0.9),
            ("tremor", "rest", "human", "tremor", person["rest_hz"]),
            ("tremor", "postural", "human", "tremor", person["postural_hz"]),
            ("tremor", "rig", "rig", "rig", person["rig_hz"]),
        )
        for session_index, (label, pose, source, kind, freq) in enumerate(plan):
            samples = synthetic_samples(kind, float(freq), n, 1000 + person_index * 100 + session_index)
            rows = session_rows(
                samples,
                person_id=str(person["person_id"]),
                label=label,
                wrist=str(person["wrist"]),
                pose=pose,
                source=source,
                synthetic="yes",
            )
            path = directory / f"synthetic_{person['person_id']}_{label}_{pose}.csv"
            write_session(path, rows)
            paths.append(path)
    return paths


def record_port(
    port: str,
    baud: int,
    seconds: float,
    *,
    metronome_hz: float,
    countdown_s: int,
    out: Callable[[str], None] = print,
) -> list[tuple[int, float, float, float, float, float, float]]:
    """Send forward mode, count down, and collect samples for `seconds`."""
    import serial

    handle = serial.Serial(port, baud, timeout=0.2)
    try:
        handle.write(b"set_mode:forward\n")
        countdown(countdown_s, write=out)
        samples: list[tuple[int, float, float, float, float, float, float]] = []
        stop = threading.Event()

        def beats() -> None:
            metronome(metronome_hz, seconds, write=out)
            stop.set()

        thread = threading.Thread(target=beats, daemon=True)
        started = time.monotonic()
        thread.start()
        while time.monotonic() - started < seconds + 0.5 and not (stop.is_set() and handle.in_waiting == 0):
            raw = handle.readline()
            if not raw:
                if stop.is_set():
                    break
                continue
            parsed = parse_forward_line(raw.decode(errors="replace"))
            if parsed is not None:
                samples.append(parsed)
        thread.join(timeout=1)
        return samples
    finally:
        handle.close()


def main(argv: list[str] | None = None) -> int:
    """Record one serial session, or write the synthetic corpus."""
    parser = argparse.ArgumentParser(description="Record a labeled TremorBand session")
    parser.add_argument("--synthetic", action="store_true", help="Write the synthetic corpus and exit")
    parser.add_argument("--out-dir", type=Path, default=Path("ml/data"))
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--port", default="")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--person-id", default="p01")
    parser.add_argument("--label", default="tremor", choices=LABELS)
    parser.add_argument("--wrist", default="left")
    parser.add_argument("--pose", default="rest")
    parser.add_argument("--source", default="human", choices=SOURCES)
    parser.add_argument("--hz", type=float, default=5.0, help="Metronome rate for a human tremor mimic")
    parser.add_argument("--seconds", type=float, default=20.0)
    parser.add_argument("--countdown", type=int, default=3)
    args = parser.parse_args(argv)
    if args.synthetic:
        paths = write_synthetic_corpus(args.out_dir)
        print(f"wrote {len(paths)} synthetic sessions to {args.out_dir}")
        return 0
    if not args.port or args.out is None:
        print("A real capture needs --port and --out. Use --synthetic when no band is connected.", file=sys.stderr)
        return 2
    samples = record_port(
        args.port,
        args.baud,
        args.seconds,
        metronome_hz=args.hz if args.label == "tremor" and args.source == "human" else 0.0,
        countdown_s=args.countdown,
    )
    rows = session_rows(
        samples,
        person_id=args.person_id,
        label=args.label,
        wrist=args.wrist,
        pose=args.pose,
        source=args.source,
        synthetic="no",
    )
    write_session(args.out, rows)
    print(f"wrote {len(rows)} samples to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

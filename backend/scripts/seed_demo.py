"""Load seven days of synthetic sessions for the Trends and Log pages.

Every session is flagged is_synthetic. Amplitude is higher 3 to 5 hours after
each logged dose than in the first 2 hours. The dose name is a log label, not
a recommendation. TremorBand is a monitoring aid, not a diagnostic device.

From backend/:

    python scripts/seed_demo.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEMO_DEVICE = "demo-band"
DOSE_NAME = "Recorded dose"
DOSE_TEXT = "synthetic demo"
SYMPTOM_NOTE = "Synthetic demo"
SESSION_PLAN = (
    ("rest", 8, 30, -0.50),
    ("postural", 9, 15, -0.35),
    ("rest", 11, 30, -0.05),
    ("postural", 12, 30, 0.10),
)


def _day_start(now: datetime, offset: int) -> datetime:
    current = now.astimezone(timezone.utc)
    midnight = current.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=offset)


def seed_database(session, now: datetime | None = None, reset: bool = True) -> dict[str, object]:
    """Write the demo band, doses, symptom notes, and sessions. Returns counts."""
    from sqlmodel import col, delete, select

    from app.models import (
        CaptureSession,
        Device,
        Feedback,
        Medication,
        PassiveSummary,
        SymptomLog,
        Window,
    )
    from app.routes.analytics import persist_baselines
    from app.schemas import utcnow

    stamp = (now or utcnow()).astimezone(timezone.utc)
    if reset:
        demo_ids = [
            row.id
            for row in session.exec(select(CaptureSession).where(CaptureSession.device_id == DEMO_DEVICE))
            if row.id is not None
        ]
        if demo_ids:
            session.exec(delete(Feedback).where(col(Feedback.session_id).in_(demo_ids)))
        session.exec(delete(Window).where(Window.device_id == DEMO_DEVICE))
        session.exec(delete(PassiveSummary).where(PassiveSummary.device_id == DEMO_DEVICE))
        session.exec(delete(CaptureSession).where(CaptureSession.device_id == DEMO_DEVICE))
        session.exec(delete(Medication).where(Medication.dose == DOSE_TEXT))
        session.exec(delete(SymptomLog).where(SymptomLog.note == SYMPTOM_NOTE))
        session.flush()

    device = session.get(Device, DEMO_DEVICE)
    if device is None:
        device = Device(id=DEMO_DEVICE, name="Demo Band", fw_version="synthetic", mode="idle")
        session.add(device)
    else:
        device.name = "Demo Band"
        device.fw_version = "synthetic"
    device.last_seen = stamp
    session.add(device)
    session.flush()

    session_count = 0
    for day_index, days_ago in enumerate(range(6, -1, -1)):
        day = _day_start(stamp, days_ago)
        session.add(
            Medication(
                ts=day.replace(hour=8),
                name=DOSE_NAME,
                dose=DOSE_TEXT,
            )
        )
        drift = day_index * 0.01
        for test_type, hour, minute, base_amp in SESSION_PLAN:
            start = day.replace(hour=hour, minute=minute)
            log_amp = base_amp + drift
            capture = CaptureSession(
                device_id=DEMO_DEVICE,
                ts_start=start,
                ts_end=start + timedelta(minutes=20),
                test_type=test_type,
                summary={"median_log_amp": log_amp, "median_hz": 5.0, "tremor_pct": 80},
                quality=0.75,
                is_synthetic=True,
            )
            session.add(capture)
            session.flush()
            for index in range(4):
                vibrating = index == 3
                session.add(
                    Window(
                        device_id=DEMO_DEVICE,
                        ts=start + timedelta(seconds=30 * index),
                        session_id=capture.id,
                        test_type=test_type,
                        peak_hz=5.0,
                        band_power=0.4,
                        rms=0.35,
                        sharpness=0.7,
                        amp_deg=2.0,
                        disp_mm=1.0,
                        log_amp=log_amp,
                        label="tremor",
                        p_tremor=0.8,
                        vibrating=vibrating,
                    )
                )
            session_count += 1
        for hour in range(8, 16):
            if hour <= 10:
                tremor_pct = 25.0
            elif hour <= 13:
                tremor_pct = 70.0
            else:
                tremor_pct = 30.0
            session.add(
                PassiveSummary(
                    device_id=DEMO_DEVICE,
                    ts=day.replace(hour=hour),
                    tremor_pct=tremor_pct,
                    median_hz=5.0,
                    median_log_amp=-0.2 + drift,
                    activity=0.2,
                )
            )

    symptom_days = (
        (6, "stress", 3),
        (4, "caffeine", 2),
        (2, "poor sleep", 3),
    )
    for days_ago, tag, rating in symptom_days:
        day = _day_start(stamp, days_ago)
        session.add(
            SymptomLog(
                ts=day.replace(hour=10),
                rating=rating,
                note=SYMPTOM_NOTE,
                tags=[tag],
            )
        )

    persist_baselines(session)
    session.commit()
    return {
        "device_id": DEMO_DEVICE,
        "sessions": session_count,
        "medications": 7,
        "symptoms": 3,
        "is_synthetic": True,
    }


def main() -> None:
    """Replace demo-band rows and print the counts."""
    parser = argparse.ArgumentParser(description="Load 7 days of synthetic TremorBand sessions.")
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Keep existing demo-band rows and append another 7 days.",
    )
    args = parser.parse_args()
    from sqlmodel import Session

    from app.db import engine, init_db

    init_db()
    with Session(engine) as db:
        summary = seed_database(db, reset=not args.no_reset)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()

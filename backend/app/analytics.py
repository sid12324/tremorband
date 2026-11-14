"""Personal baselines and recorded timing patterns.

These figures describe stored sessions. They are not a diagnosis and they do
not suggest a dose.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

DEFAULT_THRESHOLD_Z = 2.0
THRESHOLD_STEP = 0.25
THRESHOLD_MIN = 1.0
THRESHOLD_MAX = 3.5
MIN_COMPARE_N = 3
MODERATE_COMPARE_N = 5
TAG_WINDOW = timedelta(hours=6)
TRACKED_TAGS = ("stress", "caffeine", "poor sleep")
WEARING_BINS = ("0-2", "2-3", "3-5", "5+")


@dataclass
class SessionPoint:
    """One session reduced to the numbers analytics uses."""

    session_id: int | None
    test_type: str
    ts: datetime
    log_amp: float | None
    peak_hz: float | None
    is_synthetic: bool = False
    quality: float | None = None
    device_id: str = ""
    ts_end: datetime | None = None


@dataclass
class DosePoint:
    """A logged dose marker."""

    ts: datetime
    name: str = ""
    dose: str = ""


@dataclass
class SymptomPoint:
    """A symptom-log entry."""

    ts: datetime
    rating: int
    tags: list[str] = field(default_factory=list)


@dataclass
class WindowPoint:
    """A window reduced to the fields that decide exclusion."""

    vibrating: bool = False
    log_amp: float | None = None
    peak_hz: float | None = None
    label: str | None = None
    rms: float | None = None


@dataclass
class BaselineStats:
    """Mean and spread of log amplitude for one test type."""

    test_type: str
    mean_log_amp: float
    sd_log_amp: float
    mean_hz: float
    threshold_z: float
    n_sessions: int


@dataclass
class ThresholdUpdate:
    """The before and after of one threshold move."""

    test_type: str
    old_threshold_z: float
    new_threshold_z: float
    reason: str


def session_log_amp(summary: dict | None) -> float | None:
    """Read log amplitude from a session summary."""
    if not summary:
        return None
    for key in ("median_log_amp", "log_amp"):
        value = summary.get(key)
        if value is not None:
            return float(value)
    return None


def session_peak_hz(summary: dict | None) -> float | None:
    """Read peak frequency from a session summary."""
    if not summary:
        return None
    for key in ("median_hz", "peak_hz"):
        value = summary.get(key)
        if value is not None:
            return float(value)
    return None


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _sample_sd(values: list[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    spread_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    spread_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if spread_x == 0 or spread_y == 0:
        return None
    return numerator / (spread_x * spread_y)


def _cohens_d(early: list[float], late: list[float]) -> float | None:
    if len(early) < 2 or len(late) < 2:
        return None
    mean_early = sum(early) / len(early)
    mean_late = sum(late) / len(late)
    var_early = sum((value - mean_early) ** 2 for value in early) / (len(early) - 1)
    var_late = sum((value - mean_late) ** 2 for value in late) / (len(late) - 1)
    pooled = math.sqrt(((len(early) - 1) * var_early + (len(late) - 1) * var_late) / (len(early) + len(late) - 2))
    if pooled == 0:
        return 0.0
    return (mean_late - mean_early) / pooled


def baseline_from_points(
    test_type: str,
    points: list[SessionPoint],
    threshold_z: float = DEFAULT_THRESHOLD_Z,
) -> BaselineStats | None:
    """Mean and sample SD of log amplitude for one test type."""
    chosen = [point for point in points if point.test_type == test_type and point.log_amp is not None]
    if not chosen:
        return None
    amps = [float(point.log_amp) for point in chosen if point.log_amp is not None]
    peaks = [point.peak_hz for point in chosen if point.peak_hz is not None]
    mean_amp = sum(amps) / len(amps)
    mean_hz = sum(peaks) / len(peaks) if peaks else 0.0
    return BaselineStats(
        test_type=test_type,
        mean_log_amp=mean_amp,
        sd_log_amp=_sample_sd(amps, mean_amp),
        mean_hz=mean_hz,
        threshold_z=threshold_z,
        n_sessions=len(amps),
    )


def z_score(log_amp: float | None, mean_log_amp: float | None, sd_log_amp: float | None) -> float | None:
    """(log amplitude - personal mean) / personal SD. None when SD is zero."""
    if log_amp is None or mean_log_amp is None or sd_log_amp is None or sd_log_amp == 0:
        return None
    return (log_amp - mean_log_amp) / sd_log_amp


def above_threshold(score: float | None, threshold_z: float) -> bool:
    """True when a z-score is past the comparison line."""
    return score is not None and score > threshold_z


def adjust_threshold(current: float, kind: str) -> ThresholdUpdate:
    """Move threshold_z by one step and clamp it. The reason is the log line."""
    if kind == "not_a_bad_day":
        updated = min(THRESHOLD_MAX, current + THRESHOLD_STEP)
        direction = "raised"
    elif kind == "missed_symptoms":
        updated = max(THRESHOLD_MIN, current - THRESHOLD_STEP)
        direction = "lowered"
    else:
        raise ValueError(f"unknown feedback kind {kind}")
    if updated == current:
        reason = f"{kind} left threshold_z at the limit {updated:.2f}"
    else:
        reason = f"{kind} {direction} threshold_z from {current:.2f} to {updated:.2f}"
    return ThresholdUpdate("", current, updated, reason)


def hours_since_dose(ts: datetime, doses: list[DosePoint]) -> float | None:
    """Hours since the latest dose at or before `ts`."""
    prior = [dose for dose in doses if dose.ts <= ts]
    if not prior:
        return None
    latest = max(prior, key=lambda dose: dose.ts)
    return (ts - latest.ts).total_seconds() / 3600.0


def _bin_label(hours: float) -> str | None:
    if hours < 0:
        return None
    if hours < 2:
        return "0-2"
    if hours < 3:
        return "2-3"
    if hours < 5:
        return "3-5"
    return "5+"


def wearing_off(points: list[SessionPoint], doses: list[DosePoint]) -> dict[str, object]:
    """Compare median log amplitude 3 to 5 hours after a dose with the first 2 hours."""
    grouped: dict[str, list[float]] = {label: [] for label in WEARING_BINS}
    for point in points:
        if point.log_amp is None:
            continue
        hours = hours_since_dose(point.ts, doses)
        if hours is None:
            continue
        label = _bin_label(hours)
        if label is None:
            continue
        grouped[label].append(point.log_amp)
    early = grouped["0-2"]
    late = grouped["3-5"]
    median_early = _median(early)
    median_late = _median(late)
    bins = [
        {"label": label, "n": len(grouped[label]), "median_log_amp": _median(grouped[label])}
        for label in WEARING_BINS
    ]
    if len(early) < MIN_COMPARE_N or len(late) < MIN_COMPARE_N:
        return {
            "bins": bins,
            "n_early": len(early),
            "n_late": len(late),
            "median_early": median_early,
            "median_late": median_late,
            "median_difference": None,
            "effect_size": None,
            "confidence": "insufficient",
            "finding": (
                "Not enough sessions in both the 0 to 2 hour bin and the 3 to 5 hour bin to compare. "
                "This is not a diagnosis."
            ),
        }
    difference = (median_late or 0.0) - (median_early or 0.0)
    effect = _cohens_d(early, late)
    confidence = "moderate" if len(early) >= MODERATE_COMPARE_N and len(late) >= MODERATE_COMPARE_N else "low"
    if difference > 0:
        direction = f"{difference:.2f} higher"
    elif difference < 0:
        direction = f"{abs(difference):.2f} lower"
    else:
        direction = "the same"
    finding = (
        f"Median log amplitude is {direction} 3 to 5 hours after a logged dose than in the first 2 hours. "
        "This describes the recorded sessions. It is not a diagnosis."
    )
    return {
        "bins": bins,
        "n_early": len(early),
        "n_late": len(late),
        "median_early": median_early,
        "median_late": median_late,
        "median_difference": difference,
        "effect_size": effect,
        "confidence": confidence,
        "finding": finding,
    }


def _near_tag(point: SessionPoint, symptoms: list[SymptomPoint], tag: str) -> bool:
    for symptom in symptoms:
        if tag not in symptom.tags:
            continue
        if abs(symptom.ts - point.ts) <= TAG_WINDOW:
            return True
    return False


def tag_correlations(
    points: list[SessionPoint],
    symptoms: list[SymptomPoint],
    tags: tuple[str, ...] = TRACKED_TAGS,
) -> list[dict[str, object]]:
    """Compare log amplitude near a symptom tag with sessions that are not near it."""
    present = {tag for symptom in symptoms for tag in symptom.tags}
    ordered = list(tags) + sorted(present - set(tags))
    reports: list[dict[str, object]] = []
    for tag in ordered:
        tagged: list[float] = []
        untagged: list[float] = []
        for point in points:
            if point.log_amp is None:
                continue
            if _near_tag(point, symptoms, tag):
                tagged.append(point.log_amp)
            else:
                untagged.append(point.log_amp)
        median_tagged = _median(tagged)
        median_untagged = _median(untagged)
        if len(tagged) < 2 or len(untagged) < 2:
            reports.append(
                {
                    "tag": tag,
                    "n_tagged": len(tagged),
                    "n_untagged": len(untagged),
                    "median_tagged": median_tagged,
                    "median_untagged": median_untagged,
                    "median_difference": None,
                    "correlation": None,
                    "finding": f"Not enough sessions near the '{tag}' tag to compare. This is not a diagnosis.",
                }
            )
            continue
        difference = (median_tagged or 0.0) - (median_untagged or 0.0)
        correlation = _pearson([1.0] * len(tagged) + [0.0] * len(untagged), tagged + untagged)
        if difference > 0:
            direction = "higher"
        elif difference < 0:
            direction = "lower"
        else:
            direction = "the same"
        reports.append(
            {
                "tag": tag,
                "n_tagged": len(tagged),
                "n_untagged": len(untagged),
                "median_tagged": median_tagged,
                "median_untagged": median_untagged,
                "median_difference": difference,
                "correlation": correlation,
                "finding": (
                    f"Sessions within 6 hours of a '{tag}' tag have a {direction} median log amplitude "
                    f"({difference:+.2f}). This is an association in the log, not a cause, and it is not a diagnosis."
                ),
            }
        )
    return reports


def exclusion_reason(window: WindowPoint) -> str | None:
    """Why a window is left out: vibration, missing fields, or an empty signal."""
    if window.vibrating:
        return "vibration"
    if window.log_amp is None or window.peak_hz is None or not window.label:
        return "missing"
    if window.peak_hz == 0 and (window.rms or 0) == 0:
        return "low_quality"
    return None


def data_quality(windows: list[WindowPoint]) -> dict[str, object]:
    """Count windows excluded for vibration, missing fields, or an empty signal."""
    counts = {"vibration": 0, "missing": 0, "low_quality": 0}
    for window in windows:
        reason = exclusion_reason(window)
        if reason is not None:
            counts[reason] += 1
    used = len(windows) - sum(counts.values())
    quality = None if not windows else used / len(windows)
    return {
        "n_windows": len(windows),
        "excluded_vibration": counts["vibration"],
        "excluded_missing": counts["missing"],
        "excluded_low_quality": counts["low_quality"],
        "n_used": used,
        "quality": quality,
    }


def tremor_hours_by_day(rows: list[tuple[datetime, float]], hours_each: float = 1.0) -> list[dict[str, object]]:
    """Roll passive tremor percent into hours per calendar day.

    A summary covers the gap until the next summary, and never more than
    `hours_each`. The last summary repeats the previous gap. Hourly demo rows
    therefore count as one hour, and a stream of short updates does not.
    """
    ordered = sorted(rows, key=lambda row: row[0])
    totals: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for index, (ts, tremor_pct) in enumerate(ordered):
        if index + 1 < len(ordered):
            gap_hours = (ordered[index + 1][0] - ts).total_seconds() / 3600.0
        elif index > 0:
            gap_hours = (ts - ordered[index - 1][0]).total_seconds() / 3600.0
        else:
            gap_hours = hours_each
        duration = min(hours_each, max(gap_hours, 0.0))
        day = ts.date().isoformat()
        totals[day][0] += max(tremor_pct, 0.0) / 100.0 * duration
        totals[day][1] += 1
    return [
        {"day": day, "tremor_hours": totals[day][0], "n": int(totals[day][1])}
        for day in sorted(totals)
    ]

"""Movement review written from stored session numbers.

The review has three sections: the average across the stored sessions, the
session with the highest median log amplitude, and the most recent session.
The summary then states the recorded results, how strong that signal is
beside this person's own sessions, and the trend across sessions over time.
A care plan is included only when that highest median log amplitude is above
the comparison line. Synthetic sessions are called simulated.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from agent.report_text import DISCLAIMER, REPORT_LINE
from app.analytics import DEFAULT_THRESHOLD_Z, above_threshold, z_score

# The number that picks the highest session. Trends, baselines, and session
# metrics already compare sessions by median log amplitude.
HIGHEST_FIELD = "median_log_amp"
HIGHEST_LABEL = "median log amplitude"

# Half-to-half changes smaller than this stay "about the same".
_TREND_LOG_AMP = 0.05
_TREND_HZ = 0.25

# key, label, average digits, session digits, suffix
_MEASURES = (
    ("median_log_amp", "Median log amplitude", 2, 2, ""),
    ("median_amp_deg", "Median amplitude", 2, 2, " deg"),
    ("median_peak_hz", "Median peak", 2, 2, " Hz"),
    ("n_windows", "Windows", 1, 0, ""),
    ("n_tremor", "Tremor-labeled windows", 1, 0, ""),
    ("tremor_pct", "Tremor share", 1, 1, "%"),
)


def _float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _num(value: object, digits: int) -> str:
    number = _float(value)
    if number is None:
        return "not stored"
    return f"{number:.{digits}f}"


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _when(value: object) -> str:
    parsed = _parse_time(value)
    if parsed is None:
        return "not stored"
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def _label(row: dict[str, Any]) -> str:
    if row.get("data_label") in {"simulated", "recorded"}:
        return str(row["data_label"])
    return "simulated" if row.get("is_synthetic") else "recorded"


def _session_id(row: dict[str, Any]) -> int:
    number = _float(row.get("id"))
    if number is None:
        return 0
    return int(number)


def _order_key(row: dict[str, Any]) -> tuple[float, int]:
    parsed = _parse_time(row.get("ts_start"))
    stamp = parsed.timestamp() if parsed is not None else float("-inf")
    return (stamp, _session_id(row))


def _mean_sd(values: list[float]) -> tuple[float | None, float]:
    if not values:
        return None, 0.0
    mean = sum(values) / len(values)
    if len(values) < 2:
        return mean, 0.0
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return mean, math.sqrt(variance)


def _measure_line(label: str, value: object, digits: int, suffix: str) -> str:
    if _float(value) is None:
        return f"{label}: not stored."
    return f"{label}: {_num(value, digits)}{suffix}."


def _average_lines(sessions: list[dict[str, Any]], total: int) -> list[str]:
    lines = [f"Stored sessions: {total}."]
    if total > len(sessions):
        lines.append(f"This average uses {len(sessions)} of {total} stored sessions.")
    for key, label, digits, _session_digits, suffix in _MEASURES:
        values = [number for row in sessions if (number := _float(row.get(key))) is not None]
        if not values:
            lines.append(f"{label}: not stored.")
            continue
        mean = sum(values) / len(values)
        lines.append(f"{label}: {mean:.{digits}f}{suffix}.")
    return lines


def _session_lines(row: dict[str, Any] | None, empty: str) -> list[str]:
    if row is None:
        return [empty]
    lines = [
        f"Session {row.get('id')} · {row.get('test_type') or 'not stored'} · {_label(row)}.",
        f"Started {_when(row.get('ts_start'))}.",
    ]
    for key, label, _average_digits, digits, suffix in _MEASURES:
        lines.append(_measure_line(label, row.get(key), digits, suffix))
    return lines


def _ordered(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(sessions, key=_order_key)


def _series(sessions: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in _ordered(sessions):
        number = _float(row.get(key))
        if number is not None:
            values.append(number)
    return values


def _half_means(values: list[float]) -> tuple[float, float] | None:
    if len(values) < 2:
        return None
    split = len(values) // 2
    early = values[:split]
    late = values[split:]
    return sum(early) / len(early), sum(late) / len(late)


def _direction(delta: float, step: float, higher: str, lower: str, same: str) -> str:
    if delta > step:
        return higher
    if delta < -step:
        return lower
    return same


def _results_sentence(sessions: list[dict[str, Any]], amps: list[float]) -> str:
    parts = [f"{len(sessions)} stored sessions."]
    if amps:
        parts.append(f"Average {HIGHEST_LABEL} is {sum(amps) / len(amps):.2f}.")
    else:
        parts.append(f"Average {HIGHEST_LABEL} is not stored.")
    peaks = _series(sessions, "median_peak_hz")
    if peaks:
        parts.append(f"Average median peak is {sum(peaks) / len(peaks):.2f} Hz.")
    else:
        parts.append("Average median peak is not stored.")
    shares = _series(sessions, "tremor_pct")
    if shares:
        parts.append(f"Average tremor share is {sum(shares) / len(shares):.1f}%.")
    return " ".join(parts)


def _signal_detail(row: dict[str, Any]) -> str:
    bits = [f"{HIGHEST_LABEL} {_num(row.get(HIGHEST_FIELD), 2)}"]
    peak = _float(row.get("median_peak_hz"))
    if peak is not None:
        bits.append(f"median peak {_num(peak, 2)} Hz")
    amp = _float(row.get("median_amp_deg"))
    if amp is not None:
        bits.append(f"median amplitude {_num(amp, 2)} deg")
    return ", ".join(bits)


def _strength_sentence(
    highest: dict[str, Any] | None,
    score: float | None,
    concerning: bool,
) -> str:
    if highest is None:
        return (
            f"No stored session has a {HIGHEST_LABEL}, so there is no strongest signal "
            "to set beside this person's other sessions."
        )
    lead = (
        f"The strongest stored signal is session {highest.get('id')} "
        f"({highest.get('test_type') or 'not stored'}, {_label(highest)}), "
        f"with {_signal_detail(highest)}."
    )
    if score is None:
        return (
            lead + " There are not enough differing amplitudes to place that session "
            "against this person's other stored sessions."
        )
    side = "above" if score >= 0 else "below"
    place = (
        f"That amplitude is {abs(score):.2f} standard deviations {side} this person's own average, "
        f"{'past' if concerning else 'inside'} the comparison line of {DEFAULT_THRESHOLD_Z:.2f}."
    )
    if concerning:
        reading = " Relative to their stored sessions, that signal is the concerning one."
    else:
        reading = " Relative to their stored sessions, that signal stays within the usual spread."
    return f"{lead} {place}{reading}"


def _recent_sentence(recent: dict[str, Any] | None, highest: dict[str, Any] | None) -> str:
    if recent is None:
        return ""
    same = (
        highest is not None
        and _session_id(recent) == _session_id(highest)
        and _session_id(recent) != 0
    )
    if same:
        return "The most recent session is that same session."
    return (
        f"The most recent session is session {recent.get('id')} "
        f"({recent.get('test_type') or 'not stored'}, {_label(recent)}), with {_signal_detail(recent)}."
    )


def _trend_sentence(sessions: list[dict[str, Any]]) -> str:
    amps = _series(sessions, HIGHEST_FIELD)
    halves = _half_means(amps)
    if halves is None:
        trend = (
            "Fewer than two stored median log amplitudes are on record, "
            "so there is no amplitude trend across sessions yet."
        )
    else:
        early, late = halves
        direction = _direction(
            late - early,
            _TREND_LOG_AMP,
            "higher in the later sessions than in the earlier ones",
            "lower in the later sessions than in the earlier ones",
            "about the same from the earlier sessions to the later ones",
        )
        trend = (
            "Across sessions over time, median log amplitude averages "
            f"{early:.2f} in the earlier sessions and {late:.2f} in the later sessions, "
            f"so the recorded amplitude is {direction}."
        )
    peaks = _series(sessions, "median_peak_hz")
    peak_halves = _half_means(peaks)
    if peak_halves is None:
        return trend
    early_hz, late_hz = peak_halves
    if abs(late_hz - early_hz) <= _TREND_HZ:
        frequency = f" Median peak frequency stays near {late_hz:.2f} Hz across those sessions."
    else:
        frequency_direction = "higher" if late_hz > early_hz else "lower"
        frequency = (
            " Median peak frequency averages "
            f"{early_hz:.2f} Hz in the earlier sessions and {late_hz:.2f} Hz in the later sessions, "
            f"so the recorded frequency is {frequency_direction} later."
        )
    return trend + frequency


def _summary(
    sessions: list[dict[str, Any]],
    amps: list[float],
    highest: dict[str, Any] | None,
    recent: dict[str, Any] | None,
    score: float | None,
    concerning: bool,
) -> str:
    if not sessions:
        return (
            "No sessions are stored yet. There is no recorded signal to compare "
            "with this person's sessions and no trend across sessions."
        )
    parts = [
        _results_sentence(sessions, amps),
        _strength_sentence(highest, score, concerning),
        _recent_sentence(recent, highest),
        _trend_sentence(sessions),
    ]
    return " ".join(part for part in parts if part)


def _care_plan(highest: dict[str, Any], score: float) -> str:
    return (
        f"Session {highest.get('id')} has the highest {HIGHEST_LABEL} "
        f"({_num(highest.get(HIGHEST_FIELD), 2)}), {score:.2f} standard deviations "
        "above the average of the stored sessions. "
        "Another capture near the same time of day would add a point beside this one. "
        "The stored record can be shared with the person's clinician. "
        "This is not a diagnosis and it does not suggest medication."
    )


def review_from_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """Build the three sections, the summary, and a care plan only when warranted."""
    sessions = [row for row in (facts.get("sessions") or []) if isinstance(row, dict)]
    total = int(facts.get("n_sessions") or len(sessions))
    amps = [number for row in sessions if (number := _float(row.get(HIGHEST_FIELD))) is not None]
    ranked = [row for row in sessions if _float(row.get(HIGHEST_FIELD)) is not None]
    highest = max(ranked, key=lambda row: (_float(row.get(HIGHEST_FIELD)) or 0.0, _order_key(row))) if ranked else None
    recent = max(sessions, key=_order_key) if sessions else None
    mean, spread = _mean_sd(amps)
    highest_value = _float(highest.get(HIGHEST_FIELD)) if highest is not None else None
    score = z_score(highest_value, mean, spread)
    concerning = highest is not None and score is not None and above_threshold(score, DEFAULT_THRESHOLD_Z)
    care_plan = _care_plan(highest, score) if concerning and highest is not None and score is not None else None
    return {
        "measure_key": HIGHEST_FIELD,
        "measure_label": HIGHEST_LABEL,
        "n_sessions": total,
        "concerning": concerning,
        "comparison_z": DEFAULT_THRESHOLD_Z,
        "highest_z": None if score is None else round(score, 2),
        "sections": [
            {
                "id": "average",
                "title": "Average across stored sessions",
                "lines": _average_lines(sessions, total),
            },
            {
                "id": "highest",
                "title": "Highest session by median log amplitude",
                "lines": [
                    f"Chosen by the highest {HIGHEST_LABEL}.",
                    *_session_lines(highest, f"No stored session has a {HIGHEST_LABEL}."),
                ],
            },
            {
                "id": "recent",
                "title": "Most recent session",
                "lines": _session_lines(recent, "No sessions are stored yet."),
            },
        ],
        "summary": _summary(sessions, amps, highest, recent, score, concerning),
        "care_plan": care_plan,
    }


def compose_analysis(facts: dict[str, Any]) -> str:
    """Turn stored session facts into the analysis text."""
    review = review_from_facts(facts)
    lines = [DISCLAIMER, "", REPORT_LINE, ""]
    for section in review["sections"]:
        lines.append(section["title"])
        lines.extend(section["lines"])
        lines.append("")
    lines.append("Summary")
    lines.append(review["summary"])
    lines.append("")
    if review["care_plan"]:
        lines.append("Care plan")
        lines.append(review["care_plan"])
        lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)

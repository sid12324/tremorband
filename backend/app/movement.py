"""Tapping and gait summaries from a gyro-magnitude series.

The peak rule matches the band: a local peak above 5, with a refractory gap.
The coefficient of variation uses the population standard deviation, as tests.cpp does.
"""

from __future__ import annotations

import math


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _cv(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    if abs(mean) < 1e-9:
        return 0.0
    square = sum((value - mean) ** 2 for value in values)
    return math.sqrt(square / len(values)) / mean


def peaks(samples: list[tuple[int, float]], refractory_ms: int) -> tuple[list[float], list[float]]:
    """Return peak amplitudes and the gaps between them, in milliseconds."""
    if len(samples) < 3:
        return [], []
    amplitudes: list[float] = []
    intervals: list[float] = []
    last_ms: int | None = None
    for index in range(1, len(samples) - 1):
        previous_ms, previous = samples[index - 1]
        current_ms, current = samples[index]
        _next_ms, nxt = samples[index + 1]
        if not (current > previous and current > nxt and current > 5.0):
            continue
        if last_ms is not None and current_ms - last_ms < refractory_ms:
            continue
        if last_ms is not None:
            intervals.append(float(current_ms - last_ms))
        amplitudes.append(current)
        last_ms = current_ms
    return amplitudes, intervals


def tapping_summary(samples: list[tuple[int, float]], duration_s: float = 10.0) -> dict[str, float]:
    """Taps per second, amplitude drop, and inter-tap variation."""
    amplitudes, intervals = peaks(samples, 180)
    decrement = 0.0
    if len(amplitudes) >= 6:
        decrement = _mean(amplitudes[:3]) - _mean(amplitudes[-3:])
    rate = (len(amplitudes) / duration_s) if duration_s else 0.0
    return {"taps_per_s": rate, "tap_decrement": decrement, "tap_interval_cv": _cv(intervals)}


def gait_summary(samples: list[tuple[int, float]], duration_s: float = 30.0) -> dict[str, float]:
    """Cadence, stride-time variation, and step-time asymmetry."""
    amplitudes, intervals = peaks(samples, 250)
    cadence = (len(amplitudes) / duration_s * 60.0) if duration_s else 0.0
    odd = [value for index, value in enumerate(intervals) if index % 2 == 1]
    even = [value for index, value in enumerate(intervals) if index % 2 == 0]
    asymmetry = 0.0
    mean_all = _mean(intervals)
    if odd and even and mean_all > 1e-9:
        asymmetry = abs(_mean(odd) - _mean(even)) / mean_all * 100.0
    strides = [intervals[index] + intervals[index + 1] for index in range(0, len(intervals) - 1, 2)]
    return {"cadence_spm": cadence, "stride_cv": _cv(strides), "asymmetry_pct": asymmetry}


def intention_ratio(amplitudes: list[float]) -> float:
    """Late-window amplitude divided by the earlier part of the same series."""
    if not amplitudes:
        return 0.0
    split = (len(amplitudes) * 7) // 10
    early = _mean(amplitudes[:split])
    late = _mean(amplitudes[split:])
    if early <= 1e-9:
        return 0.0
    return late / early

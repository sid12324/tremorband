"""Movement analysis written from stored session numbers.

The text cites those numbers. It does not diagnose and it does not suggest
medication. Synthetic sessions are called simulated.
"""

from __future__ import annotations

from typing import Any

from agent.report_text import DISCLAIMER, REPORT_LINE


def _num(value: object, digits: int = 2) -> str:
    if value is None:
        return "not stored"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "not stored"


def compose_analysis(facts: dict[str, Any]) -> str:
    """Turn a get_session_facts payload into the analysis the page shows."""
    sessions = list(facts.get("sessions") or [])
    total = int(facts.get("n_sessions") or len(sessions))
    lines = [
        DISCLAIMER,
        "",
        REPORT_LINE,
        "",
        f"Stored sessions: {total}.",
    ]
    if total > len(sessions):
        lines.append(f"Showing the {len(sessions)} most recent of {total} stored sessions.")
    if not sessions:
        lines.append("No sessions are stored yet.")
    for row in sessions:
        label = "simulated" if row.get("is_synthetic") else "recorded"
        lines.append(
            f"Session {row.get('id')} is {label}. "
            f"Test {row.get('test_type')}. "
            f"Windows {_num(row.get('n_windows'), 0)}. "
            f"Usable windows {_num(row.get('n_usable'), 0)}. "
            f"Median peak {_num(row.get('median_peak_hz'))} Hz. "
            f"Median amplitude {_num(row.get('median_amp_deg'))} deg. "
            f"Median log amplitude {_num(row.get('median_log_amp'))}. "
            f"Tremor share {_num(row.get('tremor_pct'), 1)}%. "
            f"Mean tremor score {_num(row.get('mean_p_tremor'))}."
        )
    lines.extend(
        [
            "",
            "These figures describe stored movement. They are not a diagnosis and they do not suggest medication.",
            "",
            DISCLAIMER,
        ]
    )
    return "\n".join(lines)

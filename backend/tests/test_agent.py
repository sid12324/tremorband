"""Movement analysis and model selection, with the scripted model."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(tempfile.mkdtemp())
os.environ["DATABASE_URL"] = f"sqlite:///{_ROOT / 'agent.db'}"
os.environ["TREMORBAND_CHECKPOINT"] = str(_ROOT / "checkpoint.db")
os.environ["TREMORBAND_MODEL"] = "mock"

from sqlmodel import Session  # noqa: E402

from agent.analysis_text import compose_analysis, review_from_facts  # noqa: E402
from agent.mock_model import ScriptedChatModel  # noqa: E402
from agent.planner import _build_model, model_name, redact, run_thread  # noqa: E402
from agent.tools import _in_sleep, plan_extra_tests, trigger_test  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.pdf_note import note_pdf  # noqa: E402
from scripts.seed_demo import seed_database  # noqa: E402


class PlannerRuleTest(unittest.TestCase):
    def test_sleep_window_wraps_midnight(self) -> None:
        self.assertTrue(_in_sleep(23, 22, 7))
        self.assertTrue(_in_sleep(6, 22, 7))
        self.assertFalse(_in_sleep(12, 22, 7))

    def test_pdf_contains_the_disclaimer(self) -> None:
        blob = note_pdf("TremorBand is a monitoring aid, not a diagnostic device.")
        self.assertTrue(blob.startswith(b"%PDF-1.4"))
        self.assertIn(b"monitoring aid", blob)


class ModelSelectionTest(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ["TREMORBAND_MODEL"] = "mock"

    def test_no_key_keeps_the_scripted_model(self) -> None:
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("TREMORBAND_MODEL", None)
        self.assertEqual(model_name(), "mock")
        os.environ["TREMORBAND_MODEL"] = ""
        self.assertEqual(model_name(), "mock")

    def test_key_selects_gpt_4o_mini_when_model_is_unset(self) -> None:
        os.environ.pop("TREMORBAND_MODEL", None)
        os.environ["OPENAI_API_KEY"] = "unit-test-key"
        self.assertEqual(model_name(), "openai:gpt-4o-mini")
        self.assertNotIn("unit-test-key", model_name())

    def test_explicit_model_wins(self) -> None:
        os.environ["OPENAI_API_KEY"] = "unit-test-key"
        os.environ["TREMORBAND_MODEL"] = "mock"
        self.assertEqual(model_name(), "mock")
        with self.assertLogs("agent.planner", level="INFO") as logs:
            model = _build_model()
        self.assertIsInstance(model, ScriptedChatModel)
        self.assertNotIn("unit-test-key", "\n".join(logs.output))
        self.assertEqual(redact("prefix unit-test-key suffix"), "prefix [redacted] suffix")


def _session(session_id: int, log_amp: float, hour: int) -> dict:
    return {
        "id": session_id,
        "test_type": "rest",
        "is_synthetic": False,
        "data_label": "recorded",
        "ts_start": f"2026-01-01T{hour:02d}:00:00+00:00",
        "median_log_amp": log_amp,
        "median_amp_deg": 1.0,
        "median_peak_hz": 4.0,
        "n_windows": 4,
        "n_tremor": 1,
        "tremor_pct": 25.0,
    }


class ReviewShapeTest(unittest.TestCase):
    def test_three_sections_and_no_care_plan_inside_the_line(self) -> None:
        facts = {"n_sessions": 2, "sessions": [_session(1, 0.0, 8), _session(2, 0.1, 9)]}
        review = review_from_facts(facts)
        self.assertEqual(
            [section["id"] for section in review["sections"]],
            ["average", "highest", "recent"],
        )
        self.assertEqual(review["sections"][1]["lines"][0], "Chosen by the highest median log amplitude.")
        self.assertIn("Session 2", review["sections"][1]["lines"][1])
        self.assertIn("Session 2", review["sections"][2]["lines"][0])
        self.assertFalse(review["concerning"])
        self.assertIsNone(review["care_plan"])
        text = compose_analysis(facts)
        self.assertLess(text.index("Average across stored sessions"), text.index("Highest session by median log amplitude"))
        self.assertLess(text.index("Highest session by median log amplitude"), text.index("Most recent session"))
        self.assertLess(text.index("Most recent session"), text.index("Summary"))
        self.assertNotIn("Care plan", text)
        self.assertNotIn("you should", text.lower())

    def test_care_plan_only_when_highest_passes_the_comparison_line(self) -> None:
        sessions = [_session(index, 0.0, index) for index in range(1, 6)]
        sessions.append(_session(6, 0.0, 9))
        sessions[2]["median_log_amp"] = 3.0
        sessions[2]["ts_start"] = "2026-01-01T03:00:00+00:00"
        facts = {"n_sessions": len(sessions), "sessions": sessions}
        review = review_from_facts(facts)
        self.assertTrue(review["concerning"])
        self.assertGreater(review["highest_z"], 2.0)
        self.assertIn("Session 3", review["sections"][1]["lines"][1])
        self.assertIn("Session 6", review["sections"][2]["lines"][0])
        self.assertIsNotNone(review["care_plan"])
        text = compose_analysis(facts)
        self.assertLess(text.index("Summary"), text.index("Care plan"))
        lowered = text.lower()
        self.assertNotIn("you should", lowered)
        for banned in ("prescribe", "milligram", "levodopa", "increase the dose", "parkinson"):
            self.assertNotIn(banned, lowered)

    def test_tied_highest_keeps_the_later_session(self) -> None:
        facts = {"n_sessions": 2, "sessions": [_session(1, 1.5, 8), _session(2, 1.5, 11)]}
        review = review_from_facts(facts)
        self.assertIn("Session 2", review["sections"][1]["lines"][1])

    def test_missing_measure_omits_the_unit(self) -> None:
        row = _session(1, 0.2, 8)
        row["median_amp_deg"] = None
        review = review_from_facts({"n_sessions": 1, "sessions": [row]})
        lines = review["sections"][1]["lines"]
        self.assertIn("Median amplitude: not stored.", lines)
        self.assertNotIn("not stored deg", "\n".join(lines))
        self.assertIn("Windows: 4.", lines)

    def test_empty_store_has_three_sections_and_no_care_plan(self) -> None:
        review = review_from_facts({"n_sessions": 0, "sessions": []})
        self.assertEqual(len(review["sections"]), 3)
        self.assertFalse(review["concerning"])
        self.assertIsNone(review["care_plan"])
        self.assertIn("No sessions are stored yet.", review["summary"])
        self.assertNotIn("diagnosis", review["summary"].lower())
        self.assertNotIn("medication", review["summary"].lower())

    def test_summary_states_results_strength_and_trend(self) -> None:
        sessions = [_session(1, 0.0, 8), _session(2, 0.1, 9), _session(3, 0.2, 10)]
        review = review_from_facts({"n_sessions": 3, "sessions": sessions})
        summary = review["summary"]
        lowered = summary.lower()
        self.assertIn("Average median log amplitude is 0.10.", summary)
        self.assertIn("Average median peak is 4.00 Hz.", summary)
        self.assertIn("Average tremor share is 25.0%.", summary)
        self.assertIn("session 3", summary)
        self.assertIn("inside the comparison line", summary)
        self.assertIn("within the usual spread", summary)
        self.assertIn("higher in the later sessions", summary)
        self.assertIn("Median peak frequency stays near 4.00 Hz", summary)
        self.assertNotIn("diagnosis", lowered)
        self.assertNotIn("medication", lowered)
        self.assertNotIn("parkinson", lowered)

    def test_summary_names_a_falling_trend(self) -> None:
        sessions = [_session(1, 1.0, 8), _session(2, 0.2, 9)]
        sessions[1]["median_peak_hz"] = 6.0
        summary = review_from_facts({"n_sessions": 2, "sessions": sessions})["summary"]
        self.assertIn("lower in the later sessions", summary)
        self.assertIn("recorded frequency is higher later", summary)
        self.assertIn("session 2", summary.lower())
        self.assertNotIn("diagnosis", summary.lower())
        self.assertNotIn("medication", summary.lower())

    def test_summary_calls_a_flat_trend_about_the_same(self) -> None:
        sessions = [_session(1, 0.40, 8), _session(2, 0.42, 10)]
        summary = review_from_facts({"n_sessions": 2, "sessions": sessions})["summary"]
        self.assertIn("about the same from the earlier sessions to the later ones", summary)

    def test_concerning_summary_stays_on_the_signal(self) -> None:
        sessions = [_session(index, 0.0, index) for index in range(1, 6)]
        sessions.append(_session(6, 0.0, 9))
        sessions[2]["median_log_amp"] = 3.0
        sessions[2]["ts_start"] = "2026-01-01T03:00:00+00:00"
        review = review_from_facts({"n_sessions": len(sessions), "sessions": sessions})
        summary = review["summary"].lower()
        self.assertIn("past the comparison line", summary)
        self.assertIn("concerning", summary)
        self.assertIn("lower in the later sessions", summary)
        self.assertNotIn("diagnosis", summary)
        self.assertNotIn("medication", summary)
        self.assertNotIn("parkinson", summary)


class PlannerRunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        with Session(engine) as session:
            seed_database(session, reset=True)

    def test_analysis_cites_stored_numbers(self) -> None:
        result = run_thread("analysis-1", "Review the stored sessions and analyze the movement.")
        self.assertEqual(result["status"], "finished")
        text = result["analysis"]
        lowered = text.lower()
        self.assertIn("TremorBand is a monitoring aid, not a diagnostic device.", text)
        self.assertIn("Monitoring aid, not a diagnosis.", text)
        self.assertIn("simulated", lowered)
        self.assertIn("5.00", text)
        self.assertNotIn("you should", lowered)
        for banned in ("prescribe", "milligram", "levodopa", "increase the dose"):
            self.assertNotIn(banned, lowered)
        review = result["review"]
        titles = [section["title"] for section in review["sections"]]
        self.assertEqual(
            titles,
            [
                "Average across stored sessions",
                "Highest session by median log amplitude",
                "Most recent session",
            ],
        )
        self.assertEqual(review["measure_key"], "median_log_amp")
        self.assertFalse(review["concerning"])
        self.assertIsNone(review["care_plan"])
        self.assertNotIn("Care plan", text)
        self.assertIn("Summary", text)
        self.assertIn("inside the comparison line", review["summary"])
        self.assertIn("Across sessions over time", review["summary"])
        self.assertNotIn("diagnosis", review["summary"].lower())
        self.assertNotIn("medication", review["summary"].lower())

    def test_trigger_refuses_without_a_band(self) -> None:
        with Session(engine) as session:
            plan = plan_extra_tests(session)
        self.assertIn("decision", plan)
        result = trigger_test.invoke({"test_type": "not-a-test", "reason": "check"})
        self.assertFalse(result["queued"])


if __name__ == "__main__":
    unittest.main()

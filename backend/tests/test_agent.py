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

    def test_trigger_refuses_without_a_band(self) -> None:
        with Session(engine) as session:
            plan = plan_extra_tests(session)
        self.assertIn("decision", plan)
        result = trigger_test.invoke({"test_type": "not-a-test", "reason": "check"})
        self.assertFalse(result["queued"])


if __name__ == "__main__":
    unittest.main()

"""Care planner tools and the approval interrupt, with the scripted model."""

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

from agent.planner import resume_thread, run_thread  # noqa: E402
from agent.tools import _in_sleep, plan_extra_tests, trigger_test  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.models import Report  # noqa: E402
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


class PlannerRunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        with Session(engine) as session:
            seed_database(session, reset=True)

    def test_weekly_review_pauses_before_sending(self) -> None:
        result = run_thread("weekly-1", "Run the weekly review.")
        self.assertEqual(result["status"], "interrupted")
        action = result["interrupts"][0]["value"]["action_requests"][0]
        self.assertEqual(action["name"], "send_report")
        report_id = action["args"]["report_id"]
        with Session(engine) as session:
            report = session.get(Report, report_id)
            self.assertIsNotNone(report)
            assert report is not None
            self.assertEqual(report.status, "draft")
            self.assertIn("TremorBand is a monitoring aid, not a diagnostic device.", report.markdown)
            self.assertIn("Monitoring aid, not a diagnosis.", report.markdown)
            self.assertNotIn("you should", report.markdown.lower())
        edited = resume_thread(
            "weekly-1",
            [
                {
                    "type": "edit",
                    "edited_action": {
                        "name": "send_report",
                        "args": {"report_id": report_id, "recipient": "clinic desk"},
                    },
                }
            ],
        )
        self.assertEqual(edited["status"], "finished")
        with Session(engine) as session:
            report = session.get(Report, report_id)
            assert report is not None
            self.assertEqual(report.status, "sent")
            self.assertEqual(report.recipient, "clinic desk")

    def test_threshold_change_waits_for_approval(self) -> None:
        paused = run_thread("threshold-1", "Please move the comparison line.")
        self.assertEqual(paused["status"], "interrupted")
        action = paused["interrupts"][0]["value"]["action_requests"][0]
        self.assertEqual(action["name"], "update_baseline")
        rejected = resume_thread("threshold-1", [{"type": "reject", "message": "Leave the line where it is."}])
        self.assertEqual(rejected["status"], "finished")
        from app.models import Baseline

        with Session(engine) as session:
            baseline = session.get(Baseline, "rest")
            assert baseline is not None
            self.assertAlmostEqual(baseline.threshold_z, 2.0)
        paused_again = run_thread("threshold-2", "Please move the comparison line.")
        approved = resume_thread("threshold-2", [{"type": "approve"}])
        self.assertEqual(paused_again["status"], "interrupted")
        self.assertEqual(approved["status"], "finished")
        with Session(engine) as session:
            baseline = session.get(Baseline, "rest")
            assert baseline is not None
            self.assertAlmostEqual(baseline.threshold_z, 2.5)

    def test_trigger_refuses_without_a_band(self) -> None:
        with Session(engine) as session:
            plan = plan_extra_tests(session)
        self.assertIn("decision", plan)
        result = trigger_test.invoke({"test_type": "not-a-test", "reason": "check"})
        self.assertFalse(result["queued"])


if __name__ == "__main__":
    unittest.main()

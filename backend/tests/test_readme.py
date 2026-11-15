"""The README and every dashboard page keep the monitoring-aid line."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ReadmeTest(unittest.TestCase):
    def test_required_sections(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        for heading in ("## Wiring", "## Setup", "## Troubleshooting", "## Two-minute demo"):
            self.assertIn(heading, text)
        self.assertIn("EI_CLASSIFIER_TFLITE_ENABLE_ESP_NN 0", text)
        self.assertIn("TremorBand is a monitoring aid, not a diagnostic device.", text)
        self.assertIn("OPENAI_API_KEY", text)
        self.assertIn("TREMORBAND_MODEL", text)
        self.assertIn("openai:gpt-4o-mini", text)
        self.assertNotIn("you should take", text.lower())
        nav = (ROOT / "dashboard" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn('href="#/live"', nav)
        self.assertIn('href="#/session"', nav)
        self.assertIn('href="#/analysis"', nav)
        for removed in ('href="#/trends"', 'href="#/log"', 'href="#/agent"', 'href="#/report"'):
            self.assertNotIn(removed, nav)

    def test_every_page_renders_the_disclaimer(self) -> None:
        pages = list((ROOT / "dashboard" / "src" / "pages").glob("*.tsx"))
        self.assertGreaterEqual(len(pages), 8)
        for path in pages:
            text = path.read_text(encoding="utf-8")
            self.assertIn("{DISCLAIMER}", text, path.name)
            self.assertNotIn("you should", text.lower(), path.name)


if __name__ == "__main__":
    unittest.main()

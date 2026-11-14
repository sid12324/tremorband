"""Synthetic sessions, leave-one-person-out scores, and the exported model."""

from __future__ import annotations

import pickle
import subprocess
import tempfile
import unittest
from pathlib import Path

from ml.collect import countdown, load_sessions, metronome, parse_forward_line, session_rows, write_synthetic_corpus
from ml.export_model import export_header
from ml.inference import p_tremor_server
from ml.train import rig_tremor_fraction, run, windows_from_rows

ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "firmware" / "band" / "src" / "model_params.h"


class Milestone6Test(unittest.TestCase):
    def test_capture_helpers(self) -> None:
        lines: list[str] = []
        countdown(3, write=lines.append, sleep=lambda _seconds: None)
        self.assertEqual(lines, ["3", "2", "1"])
        ticks: list[str] = []
        self.assertEqual(metronome(5, 1.0, write=ticks.append, sleep=lambda _seconds: None, beep=False), 5)
        self.assertEqual(len(ticks), 5)
        parsed = parse_forward_line("1000,0.1,0.2,9.81,30,0,0\n")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], 1000)
        self.assertAlmostEqual(parsed[3], 9.81)
        self.assertIsNone(parse_forward_line('{"type":"log"}\n'))
        with self.assertRaises(ValueError):
            session_rows([(0, 0, 0, 0, 0, 0, 0)], person_id="p01", label="still", wrist="left", pose="rest", source="rig", synthetic="yes")

    def test_lopo_metrics_and_exported_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            model_dir = root / "model"
            plot_dir = root / "plots"
            write_synthetic_corpus(data)
            rows = load_sessions(data)
            self.assertTrue(rows)
            self.assertTrue(all(row["synthetic"] == "yes" for row in rows))
            self.assertEqual(rows[0]["person_id"], "p01")
            windows = windows_from_rows(rows)
            fraction = rig_tremor_fraction(windows)
            self.assertLess(fraction, 0.5)
            self.assertAlmostEqual(fraction, 1 / 3)
            report = run(data, model_dir, plot_dir)
            self.assertEqual(report["people"], ["p01", "p02", "p03", "p04"])
            self.assertEqual(report["windows"], 120)
            self.assertEqual(report["real_rows"], 0)
            self.assertEqual(report["chosen"], "random_forest")
            forest = report["random_forest"]
            tree = report["decision_tree"]
            self.assertEqual(forest["confusion"], [[20, 0, 0], [0, 40, 0], [0, 5, 55]])
            self.assertEqual(forest["support"], {"still": 20, "voluntary": 40, "tremor": 60})
            self.assertAlmostEqual(forest["precision"]["still"], 1.0)
            self.assertAlmostEqual(forest["precision"]["voluntary"], 0.8888888888888888)
            self.assertAlmostEqual(forest["precision"]["tremor"], 1.0)
            self.assertAlmostEqual(forest["recall"]["still"], 1.0)
            self.assertAlmostEqual(forest["recall"]["voluntary"], 1.0)
            self.assertAlmostEqual(forest["recall"]["tremor"], 0.9166666666666666)
            self.assertAlmostEqual(forest["macro_f1"], 0.9658994032395567)
            self.assertEqual(tree["confusion"], [[20, 0, 0], [0, 40, 0], [10, 0, 50]])
            self.assertAlmostEqual(tree["precision"]["still"], 0.6666666666666666)
            self.assertAlmostEqual(tree["recall"]["tremor"], 0.8333333333333334)
            self.assertAlmostEqual(tree["macro_f1"], 0.903030303030303)
            self.assertGreater(plot_dir.joinpath("confusion_random_forest.png").stat().st_size, 1000)
            self.assertGreater(plot_dir.joinpath("confusion_decision_tree.png").stat().st_size, 1000)
            header = root / "model_params.h"
            export_header(model_dir / "tremor_model.pkl", header)
            self.assertEqual(header.read_text(), HEADER.read_text())
            self.assertIn("tb_model_predict_proba", header.read_text())
            tremor = next(row for row in windows if row["label"] == "tremor" and row["source"] == "human")
            score = p_tremor_server(tremor["vector"], model_dir / "tremor_model.pkl")
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)
            binary = root / "score"
            source = root / "score.cpp"
            source.write_text(
                """
                #include <cstdio>
                #pragma GCC diagnostic push
                #pragma GCC diagnostic ignored "-Wunused-parameter"
                #pragma GCC diagnostic ignored "-Wunused-variable"
                #include "model_params.h"
                #pragma GCC diagnostic pop
                int main() {
                  float features[TB_MODEL_N_FEATURES];
                  float scores[TB_MODEL_N_CLASSES];
                  for (int i = 0; i < TB_MODEL_N_FEATURES; ++i) {
                    if (std::scanf("%f", &features[i]) != 1) return 2;
                  }
                  if (tb_model_predict_proba(features, TB_MODEL_N_FEATURES, scores, TB_MODEL_N_CLASSES) != 0) return 3;
                  std::printf("%.8f\\n", scores[TB_MODEL_TREMOR_INDEX]);
                  return 0;
                }
                """,
                encoding="utf-8",
            )
            compiled = subprocess.run(
                ["g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", f"-I{root}", str(source), "-o", str(binary), "-lm"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            vector = " ".join(f"{value:.8g}" for value in tremor["vector"])
            scored = subprocess.run([str(binary)], input=vector + "\n", text=True, capture_output=True, check=False)
            self.assertEqual(scored.returncode, 0, scored.stderr)
            self.assertAlmostEqual(float(scored.stdout.strip()), score, places=6)
            with (model_dir / "tremor_model.pkl").open("rb") as handle:
                payload = pickle.load(handle)
            self.assertEqual(payload["kind"], "random_forest")
            self.assertIn("synthetic", payload["note"])


if __name__ == "__main__":
    unittest.main()

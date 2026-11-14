"""Leave-one-person-out training for a small forest and a decision tree.

The captures used here are synthetic unless a CSV says synthetic=no.
Scores are measurements, not a diagnosis.
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.tree import DecisionTreeClassifier

from ml.collect import load_sessions, write_synthetic_corpus
from ml.features import FEATURE_NAMES, compute_windows, feature_vector

CLASS_ORDER = ("still", "voluntary", "tremor")
FOREST_PARAMS = {"n_estimators": 8, "max_depth": 6, "min_samples_leaf": 2, "random_state": 7}
TREE_PARAMS = {"max_depth": 5, "min_samples_leaf": 2, "random_state": 7}


def windows_from_rows(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    """Turn raw samples into one feature row per hop, keeping the session label."""
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, str]]] = {}
    for row in rows:
        key = (row["person_id"], row["label"], row["pose"], row["source"], row["synthetic"])
        grouped.setdefault(key, []).append(row)
    windows: list[dict[str, object]] = []
    for (person_id, label, pose, source, synthetic), samples in grouped.items():
        ordered = sorted(samples, key=lambda item: int(item["ts_us"]))
        axes = {
            name: [float(item[name]) for item in ordered]
            for name in ("ax", "ay", "az", "gx", "gy", "gz")
        }
        for features in compute_windows(axes["ax"], axes["ay"], axes["az"], axes["gx"], axes["gy"], axes["gz"]):
            windows.append(
                {
                    "person_id": person_id,
                    "label": label,
                    "pose": pose,
                    "source": source,
                    "synthetic": synthetic,
                    "vector": feature_vector(features),
                }
            )
    return windows


def rig_tremor_fraction(windows: list[dict[str, object]]) -> float:
    """Share of tremor windows that came from the rig. The cap is one half."""
    tremor = [row for row in windows if row["label"] == "tremor"]
    if not tremor:
        return 0.0
    rig = sum(1 for row in tremor if row["source"] == "rig")
    return rig / len(tremor)


def _estimator(kind: str) -> RandomForestClassifier | DecisionTreeClassifier:
    if kind == "random_forest":
        return RandomForestClassifier(**FOREST_PARAMS)
    if kind == "decision_tree":
        return DecisionTreeClassifier(**TREE_PARAMS)
    raise ValueError(kind)


def _macro_f1(precision: np.ndarray, recall: np.ndarray) -> float:
    scores = []
    for prec, rec in zip(precision, recall):
        total = prec + rec
        scores.append(0.0 if total == 0 else float(2 * prec * rec / total))
    return float(np.mean(scores))


def leave_one_person_out(windows: list[dict[str, object]], kind: str) -> dict[str, object]:
    """Train on every person but one, and stack the held-out predictions."""
    x = np.asarray([row["vector"] for row in windows], dtype=float)
    y = np.asarray([str(row["label"]) for row in windows])
    groups = np.asarray([str(row["person_id"]) for row in windows])
    folded_true: list[str] = []
    folded_pred: list[str] = []
    people: list[str] = []
    for train_index, test_index in LeaveOneGroupOut().split(x, y, groups):
        model = _estimator(kind)
        model.fit(x[train_index], y[train_index])
        predicted = model.predict(x[test_index])
        folded_true.extend(y[test_index].tolist())
        folded_pred.extend(predicted.tolist())
        people.append(str(groups[test_index][0]))
    matrix = confusion_matrix(folded_true, folded_pred, labels=list(CLASS_ORDER))
    precision, recall, _, support = precision_recall_fscore_support(
        folded_true, folded_pred, labels=list(CLASS_ORDER), zero_division=0
    )
    return {
        "kind": kind,
        "people": people,
        "labels": list(CLASS_ORDER),
        "confusion": matrix.tolist(),
        "precision": {label: float(precision[i]) for i, label in enumerate(CLASS_ORDER)},
        "recall": {label: float(recall[i]) for i, label in enumerate(CLASS_ORDER)},
        "support": {label: int(support[i]) for i, label in enumerate(CLASS_ORDER)},
        "macro_f1": _macro_f1(precision, recall),
        "n": len(folded_true),
    }


def save_confusion_plot(report: dict[str, object], path: Path) -> None:
    """Write one confusion-matrix image for a leave-one-person-out run."""
    matrix = np.asarray(report["confusion"], dtype=float)
    labels = list(report["labels"])
    figure, axis = plt.subplots(figsize=(6, 5))
    image = axis.imshow(matrix, cmap="Blues")
    axis.set_xticks(range(len(labels)), labels)
    axis.set_yticks(range(len(labels)), labels)
    axis.set_xlabel("Predicted")
    axis.set_ylabel("Session label")
    axis.set_title(f"{report['kind']} leave-one-person-out\nSynthetic unless noted. Not a diagnosis.")
    for row in range(matrix.shape[0]):
        for col in range(matrix.shape[1]):
            axis.text(col, row, str(int(matrix[row, col])), ha="center", va="center")
    figure.colorbar(image, ax=axis)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)


def fit_all(windows: list[dict[str, object]], kind: str) -> RandomForestClassifier | DecisionTreeClassifier:
    """Fit the deployed model on every person after the held-out scores are saved."""
    model = _estimator(kind)
    x = np.asarray([row["vector"] for row in windows], dtype=float)
    y = np.asarray([str(row["label"]) for row in windows])
    model.fit(x, y)
    return model


def run(data_dir: Path, model_dir: Path, plot_dir: Path) -> dict[str, object]:
    """Load sessions, score both models, and save the chosen one."""
    if not any(data_dir.glob("*.csv")):
        write_synthetic_corpus(data_dir)
    rows = load_sessions(data_dir)
    windows = windows_from_rows(rows)
    if not windows:
        raise RuntimeError(f"no feature windows in {data_dir}")
    fraction = rig_tremor_fraction(windows)
    if fraction >= 0.5:
        raise RuntimeError(f"rig tremor fraction {fraction:.3f} is not under one half")
    forest = leave_one_person_out(windows, "random_forest")
    tree = leave_one_person_out(windows, "decision_tree")
    chosen = "random_forest" if forest["macro_f1"] >= tree["macro_f1"] else "decision_tree"
    plot_dir.mkdir(parents=True, exist_ok=True)
    save_confusion_plot(forest, plot_dir / "confusion_random_forest.png")
    save_confusion_plot(tree, plot_dir / "confusion_decision_tree.png")
    model = fit_all(windows, chosen)
    model_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": model,
        "feature_names": list(FEATURE_NAMES),
        "kind": chosen,
        "classes": [str(label) for label in model.classes_],
        "note": "Trained on the CSV sessions in ml/data. A synthetic=yes row is not a real capture. Not a diagnosis.",
    }
    with (model_dir / "tremor_model.pkl").open("wb") as handle:
        pickle.dump(payload, handle)
    report = {
        "synthetic_rows": sum(1 for row in rows if row["synthetic"] == "yes"),
        "real_rows": sum(1 for row in rows if row["synthetic"] == "no"),
        "windows": len(windows),
        "people": sorted({str(row["person_id"]) for row in windows}),
        "rig_tremor_window_fraction": fraction,
        "random_forest": {key: forest[key] for key in ("precision", "recall", "support", "confusion", "macro_f1", "n")},
        "decision_tree": {key: tree[key] for key in ("precision", "recall", "support", "confusion", "macro_f1", "n")},
        "labels": list(CLASS_ORDER),
        "chosen": chosen,
        "exported_fit": "all_people_after_leave_one_person_out",
        "forest_params": FOREST_PARAMS,
        "tree_params": TREE_PARAMS,
    }
    with (model_dir / "metrics.json").open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    return report


def main(argv: list[str] | None = None) -> int:
    """Train from ml/data and write ml/model plus the confusion plots."""
    parser = argparse.ArgumentParser(description="Train the TremorBand window classifier")
    parser.add_argument("--data-dir", type=Path, default=Path("ml/data"))
    parser.add_argument("--model-dir", type=Path, default=Path("ml/model"))
    parser.add_argument("--plot-dir", type=Path, default=Path("ml/plots"))
    args = parser.parse_args(argv)
    report = run(args.data_dir, args.model_dir, args.plot_dir)
    print(
        json.dumps(
            {
                "chosen": report["chosen"],
                "windows": report["windows"],
                "rig_tremor_window_fraction": report["rig_tremor_window_fraction"],
                "random_forest_macro_f1": report["random_forest"]["macro_f1"],
                "decision_tree_macro_f1": report["decision_tree"]["macro_f1"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

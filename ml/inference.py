"""Server-side copy of the exported window model.

`p_tremor_server` is the fallback the backend can call. It is the tremor-class
probability from the same pickle `ml/export_model.py` turns into C. It is not
a diagnosis.
"""

from __future__ import annotations

import pickle
from collections.abc import Mapping, Sequence
from pathlib import Path

from ml.features import FEATURE_NAMES

MODEL_PATH = Path(__file__).resolve().parent / "model" / "tremor_model.pkl"
_CACHED: dict[str, object] | None = None


def load_model(path: Path | None = None) -> dict[str, object]:
    """Load the pickle written by ml/train.py."""
    global _CACHED
    target = path or MODEL_PATH
    if path is None and _CACHED is not None:
        return _CACHED
    with target.open("rb") as handle:
        payload = pickle.load(handle)
    if path is None:
        _CACHED = payload
    return payload


def p_tremor_server(
    features: Mapping[str, float] | Sequence[float],
    path: Path | None = None,
) -> float:
    """Tremor-class probability for one feature row. Not a diagnosis."""
    payload = load_model(path)
    model = payload["model"]
    names = list(payload.get("feature_names", FEATURE_NAMES))
    if isinstance(features, Mapping):
        vector = [float(features[name]) for name in names]
    else:
        vector = [float(value) for value in features]
        if len(vector) != len(names):
            raise ValueError(f"expected {len(names)} features")
    probabilities = model.predict_proba([vector])[0]
    classes = [str(label) for label in model.classes_]
    return float(probabilities[classes.index("tremor")])

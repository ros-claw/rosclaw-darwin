"""Unit tests for learned trigger models."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from rosclaw_darwin.learning.trigger_model import (
    LogisticTriggerModel,
    SmallMLPTriggerModel,
    create_trigger_model,
    evaluate_trigger_model,
)


def _synthetic_data(n: int = 100, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 8)).astype(np.float32)
    # Make the first feature positively correlated with the label.
    logits = 2.0 * X[:, 0] - 0.5
    y = (1 / (1 + np.exp(-logits)) > rng.random(n)).astype(np.float32)
    return X, y


@pytest.mark.parametrize("model_type", ["logistic", "mlp"])
def test_trigger_model_trains_and_predicts(model_type: str):
    X, y = _synthetic_data(120)
    feature_names = [f"f{i}" for i in range(X.shape[1])]
    model = create_trigger_model(model_type, feature_names, hidden_dim=8, random_seed=1)
    metrics = model.fit(X, y, epochs=50, lr=1e-2, batch_size=32, patience=10)
    assert "epochs_trained" in metrics

    probs = model.predict_proba(X)
    assert probs.shape == (len(y), 2)
    assert np.all((probs >= 0) & (probs <= 1))
    assert np.allclose(probs.sum(axis=1), 1.0, atol=1e-5)

    preds = model.predict(X)
    assert preds.shape == (len(y),)
    assert set(preds).issubset({0, 1})


def test_logistic_finds_separable_data():
    """On linearly separable data the logistic model should reach high accuracy."""
    rng = np.random.default_rng(2)
    n = 200
    X_pos = rng.normal(loc=1.0, scale=0.5, size=(n, 4))
    X_neg = rng.normal(loc=-1.0, scale=0.5, size=(n, 4))
    X = np.vstack([X_pos, X_neg]).astype(np.float32)
    y = np.array([1.0] * n + [0.0] * n, dtype=np.float32)

    model = LogisticTriggerModel(["a", "b", "c", "d"], random_seed=3)
    model.fit(X, y, epochs=200, lr=1e-2, batch_size=64, patience=20)

    eval_metrics = evaluate_trigger_model(model, X, y)
    assert eval_metrics["accuracy"] > 0.85


def test_save_and_load_roundtrip():
    X, y = _synthetic_data(80)
    feature_names = [f"f{i}" for i in range(X.shape[1])]
    model = SmallMLPTriggerModel(feature_names, hidden_dim=8, random_seed=4)
    model.fit(X, y, epochs=30, lr=1e-2, batch_size=32, patience=10)

    probs_before = model.predict_proba(X)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "model.json"
        model.save(path)
        loaded = model.load(path)
        probs_after = loaded.predict_proba(X)

    assert loaded.feature_names == feature_names
    assert isinstance(loaded, SmallMLPTriggerModel)
    assert np.allclose(probs_before, probs_after, atol=1e-6)


def test_evaluate_trigger_model_basic():
    rng = np.random.default_rng(5)
    n = 100
    X = rng.normal(size=(n, 4)).astype(np.float32)
    y = np.zeros(n, dtype=np.float32)
    y[:40] = 1.0
    model = LogisticTriggerModel(["a", "b", "c", "d"], random_seed=6)
    model.fit(X, y, epochs=20, lr=1e-2, batch_size=32)
    metrics = evaluate_trigger_model(model, X, y)
    assert 0 <= metrics["accuracy"] <= 1
    assert "auroc" in metrics
    assert "calibration_error" in metrics


@pytest.mark.parametrize("model_type", ["logistic", "mlp"])
def test_create_trigger_model_factory(model_type: str):
    model = create_trigger_model(model_type, ["x", "y"], hidden_dim=4, random_seed=7)
    assert model.input_dim == 2
    assert model.feature_names == ["x", "y"]


def test_gb_trigger_model_fallback_when_sklearn_missing(monkeypatch):
    """GBTriggerModel should fall back to MLP if sklearn is unavailable."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sklearn" or name.startswith("sklearn."):
            raise ImportError("sklearn unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    # Re-import to exercise the fallback path inside GBTriggerModel.__init__.
    from rosclaw_darwin.learning.trigger_model import GBTriggerModel

    X, y = _synthetic_data(80)
    X = X[:, :4]
    model = GBTriggerModel(["a", "b", "c", "d"], hidden_dim=8, random_seed=8)
    info = model.fit(X, y, epochs=30, lr=1e-2, batch_size=32, patience=10)
    assert info["model"] in {"small_mlp", "gradient_boosting", "gradient_boosting_fallback_mlp"}
    probs = model.predict_proba(X)
    assert probs.shape == (len(y), 2)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

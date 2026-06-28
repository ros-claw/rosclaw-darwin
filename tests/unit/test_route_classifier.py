"""Unit tests for route classifier."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from rosclaw_darwin.learning.residual_dataset import ResidualDataset, ResidualFrame
from rosclaw_darwin.learning.route_classifier import (
    ROUTE_CLASSES,
    SmallMLPRouteClassifier,
    create_route_classifier,
    evaluate_route_classifier,
)


def _synthetic_route_data(n_per_class: int = 30, seed: int = 0) -> tuple[np.ndarray, np.ndarray, list[str]]:
    rng = np.random.default_rng(seed)
    X: list[np.ndarray] = []
    y: list[int] = []
    for idx, route in enumerate(ROUTE_CLASSES):
        for _ in range(n_per_class):
            feat = rng.normal(size=6).astype(np.float32)
            # Make classes separable by shifting a feature dimension.
            feat[idx % 6] += 1.5
            X.append(feat)
            y.append(idx)
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.int64), [f"f{i}" for i in range(6)]


def test_small_mlp_route_classifier_trains():
    X, y, feature_names = _synthetic_route_data(40)
    model = SmallMLPRouteClassifier(feature_names, hidden_dim=8, random_seed=1)
    info = model.fit(X, y, epochs=80, lr=1e-2, batch_size=32, patience=10)
    assert "epochs_trained" in info

    preds = model.predict(X)
    assert len(preds) == len(y)
    acc = float(np.mean(preds == y))
    assert acc > 0.5


def test_save_load_roundtrip():
    X, y, feature_names = _synthetic_route_data(30)
    model = SmallMLPRouteClassifier(feature_names, hidden_dim=8, random_seed=2)
    model.fit(X, y, epochs=40, lr=1e-2, batch_size=32, patience=10)
    pred_before = model.predict_proba(X)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "route_classifier.json"
        model.save(path)
        loaded = SmallMLPRouteClassifier.load(path)
        pred_after = loaded.predict_proba(X)

    assert isinstance(loaded, SmallMLPRouteClassifier)
    assert loaded.feature_names == feature_names
    assert np.allclose(pred_before, pred_after, atol=1e-6)


def test_factory_creates_mlp():
    model = create_route_classifier("mlp", ["a", "b"], hidden_dim=4, random_seed=3)
    assert model.input_dim == 2
    assert model.num_classes == len(ROUTE_CLASSES)


def test_factory_rejects_unknown_type():
    with pytest.raises(ValueError):
        create_route_classifier("transformer", ["a", "b"])


def test_evaluate_route_classifier():
    X, y, feature_names = _synthetic_route_data(20)
    model = SmallMLPRouteClassifier(feature_names, hidden_dim=8, random_seed=4)
    model.fit(X, y, epochs=40, lr=1e-2, batch_size=32, patience=10)
    metrics = evaluate_route_classifier(model, X, y)
    assert "accuracy" in metrics
    assert "per_class_recall" in metrics
    assert "route_distribution" in metrics
    assert "confusion_matrix" in metrics
    assert len(metrics["confusion_matrix"]) == len(ROUTE_CLASSES)


def test_to_route_label_matrix():
    frames = [
        ResidualFrame(
            episode=1,
            step=0,
            task="goal_pose",
            phase="LIFT",
            success_label=True,
            observation={"object_z": 0.05, "gripper_pos": 0.02},
            route_label="continue",
            residual_target=[0.0] * 7,
        ),
        ResidualFrame(
            episode=2,
            step=0,
            task="goal_pose",
            phase="LIFT",
            success_label=False,
            observation={"object_z": 0.01, "gripper_pos": 0.04},
            route_label="blocked_external",
            residual_target=[0.0] * 7,
        ),
        ResidualFrame(
            episode=3,
            step=0,
            task="goal_pose",
            phase="LIFT",
            success_label=False,
            observation={"object_z": 0.01, "gripper_pos": 0.04},
            route_label="lower_regrip",
            residual_target=[0.0] * 7,
        ),
        ResidualFrame(
            episode=4,
            step=0,
            task="goal_pose",
            phase="LIFT",
            success_label=False,
            observation={"object_z": 0.01, "gripper_pos": 0.04},
            route_label="unknown_route",
            residual_target=[0.0] * 7,
        ),
    ]
    ds = ResidualDataset(frames)
    mat = ds.to_route_label_matrix()
    assert mat["X"].shape[0] == 3
    assert mat["y"].shape[0] == 3
    assert set(mat["y"].tolist()) == {0, 4, 2}  # continue, blocked_external, lower_regrip
    assert mat["route_classes"] == ROUTE_CLASSES


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

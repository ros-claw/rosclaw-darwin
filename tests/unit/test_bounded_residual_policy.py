"""Unit tests for bounded residual policy."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from rosclaw_darwin.learning.bounded_residual_policy import (
    BoundedMLPResidualModel,
    BoundedResidualPolicy,
    TriggeredResidualPolicy,
    TriggeredRuleResidualPolicy,
    create_bounded_residual_model,
    evaluate_bounded_residual_offline,
    load_triggered_residual_policy,
    load_triggered_rule_policy,
)
from rosclaw_darwin.learning.residual_dataset import ResidualDataset, ResidualFrame
from rosclaw_darwin.learning.residual_policy import ResidualAction, ResidualPolicyWrapper
from rosclaw_darwin.learning.trigger_model import SmallMLPTriggerModel


def _synthetic_residual_data(n: int = 80, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 6)).astype(np.float32)
    Y = np.zeros((n, 3), dtype=np.float32)
    # First half: positive dz and negative gripper corrections.
    Y[: n // 2, 0] = 0.003
    Y[: n // 2, 1] = -0.04
    Y[n // 2 :, :] = 0.0
    return X, Y


def test_bounded_mlp_trains_and_residuals_are_clamped():
    X, Y = _synthetic_residual_data(100)
    feature_names = [f"f{i}" for i in range(X.shape[1])]
    model = BoundedMLPResidualModel(feature_names, hidden_dim=8, random_seed=1)
    info = model.fit(X, Y, epochs=60, lr=1e-2, batch_size=32, patience=10)
    assert "epochs_trained" in info

    Y_pred = model.predict_residual(X)
    assert Y_pred.shape == (len(Y), 3)
    lo_dz, hi_dz = model.limits["dz"]
    lo_g, hi_g = model.limits["dgripper"]
    lo_s, hi_s = model.limits["lift_speed_scale"]
    assert np.all((Y_pred[:, 0] >= lo_dz) & (Y_pred[:, 0] <= hi_dz))
    assert np.all((Y_pred[:, 1] >= lo_g) & (Y_pred[:, 1] <= hi_g))
    assert np.all((Y_pred[:, 2] >= lo_s) & (Y_pred[:, 2] <= hi_s))


def test_save_load_roundtrip():
    X, Y = _synthetic_residual_data(80)
    feature_names = [f"f{i}" for i in range(X.shape[1])]
    model = BoundedMLPResidualModel(feature_names, hidden_dim=8, random_seed=2)
    model.fit(X, Y, epochs=30, lr=1e-2, batch_size=32, patience=10)
    pred_before = model.predict_residual(X)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "model.json"
        model.save(path)
        loaded = model.load(path)
        pred_after = loaded.predict_residual(X)

    assert isinstance(loaded, BoundedMLPResidualModel)
    assert loaded.feature_names == feature_names
    assert np.allclose(pred_before, pred_after, atol=1e-6)


def test_factory_creates_mlp():
    model = create_bounded_residual_model("mlp", ["a", "b"], hidden_dim=4, random_seed=3)
    assert model.input_dim == 2
    assert model.output_dim == 3


def test_factory_rejects_unknown_type():
    with pytest.raises(ValueError):
        create_bounded_residual_model("transformer", ["a", "b"])


def test_bounded_residual_policy_predict_shape():
    feature_names = ["GRASP", "object_z", "gripper_pos", "eef_z", "orientation_error", "object_eef_distance", "object_eef_yaw_delta", "gripper_too_open", "low_object_z", "any_slip", "slip_score", "contact_confidence", "has_contact"]
    model = BoundedMLPResidualModel(feature_names, hidden_dim=4, random_seed=4)
    policy = BoundedResidualPolicy(model)
    action = policy.predict(
        observation={"object_z": 0.01, "gripper_pos": 0.04},
        contact_signal=None,
        slip_signal=None,
        grip_quality_signal={"low_object_z": True, "gripper_too_open": True},
        phase="GRASP",
    )
    assert action.active_axes[2]
    assert action.active_axes[6]
    assert not any(action.active_axes[:2])
    assert not any(action.active_axes[3:6])
    assert action.lift_speed_scale >= 0.5


def test_wrapper_applies_lift_speed_scale():
    feature_names = ["LIFT", "object_z", "gripper_pos", "eef_z", "orientation_error", "object_eef_distance", "object_eef_yaw_delta", "gripper_too_open", "low_object_z", "any_slip", "slip_score", "contact_confidence", "has_contact"]
    model = BoundedMLPResidualModel(feature_names, hidden_dim=4, random_seed=5)
    policy = BoundedResidualPolicy(model)
    wrapper = ResidualPolicyWrapper(policy)

    heuristic = [0.0, 0.0, 0.05, 0.0, 0.0, 0.0, 0.0]
    action = ResidualAction(
        delta_pos=[0.0, 0.0, 0.002],
        delta_gripper=-0.01,
        lift_speed_scale=0.8,
        active_axes=[False, False, True, False, False, False, True],
    )
    final = wrapper.compute_final_action(heuristic, {}, residual_action=action, phase="LIFT")
    assert final[2] == pytest.approx(0.05 * 0.8 + 0.002, abs=1e-6)


def test_evaluate_offline_metrics():
    frames = [
        ResidualFrame(
            episode=1,
            step=0,
            task="goal_pose",
            phase="GRASP",
            success_label=True,
            observation={"object_z": 0.05, "gripper_pos": 0.02},
            residual_target=[0.0] * 7,
        ),
        ResidualFrame(
            episode=2,
            step=0,
            task="goal_pose",
            phase="GRASP",
            success_label=False,
            observation={"object_z": 0.01, "gripper_pos": 0.04},
            residual_target=[0.0, 0.0, -0.003, 0.0, 0.0, 0.0, -0.03],
        ),
    ]
    ds = ResidualDataset(frames)
    feature_names = ds.to_residual_target_matrix()["feature_names"]
    model = BoundedMLPResidualModel(feature_names, hidden_dim=4, random_seed=6)
    metrics = evaluate_bounded_residual_offline(model, ds)
    assert "mse" in metrics
    assert "clamp_rate" in metrics
    assert metrics["success_frame_modification_rate"] is not None


def test_triggered_residual_policy_gates_by_trigger():
    feature_names = ["GRASP", "object_z", "gripper_pos", "eef_z", "orientation_error", "object_eef_distance", "object_eef_yaw_delta", "gripper_too_open", "low_object_z", "any_slip", "slip_score", "contact_confidence", "has_contact"]
    residual_model = BoundedMLPResidualModel(feature_names, hidden_dim=4, random_seed=7)
    trigger_model = SmallMLPTriggerModel(feature_names, hidden_dim=8, random_seed=8)
    # Train trigger to fire only on GRASP with low object_z.
    X, y = [], []
    for _ in range(20):
        X.append([1.0, 0.01, 0.04, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0])
        y.append(1)
        X.append([1.0, 0.05, 0.02, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        y.append(0)
        X.append([0.0, 0.01, 0.04, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0])
        y.append(0)
    X = np.array(X, dtype=np.float32)
    y = np.array(y, dtype=np.float32)
    trigger_model.fit(X, y, epochs=80, lr=1e-2, batch_size=16, patience=20)

    policy = TriggeredResidualPolicy(trigger_model, residual_model, trigger_threshold=0.5)

    fired = policy.predict(
        observation={"object_z": 0.01, "gripper_pos": 0.04},
        contact_signal=None,
        slip_signal=None,
        grip_quality_signal={"low_object_z": True, "gripper_too_open": True},
        phase="GRASP",
    )
    assert fired.reason == "triggered_bounded_residual"
    assert fired.active_axes[2]
    assert fired.active_axes[6]

    not_fired = policy.predict(
        observation={"object_z": 0.05, "gripper_pos": 0.02},
        contact_signal=None,
        slip_signal=None,
        grip_quality_signal={"low_object_z": False, "gripper_too_open": False},
        phase="GRASP",
    )
    assert not_fired.reason == "trigger_below_threshold"
    assert not any(not_fired.active_axes)


def test_load_triggered_residual_policy_roundtrip(tmp_path: Path):
    feature_names = ["GRASP", "object_z", "gripper_pos", "eef_z", "orientation_error", "object_eef_distance", "object_eef_yaw_delta", "gripper_too_open", "low_object_z", "any_slip", "slip_score", "contact_confidence", "has_contact"]
    residual_model = BoundedMLPResidualModel(feature_names, hidden_dim=4, random_seed=9)
    trigger_model = SmallMLPTriggerModel(feature_names, hidden_dim=4, random_seed=10)
    trigger_path = tmp_path / "trigger.json"
    residual_path = tmp_path / "residual.json"
    trigger_model.save(trigger_path)
    residual_model.save(residual_path)

    loaded = load_triggered_residual_policy(trigger_path, residual_path, trigger_threshold=0.4)
    assert isinstance(loaded, TriggeredResidualPolicy)
    assert loaded.trigger_threshold == 0.4
    action = loaded.predict(
        observation={"object_z": 0.01, "gripper_pos": 0.04},
        contact_signal=None,
        slip_signal=None,
        grip_quality_signal={"low_object_z": True, "gripper_too_open": True},
        phase="GRASP",
    )
    assert action.confidence >= 0.0


def _train_toy_trigger(feature_names: list[str]) -> SmallMLPTriggerModel:
    trigger_model = SmallMLPTriggerModel(feature_names, hidden_dim=8, random_seed=11)
    X, y = [], []
    for _ in range(20):
        X.append([1.0, 0.01, 0.04, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0])
        y.append(1)
        X.append([1.0, 0.05, 0.02, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        y.append(0)
        X.append([0.0, 0.01, 0.04, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0])
        y.append(0)
    X = np.array(X, dtype=np.float32)
    y = np.array(y, dtype=np.float32)
    trigger_model.fit(X, y, epochs=80, lr=1e-2, batch_size=16, patience=20)
    return trigger_model


def test_triggered_rule_policy_fires_and_returns_rule_action():
    feature_names = ["GRASP", "object_z", "gripper_pos", "eef_z", "orientation_error", "object_eef_distance", "object_eef_yaw_delta", "gripper_too_open", "low_object_z", "any_slip", "slip_score", "contact_confidence", "has_contact"]
    trigger_model = _train_toy_trigger(feature_names)
    policy = TriggeredRuleResidualPolicy(
        trigger_model, trigger_threshold=0.5, lower_delta_z=0.015, dgripper=-0.05
    )

    fired = policy.predict(
        observation={"object_z": 0.01, "gripper_pos": 0.04},
        contact_signal=None,
        slip_signal=None,
        grip_quality_signal={"low_object_z": True, "gripper_too_open": True},
        phase="GRASP",
    )
    assert fired.reason == "triggered_rule_lower_reclose"
    assert fired.delta_pos[2] == pytest.approx(0.015, abs=1e-6)
    assert fired.delta_gripper == pytest.approx(-0.05, abs=1e-6)
    assert fired.active_axes[2]
    assert fired.active_axes[6]

    not_fired = policy.predict(
        observation={"object_z": 0.05, "gripper_pos": 0.02},
        contact_signal=None,
        slip_signal=None,
        grip_quality_signal={"low_object_z": False, "gripper_too_open": False},
        phase="GRASP",
    )
    assert not_fired.reason == "trigger_below_threshold"
    assert not any(not_fired.active_axes)


def test_load_triggered_rule_policy_roundtrip(tmp_path: Path):
    feature_names = ["GRASP", "object_z", "gripper_pos", "eef_z", "orientation_error", "object_eef_distance", "object_eef_yaw_delta", "gripper_too_open", "low_object_z", "any_slip", "slip_score", "contact_confidence", "has_contact"]
    trigger_model = _train_toy_trigger(feature_names)
    trigger_path = tmp_path / "trigger.json"
    trigger_model.save(trigger_path)

    loaded = load_triggered_rule_policy(trigger_path, trigger_threshold=0.4, lower_delta_z=0.012)
    assert isinstance(loaded, TriggeredRuleResidualPolicy)
    assert loaded.trigger_threshold == 0.4
    assert loaded.lower_delta_z == pytest.approx(0.012, abs=1e-6)
    action = loaded.predict(
        observation={"object_z": 0.01, "gripper_pos": 0.04},
        contact_signal=None,
        slip_signal=None,
        grip_quality_signal={"low_object_z": True, "gripper_too_open": True},
        phase="GRASP",
    )
    assert action.confidence >= 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

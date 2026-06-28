"""Small bounded residual micro-policy for grip-quality failures.

The policy is intentionally restricted to three axes:
- dz (small vertical correction)
- dgripper (small gripper correction)
- lift_speed_scale (bounded multiplier for lift speed)

It implements the ``ResidualPolicy`` interface so it can be wrapped by
``ResidualPolicyWrapper`` and deployed inside the Arena container.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from rosclaw_darwin.learning.residual_policy import ResidualAction, ResidualPolicy
from rosclaw_darwin.learning.trigger_model import TriggerModel

DEFAULT_BOUNDED_LIMITS: dict[str, tuple[float, float]] = {
    "dz": (-0.004, 0.004),
    "dgripper": (-0.05, 0.05),
    "lift_speed_scale": (0.5, 1.0),
}


class BoundedResidualModel(ABC):
    """Base class for a bounded residual regressor."""

    def __init__(
        self,
        feature_names: list[str],
        limits: dict[str, tuple[float, float]] | None = None,
        random_seed: int = 42,
    ) -> None:
        self.feature_names = feature_names
        self.input_dim = len(feature_names)
        self.output_dim = 3
        self.limits = limits if limits is not None else dict(DEFAULT_BOUNDED_LIMITS)
        self.random_seed = random_seed

    @abstractmethod
    def fit(
        self,
        X: np.ndarray,
        Y: np.ndarray,
        sample_weight: np.ndarray | None = None,
        val_data: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> dict[str, Any]:
        """Fit the regressor. Returns training history / metrics."""

    @abstractmethod
    def predict_residual(self, X: np.ndarray) -> np.ndarray:
        """Return shape (n_samples, 3) array of [dz, dgripper, lift_speed_scale]."""

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "class_name": self.__class__.__name__,
            "feature_names": self.feature_names,
            "input_dim": self.input_dim,
            "output_dim": self.output_dim,
            "limits": self.limits,
            "random_seed": self.random_seed,
            "state_dict": self._state_dict_to_serializable(),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @abstractmethod
    def _state_dict_to_serializable(self) -> dict[str, Any]:
        """Return JSON-serializable model weights."""

    @classmethod
    def load(cls, path: str | Path) -> "BoundedResidualModel":
        path = Path(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        class_name = payload["class_name"]
        feature_names = payload["feature_names"]
        limits = payload.get("limits", DEFAULT_BOUNDED_LIMITS)
        random_seed = payload.get("random_seed", 42)
        state_dict = payload["state_dict"]

        if class_name == "BoundedMLPResidualModel":
            hidden_dim = state_dict.get("hidden_dim", 16)
            model: BoundedResidualModel = BoundedMLPResidualModel(
                feature_names,
                limits=limits,
                hidden_dim=hidden_dim,
                random_seed=random_seed,
            )
        else:
            raise ValueError(f"Unknown bounded residual model class: {class_name}")

        model._load_state_dict_from_serializable(state_dict)
        return model

    @abstractmethod
    def _load_state_dict_from_serializable(self, state_dict: dict[str, Any]) -> None:
        """Restore weights from a JSON-serializable state dict."""

    def _clamp_residual(self, Y: np.ndarray) -> np.ndarray:
        """Clamp each output axis to its configured limits."""
        clamped = Y.copy()
        for idx, axis in enumerate(["dz", "dgripper", "lift_speed_scale"]):
            lo, hi = self.limits[axis]
            clamped[:, idx] = np.clip(clamped[:, idx], lo, hi)
        return clamped


class BoundedMLPResidualModel(BoundedResidualModel):
    """Small MLP residual regressor with post-hoc clamping."""

    def __init__(
        self,
        feature_names: list[str],
        limits: dict[str, tuple[float, float]] | None = None,
        hidden_dim: int = 16,
        random_seed: int = 42,
    ) -> None:
        super().__init__(feature_names, limits=limits, random_seed=random_seed)
        self.hidden_dim = hidden_dim
        torch.manual_seed(random_seed)
        self._module = nn.Sequential(
            nn.Linear(self.input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim, self.output_dim),
        )

    def fit(
        self,
        X: np.ndarray,
        Y: np.ndarray,
        sample_weight: np.ndarray | None = None,
        val_data: tuple[np.ndarray, np.ndarray] | None = None,
        epochs: int = 200,
        lr: float = 1e-3,
        batch_size: int = 64,
        patience: int = 20,
    ) -> dict[str, Any]:
        torch.manual_seed(self.random_seed)
        self._module.train()

        X_t = torch.tensor(X, dtype=torch.float32)
        Y_t = torch.tensor(Y, dtype=torch.float32)
        if sample_weight is not None:
            w_t = torch.tensor(sample_weight, dtype=torch.float32).unsqueeze(1)
        else:
            w_t = torch.ones((len(Y_t), 1), dtype=torch.float32)

        optimizer = torch.optim.Adam(self._module.parameters(), lr=lr, weight_decay=1e-4)
        dataset = torch.utils.data.TensorDataset(X_t, Y_t, w_t)
        loader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True)

        best_val_loss = float("inf")
        patience_counter = 0
        best_state: dict[str, Any] = {}
        history: dict[str, list[float]] = {"train_loss": [], "val_loss": []}

        for _ in range(epochs):
            self._module.train()
            epoch_losses: list[float] = []
            for xb, yb, wb in loader:
                optimizer.zero_grad()
                pred = self._module(xb)
                # Do not clamp during training: clamping would zero gradients for
                # outputs that start outside the bounds and prevent the model from
                # learning to reach in-bound targets.  Clamping is applied only at
                # inference time in predict_residual().
                loss = F.mse_loss(pred, yb, reduction="none")
                loss = (loss * wb).mean()
                loss.backward()
                optimizer.step()
                epoch_losses.append(loss.item())
            history["train_loss"].append(float(np.mean(epoch_losses)))

            if val_data is not None:
                self._module.eval()
                with torch.no_grad():
                    Xv, Yv = val_data
                    xv_t = torch.tensor(Xv, dtype=torch.float32)
                    yv_t = torch.tensor(Yv, dtype=torch.float32)
                    val_pred = self._module(xv_t)
                    val_loss = F.mse_loss(val_pred, yv_t).item()
                history["val_loss"].append(val_loss)
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    best_state = {k: v.cpu().clone() for k, v in self._module.state_dict().items()}
                    patience_counter = 0
                else:
                    patience_counter += 1
                    if patience_counter >= patience:
                        break
            else:
                history["val_loss"].append(float("nan"))

        if val_data is not None and best_state:
            self._module.load_state_dict(best_state)

        return {
            "epochs_trained": len(history["train_loss"]),
            "best_val_loss": best_val_loss if val_data is not None else None,
            "history": history,
        }

    def _clamp_tensor(self, t: torch.Tensor) -> torch.Tensor:
        clamped = t.clone()
        for idx, axis in enumerate(["dz", "dgripper", "lift_speed_scale"]):
            lo, hi = self.limits[axis]
            clamped[:, idx] = torch.clamp(t[:, idx], lo, hi)
        return clamped

    def predict_residual(self, X: np.ndarray) -> np.ndarray:
        self._module.eval()
        with torch.no_grad():
            Xt = torch.tensor(X, dtype=torch.float32)
            pred = self._module(Xt).cpu().numpy()
        return self._clamp_residual(pred)

    def _state_dict_to_serializable(self) -> dict[str, Any]:
        return {
            "hidden_dim": self.hidden_dim,
            **{k: v.detach().cpu().tolist() for k, v in self._module.state_dict().items()},
        }

    def _load_state_dict_from_serializable(self, state_dict: dict[str, Any]) -> None:
        hidden_dim = state_dict.pop("hidden_dim", self.hidden_dim)
        self.hidden_dim = hidden_dim
        self._module = nn.Sequential(
            nn.Linear(self.input_dim, self.hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(self.hidden_dim, self.output_dim),
        )
        tensors = {k: torch.tensor(v, dtype=torch.float32) for k, v in state_dict.items()}
        self._module.load_state_dict(tensors)


def create_bounded_residual_model(
    model_type: str,
    feature_names: list[str],
    limits: dict[str, tuple[float, float]] | None = None,
    hidden_dim: int = 16,
    random_seed: int = 42,
) -> BoundedResidualModel:
    """Factory for bounded residual models."""
    if model_type == "mlp":
        return BoundedMLPResidualModel(feature_names, limits=limits, hidden_dim=hidden_dim, random_seed=random_seed)
    raise ValueError(f"Unknown bounded residual model_type: {model_type}. Choose from mlp.")


class BoundedResidualPolicy(ResidualPolicy):
    """ResidualPolicy wrapper around a bounded residual model."""

    def __init__(
        self,
        model: BoundedResidualModel,
        active_phases: set[str] | None = None,
        trigger_threshold: float = 0.5,
    ) -> None:
        self.model = model
        self.active_phases = active_phases if active_phases is not None else {"GRASP", "CONTACT_VERIFY", "PRE_LIFT", "LIFT", "LIFT_VERIFY", "HOLD"}
        self.trigger_threshold = trigger_threshold

    def predict(
        self,
        observation: dict,
        contact_signal: dict | None,
        slip_signal: dict | None,
        grip_quality_signal: dict | None,
        phase: str,
    ) -> ResidualAction:
        if phase not in self.active_phases:
            return ResidualAction(
                delta_pos=[0.0, 0.0, 0.0],
                delta_rot=[0.0, 0.0, 0.0],
                delta_gripper=0.0,
                lift_speed_scale=1.0,
                active_axes=[False] * 7,
                confidence=0.0,
                reason="phase_not_active",
            )

        features = self._observation_to_features(
            observation, contact_signal, slip_signal, grip_quality_signal, phase
        )
        X = np.array([features], dtype=np.float32)
        residual = self.model.predict_residual(X)[0]
        dz, dgripper, speed_scale = residual

        active_axes = [False] * 7
        active_axes[2] = True
        active_axes[6] = True

        return ResidualAction(
            delta_pos=[0.0, 0.0, float(dz)],
            delta_rot=[0.0, 0.0, 0.0],
            delta_gripper=float(dgripper),
            lift_speed_scale=float(speed_scale),
            active_axes=active_axes,
            confidence=1.0,
            reason="bounded_residual_micro_policy",
        )

    def _observation_to_features(
        self,
        observation: dict,
        contact_signal: dict | None,
        slip_signal: dict | None,
        grip_quality_signal: dict | None,
        phase: str,
    ) -> list[float]:
        """Build a feature vector consistent with ResidualDataset.to_residual_target_matrix."""
        phases = self.model.feature_names[: self.model.input_dim - 12]
        numeric_keys = [
            "object_z",
            "gripper_pos",
            "eef_z",
            "orientation_error",
            "object_eef_distance",
            "object_eef_yaw_delta",
        ]
        vec = [0.0] * self.model.input_dim
        if phase in phases:
            vec[phases.index(phase)] = 1.0
        offset = len(phases)
        for i, key in enumerate(numeric_keys):
            vec[offset + i] = float(observation.get(key, 0.0))
        offset += len(numeric_keys)
        gq = grip_quality_signal or {}
        vec[offset + 0] = float(bool(gq.get("gripper_too_open", False)))
        vec[offset + 1] = float(bool(gq.get("low_object_z", False)))
        ss = slip_signal or {}
        vec[offset + 2] = float(bool(ss.get("any_slip", False)))
        vec[offset + 3] = float(ss.get("slip_score", 0.0))
        cs = contact_signal or {}
        vec[offset + 4] = float(cs.get("confidence", 0.0))
        vec[offset + 5] = float(cs.get("state") in {"stable", "contact", "grasp"})
        return vec


class TriggeredResidualPolicy(ResidualPolicy):
    """Residual policy that gates a bounded residual model with a trigger model.

    The trigger model predicts the probability that a micro-recovery is needed.
    If the probability is below ``trigger_threshold`` the policy returns a no-op
    residual; otherwise it returns the bounded residual action.  This keeps the
    residual micro-policy off the success manifold and reduces false positives.
    """

    def __init__(
        self,
        trigger_model: TriggerModel,
        residual_model: BoundedResidualModel,
        active_phases: set[str] | None = None,
        trigger_threshold: float = 0.5,
    ) -> None:
        self.trigger_model = trigger_model
        self.residual_model = residual_model
        self.active_phases = active_phases if active_phases is not None else {"GRASP", "CONTACT_VERIFY", "PRE_LIFT", "LIFT", "LIFT_VERIFY", "HOLD"}
        self.trigger_threshold = trigger_threshold

    def predict(
        self,
        observation: dict,
        contact_signal: dict | None,
        slip_signal: dict | None,
        grip_quality_signal: dict | None,
        phase: str,
    ) -> ResidualAction:
        if phase not in self.active_phases:
            return ResidualAction(
                delta_pos=[0.0, 0.0, 0.0],
                delta_rot=[0.0, 0.0, 0.0],
                delta_gripper=0.0,
                lift_speed_scale=1.0,
                active_axes=[False] * 7,
                confidence=0.0,
                reason="phase_not_active",
            )

        features = self._observation_to_features(
            observation, contact_signal, slip_signal, grip_quality_signal, phase
        )
        X = np.array([features], dtype=np.float32)
        trigger_prob = float(self.trigger_model.predict_proba(X)[0, 1])

        if trigger_prob < self.trigger_threshold:
            return ResidualAction(
                delta_pos=[0.0, 0.0, 0.0],
                delta_rot=[0.0, 0.0, 0.0],
                delta_gripper=0.0,
                lift_speed_scale=1.0,
                active_axes=[False] * 7,
                confidence=trigger_prob,
                reason="trigger_below_threshold",
            )

        residual = self.residual_model.predict_residual(X)[0]
        dz, dgripper, speed_scale = residual
        active_axes = [False] * 7
        active_axes[2] = True
        active_axes[6] = True

        return ResidualAction(
            delta_pos=[0.0, 0.0, float(dz)],
            delta_rot=[0.0, 0.0, 0.0],
            delta_gripper=float(dgripper),
            lift_speed_scale=float(speed_scale),
            active_axes=active_axes,
            confidence=trigger_prob,
            reason="triggered_bounded_residual",
        )

    def _observation_to_features(
        self,
        observation: dict,
        contact_signal: dict | None,
        slip_signal: dict | None,
        grip_quality_signal: dict | None,
        phase: str,
    ) -> list[float]:
        """Build a feature vector consistent with ResidualDataset feature matrices."""
        phases = self.residual_model.feature_names[: self.residual_model.input_dim - 12]
        numeric_keys = [
            "object_z",
            "gripper_pos",
            "eef_z",
            "orientation_error",
            "object_eef_distance",
            "object_eef_yaw_delta",
        ]
        vec = [0.0] * self.residual_model.input_dim
        if phase in phases:
            vec[phases.index(phase)] = 1.0
        offset = len(phases)
        for i, key in enumerate(numeric_keys):
            vec[offset + i] = float(observation.get(key, 0.0))
        offset += len(numeric_keys)
        gq = grip_quality_signal or {}
        vec[offset + 0] = float(bool(gq.get("gripper_too_open", False)))
        vec[offset + 1] = float(bool(gq.get("low_object_z", False)))
        ss = slip_signal or {}
        vec[offset + 2] = float(bool(ss.get("any_slip", False)))
        vec[offset + 3] = float(ss.get("slip_score", 0.0))
        cs = contact_signal or {}
        vec[offset + 4] = float(cs.get("confidence", 0.0))
        vec[offset + 5] = float(cs.get("state") in {"stable", "contact", "grasp"})
        return vec


def load_triggered_residual_policy(
    trigger_model_path: str | Path,
    residual_model_path: str | Path,
    trigger_threshold: float = 0.5,
) -> TriggeredResidualPolicy:
    """Load a triggered residual policy from two JSON model files."""
    trigger_model = TriggerModel.load(trigger_model_path)
    residual_model = BoundedResidualModel.load(residual_model_path)
    return TriggeredResidualPolicy(
        trigger_model=trigger_model,
        residual_model=residual_model,
        trigger_threshold=trigger_threshold,
    )


class TriggeredRuleResidualPolicy(ResidualPolicy):
    """Residual policy that gates a hard-coded rule action with a learned trigger.

    When the trigger model fires, the policy returns the same ``lower_reclose``
    micro-recovery action used by the hand-written grip-quality monitor:
    a small downward z correction and a stronger gripper close.  This lets the
    benchmark isolate the value of the learned trigger from the value of the
    bounded residual regressor.
    """

    def __init__(
        self,
        trigger_model: TriggerModel,
        active_phases: set[str] | None = None,
        trigger_threshold: float = 0.5,
        lower_delta_z: float = 0.015,
        dgripper: float = -0.05,
    ) -> None:
        self.trigger_model = trigger_model
        self.active_phases = active_phases if active_phases is not None else {
            "GRASP", "CONTACT_VERIFY", "PRE_LIFT", "LIFT", "LIFT_VERIFY", "HOLD"
        }
        self.trigger_threshold = trigger_threshold
        self.lower_delta_z = lower_delta_z
        self.dgripper = dgripper

    def predict(
        self,
        observation: dict,
        contact_signal: dict | None,
        slip_signal: dict | None,
        grip_quality_signal: dict | None,
        phase: str,
    ) -> ResidualAction:
        if phase not in self.active_phases:
            return ResidualAction(
                delta_pos=[0.0, 0.0, 0.0],
                delta_rot=[0.0, 0.0, 0.0],
                delta_gripper=0.0,
                lift_speed_scale=1.0,
                active_axes=[False] * 7,
                confidence=0.0,
                reason="phase_not_active",
            )

        features = self._observation_to_features(
            observation, contact_signal, slip_signal, grip_quality_signal, phase
        )
        X = np.array([features], dtype=np.float32)
        trigger_prob = float(self.trigger_model.predict_proba(X)[0, 1])

        if trigger_prob < self.trigger_threshold:
            return ResidualAction(
                delta_pos=[0.0, 0.0, 0.0],
                delta_rot=[0.0, 0.0, 0.0],
                delta_gripper=0.0,
                lift_speed_scale=1.0,
                active_axes=[False] * 7,
                confidence=trigger_prob,
                reason="trigger_below_threshold",
            )

        active_axes = [False] * 7
        active_axes[2] = True
        active_axes[6] = True
        return ResidualAction(
            delta_pos=[0.0, 0.0, self.lower_delta_z],
            delta_rot=[0.0, 0.0, 0.0],
            delta_gripper=self.dgripper,
            lift_speed_scale=1.0,
            active_axes=active_axes,
            confidence=trigger_prob,
            reason="triggered_rule_lower_reclose",
        )

    def _observation_to_features(
        self,
        observation: dict,
        contact_signal: dict | None,
        slip_signal: dict | None,
        grip_quality_signal: dict | None,
        phase: str,
    ) -> list[float]:
        """Build a feature vector consistent with ResidualDataset feature matrices."""
        phases = self.trigger_model.feature_names[: self.trigger_model.input_dim - 12]
        numeric_keys = [
            "object_z",
            "gripper_pos",
            "eef_z",
            "orientation_error",
            "object_eef_distance",
            "object_eef_yaw_delta",
        ]
        vec = [0.0] * self.trigger_model.input_dim
        if phase in phases:
            vec[phases.index(phase)] = 1.0
        offset = len(phases)
        for i, key in enumerate(numeric_keys):
            vec[offset + i] = float(observation.get(key, 0.0))
        offset += len(numeric_keys)
        gq = grip_quality_signal or {}
        vec[offset + 0] = float(bool(gq.get("gripper_too_open", False)))
        vec[offset + 1] = float(bool(gq.get("low_object_z", False)))
        ss = slip_signal or {}
        vec[offset + 2] = float(bool(ss.get("any_slip", False)))
        vec[offset + 3] = float(ss.get("slip_score", 0.0))
        cs = contact_signal or {}
        vec[offset + 4] = float(cs.get("confidence", 0.0))
        vec[offset + 5] = float(cs.get("state") in {"stable", "contact", "grasp"})
        return vec


def load_triggered_rule_policy(
    trigger_model_path: str | Path,
    trigger_threshold: float = 0.5,
    lower_delta_z: float = 0.015,
    dgripper: float = -0.05,
) -> TriggeredRuleResidualPolicy:
    """Load a trigger-gated rule residual policy from a trigger model JSON."""
    trigger_model = TriggerModel.load(trigger_model_path)
    return TriggeredRuleResidualPolicy(
        trigger_model=trigger_model,
        trigger_threshold=trigger_threshold,
        lower_delta_z=lower_delta_z,
        dgripper=dgripper,
    )


def evaluate_bounded_residual_offline(
    model: BoundedResidualModel,
    ds: Any,
    frames: list[Any] | None = None,
) -> dict[str, Any]:
    """Evaluate a bounded residual model with offline replay metrics."""

    frames = frames if frames is not None else ds.frames
    mat = ds.to_residual_target_matrix(frames=frames)
    X, Y_true = mat["X"], mat["Y"]
    Y_pred = model.predict_residual(X)

    mse = float(np.mean((Y_pred - Y_true) ** 2))
    mae = float(np.mean(np.abs(Y_pred - Y_true)))

    # Per-axis clamp rate.  For lift_speed_scale the no-op target is 1.0 (the
    # upper bound), so being within tolerance of 1.0 is not a meaningful clamp.
    # Only lower-bound clamps count as true clamping for that axis.
    clamp_count = 0
    total = 0
    for idx, axis in enumerate(["dz", "dgripper", "lift_speed_scale"]):
        lo, hi = model.limits[axis]
        eps = 1e-6
        if axis == "lift_speed_scale":
            clamped = Y_pred[:, idx] <= lo + eps
        else:
            clamped = (Y_pred[:, idx] <= lo + eps) | (Y_pred[:, idx] >= hi - eps)
        clamp_count += int(np.sum(clamped))
        total += len(Y_pred)
    clamp_rate = clamp_count / total if total > 0 else 0.0

    # Success-frame modification rate.  Only count residuals that are large
    # enough to actually change the action, not numerical noise.
    success_modified = 0
    success_total = 0
    for frame, pred in zip(frames, Y_pred):
        if frame.success_label:
            success_total += 1
            dz, dgripper, speed = pred
            if (
                abs(dz) > 0.0005
                or abs(dgripper) > 0.005
                or abs(speed - 1.0) > 0.01
            ):
                success_modified += 1
    success_mod_rate = success_modified / success_total if success_total > 0 else None

    # Residual norm distribution.
    norms = np.linalg.norm(Y_pred[:, :2], axis=1)

    return {
        "n_samples": int(len(frames)),
        "mse": mse,
        "mae": mae,
        "clamp_rate": clamp_rate,
        "success_frame_modification_rate": success_mod_rate,
        "mean_residual_norm": float(np.mean(norms)),
        "max_residual_norm": float(np.max(norms)),
        "dz_min": float(np.min(Y_pred[:, 0])),
        "dz_max": float(np.max(Y_pred[:, 0])),
        "dgripper_min": float(np.min(Y_pred[:, 1])),
        "dgripper_max": float(np.max(Y_pred[:, 1])),
        "lift_speed_scale_min": float(np.min(Y_pred[:, 2])),
        "lift_speed_scale_max": float(np.max(Y_pred[:, 2])),
    }


__all__ = [
    "DEFAULT_BOUNDED_LIMITS",
    "BoundedResidualModel",
    "BoundedMLPResidualModel",
    "BoundedResidualPolicy",
    "TriggeredResidualPolicy",
    "TriggeredRuleResidualPolicy",
    "create_bounded_residual_model",
    "evaluate_bounded_residual_offline",
    "load_triggered_residual_policy",
    "load_triggered_rule_policy",
]

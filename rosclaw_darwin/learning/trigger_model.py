"""Small learned trigger models for residual micro-recovery.

Trigger models predict whether a micro-recovery should be triggered for the
current frame.  All models are intentionally small (logistic, tiny MLP, or a
gradient-boosted classifier with a PyTorch fallback) and operate on the fixed
feature matrix produced by ``ResidualDataset.to_feature_matrix``.
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


class TriggerModel(ABC):
    """Base class for a learned trigger model."""

    def __init__(self, feature_names: list[str], random_seed: int = 42) -> None:
        self.feature_names = feature_names
        self.input_dim = len(feature_names)
        self.random_seed = random_seed

    @abstractmethod
    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        sample_weight: np.ndarray | None = None,
        val_data: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> dict[str, Any]:
        """Fit the model. Returns a dict of training history / metrics."""

    @abstractmethod
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Return shape (n_samples, 2) probability array [p_neg, p_pos]."""

    def predict(self, X: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        """Return binary predictions at the given threshold."""
        return (self.predict_proba(X)[:, 1] >= threshold).astype(int)

    def save(self, path: str | Path) -> None:
        """Serialize model config and weights to JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "class_name": self.__class__.__name__,
            "feature_names": self.feature_names,
            "input_dim": self.input_dim,
            "random_seed": self.random_seed,
            "state_dict": self._state_dict_to_serializable(),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @abstractmethod
    def _state_dict_to_serializable(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of model weights."""

    @classmethod
    def load(cls, path: str | Path) -> "TriggerModel":
        """Load a trigger model from a JSON payload."""
        path = Path(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        class_name = payload["class_name"]
        feature_names = payload["feature_names"]
        random_seed = payload.get("random_seed", 42)
        state_dict = payload["state_dict"]

        if class_name == "LogisticTriggerModel":
            model: TriggerModel = LogisticTriggerModel(feature_names, random_seed=random_seed)
        elif class_name == "SmallMLPTriggerModel":
            hidden_dim = state_dict.get("hidden_dim", 16)
            model = SmallMLPTriggerModel(feature_names, hidden_dim=hidden_dim, random_seed=random_seed)
        elif class_name == "GBTriggerModel":
            model = GBTriggerModel(feature_names, random_seed=random_seed)
        else:
            raise ValueError(f"Unknown trigger model class: {class_name}")

        model._load_state_dict_from_serializable(state_dict)
        return model

    @abstractmethod
    def _load_state_dict_from_serializable(self, state_dict: dict[str, Any]) -> None:
        """Restore weights from a JSON-serializable state dict."""


class _TorchBinaryClassifierMixin:
    """Shared training loop for small PyTorch binary classifiers."""

    def _fit_torch_module(
        self,
        module: nn.Module,
        X: np.ndarray,
        y: np.ndarray,
        sample_weight: np.ndarray | None = None,
        val_data: tuple[np.ndarray, np.ndarray] | None = None,
        epochs: int = 200,
        lr: float = 1e-2,
        batch_size: int = 64,
        patience: int = 20,
    ) -> dict[str, Any]:
        torch.manual_seed(self.random_seed)
        module.train()

        X_t = torch.tensor(X, dtype=torch.float32)
        y_t = torch.tensor(y, dtype=torch.float32).unsqueeze(1)
        if sample_weight is not None:
            w_t = torch.tensor(sample_weight, dtype=torch.float32).unsqueeze(1)
        else:
            w_t = torch.ones_like(y_t)

        optimizer = torch.optim.Adam(module.parameters(), lr=lr, weight_decay=1e-4)
        dataset = torch.utils.data.TensorDataset(X_t, y_t, w_t)
        loader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True)

        best_val_loss = float("inf")
        patience_counter = 0
        best_state: dict[str, Any] = {}
        history: dict[str, list[float]] = {"train_loss": [], "val_loss": []}

        for epoch in range(epochs):
            module.train()
            epoch_losses: list[float] = []
            for xb, yb, wb in loader:
                optimizer.zero_grad()
                logits = module(xb)
                loss = F.binary_cross_entropy_with_logits(logits, yb, weight=wb)
                loss.backward()
                optimizer.step()
                epoch_losses.append(loss.item())
            history["train_loss"].append(float(np.mean(epoch_losses)))

            if val_data is not None:
                module.eval()
                with torch.no_grad():
                    Xv, yv = val_data
                    xv_t = torch.tensor(Xv, dtype=torch.float32)
                    yv_t = torch.tensor(yv, dtype=torch.float32).unsqueeze(1)
                    val_logits = module(xv_t)
                    val_loss = F.binary_cross_entropy_with_logits(val_logits, yv_t).item()
                history["val_loss"].append(val_loss)
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    best_state = {k: v.cpu().clone() for k, v in module.state_dict().items()}
                    patience_counter = 0
                else:
                    patience_counter += 1
                    if patience_counter >= patience:
                        break
            else:
                history["val_loss"].append(float("nan"))

        if val_data is not None and best_state:
            module.load_state_dict(best_state)

        return {
            "epochs_trained": len(history["train_loss"]),
            "best_val_loss": best_val_loss if val_data is not None else None,
            "history": history,
        }

    def _predict_proba_torch(self, module: nn.Module, X: np.ndarray) -> np.ndarray:
        module.eval()
        with torch.no_grad():
            Xt = torch.tensor(X, dtype=torch.float32)
            logits = module(Xt)
            probs = torch.sigmoid(logits).cpu().numpy().reshape(-1)
        return np.stack([1 - probs, probs], axis=1)


class LogisticTriggerModel(TriggerModel, _TorchBinaryClassifierMixin):
    """Logistic regression trigger model (PyTorch, no hidden layers)."""

    def __init__(self, feature_names: list[str], random_seed: int = 42) -> None:
        super().__init__(feature_names, random_seed=random_seed)
        torch.manual_seed(random_seed)
        self._module = nn.Linear(self.input_dim, 1)

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        sample_weight: np.ndarray | None = None,
        val_data: tuple[np.ndarray, np.ndarray] | None = None,
        epochs: int = 200,
        lr: float = 1e-2,
        batch_size: int = 64,
        patience: int = 20,
    ) -> dict[str, Any]:
        history = self._fit_torch_module(
            self._module, X, y, sample_weight, val_data, epochs, lr, batch_size, patience
        )
        return {"model": "logistic", **history}

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return self._predict_proba_torch(self._module, X)

    def _state_dict_to_serializable(self) -> dict[str, Any]:
        return {k: v.detach().cpu().tolist() for k, v in self._module.state_dict().items()}

    def _load_state_dict_from_serializable(self, state_dict: dict[str, Any]) -> None:
        tensors = {k: torch.tensor(v, dtype=torch.float32) for k, v in state_dict.items()}
        self._module.load_state_dict(tensors)


class SmallMLPTriggerModel(TriggerModel, _TorchBinaryClassifierMixin):
    """Small MLP trigger model (one hidden layer)."""

    def __init__(
        self,
        feature_names: list[str],
        hidden_dim: int = 16,
        random_seed: int = 42,
    ) -> None:
        super().__init__(feature_names, random_seed=random_seed)
        self.hidden_dim = hidden_dim
        torch.manual_seed(random_seed)
        self._module = nn.Sequential(
            nn.Linear(self.input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim, 1),
        )

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        sample_weight: np.ndarray | None = None,
        val_data: tuple[np.ndarray, np.ndarray] | None = None,
        epochs: int = 200,
        lr: float = 1e-3,
        batch_size: int = 64,
        patience: int = 20,
    ) -> dict[str, Any]:
        history = self._fit_torch_module(
            self._module, X, y, sample_weight, val_data, epochs, lr, batch_size, patience
        )
        return {"model": "small_mlp", "hidden_dim": self.hidden_dim, **history}

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return self._predict_proba_torch(self._module, X)

    def _state_dict_to_serializable(self) -> dict[str, Any]:
        return {
            "hidden_dim": self.hidden_dim,
            **{k: v.detach().cpu().tolist() for k, v in self._module.state_dict().items()},
        }

    def _load_state_dict_from_serializable(self, state_dict: dict[str, Any]) -> None:
        hidden_dim = state_dict.pop("hidden_dim", self.hidden_dim)
        self.hidden_dim = hidden_dim
        # Recreate module in case hidden_dim changed.
        self._module = nn.Sequential(
            nn.Linear(self.input_dim, self.hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(self.hidden_dim, 1),
        )
        tensors = {k: torch.tensor(v, dtype=torch.float32) for k, v in state_dict.items()}
        self._module.load_state_dict(tensors)


class GBTriggerModel(TriggerModel):
    """Gradient-boosted trigger model.

    Uses ``sklearn.ensemble.GradientBoostingClassifier`` when available; falls
    back to a ``SmallMLPTriggerModel`` otherwise so that container images
    without sklearn can still load and train a model.
    """

    def __init__(
        self,
        feature_names: list[str],
        hidden_dim: int = 16,
        random_seed: int = 42,
    ) -> None:
        super().__init__(feature_names, random_seed=random_seed)
        self.hidden_dim = hidden_dim
        self._sklearn_model: Any = None
        self._fallback: SmallMLPTriggerModel | None = None
        try:
            from sklearn.ensemble import GradientBoostingClassifier

            self._sklearn_model = GradientBoostingClassifier(
                n_estimators=100,
                max_depth=3,
                random_state=random_seed,
            )
        except Exception:
            self._fallback = SmallMLPTriggerModel(feature_names, hidden_dim=hidden_dim, random_seed=random_seed)

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        sample_weight: np.ndarray | None = None,
        val_data: tuple[np.ndarray, np.ndarray] | None = None,
        epochs: int = 200,
        lr: float = 1e-3,
        batch_size: int = 64,
        patience: int = 20,
    ) -> dict[str, Any]:
        if self._sklearn_model is not None:
            self._sklearn_model.fit(X, y, sample_weight=sample_weight)
            return {"model": "gradient_boosting", "sklearn": True, "epochs_trained": 1}
        if self._fallback is None:
            self._fallback = SmallMLPTriggerModel(self.feature_names, hidden_dim=self.hidden_dim, random_seed=self.random_seed)
        history = self._fallback.fit(X, y, sample_weight=sample_weight, val_data=val_data, epochs=epochs, lr=lr, batch_size=batch_size, patience=patience)
        return {"model": "gradient_boosting_fallback_mlp", **history}

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self._sklearn_model is not None:
            return self._sklearn_model.predict_proba(X)
        if self._fallback is None:
            raise RuntimeError("GBTriggerModel has not been fitted.")
        return self._fallback.predict_proba(X)

    def _state_dict_to_serializable(self) -> dict[str, Any]:
        if self._sklearn_model is not None:
            import base64
            import pickle

            blob = base64.b64encode(pickle.dumps(self._sklearn_model)).decode("utf-8")
            return {"sklearn": True, "hidden_dim": self.hidden_dim, "pickle_blob": blob}
        if self._fallback is not None:
            return {"sklearn": False, "hidden_dim": self.hidden_dim, "fallback_state": self._fallback._state_dict_to_serializable()}
        raise RuntimeError("GBTriggerModel has not been fitted.")

    def _load_state_dict_from_serializable(self, state_dict: dict[str, Any]) -> None:
        self.hidden_dim = state_dict.get("hidden_dim", self.hidden_dim)
        if state_dict.get("sklearn"):
            import base64
            import pickle

            blob = base64.b64decode(state_dict["pickle_blob"])
            self._sklearn_model = pickle.loads(blob)
        else:
            self._sklearn_model = None
            self._fallback = SmallMLPTriggerModel(self.feature_names, hidden_dim=self.hidden_dim, random_seed=self.random_seed)
            self._fallback._load_state_dict_from_serializable(state_dict["fallback_state"])


def create_trigger_model(
    model_type: str,
    feature_names: list[str],
    hidden_dim: int = 16,
    random_seed: int = 42,
) -> TriggerModel:
    """Factory for trigger models."""
    if model_type == "logistic":
        return LogisticTriggerModel(feature_names, random_seed=random_seed)
    if model_type == "mlp":
        return SmallMLPTriggerModel(feature_names, hidden_dim=hidden_dim, random_seed=random_seed)
    if model_type == "gb":
        return GBTriggerModel(feature_names, hidden_dim=hidden_dim, random_seed=random_seed)
    raise ValueError(f"Unknown model_type: {model_type}. Choose from logistic, mlp, gb.")


def evaluate_trigger_model(
    model: TriggerModel,
    X: np.ndarray,
    y: np.ndarray,
    frames: list[Any] | None = None,
) -> dict[str, Any]:
    """Evaluate a trigger model and return a rich metrics dict."""
    probs = model.predict_proba(X)
    preds = (probs[:, 1] >= 0.5).astype(int)

    tp = int(np.sum((preds == 1) & (y == 1)))
    fp = int(np.sum((preds == 1) & (y == 0)))
    tn = int(np.sum((preds == 0) & (y == 0)))
    fn = int(np.sum((preds == 0) & (y == 1)))

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    accuracy = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) > 0 else 0.0

    pos_probs = probs[:, 1]
    auroc = _compute_auroc(y, pos_probs)
    auprc = _compute_auprc(y, pos_probs)
    calibration_error = _compute_expected_calibration_error(y, pos_probs)

    metrics: dict[str, Any] = {
        "n_samples": int(len(y)),
        "positive_count": int(np.sum(y)),
        "negative_count": int(np.sum(1 - y)),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "fpr": fpr,
        "auroc": auroc,
        "auprc": auprc,
        "calibration_error": calibration_error,
    }

    # Success-frame false-positive rate (requires frame success labels).
    if frames is not None:
        success_frame_fpr: float | None = None
        success_fps = 0
        success_total = 0
        seed24_recall: float | None = None
        seed24_tp = 0
        seed24_total = 0
        for pred, frame in zip(preds, frames):
            if frame.success_label:
                success_total += 1
                if pred == 1:
                    success_fps += 1
            # Use the internal helper to avoid re-implementing the heuristic.
            from rosclaw_darwin.learning.residual_dataset import _is_seed24_like

            if _is_seed24_like(frame):
                seed24_total += 1
                if pred == 1:
                    seed24_tp += 1
        if success_total > 0:
            success_frame_fpr = success_fps / success_total
        if seed24_total > 0:
            seed24_recall = seed24_tp / seed24_total
        metrics["success_frame_fpr"] = success_frame_fpr
        metrics["seed24_like_recall"] = seed24_recall

        trigger_rate_by_phase: dict[str, dict[str, float]] = {}
        phase_counts: dict[str, int] = {}
        phase_triggers: dict[str, int] = {}
        for pred, frame in zip(preds, frames):
            phase = frame.phase
            phase_counts[phase] = phase_counts.get(phase, 0) + 1
            if pred == 1:
                phase_triggers[phase] = phase_triggers.get(phase, 0) + 1
        for phase, count in phase_counts.items():
            trigger_rate_by_phase[phase] = {
                "count": count,
                "triggered": phase_triggers.get(phase, 0),
                "rate": phase_triggers.get(phase, 0) / count,
            }
        metrics["trigger_rate_by_phase"] = trigger_rate_by_phase

    return metrics


def _compute_auroc(y_true: np.ndarray, scores: np.ndarray) -> float:
    """Compute AUROC using the trapezoid rule on sorted scores."""
    order = np.argsort(scores)[::-1]
    y_sorted = y_true[order]
    n_pos = int(np.sum(y_true))
    n_neg = int(len(y_true) - n_pos)
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    tpr = np.cumsum(y_sorted) / n_pos
    fpr = np.cumsum(1 - y_sorted) / n_neg
    _trapz = getattr(np, "trapezoid", getattr(np, "trapz", None))
    if _trapz is None:
        return float("nan")
    return float(_trapz(tpr, fpr))


def _compute_auprc(y_true: np.ndarray, scores: np.ndarray) -> float:
    """Compute area under the precision-recall curve."""
    order = np.argsort(scores)[::-1]
    y_sorted = y_true[order]
    n_pos = int(np.sum(y_true))
    if n_pos == 0:
        return float("nan")
    cum_tp = np.cumsum(y_sorted)
    cum_fp = np.cumsum(1 - y_sorted)
    precision = cum_tp / (cum_tp + cum_fp)
    recall = cum_tp / n_pos
    _trapz = getattr(np, "trapezoid", getattr(np, "trapz", None))
    if _trapz is None:
        return float("nan")
    return float(_trapz(precision, recall))


def _compute_expected_calibration_error(
    y_true: np.ndarray,
    probs: np.ndarray,
    n_bins: int = 10,
) -> float:
    """Compute expected calibration error with uniform bins."""
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for low, high in zip(bin_edges[:-1], bin_edges[1:]):
        if low == 0.0:
            mask = (probs >= low) & (probs <= high)
        else:
            mask = (probs > low) & (probs <= high)
        if not np.any(mask):
            continue
        bin_acc = np.mean(y_true[mask])
        bin_conf = np.mean(probs[mask])
        ece += np.sum(mask) * abs(bin_acc - bin_conf)
    return float(ece / len(y_true)) if len(y_true) > 0 else 0.0

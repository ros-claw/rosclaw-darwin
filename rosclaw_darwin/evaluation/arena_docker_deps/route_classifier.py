"""Small learned route classifier for large-yaw slip feasibility (Sprint 8 v1.10).

Route classifiers do **not** output a continuous action residual.  They predict
one of five discrete recovery routes:

- ``continue`` -- no intervention needed.
- ``pause`` -- pause lateral / yaw motion and wait for object to settle.
- ``lower_regrip`` -- lower, re-open, and re-close the gripper.
- ``abort_safe`` -- stop and report failure without making things worse.
- ``blocked_external`` -- the failure mechanism is outside the policy's control.

All models are intentionally small and operate on the same feature matrix used
by the trigger model.
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

ROUTE_CLASSES = ["continue", "pause", "lower_regrip", "abort_safe", "blocked_external"]
ROUTE_CLASS_TO_INDEX = {label: i for i, label in enumerate(ROUTE_CLASSES)}


class RouteClassifier(ABC):
    """Base class for a discrete route classifier."""

    def __init__(self, feature_names: list[str], random_seed: int = 42) -> None:
        self.feature_names = feature_names
        self.input_dim = len(feature_names)
        self.num_classes = len(ROUTE_CLASSES)
        self.random_seed = random_seed

    @abstractmethod
    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        sample_weight: np.ndarray | None = None,
        val_data: tuple[np.ndarray, np.ndarray] | None = None,
    ) -> dict[str, Any]:
        """Fit the classifier. Returns training history / metrics."""

    @abstractmethod
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Return shape (n_samples, num_classes) probability array."""

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return integer class indices."""
        return np.argmax(self.predict_proba(X), axis=1)

    def predict_route(self, X: np.ndarray) -> list[str]:
        """Return string route labels."""
        indices = self.predict(X)
        return [ROUTE_CLASSES[i] for i in indices]

    def save(self, path: str | Path) -> None:
        """Serialize model config and weights to JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "class_name": self.__class__.__name__,
            "feature_names": self.feature_names,
            "input_dim": self.input_dim,
            "num_classes": self.num_classes,
            "route_classes": ROUTE_CLASSES,
            "random_seed": self.random_seed,
            "state_dict": self._state_dict_to_serializable(),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @abstractmethod
    def _state_dict_to_serializable(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of model weights."""

    @classmethod
    def load(cls, path: str | Path) -> "RouteClassifier":
        """Load a route classifier from a JSON payload."""
        path = Path(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        class_name = payload["class_name"]
        feature_names = payload["feature_names"]
        random_seed = payload.get("random_seed", 42)
        state_dict = payload["state_dict"]

        if class_name == "SmallMLPRouteClassifier":
            hidden_dim = state_dict.get("hidden_dim", 16)
            model: RouteClassifier = SmallMLPRouteClassifier(
                feature_names, hidden_dim=hidden_dim, random_seed=random_seed
            )
        else:
            raise ValueError(f"Unknown route classifier class: {class_name}")

        model._load_state_dict_from_serializable(state_dict)
        return model

    @abstractmethod
    def _load_state_dict_from_serializable(self, state_dict: dict[str, Any]) -> None:
        """Restore weights from a JSON-serializable state dict."""


class SmallMLPRouteClassifier(RouteClassifier):
    """Small MLP route classifier (one hidden layer, num_classes outputs)."""

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
            nn.Linear(hidden_dim, self.num_classes),
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
        torch.manual_seed(self.random_seed)
        self._module.train()

        X_t = torch.tensor(X, dtype=torch.float32)
        y_t = torch.tensor(y, dtype=torch.long)
        if sample_weight is not None:
            w_t = torch.tensor(sample_weight, dtype=torch.float32)
        else:
            w_t = torch.ones(len(y_t), dtype=torch.float32)

        optimizer = torch.optim.Adam(self._module.parameters(), lr=lr, weight_decay=1e-4)
        dataset = torch.utils.data.TensorDataset(X_t, y_t, w_t)
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
                logits = self._module(xb)
                loss_per_example = F.cross_entropy(logits, yb, reduction="none")
                loss = (loss_per_example * wb).mean()
                loss.backward()
                optimizer.step()
                epoch_losses.append(loss.item())
            history["train_loss"].append(float(np.mean(epoch_losses)))

            if val_data is not None:
                self._module.eval()
                with torch.no_grad():
                    Xv, yv = val_data
                    xv_t = torch.tensor(Xv, dtype=torch.float32)
                    yv_t = torch.tensor(yv, dtype=torch.long)
                    val_logits = self._module(xv_t)
                    val_loss = F.cross_entropy(val_logits, yv_t).item()
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
            "model": "small_mlp",
            "hidden_dim": self.hidden_dim,
            "epochs_trained": len(history["train_loss"]),
            "best_val_loss": best_val_loss if val_data is not None else None,
            "history": history,
        }

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        self._module.eval()
        with torch.no_grad():
            Xt = torch.tensor(X, dtype=torch.float32)
            logits = self._module(Xt)
            probs = F.softmax(logits, dim=1).cpu().numpy()
        return probs

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
            nn.Linear(self.hidden_dim, self.num_classes),
        )
        tensors = {k: torch.tensor(v, dtype=torch.float32) for k, v in state_dict.items()}
        self._module.load_state_dict(tensors)


def create_route_classifier(
    model_type: str,
    feature_names: list[str],
    hidden_dim: int = 16,
    random_seed: int = 42,
) -> RouteClassifier:
    """Factory for route classifiers."""
    if model_type == "mlp":
        return SmallMLPRouteClassifier(feature_names, hidden_dim=hidden_dim, random_seed=random_seed)
    raise ValueError(f"Unknown route classifier model_type: {model_type}. Choose from mlp.")


def evaluate_route_classifier(
    model: RouteClassifier,
    X: np.ndarray,
    y: np.ndarray,
    frames: list[Any] | None = None,
) -> dict[str, Any]:
    """Evaluate a route classifier and return a rich metrics dict."""
    probs = model.predict_proba(X)
    preds = np.argmax(probs, axis=1)

    n = len(y)
    accuracy = float(np.mean(preds == y)) if n > 0 else 0.0

    per_class_recall: dict[str, float] = {}
    confusion = np.zeros((model.num_classes, model.num_classes), dtype=int)
    for true_label in range(model.num_classes):
        mask = y == true_label
        total = int(np.sum(mask))
        correct = int(np.sum((preds == true_label) & mask))
        per_class_recall[ROUTE_CLASSES[true_label]] = correct / total if total > 0 else 0.0
        for pred_label in range(model.num_classes):
            confusion[true_label, pred_label] = int(np.sum((y == true_label) & (preds == pred_label)))

    route_distribution: dict[str, float] = {}
    for idx, label in enumerate(ROUTE_CLASSES):
        count = int(np.sum(preds == idx))
        route_distribution[label] = count / n if n > 0 else 0.0

    metrics: dict[str, Any] = {
        "n_samples": n,
        "accuracy": accuracy,
        "per_class_recall": per_class_recall,
        "route_distribution": route_distribution,
        "confusion_matrix": confusion.tolist(),
        "route_classes": ROUTE_CLASSES,
    }

    if frames is not None:
        success_dominant_route: dict[str, int] = {}
        failure_dominant_route: dict[str, int] = {}
        for frame, pred in zip(frames, preds):
            bucket = success_dominant_route if frame.success_label else failure_dominant_route
            bucket[ROUTE_CLASSES[pred]] = bucket.get(ROUTE_CLASSES[pred], 0) + 1
        metrics["success_route_counts"] = success_dominant_route
        metrics["failure_route_counts"] = failure_dominant_route

    return metrics

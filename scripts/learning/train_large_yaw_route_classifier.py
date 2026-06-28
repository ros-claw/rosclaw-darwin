#!/usr/bin/env python3
"""Train a small route classifier for large-yaw slip feasibility (Sprint 8 v1.10).

Example:
    python scripts/learning/train_large_yaw_route_classifier.py \\
        --input-dir data_v20/datasets/residual_learning_v2 \\
        --output-dir data_v20/models/large_yaw_route_classifier \\
        --model-type mlp
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import numpy as np
import typer
from rich.console import Console

from rosclaw_darwin.learning.residual_dataset import ResidualDataset
from rosclaw_darwin.learning.route_classifier import create_route_classifier, evaluate_route_classifier

app = typer.Typer(help="Train a small large-yaw route classifier.")
console = Console()


def _synthetic_route_dataset(tmpdir: Path, n_per_class: int = 40, seed: int = 0) -> str:
    """Generate a minimal synthetic ResidualDataset for --synthetic smoke runs."""
    import random as py_random

    from rosclaw_darwin.learning.residual_dataset import ResidualFrame
    from rosclaw_darwin.learning.route_classifier import ROUTE_CLASSES

    py_random.seed(seed)
    rng = np.random.default_rng(seed)
    frames: list[ResidualFrame] = []
    episode = 0

    for route_idx, route in enumerate(ROUTE_CLASSES):
        for _ in range(n_per_class):
            episode += 1
            for step in range(5):
                obs = {
                    "object_z": 0.01 + rng.random() * 0.04,
                    "gripper_pos": 0.02 + rng.random() * 0.04,
                    "eef_z": 0.1 + rng.random() * 0.05,
                    "orientation_error": rng.random() * 0.5,
                    "object_eef_distance": rng.random() * 0.05,
                    "object_eef_yaw_delta": rng.random() * 1.5,
                }
                if route == "blocked_external":
                    obs["object_eef_yaw_delta"] = 1.8 + rng.random() * 0.5
                    obs["object_eef_distance"] = 0.04 + rng.random() * 0.03
                elif route == "lower_regrip":
                    obs["object_z"] = 0.01 + rng.random() * 0.01
                    obs["gripper_pos"] = 0.04 + rng.random() * 0.01
                elif route == "continue":
                    obs["object_z"] = 0.04 + rng.random() * 0.02
                    obs["gripper_pos"] = 0.02 + rng.random() * 0.01

                frames.append(
                    ResidualFrame(
                        episode=episode,
                        step=step,
                        task="goal_pose",
                        phase="LIFT" if step < 2 else "ALIGN",
                        success_label=route == "continue",
                        observation=obs,
                        route_label=route,
                        residual_target=[0.0] * 7,
                        residual_mask=[True] * 7,
                    )
                )

    ds = ResidualDataset(frames)
    ds._split_by_episode(0.7, 0.15, 0.15, seed)
    ds.save(tmpdir)
    return str(tmpdir)


@app.command()
def train(
    input_dir: Annotated[str, typer.Option("--input-dir", help="Directory containing a saved ResidualDataset v2.")] = "data_v20/datasets/residual_learning_v2",
    output_dir: Annotated[str, typer.Option("--output-dir", help="Directory to write model and metrics.")] = "data_v20/models/large_yaw_route_classifier",
    model_type: Annotated[str, typer.Option("--model-type", help="Model type: mlp.")] = "mlp",
    hidden_dim: Annotated[int, typer.Option("--hidden-dim", help="Hidden dimension for MLP.")] = 16,
    epochs: Annotated[int, typer.Option("--epochs", help="Max training epochs.")] = 200,
    lr: Annotated[float, typer.Option("--lr", help="Learning rate.")] = 1e-3,
    batch_size: Annotated[int, typer.Option("--batch-size", help="Training batch size.")] = 64,
    patience: Annotated[int, typer.Option("--patience", help="Early-stopping patience.")] = 20,
    random_seed: Annotated[int, typer.Option("--random-seed", help="Random seed.")] = 42,
    synthetic: Annotated[bool, typer.Option("--synthetic", help="Generate a synthetic dataset for a smoke run.")] = False,
) -> None:
    """Train a route classifier on a saved residual dataset."""
    import tempfile

    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    if synthetic:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = _synthetic_route_dataset(Path(tmpdir), n_per_class=40, seed=random_seed)
            _run_training(input_dir, out_path, model_type, hidden_dim, epochs, lr, batch_size, patience, random_seed)
    else:
        _run_training(input_dir, out_path, model_type, hidden_dim, epochs, lr, batch_size, patience, random_seed)


def _run_training(
    input_dir: str,
    out_path: Path,
    model_type: str,
    hidden_dim: int,
    epochs: int,
    lr: float,
    batch_size: int,
    patience: int,
    random_seed: int,
) -> None:
    console.print(f"Loading dataset from {input_dir}")
    ds = ResidualDataset.from_saved(input_dir)

    train_frames = ds.train if ds._train is not None else ds.frames
    val_frames = ds.val
    test_frames = ds.test

    console.print(f"Frames: {len(ds.frames)}  train: {len(train_frames)}  val: {len(val_frames)}  test: {len(test_frames)}")

    train_mat = ds.to_route_label_matrix(frames=train_frames)
    phases = train_mat["phases"]

    if not train_mat["X"].size:
        console.print("[red]No frames with route_label found. Aborting.[/red]")
        raise typer.Exit(1)

    val_mat = ds.to_route_label_matrix(frames=val_frames, phase_list=phases) if val_frames else None
    test_mat = ds.to_route_label_matrix(frames=test_frames, phase_list=phases) if test_frames else None

    model = create_route_classifier(
        model_type,
        train_mat["feature_names"],
        hidden_dim=hidden_dim,
        random_seed=random_seed,
    )
    console.print(f"Training {model_type} route classifier (input_dim={model.input_dim}, classes={model.num_classes})")

    val_data = (val_mat["X"], val_mat["y"]) if val_mat is not None else None
    train_info = model.fit(
        train_mat["X"],
        train_mat["y"],
        sample_weight=train_mat["sample_weight"],
        val_data=val_data,
        epochs=epochs,
        lr=lr,
        batch_size=batch_size,
        patience=patience,
    )

    metrics: dict[str, object] = {
        "model_type": model_type,
        "feature_names": train_mat["feature_names"],
        "phases": phases,
        "route_classes": train_mat["route_classes"],
        "train_info": train_info,
    }

    for split, mat in (("train", train_mat), ("val", val_mat), ("test", test_mat)):
        if mat is None:
            continue
        split_metrics = evaluate_route_classifier(model, mat["X"], mat["y"], frames=mat["frames"])
        metrics[split] = split_metrics
        acc = split_metrics["accuracy"]
        console.print(f"{split}: accuracy={acc:.3f}  n={split_metrics['n_samples']}")
        console.print(f"  per_class_recall={split_metrics['per_class_recall']}")

    model.save(out_path / "model.json")
    (out_path / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")

    console.print(f"Saved model to {out_path / 'model.json'}")
    console.print(f"Saved metrics to {out_path / 'metrics.json'}")


if __name__ == "__main__":
    app()

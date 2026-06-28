#!/usr/bin/env python3
"""Train a bounded residual micro-policy for grip-quality failures.

Example:
    python scripts/learning/train_bounded_residual_policy.py \\
        --input-dir data_v20/datasets/residual_learning_v2 \\
        --output-dir data_v20/models/bounded_residual_policy \\
        --model-type mlp
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from rosclaw_darwin.learning.bounded_residual_policy import (
    create_bounded_residual_model,
    evaluate_bounded_residual_offline,
)
from rosclaw_darwin.learning.residual_dataset import ResidualDataset

app = typer.Typer(help="Train a bounded residual micro-policy.")
console = Console()


@app.command()
def train(
    input_dir: Annotated[str, typer.Option("--input-dir", help="Directory containing a saved ResidualDataset v2.")] = "data_v20/datasets/residual_learning_v2",
    output_dir: Annotated[str, typer.Option("--output-dir", help="Directory to write model and metrics.")] = "data_v20/models/bounded_residual_policy",
    model_type: Annotated[str, typer.Option("--model-type", help="Model type: mlp.")] = "mlp",
    hidden_dim: Annotated[int, typer.Option("--hidden-dim", help="Hidden dimension for MLP.")] = 16,
    epochs: Annotated[int, typer.Option("--epochs", help="Max training epochs.")] = 200,
    lr: Annotated[float, typer.Option("--lr", help="Learning rate.")] = 1e-3,
    batch_size: Annotated[int, typer.Option("--batch-size", help="Training batch size.")] = 64,
    patience: Annotated[int, typer.Option("--patience", help="Early-stopping patience.")] = 20,
    random_seed: Annotated[int, typer.Option("--random-seed", help="Random seed.")] = 42,
    dz_limit: Annotated[float, typer.Option("--dz-limit", help="Absolute dz residual limit.")] = 0.004,
    dgripper_limit: Annotated[float, typer.Option("--dgripper-limit", help="Absolute gripper residual limit.")] = 0.05,
    speed_min: Annotated[float, typer.Option("--speed-min", help="Minimum lift speed scale.")] = 0.5,
    speed_max: Annotated[float, typer.Option("--speed-max", help="Maximum lift speed scale.")] = 1.0,
) -> None:
    """Train a bounded residual micro-policy on a saved residual dataset."""
    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    limits = {
        "dz": (-dz_limit, dz_limit),
        "dgripper": (-dgripper_limit, dgripper_limit),
        "lift_speed_scale": (speed_min, speed_max),
    }

    console.print(f"Loading dataset from {input_dir}")
    ds = ResidualDataset.from_saved(input_dir)

    train_frames = ds.train if ds._train is not None else ds.frames
    val_frames = ds.val
    test_frames = ds.test

    console.print(f"Frames: {len(ds.frames)}  train: {len(train_frames)}  val: {len(val_frames)}  test: {len(test_frames)}")

    train_mat = ds.to_residual_target_matrix(frames=train_frames)
    phases = train_mat["phases"]

    val_mat = ds.to_residual_target_matrix(frames=val_frames, phase_list=phases) if val_frames else None
    test_mat = ds.to_residual_target_matrix(frames=test_frames, phase_list=phases) if test_frames else None

    model = create_bounded_residual_model(
        model_type, train_mat["feature_names"], limits=limits, hidden_dim=hidden_dim, random_seed=random_seed
    )
    console.print(f"Training {model_type} bounded residual model (input_dim={model.input_dim})")

    val_data = (val_mat["X"], val_mat["Y"]) if val_mat is not None else None
    train_info = model.fit(
        train_mat["X"],
        train_mat["Y"],
        sample_weight=train_mat["sample_weight"],
        val_data=val_data,
        epochs=epochs,
        lr=lr,
        batch_size=batch_size,
        patience=patience,
    )

    metrics: dict[str, dict[str, object]] = {
        "model_type": model_type,
        "limits": {k: list(v) for k, v in limits.items()},
        "feature_names": train_mat["feature_names"],
        "phases": phases,
        "axes": train_mat["axes"],
        "train_info": train_info,
    }

    for split, mat in (("train", train_mat), ("val", val_mat), ("test", test_mat)):
        if mat is None:
            continue
        split_metrics = evaluate_bounded_residual_offline(model, ds, frames=mat["frames"])
        metrics[split] = split_metrics
        console.print(
            f"{split}: mse={split_metrics['mse']:.6f}  "
            f"success_mod_rate={split_metrics['success_frame_modification_rate']}  "
            f"clamp_rate={split_metrics['clamp_rate']:.3f}"
        )

    model.save(out_path / "model.json")
    (out_path / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")

    console.print(f"Saved model to {out_path / 'model.json'}")
    console.print(f"Saved metrics to {out_path / 'metrics.json'}")


if __name__ == "__main__":
    app()

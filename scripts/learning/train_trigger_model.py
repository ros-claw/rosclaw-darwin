#!/usr/bin/env python3
"""Train a small learned trigger model for residual micro-recovery.

Example:
    python scripts/learning/train_trigger_model.py \\
        --input-dir data_v20/datasets/residual_learning_v2 \\
        --output-dir data_v20/models/trigger_model \\
        --model-type mlp \\
        --label-mode seed24_like
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from rosclaw_darwin.learning.residual_dataset import ResidualDataset
from rosclaw_darwin.learning.trigger_model import create_trigger_model, evaluate_trigger_model

app = typer.Typer(help="Train a small learned trigger model.")
console = Console()


@app.command()
def train(
    input_dir: Annotated[str, typer.Option("--input-dir", help="Directory containing a saved ResidualDataset v2.")] = "data_v20/datasets/residual_learning_v2",
    output_dir: Annotated[str, typer.Option("--output-dir", help="Directory to write model and metrics.")] = "data_v20/models/trigger_model",
    model_type: Annotated[str, typer.Option("--model-type", help="Model type: logistic, mlp, gb.")] = "mlp",
    label_mode: Annotated[str, typer.Option("--label-mode", help="Label mode: seed24_like, grip_failure, pair_rescued, pair_failure.")] = "seed24_like",
    hidden_dim: Annotated[int, typer.Option("--hidden-dim", help="Hidden dimension for MLP / GB fallback.")] = 16,
    epochs: Annotated[int, typer.Option("--epochs", help="Max training epochs.")] = 200,
    lr: Annotated[float, typer.Option("--lr", help="Learning rate.")] = 1e-3,
    batch_size: Annotated[int, typer.Option("--batch-size", help="Training batch size.")] = 64,
    patience: Annotated[int, typer.Option("--patience", help="Early-stopping patience.")] = 20,
    random_seed: Annotated[int, typer.Option("--random-seed", help="Random seed.")] = 42,
) -> None:
    """Train a trigger model on a saved residual dataset."""
    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    console.print(f"Loading dataset from {input_dir}")
    ds = ResidualDataset.from_saved(input_dir)

    train_frames = ds.train if ds._train is not None else ds.frames
    val_frames = ds.val
    test_frames = ds.test

    console.print(f"Frames: {len(ds.frames)}  train: {len(train_frames)}  val: {len(val_frames)}  test: {len(test_frames)}")

    train_mat = ds.to_feature_matrix(label_mode=label_mode, frames=train_frames)
    phases = train_mat["phases"]

    val_mat = ds.to_feature_matrix(label_mode=label_mode, frames=val_frames, phase_list=phases) if val_frames else None
    test_mat = ds.to_feature_matrix(label_mode=label_mode, frames=test_frames, phase_list=phases) if test_frames else None

    model = create_trigger_model(model_type, train_mat["feature_names"], hidden_dim=hidden_dim, random_seed=random_seed)
    console.print(f"Training {model_type} model (input_dim={model.input_dim})")

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

    metrics: dict[str, dict[str, object]] = {
        "model_type": model_type,
        "label_mode": label_mode,
        "feature_names": train_mat["feature_names"],
        "phases": phases,
        "train_info": train_info,
    }

    for split, mat in (("train", train_mat), ("val", val_mat), ("test", test_mat)):
        if mat is None:
            continue
        split_metrics = evaluate_trigger_model(model, mat["X"], mat["y"], frames=mat["frames"])
        metrics[split] = split_metrics
        console.print(f"{split}: accuracy={split_metrics['accuracy']:.3f}  recall={split_metrics['recall']:.3f}  fpr={split_metrics['fpr']:.3f}  auroc={split_metrics['auroc']:.3f}")

    model.save(out_path / "model.json")
    (out_path / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")

    console.print(f"Saved model to {out_path / 'model.json'}")
    console.print(f"Saved metrics to {out_path / 'metrics.json'}")


if __name__ == "__main__":
    app()

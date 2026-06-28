#!/usr/bin/env python3
"""Offline replay of residual policies on a residual dataset.

Loads a residual dataset (frames.parquet or frames.jsonl), replays each frame
through a selected residual policy, and records safety metrics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from rosclaw_darwin.learning.residual_dataset import ResidualFrame
from rosclaw_darwin.learning.residual_policy import (
    DEFAULT_RESIDUAL_LIMITS,
    ResidualNonePolicy,
    ResidualPolicyWrapper,
    ResidualSeed24GuardPolicy,
    ResidualSlipGuardPolicy,
)

app = typer.Typer(help="Offline replay residual policies on a residual dataset.")
console = Console()

POLICY_REGISTRY = {
    "none": ResidualNonePolicy,
    "seed24_guard": ResidualSeed24GuardPolicy,
    "slip_guard": ResidualSlipGuardPolicy,
}


def _load_frames(dataset_dir: Path) -> list[ResidualFrame]:
    """Load frames from parquet (preferred) or JSONL fallback."""
    parquet_path = dataset_dir / "frames.parquet"
    jsonl_path = dataset_dir / "frames.jsonl"

    if parquet_path.exists():
        try:
            import pandas as pd

            df = pd.read_parquet(parquet_path)
            records = df.to_dict(orient="records")
            frames: list[ResidualFrame] = []
            for rec in records:
                # Flatten nested keys back to dicts if needed.
                _flatten_nested_dicts(rec)
                frames.append(ResidualFrame(**rec))
            return frames
        except ImportError:
            console.print("[yellow]pandas/pyarrow not available, falling back to JSONL...[/yellow]")
        except FileNotFoundError:
            pass  # Parquet disappeared between exists() and read; fall through to JSONL.
        except Exception as exc:
            console.print(f"[yellow]Parquet load failed ({exc}), trying JSONL...[/yellow]")

    if jsonl_path.exists():
        frames = []
        with jsonl_path.open() as fh:
            for line in fh:
                if not line.strip():
                    continue
                rec = json.loads(line)
                frames.append(ResidualFrame(**rec))
        return frames

    raise FileNotFoundError(f"No frames.parquet or frames.jsonl found in {dataset_dir}")


def _flatten_nested_dicts(rec: dict) -> None:
    """Best-effort flatten of pandas json_normalize nested keys back to plain dicts."""
    # Pydantic v2 will generally accept nested dicts as long as field names match,
    # but json_normalize may produce keys like "observation_eef_x".  We do not
    # attempt full un-normalisation here; instead we rely on JSONL fallback for
    # complex nested structures.  For the offline replay the top-level scalar
    # fields (episode, step, phase, success_label, etc.) are sufficient.
    pass


def _replay(
    frames: list[ResidualFrame],
    policy_cls: type,
    limits: dict[str, float],
) -> dict:
    """Replay all frames and compute metrics."""
    policy = policy_cls()
    wrapper = ResidualPolicyWrapper(residual_policy=policy)
    wrapper.residual_limits = limits

    total = len(frames)
    triggered = 0
    success_triggered = 0
    failure_triggered = 0
    clamped = 0
    residual_norms: list[float] = []
    modified_success = 0
    modified_failure = 0

    for frame in frames:
        heuristic = frame.heuristic_action if frame.heuristic_action else [0.0] * 7
        # Ensure 7-DOF heuristic.
        if len(heuristic) < 7:
            heuristic = heuristic + [0.0] * (7 - len(heuristic))

        obs = frame.observation
        contact = frame.contact_signal
        slip = frame.slip_signal
        grip = frame.grip_quality_signal

        residual_action = policy.predict(obs, contact, slip, grip, frame.phase)
        norm = wrapper.residual_action_norm(residual_action)
        residual_norms.append(norm)

        any_active = any(residual_action.active_axes)
        if any_active:
            triggered += 1

        if any_active and frame.success_label:
            success_triggered += 1
        if any_active and not frame.success_label:
            failure_triggered += 1

        # Check clamping: would the raw residual exceed limits?
        raw_vector = residual_action.delta_pos + residual_action.delta_rot + [residual_action.delta_gripper]
        for i, (val, active) in enumerate(zip(raw_vector, residual_action.active_axes)):
            if not active:
                continue
            if i < 3:
                limit = limits["positional"]
            elif i < 6:
                limit = limits["rotational"]
            else:
                limit = limits["gripper"]
            if abs(val) > limit:
                clamped += 1
                break

        # Compute final action, reusing the already-predicted residual action.
        final = wrapper.compute_final_action(
            heuristic,
            obs,
            residual_action=residual_action,
        )
        differs = any(abs(f - h) > 1e-9 for f, h in zip(final, heuristic))
        if differs and frame.success_label:
            modified_success += 1
        if differs and not frame.success_label:
            modified_failure += 1

    success_frames = sum(1 for f in frames if f.success_label)
    failure_frames = total - success_frames

    def _safe_rate(num: int, den: int) -> float:
        return num / den if den > 0 else 0.0

    summary = {
        "policy": policy_cls.__name__,
        "num_frames": total,
        "residual_trigger_rate": _safe_rate(triggered, total),
        "success_frame_trigger_rate": _safe_rate(success_triggered, success_frames),
        "failure_frame_trigger_rate": _safe_rate(failure_triggered, failure_frames),
        "residual_action_norm_mean": sum(residual_norms) / len(residual_norms) if residual_norms else 0.0,
        "residual_action_norm_max": max(residual_norms) if residual_norms else 0.0,
        "safety_clamp_rate": _safe_rate(clamped, total),
        "would_modify_success_frames_rate": _safe_rate(modified_success, success_frames),
        "would_modify_failure_frames_rate": _safe_rate(modified_failure, failure_frames),
        "limits": limits,
    }
    return summary


@app.command()
def replay(
    dataset_dir: Annotated[str, typer.Option("--dataset-dir", help="Directory containing frames.parquet or frames.jsonl.")] = "data_v19/datasets/residual_learning",
    policy: Annotated[str, typer.Option("--policy", help="Residual policy to replay.")] = "none",
    output_dir: Annotated[str, typer.Option("--output-dir", help="Directory to write replay_summary.json.")] = "data_v19/reports/residual_replay",
) -> None:
    """Run offline replay and write summary."""
    dataset_path = Path(dataset_dir)
    if not dataset_path.exists():
        console.print(f"[red]Dataset directory not found: {dataset_dir}[/red]")
        raise typer.Exit(1)

    if policy not in POLICY_REGISTRY:
        console.print(f"[red]Unknown policy '{policy}'. Choose from: {', '.join(POLICY_REGISTRY)}[/red]")
        raise typer.Exit(1)

    frames = _load_frames(dataset_path)
    if not frames:
        console.print("[red]No frames loaded.[/red]")
        raise typer.Exit(1)

    summary = _replay(frames, POLICY_REGISTRY[policy], DEFAULT_RESIDUAL_LIMITS)

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    summary_path = out_path / "replay_summary.json"
    with summary_path.open("w") as fh:
        json.dump(summary, fh, indent=2, default=str)

    table = Table(title=f"Offline Replay Summary — {policy}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")
    for key, value in summary.items():
        if key == "limits":
            continue
        table.add_row(key, f"{value:.6f}" if isinstance(value, float) else str(value))
    console.print(table)

    console.print(f"\n[green]Summary written to {summary_path}[/green]")


if __name__ == "__main__":
    app()

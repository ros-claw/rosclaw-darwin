#!/usr/bin/env python3
"""Build Residual Dataset v2 with paired / route / medium-OOD labels.

This CLI extends `build_residual_dataset.py` by merging v1.10 labels:
- `pair_label` from a paired-evaluation summary (`paired_summary.json`).
- `route_label` from an optional route-label JSONL file.
- `medium_ood_label` from an optional medium-OOD label JSONL file.

It also supports building directly from a v1.9 ``frames.parquet`` via
``--from-parquet``.  In parquet mode, route labels are derived from frame
context (success, large-yaw context, grip-quality signals) so that downstream
Sprint-8 classifiers can be trained without hand-authoring a label file.

The output is a `residual_learning` v2 dataset compatible with the
`ResidualDataset` v2 schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import numpy as np
import pandas as pd
import typer
from rich.console import Console

from rosclaw_darwin.learning.residual_dataset import ResidualDataset, ResidualFrame

app = typer.Typer(help="Build residual-learning dataset v2 from traces with v1.10 labels.")
console = Console()


_OBSERVATION_KEYS = {
    "eef_x",
    "eef_y",
    "eef_z",
    "eef_roll",
    "eef_pitch",
    "eef_yaw",
    "object_x",
    "object_y",
    "object_z",
    "object_yaw",
    "target_x",
    "target_y",
    "target_z",
    "target_yaw",
    "gripper_pos",
    "orientation_error",
    "object_eef_distance",
    "object_eef_yaw_delta",
}

_SIGNAL_PREFIXES = {
    "contact": "contact_signal_",
    "slip": "slip_signal_",
    "grip_quality": "grip_quality_signal_",
}


def _load_pair_labels(paired_summary_path: Path) -> dict[int, str]:
    """Map seed -> delta_class from a paired-evaluation summary."""
    data = json.loads(paired_summary_path.read_text(encoding="utf-8"))
    outcomes = data.get("outcomes", [])
    return {int(o["seed"]): str(o["delta_class"]) for o in outcomes if "seed" in o and "delta_class" in o}


def _load_frame_labels(path: Path | None, key: str) -> dict[tuple[int | None, int], str]:
    """Load per-frame labels from a JSONL file keyed by (seed, step).

    Each record must contain at least ``step`` and the label field ``key``.
    ``seed`` is optional and used when present.
    """
    labels: dict[tuple[int | None, int], str] = {}
    if path is None or not path.exists():
        return labels
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            step = int(rec["step"])
            seed = int(rec["seed"]) if "seed" in rec else None
            if key in rec:
                labels[(seed, step)] = str(rec[key])
    return labels


def _apply_labels(
    frames: list[ResidualFrame],
    pair_labels: dict[int, str],
    route_labels: dict[tuple[int | None, int], str],
    medium_ood_labels: dict[tuple[int | None, int], str],
) -> list[ResidualFrame]:
    """Apply v1.10 labels to frames in-place."""
    for frame in frames:
        if frame.seed is not None and frame.seed in pair_labels:
            frame.pair_label = pair_labels[frame.seed]
        key = (frame.seed, frame.step)
        if key in route_labels:
            frame.route_label = route_labels[key]
        if key in medium_ood_labels:
            frame.medium_ood_label = medium_ood_labels[key]
    return frames


# ---------------------------------------------------------------------------
# Parquet support
# ---------------------------------------------------------------------------


def _extract_signal(row: pd.Series, prefix: str) -> dict[str, Any] | None:
    """Reconstruct a signal dict from flattened parquet columns."""
    short_prefix = _SIGNAL_PREFIXES[prefix]
    signal: dict[str, Any] = {}
    for col in row.index:
        if col.startswith(short_prefix):
            short_key = col[len(short_prefix) :]
            value = row[col]
            if isinstance(value, (np.integer, np.floating)):
                value = value.item()
            elif isinstance(value, np.ndarray):
                value = value.tolist()
            elif pd.isna(value):
                value = None
            signal[short_key] = value
    return signal if signal else None


def _extract_observation(row: pd.Series) -> dict[str, Any]:
    """Reconstruct the observation dict from flattened parquet columns."""
    obs: dict[str, Any] = {}
    for key in _OBSERVATION_KEYS:
        col = f"observation_{key}"
        if col in row.index:
            value = row[col]
            if isinstance(value, (np.integer, np.floating)):
                value = value.item()
            elif pd.isna(value):
                value = None
            obs[key] = value
    return obs


def _ensure_list(value: Any) -> list[float]:
    """Coerce a parquet list cell to a Python list of floats."""
    if isinstance(value, (list, tuple, np.ndarray)):
        return [float(v) for v in value]
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return []
    return [float(value)]


def _assign_route_label_from_context(frame: ResidualFrame, source_trace: str) -> str:
    """Derive a conservative Sprint-8 route label from frame context."""
    if frame.success_label:
        return "continue"

    obs = frame.observation
    target_yaw = abs(obs.get("target_yaw") or 0.0)
    yaw_delta = abs(obs.get("object_eef_yaw_delta") or 0.0)

    if "large_yaw_slip" in source_trace or target_yaw > 1.2 or yaw_delta > 1.0:
        return "blocked_external"

    gq = frame.grip_quality_signal or {}
    grip_trigger = bool(gq.get("trigger", False))
    low_object_z = bool(gq.get("low_object_z", False))
    gripper_too_open = bool(gq.get("gripper_too_open", False))

    if frame.phase in {"GRASP", "LIFT", "HOLD", "VERIFY_OBJECT_FOLLOWING"}:
        if grip_trigger or (low_object_z and gripper_too_open):
            return "lower_regrip"

    orientation_error = obs.get("orientation_error") or 0.0
    if frame.phase in {"ALIGN", "REORIENT", "STABILIZE"} and orientation_error > 0.5:
        return "pause"

    return "abort_safe"


def _row_to_frame(row: pd.Series, global_episode: int) -> ResidualFrame:
    """Convert one flattened dataframe row to a ``ResidualFrame``."""
    source_trace = str(row.get("source_trace", ""))

    heuristic_action = _ensure_list(row.get("heuristic_action"))
    executed_action = _ensure_list(row.get("executed_action"))
    residual_target = _ensure_list(row.get("residual_target"))
    residual_mask = _ensure_list(row.get("residual_mask"))
    if residual_mask:
        residual_mask = [bool(v) for v in residual_mask]

    observation = _extract_observation(row)
    contact_signal = _extract_signal(row, "contact")
    slip_signal = _extract_signal(row, "slip")
    grip_quality_signal = _extract_signal(row, "grip_quality")

    if grip_quality_signal is not None:
        if "low_object_z" not in grip_quality_signal:
            obj_z = observation.get("object_z")
            grip_quality_signal["low_object_z"] = bool(obj_z is not None and obj_z < 0.023)
        if "gripper_too_open" not in grip_quality_signal:
            grip_pos = observation.get("gripper_pos")
            grip_quality_signal["gripper_too_open"] = bool(grip_pos is not None and grip_pos > 0.035)

    frame = ResidualFrame(
        episode=global_episode,
        step=int(row.get("step", 0)),
        task=str(row.get("task", "unknown")),
        object_name=row.get("object_name") if pd.notna(row.get("object_name")) else None,
        seed=int(row.get("seed")) if pd.notna(row.get("seed")) else None,
        phase=str(row.get("phase", "UNKNOWN")),
        observation=observation,
        heuristic_action=heuristic_action,
        executed_action=executed_action,
        success_label=bool(row.get("success_label", False)),
        failure_type=row.get("failure_type") if pd.notna(row.get("failure_type")) else None,
        contact_signal=contact_signal,
        slip_signal=slip_signal,
        grip_quality_signal=grip_quality_signal,
        residual_target=residual_target,
        residual_mask=residual_mask,
        sample_weight=float(row.get("sample_weight", 1.0)),
        source_trace=source_trace,
    )

    frame.route_label = _assign_route_label_from_context(frame, source_trace)
    return frame


def _load_frames_from_parquet(parquet_path: Path) -> list[ResidualFrame]:
    """Load ``ResidualFrame`` records from a v1.9 parquet dataset."""
    if not parquet_path.exists():
        raise FileNotFoundError(f"Parquet dataset not found: {parquet_path}")
    df = pd.read_parquet(parquet_path)
    frames: list[ResidualFrame] = []
    for idx, row in df.iterrows():
        frames.append(_row_to_frame(row, global_episode=idx + 1))
    return frames


@app.command()
def build(
    input_dirs: Annotated[
        list[str],
        typer.Option("--input-dir", help="Input trace directories (repeatable)."),
    ] = None,
    from_parquet: Annotated[
        str | None,
        typer.Option("--from-parquet", help="Path to a v1.9 frames.parquet file."),
    ] = None,
    output_dir: Annotated[str, typer.Option("--output-dir", help="Output directory for dataset artifacts.")] = "data_v20/datasets/residual_learning_v2",
    paired_summary: Annotated[str | None, typer.Option("--paired-summary", help="Path to paired_summary.json for pair labels.")] = None,
    route_labels: Annotated[str | None, typer.Option("--route-labels", help="Path to route_labels.jsonl (overrides parquet-derived labels.")] = None,
    medium_ood_labels: Annotated[str | None, typer.Option("--medium-ood-labels", help="Path to medium_ood_labels.jsonl.")] = None,
    train_ratio: Annotated[float, typer.Option("--train-ratio", help="Train split ratio.")] = 0.70,
    val_ratio: Annotated[float, typer.Option("--val-ratio", help="Validation split ratio.")] = 0.15,
    test_ratio: Annotated[float, typer.Option("--test-ratio", help="Test split ratio.")] = 0.15,
    random_seed: Annotated[int, typer.Option("--random-seed", help="Random seed for splits.")] = 42,
    failure_weight: Annotated[float, typer.Option("--failure-weight", help="Sample weight for failure frames.")] = 2.0,
    success_weight: Annotated[float, typer.Option("--success-weight", help="Sample weight for success frames.")] = 1.0,
) -> None:
    """Build a v2 residual dataset from traces and/or a parquet file."""
    out_path = Path(output_dir).resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    pair_map: dict[int, str] = {}
    if paired_summary is not None:
        pair_map = _load_pair_labels(Path(paired_summary))
        console.print(f"Loaded {len(pair_map)} pair labels from {paired_summary}")

    route_map = _load_frame_labels(Path(route_labels) if route_labels else None, "route_label")
    ood_map = _load_frame_labels(Path(medium_ood_labels) if medium_ood_labels else None, "medium_ood_label")

    all_frames: list[ResidualFrame] = []

    if from_parquet is not None:
        parquet_path = Path(from_parquet)
        console.print(f"Loading frames from parquet: {parquet_path}")
        parquet_frames = _load_frames_from_parquet(parquet_path)
        # Apply explicit route labels if provided; otherwise keep parquet-derived labels.
        if route_map:
            parquet_frames = _apply_labels(parquet_frames, {}, route_map, {})
        all_frames.extend(parquet_frames)

    if input_dirs:
        for input_dir in input_dirs:
            ds = ResidualDataset.from_traces(
                input_dir,
                train_ratio=train_ratio,
                val_ratio=val_ratio,
                test_ratio=test_ratio,
                random_seed=random_seed,
                failure_weight=failure_weight,
                success_weight=success_weight,
            )
            all_frames.extend(ds.frames)

    if not all_frames:
        console.print("[red]No input frames. Provide --from-parquet and/or --input-dir.[/red]")
        raise typer.Exit(1)

    all_frames = _apply_labels(all_frames, pair_map, route_map, ood_map)

    # Rebuild dataset with merged frames and re-split.
    merged_ds = ResidualDataset(all_frames)
    merged_ds._split_by_episode(train_ratio, val_ratio, test_ratio, random_seed)
    merged_ds.save(out_path, force_jsonl=True)

    stats = merged_ds.statistics()
    route_counts: dict[str, int] = {}
    for frame in merged_ds.frames:
        if frame.route_label:
            route_counts[frame.route_label] = route_counts.get(frame.route_label, 0) + 1

    console.print("\n=== Residual Dataset v2 Summary ===")
    console.print(f"Frames: {stats['num_frames']}")
    console.print(f"Episodes: {stats['num_episodes']}")
    console.print(f"Train/Val/Test episodes: {stats['train_episodes']}/{stats['val_episodes']}/{stats['test_episodes']}")
    console.print(f"Pair-labeled frames: {sum(1 for f in all_frames if f.pair_label is not None)}")
    console.print(f"Route-labeled frames: {sum(1 for f in all_frames if f.route_label is not None)}")
    console.print(f"Route label counts: {route_counts}")
    console.print(f"Medium-OOD-labeled frames: {sum(1 for f in all_frames if f.medium_ood_label is not None)}")
    console.print(f"Output: {out_path}")


if __name__ == "__main__":
    app()

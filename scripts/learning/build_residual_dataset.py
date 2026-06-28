#!/usr/bin/env python3
"""CLI to build a residual-learning dataset from episode trace directories."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from rosclaw_darwin.learning.residual_dataset import ResidualDataset, ResidualFrame

app = typer.Typer(help="Build residual-learning datasets from traces.")
console = Console()


def _load_seed_success_map(csv_path: Path) -> dict[int, bool]:
    """Load per-seed success labels from an audit CSV.

    Expected columns include at least ``seed`` and ``env_success_rate``.
    Only seeds with ``status == completed`` are used; success is declared when
    ``env_success_rate >= 0.5``.
    """
    import csv

    seed_success_map: dict[int, bool] = {}
    with csv_path.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            status = row.get("status", "completed")
            if status != "completed":
                continue
            try:
                seed = int(row["seed"])
                rate = float(row["env_success_rate"])
            except (KeyError, ValueError):
                continue
            seed_success_map[seed] = rate >= 0.5
    return seed_success_map


def _load_trace_success_map(csv_path: Path) -> dict[str, bool]:
    """Load per-trace success labels from an audit CSV.

    Expected columns include at least ``trace_path`` and ``success``.
    ``trace_path`` may be the path to a trace file relative to its input
    directory, or simply ``trace.jsonl`` with enough parent directories to be
    unique. ``success`` may be ``true``/``1`` or a floating-point success rate
    (>= 0.5 is treated as success).
    """
    import csv

    trace_success_map: dict[str, bool] = {}
    with csv_path.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            trace_path = row.get("trace_path") or row.get("trace_file")
            if not trace_path:
                continue
            success_raw = row.get("success", row.get("env_success_rate", "false"))
            success = False
            try:
                success = bool(float(success_raw) >= 0.5)
            except ValueError:
                success = success_raw.strip().lower() in ("true", "1", "yes", "success")
            trace_success_map[trace_path] = success
    return trace_success_map


def _reject_parent_components(paths: list[str]) -> None:
    """Refuse paths containing '..' to avoid accidental writes outside the project."""
    for p in paths:
        if ".." in Path(p).parts:
            console.print(f"[red]Paths with '..' are not allowed: {p}[/red]")
            raise typer.Exit(1)


DEFAULT_INPUT_DIRS = [
    "data_v17/diagnostics/large_yaw_slip",
    "data_v18/diagnostics/slip_monitor_validation",
    "data_v18/ablations/slip_aware_recovery",
    "data_v18/ablations/valid_ood_cube_matrix",
    "data_v19/diagnostics/micro_recovery_trigger_audit_gated_v2",
]


@app.command()
def build(
    input_dirs: Annotated[
        list[str],
        typer.Option(
            "--input-dir",
            help="Input trace directories (repeatable). Defaults to known v17/v18/v19 dirs.",
        ),
    ] = None,
    output_dir: Annotated[str, typer.Option("--output-dir", help="Output directory for dataset artifacts.")] = "data_v19/datasets/residual_learning",
    train_ratio: Annotated[float, typer.Option("--train-ratio", help="Train split ratio.")] = 0.70,
    val_ratio: Annotated[float, typer.Option("--val-ratio", help="Validation split ratio.")] = 0.15,
    test_ratio: Annotated[float, typer.Option("--test-ratio", help="Test split ratio.")] = 0.15,
    random_seed: Annotated[int, typer.Option("--random-seed", help="Split reproducibility seed.")] = 42,
    failure_weight: Annotated[float, typer.Option("--failure-weight", help="Sample weight for failure frames.")] = 2.0,
    success_weight: Annotated[float, typer.Option("--success-weight", help="Sample weight for success frames.")] = 1.0,
    per_seed_csv: Annotated[
        str | None,
        typer.Option(
            "--per-seed-csv",
            help="Optional audit CSV with seed-level success labels (overrides summary metadata).",
        ),
    ] = None,
    per_trace_csvs: Annotated[
        list[str] | None,
        typer.Option(
            "--per-trace-csv",
            help="Optional audit CSV(s) with trace-path-level success labels. Takes precedence over --per-seed-csv and summary metadata (repeatable).",
        ),
    ] = None,
    jsonl: Annotated[
        bool,
        typer.Option(
            "--jsonl",
            help="Force frames.jsonl output instead of parquet (better nested-dict round-trip).",
        ),
    ] = False,
) -> None:
    """Build residual dataset from trace directories."""
    input_dirs = input_dirs or DEFAULT_INPUT_DIRS
    _reject_parent_components([*input_dirs, output_dir])
    if per_seed_csv is not None:
        _reject_parent_components([per_seed_csv])
    if per_trace_csvs is not None:
        _reject_parent_components(per_trace_csvs)

    seed_success_map = None
    if per_seed_csv is not None:
        csv_path = Path(per_seed_csv)
        if not csv_path.exists():
            console.print(f"[red]Per-seed CSV not found: {per_seed_csv}[/red]")
            raise typer.Exit(1)
        seed_success_map = _load_seed_success_map(csv_path)
        console.print(
            f"[cyan]Loaded {len(seed_success_map)} seed-level labels from {per_seed_csv}[/cyan]"
        )

    trace_success_map: dict[str, bool] | None = None
    if per_trace_csvs is not None:
        trace_success_map = {}
        for csv_file in per_trace_csvs:
            csv_path = Path(csv_file)
            if not csv_path.exists():
                console.print(f"[red]Per-trace CSV not found: {csv_file}[/red]")
                raise typer.Exit(1)
            trace_success_map.update(_load_trace_success_map(csv_path))
        console.print(
            f"[cyan]Loaded {len(trace_success_map)} trace-level labels from {len(per_trace_csvs)} CSV(s)[/cyan]"
        )

    # Gracefully skip missing directories.
    valid_dirs: list[Path] = []
    for d in input_dirs:
        p = Path(d)
        if p.exists() and p.is_dir():
            valid_dirs.append(p)
        else:
            console.print(f"[yellow]Skipping missing directory:[/yellow] {d}")

    if not valid_dirs:
        console.print("[red]No valid input directories found. Exiting.[/red]")
        raise typer.Exit(1)

    # Aggregate all traces into a single dataset.
    all_frames: list[ResidualFrame] = []
    for trace_dir in valid_dirs:
        # Look for summary.json in the same directory or parent.
        summary_candidates = [
            trace_dir / "aggregate_summary.json",
            trace_dir / "summary.json",
            trace_dir.parent / "aggregate_summary.json",
            trace_dir.parent / "summary.json",
        ]
        summary_path = None
        for cand in summary_candidates:
            if cand.exists():
                summary_path = str(cand)
                break

        try:
            ds = ResidualDataset.from_traces(
                trace_dir=trace_dir,
                summary_path=summary_path,
                train_ratio=train_ratio,
                val_ratio=val_ratio,
                test_ratio=test_ratio,
                random_seed=random_seed,
                failure_weight=failure_weight,
                success_weight=success_weight,
                seed_success_map=seed_success_map,
                trace_success_map=trace_success_map,
            )
            all_frames.extend(ds.frames)
        except FileNotFoundError:
            console.print(f"[yellow]No traces found in {trace_dir}; skipping.[/yellow]")

    if not all_frames:
        console.print("[red]No frames loaded from any input directory. Exiting.[/red]")
        raise typer.Exit(1)

    # Ensure globally unique episode IDs across input directories.
    episode_id_map: dict[int | tuple[int, str], int] = {}
    next_episode_id = 0
    for frame in all_frames:
        old_episode = frame.episode
        # Use source_trace as a secondary key if available to distinguish
        # episodes with the same numeric id from different directories.
        source_key: int | tuple[int, str] = old_episode
        if frame.source_trace is not None:
            source_key = (old_episode, frame.source_trace)
        if source_key not in episode_id_map:
            next_episode_id += 1
            episode_id_map[source_key] = next_episode_id
        frame.episode = episode_id_map[source_key]

    # Rebuild a unified dataset with the combined frames.
    unified = ResidualDataset(all_frames)
    unified._split_by_episode(train_ratio, val_ratio, test_ratio, random_seed)

    # Save artifacts.
    unified.save(output_dir, force_jsonl=jsonl)

    # Print statistics.
    stats = unified.statistics()
    table = Table(title="Residual Dataset Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")
    for key, value in stats.items():
        table.add_row(key, str(value))
    console.print(table)

    console.print(f"\n[green]Dataset saved to {output_dir}[/green]")


if __name__ == "__main__":
    app()

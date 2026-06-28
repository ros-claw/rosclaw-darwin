"""Integration test for the residual dataset build CLI."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from rosclaw_darwin.learning.residual_dataset import ResidualDataset


def _project_root() -> Path:
    """Return the project root by looking for rosclaw_darwin package."""
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "rosclaw_darwin" / "learning" / "residual_dataset.py").exists():
            return parent
    raise RuntimeError("Could not find project root")


def _make_trace_record(
    step: int = 0,
    phase: str = "APPROACH",
    action: list[float] | None = None,
    heuristic_action: list[float] | None = None,
) -> dict:
    rec: dict = {
        "episode": 1,
        "step": step,
        "phase": phase,
        "eef_x": 0.1,
        "object_z": 0.025,
        "gripper_pos": 0.02,
    }
    if action is not None:
        rec["action"] = action
    if heuristic_action is not None:
        rec["heuristic_action"] = heuristic_action
    return rec


def test_build_residual_dataset_cli():
    """Run the CLI on a temporary synthetic trace directory and verify outputs."""
    root = _project_root()
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input" / "seed_000"
        input_dir.mkdir(parents=True)
        trace_file = input_dir / "trace.jsonl"
        records = [
            _make_trace_record(step=0, phase="APPROACH", action=[0.1, 0.0, 0.0], heuristic_action=[0.1, 0.0, 0.0]),
            _make_trace_record(step=1, phase="GRASP", action=[0.0, 0.0, -0.01], heuristic_action=[0.0, 0.0, -0.01]),
            _make_trace_record(step=2, phase="LIFT", action=[0.0, 0.0, 0.05], heuristic_action=[0.0, 0.0, 0.05]),
        ]
        with trace_file.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        summary = {
            "episodes": [
                {
                    "episode_id": 1,
                    "success": True,
                    "task": "goal_pose",
                    "object_name": "dex_cube",
                    "seed": 0,
                    "failure_type": None,
                }
            ]
        }
        summary_path = Path(tmpdir) / "input" / "summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh)

        output_dir = Path(tmpdir) / "output"

        script_path = root / "scripts" / "learning" / "build_residual_dataset.py"
        result = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--input-dir",
                str(input_dir.parent),
                "--output-dir",
                str(output_dir),
                "--train-ratio",
                "0.6",
                "--val-ratio",
                "0.2",
                "--test-ratio",
                "0.2",
            ],
            capture_output=True,
            text=True,
            cwd=str(root),
            env={**os.environ, "PYTHONPATH": str(root)},
        )

        assert result.returncode == 0, result.stderr

        # Verify output files exist.
        assert (output_dir / "frames.parquet").exists() or (output_dir / "frames.jsonl").exists()
        assert (output_dir / "episodes.jsonl").exists()
        assert (output_dir / "metadata.yaml").exists()
        assert (output_dir / "split_train.json").exists()
        assert (output_dir / "split_val.json").exists()
        assert (output_dir / "split_test.json").exists()

        # Verify split manifests.
        with (output_dir / "split_train.json").open() as fh:
            train_manifest = json.load(fh)
        assert "episodes" in train_manifest
        assert train_manifest["count"] >= 0

        # Verify episodes.jsonl.
        with (output_dir / "episodes.jsonl").open() as fh:
            episode_lines = [json.loads(line) for line in fh]
        assert len(episode_lines) == 1
        assert episode_lines[0]["episode"] == 1
        assert episode_lines[0]["success"] is True
        assert episode_lines[0]["num_frames"] == 3

        # Verify metadata.
        import yaml

        with (output_dir / "metadata.yaml").open() as fh:
            metadata = yaml.safe_load(fh)
        assert metadata["dataset"] == "residual_learning"
        assert metadata["version"] == "v2"
        assert metadata["num_frames"] == 3
        assert metadata["num_episodes"] == 1


def _read_frames(output_dir: Path):
    """Read frames from parquet if available, otherwise from JSONL fallback."""
    pytest.importorskip("pandas")
    import pandas as pd

    parquet_path = output_dir / "frames.parquet"
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    jsonl_path = output_dir / "frames.jsonl"
    assert jsonl_path.exists(), "No frames.parquet or frames.jsonl found"
    return pd.read_json(jsonl_path, lines=True)


def test_build_residual_dataset_cli_per_seed_csv_overrides_summary():
    """--per-seed-csv should override summary success labels for matching seeds."""
    root = _project_root()
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input" / "seed_024"
        input_dir.mkdir(parents=True)
        trace_file = input_dir / "trace.jsonl"
        records = [
            _make_trace_record(step=0, phase="APPROACH", action=[0.1, 0.0, 0.0], heuristic_action=[0.1, 0.0, 0.0]),
        ]
        with trace_file.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        summary = {
            "episodes": [
                {
                    "episode_id": 1,
                    "success": False,
                    "task": "goal_pose",
                    "object_name": "dex_cube",
                    "seed": 24,
                    "failure_type": "object_not_lifted",
                }
            ]
        }
        summary_path = Path(tmpdir) / "input" / "summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh)

        per_seed_csv = Path(tmpdir) / "per_seed_results.csv"
        with per_seed_csv.open("w", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "seed",
                    "status",
                    "env_success_rate",
                    "env_progress_mean",
                    "grip_quality_trigger",
                    "micro_recovery_triggered",
                    "max_grip_failure_risk",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "seed": "24",
                    "status": "completed",
                    "env_success_rate": "1.0",
                    "env_progress_mean": "0.8",
                    "grip_quality_trigger": "False",
                    "micro_recovery_triggered": "False",
                    "max_grip_failure_risk": "0.6667",
                }
            )

        output_dir = Path(tmpdir) / "output"
        script_path = root / "scripts" / "learning" / "build_residual_dataset.py"
        result = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--input-dir",
                str(input_dir.parent),
                "--output-dir",
                str(output_dir),
                "--per-seed-csv",
                str(per_seed_csv),
            ],
            capture_output=True,
            text=True,
            cwd=str(root),
            env={**os.environ, "PYTHONPATH": str(root)},
        )

        assert result.returncode == 0, result.stderr
        df = _read_frames(output_dir)
        assert len(df) == 1
        assert df.iloc[0]["success_label"]
        assert df.iloc[0]["sample_weight"] == 1.0


def test_build_residual_dataset_cli_per_trace_csv_overrides_seed_map():
    """--per-trace-csv should override seed-level and summary labels."""
    root = _project_root()
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input" / "seed_024"
        input_dir.mkdir(parents=True)
        trace_file = input_dir / "trace.jsonl"
        records = [
            _make_trace_record(step=0, phase="APPROACH", action=[0.1, 0.0, 0.0], heuristic_action=[0.1, 0.0, 0.0]),
        ]
        with trace_file.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        summary = {
            "episodes": [
                {
                    "episode_id": 1,
                    "success": False,
                    "task": "goal_pose",
                    "object_name": "dex_cube",
                    "seed": 24,
                    "failure_type": "object_not_lifted",
                }
            ]
        }
        summary_path = Path(tmpdir) / "input" / "summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh)

        per_trace_csv = Path(tmpdir) / "per_trace_results.csv"
        with per_trace_csv.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["trace_path", "success"])
            writer.writeheader()
            writer.writerow({"trace_path": "seed_024/trace.jsonl", "success": "true"})

        output_dir = Path(tmpdir) / "output"
        script_path = root / "scripts" / "learning" / "build_residual_dataset.py"
        result = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--input-dir",
                str(input_dir.parent),
                "--output-dir",
                str(output_dir),
                "--per-trace-csv",
                str(per_trace_csv),
            ],
            capture_output=True,
            text=True,
            cwd=str(root),
            env={**os.environ, "PYTHONPATH": str(root)},
        )

        assert result.returncode == 0, result.stderr
        df = _read_frames(output_dir)
        assert len(df) == 1
        assert df.iloc[0]["success_label"]
        assert df.iloc[0]["sample_weight"] == 1.0


def test_build_residual_dataset_cli_missing_dir_graceful():
    """CLI should skip missing directories and still succeed if at least one is valid."""
    root = _project_root()
    with tempfile.TemporaryDirectory() as tmpdir:
        valid_dir = Path(tmpdir) / "valid" / "seed_000"
        valid_dir.mkdir(parents=True)
        trace_file = valid_dir / "trace.jsonl"
        records = [
            _make_trace_record(step=0, action=[0.0], heuristic_action=[0.0]),
        ]
        with trace_file.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        summary = {"episodes": [{"episode_id": 1, "success": True, "task": "t"}]}
        summary_path = Path(tmpdir) / "valid" / "summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh)

        output_dir = Path(tmpdir) / "output"
        missing_dir = Path(tmpdir) / "does_not_exist"

        script_path = root / "scripts" / "learning" / "build_residual_dataset.py"
        result = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--input-dir",
                str(missing_dir),
                "--input-dir",
                str(valid_dir.parent),
                "--output-dir",
                str(output_dir),
            ],
            capture_output=True,
            text=True,
            cwd=str(root),
            env={**os.environ, "PYTHONPATH": str(root)},
        )

        assert result.returncode == 0, result.stderr
        assert (output_dir / "episodes.jsonl").exists()


def test_build_residual_dataset_cli_all_missing_dirs():
    """CLI should exit with error if all input directories are missing."""
    root = _project_root()
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "output"
        missing_dir = Path(tmpdir) / "does_not_exist"

        script_path = root / "scripts" / "learning" / "build_residual_dataset.py"
        result = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--input-dir",
                str(missing_dir),
                "--output-dir",
                str(output_dir),
            ],
            capture_output=True,
            text=True,
            cwd=str(root),
            env={**os.environ, "PYTHONPATH": str(root)},
        )

        assert result.returncode == 1
        assert (
            "No valid input directories" in result.stdout
            or "No valid input directories" in result.stderr
        )


def test_dataset_save_and_load_parquet():
    """Save dataset and verify it can be loaded back from parquet."""
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    with tempfile.TemporaryDirectory() as tmpdir:
        trace_dir = Path(tmpdir) / "seed_000"
        trace_dir.mkdir()
        trace_file = trace_dir / "trace.jsonl"
        records = [
            _make_trace_record(step=0, phase="APPROACH", action=[0.1, 0.0, 0.0], heuristic_action=[0.1, 0.0, 0.0]),
        ]
        with trace_file.open("w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")

        summary = {"episodes": [{"episode_id": 1, "success": True, "task": "t"}]}
        summary_path = Path(tmpdir) / "summary.json"
        with summary_path.open("w") as fh:
            json.dump(summary, fh)

        ds = ResidualDataset.from_traces(tmpdir, summary_path=summary_path)
        output_dir = Path(tmpdir) / "dataset"
        ds.save(output_dir)

        assert (output_dir / "frames.parquet").exists() or (output_dir / "frames.jsonl").exists()
        df = _read_frames(output_dir)
        assert len(df) == 1
        assert df.iloc[0]["episode"] == 1

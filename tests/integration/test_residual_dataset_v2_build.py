#!/usr/bin/env python3
"""Integration test for build_residual_dataset_v2 CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _make_trace_record(step: int = 0, phase: str = "APPROACH", action: list[float] | None = None) -> dict:
    rec: dict = {"episode": 1, "step": step, "phase": phase, "eef_x": 0.1, "object_z": 0.025, "gripper_pos": 0.02}
    if action is not None:
        rec["action"] = action
        rec["heuristic_action"] = action
    return rec


@pytest.fixture
def runner_path() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "learning" / "build_residual_dataset_v2.py"


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_build_v2_with_pair_labels(runner_path: Path, project_root: Path, tmp_path: Path):
    trace_dir = tmp_path / "seed_000"
    trace_dir.mkdir(parents=True)
    records = [
        _make_trace_record(step=0, phase="GRASP", action=[0.0, 0.0, -0.01]),
        _make_trace_record(step=1, phase="LIFT", action=[0.0, 0.0, 0.05]),
    ]
    with (trace_dir / "trace.jsonl").open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")

    paired_summary = {
        "outcomes": [
            {"seed": 0, "delta_class": "rescued"},
        ]
    }
    summary_path = tmp_path / "paired_summary.json"
    with summary_path.open("w") as fh:
        json.dump(paired_summary, fh)

    out_dir = tmp_path / "dataset_v2"
    cmd = [
        sys.executable,
        str(runner_path),
        "--input-dir",
        str(trace_dir.parent),
        "--output-dir",
        str(out_dir),
        "--paired-summary",
        str(summary_path),
        "--train-ratio",
        "0.6",
        "--val-ratio",
        "0.2",
        "--test-ratio",
        "0.2",
    ]
    env = {"PYTHONPATH": str(project_root)}
    result = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True, env=env, check=False)
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

    assert (out_dir / "metadata.yaml").exists()
    assert (out_dir / "pair_labels.jsonl").exists()

    pair_labels = [json.loads(line) for line in (out_dir / "pair_labels.jsonl").open()]
    assert len(pair_labels) == 2
    assert all(pl["pair_label"] == "rescued" for pl in pair_labels)

    with (out_dir / "metadata.yaml").open() as fh:
        import yaml
        metadata = yaml.safe_load(fh)
    assert metadata["version"] == "v2"


def test_build_v2_without_labels_runs(runner_path: Path, project_root: Path, tmp_path: Path):
    trace_dir = tmp_path / "seed_001"
    trace_dir.mkdir(parents=True)
    records = [_make_trace_record(step=0, phase="GRASP", action=[0.0, 0.0, -0.01])]
    with (trace_dir / "trace.jsonl").open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")

    out_dir = tmp_path / "dataset_v2"
    cmd = [
        sys.executable,
        str(runner_path),
        "--input-dir",
        str(trace_dir.parent),
        "--output-dir",
        str(out_dir),
    ]
    env = {"PYTHONPATH": str(project_root)}
    result = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True, env=env, check=False)
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

    assert (out_dir / "metadata.yaml").exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

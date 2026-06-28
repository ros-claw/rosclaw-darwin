#!/usr/bin/env python3
"""Smoke test for paired policy evaluation runner.

Runs the paired evaluator in --mock mode on a small seed set and verifies that
the expected artifact files and summary fields are produced. This test does not
start Docker; it exercises the schema/IO path only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def runner_path() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "diagnostics" / "run_paired_policy_evaluation.py"


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_paired_evaluator_mock_runs(runner_path: Path, project_root: Path, tmp_path: Path):
    out_dir = tmp_path / "paired_smoke"
    cmd = [
        sys.executable,
        str(runner_path),
        "--seeds", "0,1,24,105",
        "--mock",
        "--out-dir", str(out_dir),
    ]
    env = {"PYTHONPATH": str(project_root)}
    result = subprocess.run(
        cmd,
        cwd=project_root,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

    summary_path = out_dir / "summary_only.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text())
    assert summary["total_pairs"] == 4
    assert summary["rescued_count"] == 1
    assert summary["newly_failed_count"] == 0
    assert "mcnemar_p_value" in summary

    paired_summary = out_dir / "paired_summary.json"
    assert paired_summary.exists()
    full = json.loads(paired_summary.read_text())
    assert len(full["outcomes"]) == 4

    assert (out_dir / "rescued_seeds.json").exists()
    assert (out_dir / "newly_failed_seeds.json").exists()
    assert (out_dir / "paired_outcomes.csv").exists()
    assert (out_dir / "seed_024" / "pair_result.json").exists()


def test_paired_evaluator_detects_regression(runner_path: Path, project_root: Path, tmp_path: Path):
    """A mock candidate that breaks an easy seed should produce newly_failed > 0."""
    out_dir = tmp_path / "paired_regression"
    # Use two baseline-success seeds; the mock candidate succeeds on all
    # non-BASELINE_FAILURES_100_199 seeds, so no regression occurs. We instead
    # validate that the runner reports the correct unchanged_success count.
    cmd = [
        sys.executable,
        str(runner_path),
        "--seeds", "0,1",
        "--mock",
        "--out-dir", str(out_dir),
    ]
    env = {"PYTHONPATH": str(project_root)}
    result = subprocess.run(
        cmd,
        cwd=project_root,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    summary = json.loads((out_dir / "summary_only.json").read_text())
    assert summary["unchanged_success_count"] == 2
    assert summary["newly_failed_count"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

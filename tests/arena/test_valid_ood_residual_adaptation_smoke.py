#!/usr/bin/env python3
"""Smoke test for valid OOD residual / adaptation benchmark runner (Sprint 7).

Verifies the runner can be imported and its dry-run mode runs with synthetic
input. Does NOT run actual Arena Docker jobs in pytest by default.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

_RUNNER = Path("scripts/ablations/run_valid_ood_residual_adaptation.py")


def test_runner_imports():
    """The runner script should be importable without crashing."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_valid_ood_residual_adaptation", _RUNNER
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_valid_ood_residual_adaptation"] = module
    spec.loader.exec_module(module)
    assert hasattr(module, "main")
    assert hasattr(module, "parse_args")


def test_dry_run_mode():
    """Dry-run mode should print matrix dimensions and exit 0 with synthetic summary."""
    # Build a synthetic Sprint 6 summary.
    summary = {
        "by_task_subtask_condition": {
            "task_1__lift_only__baseline_v3": {
                "task_id": "task_1",
                "subtask": "lift_only",
                "condition": "baseline_v3",
                "count": 20,
                "success_rate": 0.8,
                "object_lifted_rate": 0.9,
                "grasp_reached_rate": 0.85,
                "slip_rate": 0.1,
                "reachability_failure_rate": 0.0,
                "gripper_aperture_limit_rate": 0.0,
                "first_failing_subtask": "lift_only",
            }
        }
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(summary, f)
        summary_path = Path(f.name)

    try:
        result = subprocess.run(
            [
                sys.executable,
                str(_RUNNER),
                "--dry-run",
                "--subtask-summary",
                str(summary_path),
                "--tasks",
                "task_1",
                "--seeds",
                "0:2",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[2],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Dry-run:" in result.stdout
        assert "selected" in result.stdout
        assert "conditions" in result.stdout
        assert "seeds" in result.stdout
    finally:
        summary_path.unlink()


def test_dry_run_custom_conditions():
    """Dry-run with a subset of conditions should reflect the smaller matrix."""
    summary = {
        "by_task_subtask_condition": {
            "task_1__yaw_0__baseline_v3": {
                "task_id": "task_1",
                "subtask": "yaw_0",
                "condition": "baseline_v3",
                "count": 20,
                "success_rate": 0.7,
                "object_lifted_rate": 0.8,
                "grasp_reached_rate": 0.75,
                "slip_rate": 0.15,
                "reachability_failure_rate": 0.0,
                "gripper_aperture_limit_rate": 0.0,
                "first_failing_subtask": "yaw_0",
            }
        }
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(summary, f)
        summary_path = Path(f.name)

    try:
        result = subprocess.run(
            [
                sys.executable,
                str(_RUNNER),
                "--dry-run",
                "--subtask-summary",
                str(summary_path),
                "--tasks",
                "task_1",
                "--conditions",
                "baseline_v3",
                "best_combined",
                "--seeds",
                "0:4",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[2],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "2 conditions" in result.stdout
        assert "5 seeds" in result.stdout
    finally:
        summary_path.unlink()

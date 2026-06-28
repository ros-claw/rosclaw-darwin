#!/usr/bin/env python3
"""Smoke test for valid OOD subtask decomposition runner.

Verifies the runner can be imported and its dry-run mode runs without Docker.
Does NOT run actual Arena Docker jobs in pytest by default.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_RUNNER = Path("scripts/diagnostics/run_valid_ood_subtask_decomposition.py")


def test_runner_imports():
    """The runner script should be importable without crashing."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_valid_ood_subtask_decomposition", _RUNNER
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_valid_ood_subtask_decomposition"] = module
    spec.loader.exec_module(module)
    assert hasattr(module, "main")
    assert hasattr(module, "parse_args")


def test_dry_run_mode():
    """Dry-run mode should print matrix dimensions and exit 0."""
    result = subprocess.run(
        [sys.executable, str(_RUNNER), "--dry-run"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Dry-run matrix:" in result.stdout
    assert "tasks" in result.stdout
    assert "subtasks" in result.stdout
    assert "conditions" in result.stdout
    assert "seeds" in result.stdout


def test_dry_run_custom_subtasks():
    """Dry-run with custom subtasks should reflect the smaller matrix."""
    result = subprocess.run(
        [
            sys.executable,
            str(_RUNNER),
            "--dry-run",
            "--subtasks",
            "lift_only",
            "full",
            "--conditions",
            "baseline_v3",
            "best_combined",
            "--seeds",
            "0:2",
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "2 subtasks" in result.stdout
    assert "2 conditions" in result.stdout
    assert "3 seeds" in result.stdout

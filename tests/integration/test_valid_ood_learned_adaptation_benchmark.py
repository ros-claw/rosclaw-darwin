"""Integration test for the Sprint 7 valid OOD learned adaptation benchmark."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts" / "ablations" / "run_valid_ood_learned_adaptation_benchmark.py"


def test_learned_adaptation_benchmark_dry_run():
    """The benchmark runner prints matrix size and exits without touching Docker."""
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--dry-run",
            "--conditions",
            "baseline_v3",
            "rule_micro_recovery",
            "learned_trigger_only",
            "--seeds",
            "0:2",
            "--out-dir",
            "/tmp/valid_ood_learned_adaptation_test",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "Dry-run:" in result.stdout
    assert "baseline_v3" in result.stdout
    assert "rule_micro_recovery" in result.stdout
    assert "learned_trigger_only" in result.stdout


def test_learned_adaptation_benchmark_rejects_unknown_condition():
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--dry-run",
            "--conditions",
            "baseline_v3",
            "magic_condition",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode != 0
    assert "Invalid conditions" in result.stderr or "magic_condition" in result.stderr


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

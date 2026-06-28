"""Integration tests for Sprint 8 large-yaw route classifier training and pilot."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TRAIN_CLI = REPO_ROOT / "scripts" / "learning" / "train_large_yaw_route_classifier.py"
PILOT_CLI = REPO_ROOT / "scripts" / "ablations" / "run_large_yaw_route_policy_pilot.py"


def test_train_large_yaw_route_classifier_synthetic():
    """The training CLI runs in --synthetic mode and writes model + metrics."""
    out_dir = Path("/tmp/large_yaw_route_classifier_test")
    result = subprocess.run(
        [
            sys.executable,
            str(TRAIN_CLI),
            "--synthetic",
            "--output-dir",
            str(out_dir),
            "--epochs",
            "50",
            "--random-seed",
            "7",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
        env={**dict(**subprocess.os.environ), "PYTHONPATH": str(REPO_ROOT)},
    )
    assert result.returncode == 0, result.stderr
    assert (out_dir / "model.json").exists()
    assert (out_dir / "metrics.json").exists()


def test_large_yaw_route_policy_pilot_dry_run():
    """The pilot runner prints matrix size and exits without touching Docker."""
    result = subprocess.run(
        [
            sys.executable,
            str(PILOT_CLI),
            "--dry-run",
            "--seeds",
            "0:2",
            "--out-dir",
            "/tmp/large_yaw_route_policy_pilot_test",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "Dry-run:" in result.stdout
    assert "baseline_v3" in result.stdout
    assert "route_diagnostic" in result.stdout
    assert "yaw_90" in result.stdout
    assert "yaw_120" in result.stdout


def test_large_yaw_route_policy_pilot_rejects_unknown_condition():
    result = subprocess.run(
        [
            sys.executable,
            str(PILOT_CLI),
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

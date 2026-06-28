#!/usr/bin/env python3
"""Integration test for offline replay residual policy CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "rosclaw_darwin" / "learning" / "residual_policy.py").exists():
            return parent
    raise RuntimeError("Could not find project root")


def _make_frame_record(
    step: int = 0,
    phase: str = "APPROACH",
    action: list[float] | None = None,
    heuristic_action: list[float] | None = None,
    success: bool = True,
    grip_quality_signal: dict | None = None,
    slip_signal: dict | None = None,
) -> dict:
    rec: dict = {
        "episode": 1,
        "step": step,
        "phase": phase,
        "task": "goal_pose",
        "object_name": "dex_cube",
        "seed": 0,
        "success_label": success,
        "failure_type": None,
        "observation": {"eef_x": 0.1, "object_z": 0.025, "gripper_pos": 0.02},
    }
    if action is not None:
        rec["executed_action"] = action
    if heuristic_action is not None:
        rec["heuristic_action"] = heuristic_action
    if grip_quality_signal is not None:
        rec["grip_quality_signal"] = grip_quality_signal
    if slip_signal is not None:
        rec["slip_signal"] = slip_signal
    rec["residual_target"] = [0.0] * 7
    rec["residual_mask"] = [True] * 7
    rec["sample_weight"] = 1.0
    rec["contact_signal"] = None
    return rec


def _build_synthetic_dataset(tmpdir: str) -> Path:
    """Build a tiny synthetic residual dataset with success and failure frames."""
    output_dir = Path(tmpdir) / "dataset"
    output_dir.mkdir(parents=True)

    frames = [
        # Success frames: no special signals.
        _make_frame_record(step=0, phase="APPROACH", success=True, action=[0.1] * 7, heuristic_action=[0.1] * 7),
        _make_frame_record(step=1, phase="GRASP", success=True, action=[0.0] * 7, heuristic_action=[0.0] * 7),
        # Failure frame with seed24-like signature.
        _make_frame_record(
            step=2,
            phase="GRASP",
            success=False,
            action=[0.0] * 7,
            heuristic_action=[0.0] * 7,
            grip_quality_signal={"low_object_z": True, "gripper_too_open": True},
        ),
        # Failure frame with slip signature.
        _make_frame_record(
            step=3,
            phase="LIFT",
            success=False,
            action=[0.0] * 7,
            heuristic_action=[0.0] * 7,
            slip_signal={"slip_risk": "high", "slip_score": 3.0},
        ),
    ]

    with (output_dir / "frames.jsonl").open("w") as fh:
        for rec in frames:
            fh.write(json.dumps(rec, default=str) + "\n")

    return output_dir


def test_offline_replay_none_policy():
    """Replay with none policy should have zero trigger rate on all frames."""
    root = _project_root()
    with tempfile.TemporaryDirectory() as tmpdir:
        dataset_dir = _build_synthetic_dataset(tmpdir)
        output_dir = Path(tmpdir) / "replay_none"

        script_path = root / "scripts" / "learning" / "offline_replay_residual_policy.py"
        result = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--dataset-dir",
                str(dataset_dir),
                "--policy",
                "none",
                "--output-dir",
                str(output_dir),
            ],
            capture_output=True,
            text=True,
            cwd=str(root),
            env={**os.environ, "PYTHONPATH": str(root)},
        )

        assert result.returncode == 0, result.stderr

        summary_path = output_dir / "replay_summary.json"
        assert summary_path.exists()
        with summary_path.open() as fh:
            summary = json.load(fh)

        assert summary["policy"] == "ResidualNonePolicy"
        assert summary["num_frames"] == 4
        assert summary["residual_trigger_rate"] == 0.0
        assert summary["success_frame_trigger_rate"] == 0.0
        assert summary["failure_frame_trigger_rate"] == 0.0
        assert summary["residual_action_norm_mean"] == 0.0
        assert summary["safety_clamp_rate"] == 0.0
        assert summary["would_modify_success_frames_rate"] == 0.0


def test_offline_replay_seed24_guard_policy():
    """Replay with seed24_guard should trigger only on failure frames with matching signature."""
    root = _project_root()
    with tempfile.TemporaryDirectory() as tmpdir:
        dataset_dir = _build_synthetic_dataset(tmpdir)
        output_dir = Path(tmpdir) / "replay_seed24"

        script_path = root / "scripts" / "learning" / "offline_replay_residual_policy.py"
        result = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--dataset-dir",
                str(dataset_dir),
                "--policy",
                "seed24_guard",
                "--output-dir",
                str(output_dir),
            ],
            capture_output=True,
            text=True,
            cwd=str(root),
            env={**os.environ, "PYTHONPATH": str(root)},
        )

        assert result.returncode == 0, result.stderr

        summary_path = output_dir / "replay_summary.json"
        assert summary_path.exists()
        with summary_path.open() as fh:
            summary = json.load(fh)

        assert summary["policy"] == "ResidualSeed24GuardPolicy"
        assert summary["num_frames"] == 4
        # Should trigger on the seed24-like failure frame only.
        assert summary["success_frame_trigger_rate"] == 0.0
        assert summary["failure_frame_trigger_rate"] > 0.0
        assert summary["residual_trigger_rate"] > 0.0
        assert summary["residual_action_norm_mean"] > 0.0
        assert summary["safety_clamp_rate"] == 0.0


def test_offline_replay_slip_guard_policy():
    """Replay with slip_guard should trigger only on failure frames with high slip signal."""
    root = _project_root()
    with tempfile.TemporaryDirectory() as tmpdir:
        dataset_dir = _build_synthetic_dataset(tmpdir)
        output_dir = Path(tmpdir) / "replay_slip"

        script_path = root / "scripts" / "learning" / "offline_replay_residual_policy.py"
        result = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--dataset-dir",
                str(dataset_dir),
                "--policy",
                "slip_guard",
                "--output-dir",
                str(output_dir),
            ],
            capture_output=True,
            text=True,
            cwd=str(root),
            env={**os.environ, "PYTHONPATH": str(root)},
        )

        assert result.returncode == 0, result.stderr

        summary_path = output_dir / "replay_summary.json"
        assert summary_path.exists()
        with summary_path.open() as fh:
            summary = json.load(fh)

        assert summary["policy"] == "ResidualSlipGuardPolicy"
        assert summary["num_frames"] == 4
        assert summary["success_frame_trigger_rate"] == 0.0
        assert summary["failure_frame_trigger_rate"] > 0.0
        assert summary["residual_trigger_rate"] > 0.0
        assert summary["safety_clamp_rate"] == 0.0


def test_offline_replay_all_policies():
    """Run all three policies and verify output files exist for each."""
    root = _project_root()
    with tempfile.TemporaryDirectory() as tmpdir:
        dataset_dir = _build_synthetic_dataset(tmpdir)

        for pol in ("none", "seed24_guard", "slip_guard"):
            output_dir = Path(tmpdir) / f"replay_{pol}"
            script_path = root / "scripts" / "learning" / "offline_replay_residual_policy.py"
            result = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--dataset-dir",
                    str(dataset_dir),
                    "--policy",
                    pol,
                    "--output-dir",
                    str(output_dir),
                ],
                capture_output=True,
                text=True,
                cwd=str(root),
                env={**os.environ, "PYTHONPATH": str(root)},
            )
            assert result.returncode == 0, f"Policy {pol} failed: {result.stderr}"
            assert (output_dir / "replay_summary.json").exists()

"""Integration test for train_bounded_residual_policy.py CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _project_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "rosclaw_darwin" / "learning" / "bounded_residual_policy.py").exists():
            return parent
    raise RuntimeError("Could not find project root")


def _make_frame(
    episode: int,
    step: int,
    phase: str = "GRASP",
    success: bool = True,
    object_z: float = 0.05,
    gripper_pos: float = 0.02,
    residual_target: list[float] | None = None,
) -> dict:
    if residual_target is None:
        residual_target = [0.0] * 7
    return {
        "episode": episode,
        "step": step,
        "task": "goal_pose",
        "object_name": "dex_cube",
        "seed": episode,
        "phase": phase,
        "observation": {
            "object_z": object_z,
            "gripper_pos": gripper_pos,
            "eef_z": 0.1,
            "orientation_error": 0.0,
            "object_eef_distance": 0.0,
            "object_eef_yaw_delta": 0.0,
        },
        "heuristic_action": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "executed_action": residual_target,
        "success_label": success,
        "failure_type": None if success else "object_not_lifted",
        "grip_quality_signal": {
            "low_object_z": object_z < 0.023,
            "gripper_too_open": gripper_pos > 0.035,
        },
        "slip_signal": None,
        "contact_signal": None,
        "residual_target": residual_target,
        "residual_mask": [True] * 7,
        "sample_weight": 1.0,
        "source_trace": f"seed_{episode:03d}/trace.jsonl",
    }


def test_train_bounded_residual_policy_cli(tmp_path: Path):
    root = _project_root()
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()

    frames = []
    # Success frames with zero residual.
    for ep in range(1, 11):
        frames.append(_make_frame(episode=ep, step=0, phase="GRASP", success=True, object_z=0.05, gripper_pos=0.02))
    # Failure frames with seed24-like residual.
    for ep in range(11, 21):
        frames.append(
            _make_frame(
                episode=ep,
                step=0,
                phase="GRASP",
                success=False,
                object_z=0.01,
                gripper_pos=0.04,
                residual_target=[0.0, 0.0, -0.003, 0.0, 0.0, 0.0, -0.03],
            )
        )

    with (dataset_dir / "frames.jsonl").open("w") as fh:
        for frame in frames:
            fh.write(json.dumps(frame) + "\n")

    def _write_split(name: str, episodes: list[int]) -> None:
        with (dataset_dir / f"split_{name}.json").open("w") as fh:
            json.dump({"episodes": episodes, "count": len(episodes)}, fh)

    _write_split("train", list(range(1, 17)))
    _write_split("val", [17, 18])
    _write_split("test", [19, 20])

    output_dir = tmp_path / "model"
    script = root / "scripts" / "learning" / "train_bounded_residual_policy.py"
    cmd = [
        sys.executable,
        str(script),
        "--input-dir",
        str(dataset_dir),
        "--output-dir",
        str(output_dir),
        "--model-type",
        "mlp",
        "--hidden-dim",
        "8",
        "--epochs",
        "30",
        "--random-seed",
        "42",
    ]
    env = {"PYTHONPATH": str(root)}
    result = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, env=env, check=False)
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

    assert (output_dir / "model.json").exists()
    assert (output_dir / "metrics.json").exists()

    metrics = json.loads((output_dir / "metrics.json").read_text())
    assert metrics["model_type"] == "mlp"
    assert "train" in metrics
    assert "test" in metrics
    assert 0 <= metrics["test"]["clamp_rate"] <= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

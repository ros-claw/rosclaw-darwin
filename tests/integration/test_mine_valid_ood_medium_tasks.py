"""Integration test for mine_valid_ood_medium_tasks.py CLI."""

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


def test_mine_valid_ood_medium_tasks_cli(tmp_path: Path):
    root = _project_root()
    summary = {
        "by_task_subtask_condition": {
            "cube_006__full__baseline_v3": {
                "task_id": "goal_pose_rosclaw_valid_cube_006",
                "subtask": "full",
                "condition": "baseline_v3",
                "count": 20,
                "success_rate": 0.55,
                "object_lifted_rate": 0.7,
                "grasp_reached_rate": 0.9,
                "slip_rate": 0.1,
                "reachability_failure_rate": 0.0,
                "gripper_aperture_limit_rate": 0.0,
                "first_failing_subtask": "yaw_90",
            },
            "cube_010__full__baseline_v3": {
                "task_id": "goal_pose_rosclaw_valid_cube_010",
                "subtask": "full",
                "condition": "baseline_v3",
                "count": 20,
                "success_rate": 0.95,
                "object_lifted_rate": 1.0,
                "grasp_reached_rate": 1.0,
                "slip_rate": 0.0,
                "reachability_failure_rate": 0.0,
                "gripper_aperture_limit_rate": 0.0,
                "first_failing_subtask": None,
            },
        }
    }
    summary_path = tmp_path / "aggregate_summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    out_dir = tmp_path / "mining"
    script = root / "scripts" / "diagnostics" / "mine_valid_ood_medium_tasks.py"
    cmd = [
        sys.executable,
        str(script),
        "--summary",
        str(summary_path),
        "--out-dir",
        str(out_dir),
    ]
    env = {"PYTHONPATH": str(root)}
    result = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, env=env, check=False)
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"

    assert (out_dir / "selected_tasks.yaml").exists()
    assert (out_dir / "rejected_tasks.yaml").exists()
    assert (out_dir / "difficulty_table.csv").exists()
    assert (out_dir / "mining_result.json").exists()

    result_data = json.loads((out_dir / "mining_result.json").read_text())
    selected_ids = {t["task_id"] for t in result_data["selected"]}
    rejected_ids = {t["task_id"] for t in result_data["rejected"]}
    assert "goal_pose_rosclaw_valid_cube_006" in selected_ids
    assert "goal_pose_rosclaw_valid_cube_010" in rejected_ids


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

#!/usr/bin/env python3
"""Run goal_pose subtask decomposition matrix."""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.evaluation.grasp_metrics import infer_grasp_stability
from rosclaw_darwin.tdl.loader import TaskLoader

_TASK_DIR = Path("configs/tasks")
_POLICY_PATH = "configs/policies/heuristic_servo_goal_pose.yaml"
_TRACE_PATH = Path("/tmp/rosclaw_data/traces/episode_trace.jsonl")


def _read_trace() -> list[dict]:
    if not _TRACE_PATH.exists():
        return []
    lines = _TRACE_PATH.read_text().strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _run_subtask(task_path: Path, out_dir: Path):
    import yaml

    if _TRACE_PATH.exists():
        _TRACE_PATH.unlink()

    task = TaskLoader().load(str(task_path))
    with open(_POLICY_PATH, "r", encoding="utf-8") as f:
        policy_config = yaml.safe_load(f) or {}
    policy_config.setdefault("policy_id", Path(_POLICY_PATH).stem)
    policy_config["skill_hints"] = [
        "orientation_aware_grasp",
        "two_stage_reorientation",
        "lower_lift_acceleration",
        "stabilize_lift",
        "longer_gripper_close",
    ]

    adapter = ArenaAdapter(task)
    result = adapter.run_policy(policy_config, episodes=1, max_steps=None)

    trace = _read_trace()
    stability = infer_grasp_stability(trace, lift_threshold=0.10, drop_threshold=0.05)

    # Task-aware success: object lifted above 0.2 and (if pose_reached) near target.
    task_eval = task.eval
    success_conditions = set(task_eval.success_conditions or [])
    object_z_values = [s.get("object_z") for s in trace if s.get("object_z") is not None]
    object_peak = max(object_z_values) if object_z_values else 0.0
    lifted = object_peak >= 0.2
    pose_ok = True
    if "pose_reached" in success_conditions:
        yaw_errors = [
            abs(s.get("object_yaw_error") or 0.0)
            for s in trace
            if s.get("object_yaw_error") is not None
        ]
        pose_ok = min(yaw_errors, default=1.0) < 0.2

    subtask_success = lifted and pose_ok

    summary = {
        "task_id": task.id,
        "arena_status": result.status,
        "subtask_success": subtask_success,
        "object_lifted": lifted,
        "object_peak": object_peak,
        "pose_ok": pose_ok,
        "grasp_stability": stability,
        "arena_metrics": result.metrics,
    }

    if trace:
        stamped = out_dir / f"trace_{task.id}_{int(time.time())}.jsonl"
        shutil.copy(_TRACE_PATH, stamped)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=Path("/tmp/rosclaw_data/subtasks"))
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    task_files = [
        "goal_pose_lift_only.yaml",
        "goal_pose_lift_hold.yaml",
        "goal_pose_lift_small_yaw.yaml",
        "goal_pose_lift_90_yaw.yaml",
        "goal_pose.yaml",
    ]
    results = []
    for fname in task_files:
        task_path = _TASK_DIR / fname
        if not task_path.exists():
            print(f"Missing {task_path}, skipping")
            continue
        print(f"\nRunning {fname} ...")
        result = _run_subtask(task_path, args.out_dir)
        results.append(result)
        print(json.dumps(result, indent=2, default=str))

    out_path = args.out_dir / f"subtask_decomposition_{int(time.time())}.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nSummary written to {out_path}")


if __name__ == "__main__":
    main()

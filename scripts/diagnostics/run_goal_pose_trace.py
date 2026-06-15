#!/usr/bin/env python3
"""Capture a single-episode per-step trace for goal_pose diagnostic analysis."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import yaml

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.tdl.loader import TaskLoader


def main() -> None:
    task_path = "configs/tasks/goal_pose.yaml"
    policy_path = "configs/policies/heuristic_servo_goal_pose.yaml"
    out_dir = Path("/tmp/rosclaw_data/traces")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Clear any stale trace so we know the file belongs to this run.
    trace_path = out_dir / "episode_trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    task = TaskLoader().load(task_path)
    with open(policy_path, "r", encoding="utf-8") as f:
        policy_config = yaml.safe_load(f) or {}
    policy_config.setdefault("policy_id", Path(policy_path).stem)

    # Manual grasp-stability v2 hints.
    policy_config["skill_hints"] = [
        "orientation_aware_grasp",
        "two_stage_reorientation",
        "lower_lift_acceleration",
        "stabilize_lift",
        "longer_gripper_close",
    ]

    adapter = ArenaAdapter(task)
    result = adapter.run_policy(policy_config, episodes=1, max_steps=None)
    print(json.dumps({
        "status": result.status,
        "metrics": result.metrics,
        "failure_types": result.failure_types,
        "run_id": result.run_id,
    }, indent=2, default=str))

    # The container writes to /workspace/data/traces/episode_trace.jsonl,
    # which is bind-mounted to /tmp/rosclaw_data/traces/episode_trace.jsonl.
    if trace_path.exists():
        stamped = out_dir / f"goal_pose_trace_{int(time.time())}.jsonl"
        shutil.copy(trace_path, stamped)
        print(f"Trace saved to {stamped}")
    else:
        print("No trace file produced.")


if __name__ == "__main__":
    main()

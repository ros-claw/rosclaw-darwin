#!/usr/bin/env python3
"""Run goal_pose physics ablation variants."""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

import yaml

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.evaluation.grasp_metrics import infer_grasp_stability
from rosclaw_darwin.tdl.loader import TaskLoader

_POLICY_PATH = "configs/policies/heuristic_servo_goal_pose.yaml"
_TRACE_PATH = Path("/tmp/rosclaw_data/traces/episode_trace.jsonl")


def _read_trace() -> list[dict]:
    if not _TRACE_PATH.exists():
        return []
    lines = _TRACE_PATH.read_text().strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _run_variant(task_path: Path, out_dir: Path):
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

    object_z_values = [s.get("object_z") for s in trace if s.get("object_z") is not None]
    object_peak = max(object_z_values) if object_z_values else 0.0
    yaw_errors = [
        abs(s.get("object_yaw_error") or 0.0)
        for s in trace
        if s.get("object_yaw_error") is not None
    ]
    summary = {
        "task_id": task.id,
        "physics_ablation": task.metadata.get("physics_ablation", {}),
        "arena_status": result.status,
        "object_lifted": object_peak >= 0.2,
        "object_peak": object_peak,
        "min_object_yaw_error": min(yaw_errors) if yaw_errors else None,
        "final_object_yaw_error": yaw_errors[-1] if yaw_errors else None,
        "grasp_stability": stability,
        "arena_metrics": result.metrics,
    }

    if trace:
        stamped = out_dir / f"trace_{task.id}_{int(time.time())}.jsonl"
        shutil.copy(_TRACE_PATH, stamped)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=Path("/tmp/rosclaw_data/physics_ablation"))
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    task_files = [
        "goal_pose.yaml",
        "goal_pose_high_friction.yaml",
        "goal_pose_small_cube.yaml",
        "goal_pose_light_cube.yaml",
    ]
    results = []
    for fname in task_files:
        task_path = Path("configs/tasks") / fname
        print(f"\nRunning {fname} ...")
        result = _run_variant(task_path, args.out_dir)
        results.append(result)
        print(json.dumps(result, indent=2, default=str))

    out_path = args.out_dir / f"physics_ablation_{int(time.time())}.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nSummary written to {out_path}")


if __name__ == "__main__":
    main()

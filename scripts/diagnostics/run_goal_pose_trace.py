#!/usr/bin/env python3
"""Capture a single-episode per-step trace for goal_pose diagnostic analysis.

Supports arbitrary policy configs and seeds so that multi-seed ablations can be
run reproducibly.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

import yaml

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.tdl.loader import TaskLoader

_DEFAULT_TASK = "configs/tasks/goal_pose.yaml"
_DEFAULT_POLICY = "configs/policies/heuristic_servo_goal_pose.yaml"
_DEFAULT_OUT_DIR = Path("/tmp/rosclaw_data/traces")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture a goal_pose episode trace")
    parser.add_argument("--task", default=_DEFAULT_TASK, help="Task config path")
    parser.add_argument("--policy", default=_DEFAULT_POLICY, help="Policy config path")
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR, help="Trace output directory")
    parser.add_argument("--seed", type=int, default=None, help="Random seed (optional)")
    parser.add_argument(
        "--embodiment",
        type=str,
        default=None,
        help="Override Arena embodiment (e.g., franka_ik, franka_ik_abs, franka_joint_pos).",
    )
    parser.add_argument(
        "--hints",
        nargs="*",
        default=None,
        help="Override skill hints (default: use policy file skill_hints)",
    )
    parser.add_argument(
        "--target-yaw",
        type=float,
        default=None,
        help="Override the environment's target yaw (radians) for orientation generalization diagnostics.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Each run gets its own trace directory to avoid racing on the shared
    # episode_trace.jsonl file when multiple Arena containers are launched.
    run_trace_dir = out_dir / "traces"
    run_trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = run_trace_dir / "episode_trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    task = TaskLoader().load(args.task)
    if args.seed is not None:
        task.mutation.seed = args.seed
    if args.embodiment is not None:
        task.metadata.setdefault("arena_env_args", {})
        task.metadata["arena_env_args"]["embodiment"] = args.embodiment

    with open(args.policy, "r", encoding="utf-8") as f:
        policy_config = yaml.safe_load(f) or {}
    policy_config.setdefault("policy_id", Path(args.policy).stem)
    if args.target_yaw is not None:
        policy_config.setdefault("policy_config_dict", {})
        policy_config["policy_config_dict"]["target_yaw_override"] = args.target_yaw

    # Default to the policy file's skill_hints unless overridden on CLI.
    if args.hints is not None:
        policy_config["skill_hints"] = args.hints

    adapter = ArenaAdapter(task)
    result = adapter.run_policy(
        policy_config,
        episodes=1,
        max_steps=None,
        trace_dir=run_trace_dir,
    )
    summary = {
        "status": result.status,
        "metrics": result.metrics,
        "failure_types": result.failure_types,
        "run_id": result.run_id,
    }
    print(json.dumps(summary, indent=2, default=str))
    # Also emit a single-line machine-readable summary so wrappers can parse
    # robustly without trying to reconstruct multi-line JSON from stdout.
    print(f"<<<ROSCLAW_SEED_SUMMARY>>>{json.dumps(summary, default=str)}<<<ROSCLAW_SEED_SUMMARY>>>")

    # The container writes episode_trace.jsonl into the per-run trace directory
    # that was bind-mounted to /workspace/data/traces.
    if trace_path.exists():
        policy_name = Path(args.policy).stem
        seed_tag = f"_seed{args.seed}" if args.seed is not None else ""
        stamped = out_dir / f"{policy_name}{seed_tag}_{int(time.time())}.jsonl"
        shutil.copy(trace_path, stamped)
        print(f"Trace saved to {stamped}")
    else:
        print("No trace file produced.")


if __name__ == "__main__":
    main()

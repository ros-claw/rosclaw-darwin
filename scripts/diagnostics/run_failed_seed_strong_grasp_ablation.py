#!/usr/bin/env python3
"""Re-run the seeds that failed in the 30-seed dex_cube matrix with a stronger grasp config.

The 30-seed randomized matrix identified two failure modes:
  - approach collision (seeds 7, 15, 28)
  - grasp slip after LIFT (seeds 2, 4, 9, 10, 11, 12, 13, 24, 29)

This script re-evaluates the slip seeds with
`configs/policies/heuristic_servo_goal_pose_v3_strong_grasp.yaml`, which uses a
longer squeeze, a tighter close threshold, and a stricter object-following check.
Approach-collision seeds are expected to be geometry/initial-pose issues and are
not the target of this ablation.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any

import yaml

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.tdl.loader import TaskLoader

_SLIP_SEEDS = [2, 4, 9, 10, 11, 12, 13, 24, 29]
_DEFAULT_TASK = "configs/tasks/goal_pose_dex_cube_official.yaml"
_DEFAULT_STRONG_POLICY = "configs/policies/heuristic_servo_goal_pose_v3_strong_grasp.yaml"
_DEFAULT_BASE_POLICY = "configs/policies/heuristic_servo_goal_pose_v3.yaml"
_DEFAULT_OUT_DIR = Path("/tmp/rosclaw_data/dex_cube_strong_grasp_ablation")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-run failed dex_cube seeds with strong-grasp policy"
    )
    parser.add_argument("--task", default=_DEFAULT_TASK)
    parser.add_argument("--strong-policy", default=_DEFAULT_STRONG_POLICY)
    parser.add_argument("--base-policy", default=_DEFAULT_BASE_POLICY)
    parser.add_argument("--seeds", type=int, nargs="+", default=_SLIP_SEEDS)
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    parser.add_argument(
        "--run-base",
        action="store_true",
        help="Also re-run the base v3 policy on the same seeds for a paired comparison.",
    )
    return parser.parse_args()


def _run_seed(
    task_path: str,
    policy_config: dict[str, Any],
    seed: int,
    out_dir: Path,
) -> dict[str, Any]:
    run_dir = out_dir / f"seed_{seed}"
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / "episode_trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    task = TaskLoader().load(task_path)
    task.mutation.seed = seed

    adapter = ArenaAdapter(task)
    result = adapter.run_policy(
        policy_config,
        episodes=1,
        max_steps=None,
        trace_dir=trace_dir,
    )

    if trace_path.exists():
        policy_name = policy_config.get("policy_id", "policy")
        stamped = run_dir / f"{policy_name}_seed{seed}_{int(time.time())}.jsonl"
        shutil.copy(trace_path, stamped)

    metrics = result.metrics or {}
    return {
        "seed": seed,
        "policy": policy_name,
        "status": result.status,
        "success_rate": metrics.get("success_rate"),
        "progress_mean": metrics.get("progress_mean"),
        "object_height_max_mean": metrics.get("object_height_max_mean"),
        "object_height_delta_mean": metrics.get("object_height_delta_mean"),
        "descend_exit_rate": metrics.get("descend_exit_rate"),
        "grasp_phase_reached_rate": metrics.get("grasp_phase_reached_rate"),
        "lift_phase_reached_rate": metrics.get("lift_phase_reached_rate"),
        "run_id": result.run_id,
    }


def _load_policy(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("policy_id", Path(path).stem)
    return cfg


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    strong_policy = _load_policy(args.strong_policy)
    base_policy = _load_policy(args.base_policy)

    rows: list[dict[str, Any]] = []
    for seed in args.seeds:
        print(f"\n=== seed {seed} strong_grasp ===")
        row = _run_seed(args.task, strong_policy, seed, args.out_dir)
        rows.append(row)
        print(json.dumps(row, indent=2, default=str))

        if args.run_base:
            print(f"=== seed {seed} base ===")
            base_row = _run_seed(args.task, base_policy, seed, args.out_dir / "base_baseline")
            rows.append(base_row)
            print(json.dumps(base_row, indent=2, default=str))

    summary = {
        "seeds": args.seeds,
        "task": args.task,
        "strong_policy": args.strong_policy,
        "base_policy": args.base_policy,
        "run_base": args.run_base,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "strong_success_count": sum(
            1 for r in rows if r["policy"].endswith("strong_grasp") and r.get("success_rate") == 1.0
        ),
        "strong_lifted_count": sum(
            1 for r in rows if r["policy"].endswith("strong_grasp") and (r.get("object_height_delta_mean") or 0) > 0.02
        ),
        "rows": rows,
    }

    summary_path = args.out_dir / "strong_grasp_ablation_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print("\n=== summary ===")
    print(json.dumps(summary, indent=2, default=str))
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()

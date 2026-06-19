#!/usr/bin/env python3
"""Generalization test for the franka_ik_abs goal_pose policy.

Runs the policy across a matrix of target orientations and object variants.
Each condition is executed sequentially with a private trace directory so that
Docker containers do not race on ``episode_trace.jsonl`` or GPU resources.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import yaml

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.tdl.loader import TaskLoader

_DEFAULT_TASK = "configs/tasks/goal_pose.yaml"
_DEFAULT_POLICY = "configs/policies/heuristic_servo_goal_pose_abs.yaml"
_DEFAULT_OUT_DIR = Path("/tmp/rosclaw_data/goal_pose_generalization")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generalization test for franka_ik_abs goal_pose policy"
    )
    parser.add_argument("--task", default=_DEFAULT_TASK, help="Base task config path")
    parser.add_argument("--policy", default=_DEFAULT_POLICY, help="Base policy config path")
    parser.add_argument(
        "--embodiment",
        default="franka_ik_abs",
        help="Arena embodiment override (default: franka_ik_abs).",
    )
    parser.add_argument(
        "--seeds",
        type=int,
        default=1,
        help="Number of seeds to run per condition.",
    )
    parser.add_argument(
        "--orientations",
        nargs="+",
        type=float,
        default=[0.0, 45.0, 90.0, 135.0, 180.0],
        help="Target yaw orientations in degrees.",
    )
    parser.add_argument(
        "--objects",
        nargs="+",
        default=["dex_cube", "procedural_cube"],
        help="Arena object variants to test.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_DEFAULT_OUT_DIR,
        help="Output directory for traces and summaries.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Kill any running rosclaw-darwin:arena-base containers before starting.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the conditions that would run without executing them.",
    )
    return parser.parse_args()


def _yaw_quaternion(yaw_deg: float) -> list[float]:
    """Return a quaternion [x, y, z, w] for a pure z-axis rotation."""
    half = math.radians(yaw_deg) / 2.0
    return [0.0, 0.0, math.sin(half), math.cos(half)]


def _cleanup_arena_containers(image: str = "rosclaw-darwin:arena-base") -> int:
    """Kill any running containers based on the Arena image."""
    try:
        result = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"ancestor={image}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print("docker not found; skipping cleanup.", file=sys.stderr)
        return 0
    container_ids = [c for c in result.stdout.strip().splitlines() if c]
    if not container_ids:
        return 0
    print(f"Killing {len(container_ids)} lingering Arena container(s)...", file=sys.stderr)
    killed = 0
    for cid in container_ids:
        kill_result = subprocess.run(
            ["docker", "kill", cid],
            capture_output=True,
            text=True,
            check=False,
        )
        if kill_result.returncode == 0:
            killed += 1
        else:
            print(f"Failed to kill {cid}: {kill_result.stderr.strip()}", file=sys.stderr)
    return killed


def _run_condition(
    task: object,
    policy_config: dict,
    obj: str,
    yaw_deg: float,
    seed: int,
    args: argparse.Namespace,
) -> dict:
    """Run a single (object, orientation, seed) condition and return a summary."""
    cond_dir = args.out_dir / f"object_{obj}" / f"yaw_{yaw_deg:.0f}" / f"seed_{seed}"
    cond_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = cond_dir / "traces"

    task_copy = copy.deepcopy(task)
    task_copy.mutation.seed = seed
    task_copy.metadata.setdefault("arena_env_args", {})
    task_copy.metadata["arena_env_args"]["embodiment"] = args.embodiment
    task_copy.metadata["arena_env_args"]["object"] = obj

    policy = copy.deepcopy(policy_config)
    policy["policy_config_dict"]["fixed_target_quat"] = _yaw_quaternion(yaw_deg)

    if args.dry_run:
        print(f"Would run: object={obj} yaw={yaw_deg} seed={seed}")
        return {
            "object": obj,
            "yaw_deg": yaw_deg,
            "seed": seed,
            "status": "dry_run",
            "metrics": {},
            "failure_types": {},
        }

    print(f"\n=== object={obj} yaw={yaw_deg}° seed={seed} ===")
    started_at = time.time()
    adapter = ArenaAdapter(task_copy)
    result = adapter.run_policy(
        policy,
        episodes=1,
        max_steps=None,
        trace_dir=trace_dir,
    )
    elapsed = time.time() - started_at

    summary = {
        "object": obj,
        "yaw_deg": yaw_deg,
        "seed": seed,
        "status": result.status,
        "metrics": result.metrics,
        "failure_types": result.failure_types,
        "elapsed_seconds": round(elapsed, 2),
    }
    (cond_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, default=str))
    return summary


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.cleanup:
        _cleanup_arena_containers()

    task = TaskLoader().load(args.task)
    with open(args.policy, "r", encoding="utf-8") as f:
        policy_config = yaml.safe_load(f) or {}
    policy_config.setdefault("policy_id", Path(args.policy).stem)

    if args.dry_run:
        print("Dry-run conditions:")

    results: list[dict] = []
    for obj in args.objects:
        for yaw_deg in args.orientations:
            for seed in range(args.seeds):
                summary = _run_condition(task, policy_config, obj, yaw_deg, seed, args)
                results.append(summary)

    if args.dry_run:
        return 0

    # Aggregate by (object, orientation).
    aggregate: dict[tuple[str, float], dict] = {}
    for r in results:
        key = (r["object"], r["yaw_deg"])
        agg = aggregate.setdefault(
            key,
            {
                "object": r["object"],
                "yaw_deg": r["yaw_deg"],
                "runs": 0,
                "successes": 0,
                "progress_values": [],
                "statuses": [],
            },
        )
        agg["runs"] += 1
        success_rate = r.get("metrics", {}).get("success_rate")
        if success_rate is not None and float(success_rate) >= 1.0:
            agg["successes"] += 1
        progress = r.get("metrics", {}).get("progress")
        if progress is not None:
            agg["progress_values"].append(float(progress))
        agg["statuses"].append(r.get("status"))

    aggregate_list = []
    for key in sorted(aggregate):
        agg = aggregate[key]
        progress_values = agg.pop("progress_values")
        agg["success_rate"] = round(agg["successes"] / agg["runs"], 4) if agg["runs"] else 0.0
        agg["progress_mean"] = round(sum(progress_values) / len(progress_values), 4) if progress_values else None
        aggregate_list.append(agg)

    final_output = {
        "args": {
            "task": args.task,
            "policy": args.policy,
            "embodiment": args.embodiment,
            "seeds": args.seeds,
            "orientations": args.orientations,
            "objects": args.objects,
            "out_dir": str(args.out_dir),
        },
        "per_run": results,
        "by_condition": aggregate_list,
    }

    aggregate_path = args.out_dir / f"generalization_{time.strftime('%Y-%m-%d_%H%M%S')}.json"
    aggregate_path.write_text(json.dumps(final_output, indent=2, default=str), encoding="utf-8")
    print(f"\nAggregate summary written to {aggregate_path}")

    csv_path = args.out_dir / f"generalization_{time.strftime('%Y-%m-%d_%H%M%S')}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["object", "yaw_deg", "success_rate", "progress_mean", "runs", "statuses"])
        for agg in aggregate_list:
            writer.writerow([
                agg["object"],
                agg["yaw_deg"],
                agg["success_rate"],
                agg["progress_mean"],
                agg["runs"],
                ",".join(agg["statuses"]),
            ])
    print(f"Per-condition CSV written to {csv_path}")

    total_runs = len(results)
    total_successes = sum(
        1 for r in results
        if r.get("metrics", {}).get("success_rate") is not None
        and float(r["metrics"]["success_rate"]) >= 1.0
    )
    print(f"\n=== RESULT: {total_successes}/{total_runs} runs succeeded ===")
    return 0 if total_successes == total_runs else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Arena residual policy pilot runner (Sprint 5 v1.9).

Runs bounded residual policies in Arena for two scenarios:
  1. seed24_guard: seed 24 (20 repeats) + 0:99 regression.
  2. slip_guard: target_yaws [1.5708, 2.0944] with seeds 0:19.

Does NOT start Docker jobs itself; it generates the run matrix and can be
invoked by the user once the background 0:99 rerun finishes.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.tdl.loader import TaskLoader

_DEFAULT_TASK = "configs/tasks/goal_pose_dex_cube_official.yaml"
_DEFAULT_SEED24_POLICY = "configs/policies/heuristic_servo_goal_pose_v3_residual_seed24_guard.yaml"
_DEFAULT_SLIP_POLICY = "configs/policies/heuristic_servo_goal_pose_v3_residual_slip_guard.yaml"
_DEFAULT_OUT_DIR = Path("data_v19/ablations/residual_policy_pilot")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Arena residual policy pilot")
    parser.add_argument("--policy", choices=["seed24_guard", "slip_guard"], required=True)
    parser.add_argument("--seeds", type=str, default=None,
                        help="Comma-separated seeds (default: 24 for seed24_guard, 0-19 for slip_guard)")
    parser.add_argument("--task", default=_DEFAULT_TASK)
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    parser.add_argument("--repeat", type=int, default=20,
                        help="Repeat count for deterministic seed24")
    parser.add_argument("--target-yaws", type=str, default="1.5708,2.0944",
                        help="Target yaws for slip_guard (comma-separated radians)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the run matrix without executing")
    parser.add_argument("--cleanup", action="store_true", default=True)
    parser.add_argument("--no-cleanup", action="store_true", default=False)
    return parser.parse_args()


def _cleanup_arena_containers(image: str = "rosclaw-darwin:arena-base") -> int:
    try:
        result = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"ancestor={image}"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return 0
    container_ids = [c for c in result.stdout.strip().splitlines() if c]
    if not container_ids:
        return 0
    killed = 0
    for cid in container_ids:
        kill_result = subprocess.run(
            ["docker", "kill", cid], capture_output=True, text=True, check=False
        )
        if kill_result.returncode == 0:
            killed += 1
    return killed


def _load_policy_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _run_seed(
    task_path: str,
    policy_config: dict[str, Any],
    seed: int,
    out_dir: Path,
    cleanup: bool,
) -> dict[str, Any]:
    """Run a single seed and return aggregate metrics."""
    if cleanup:
        _cleanup_arena_containers()

    task = TaskLoader().load(task_path)
    adapter = ArenaAdapter(task, mode="docker")

    policy_dict = {
        "type": policy_config["type"],
        "policy_id": policy_config["policy_id"],
        "policy_config_dict": policy_config.get("policy_config_dict", {}),
    }

    result = adapter.run_policy(policy_dict, episodes=1, seed=seed)

    # Read trace if available.
    trace_path = out_dir / f"seed_{seed}" / "episode_trace.jsonl"
    trace_records: list[dict[str, Any]] = []
    if trace_path.exists():
        with trace_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        trace_records.append(json.loads(line))
                    except Exception:
                        pass

    # Extract residual trigger stats from trace.
    residual_trigger_count = sum(
        1 for r in trace_records if r.get("residual_enabled") and r.get("residual_confidence", 0.0) > 0.0
    )
    residual_trigger_steps = [
        r.get("step") for r in trace_records
        if r.get("residual_enabled") and r.get("residual_confidence", 0.0) > 0.0
    ]

    return {
        "seed": seed,
        "status": result.status,
        "success_rate": result.metrics.get("success_rate", 0.0),
        "object_lifted": result.metrics.get("object_lifted", False),
        "object_oriented": result.metrics.get("object_oriented", False),
        "residual_trigger_count": residual_trigger_count,
        "residual_trigger_steps": residual_trigger_steps,
        "trace_length": len(trace_records),
        "stderr_path": str(result.stderr_path) if result.stderr_path else None,
        "stdout_path": str(result.stdout_path) if result.stdout_path else None,
    }


def _run_seed24_guard(
    task_path: str,
    policy_config: dict[str, Any],
    seeds: list[int],
    out_dir: Path,
    repeat: int,
    cleanup: bool,
) -> dict[str, Any]:
    """Run seed24_guard: 20 repeats on seed 24, plus 0:99 regression."""
    out_dir.mkdir(parents=True, exist_ok=True)
    per_seed_results: list[dict[str, Any]] = []

    for seed in seeds:
        seed_out = out_dir / f"seed_{seed}"
        seed_out.mkdir(parents=True, exist_ok=True)
        for rep in range(repeat if seed == 24 else 1):
            rep_out = seed_out / f"repeat_{rep}"
            rep_out.mkdir(parents=True, exist_ok=True)
            result = _run_seed(task_path, policy_config, seed, rep_out, cleanup)
            result["repeat"] = rep
            per_seed_results.append(result)

    successes = sum(1 for r in per_seed_results if r["success_rate"] >= 1.0)
    lifted = sum(1 for r in per_seed_results if r["object_lifted"])
    oriented = sum(1 for r in per_seed_results if r["object_oriented"])
    total = len(per_seed_results)

    # Compute normal-seed trigger rate (excluding seed 24).
    normal_triggers = sum(
        r["residual_trigger_count"] for r in per_seed_results if r["seed"] != 24
    )
    normal_trace_lengths = sum(
        r["trace_length"] for r in per_seed_results if r["seed"] != 24
    )
    normal_trigger_rate = normal_triggers / max(1, normal_trace_lengths)

    seed24_results = [r for r in per_seed_results if r["seed"] == 24]
    seed24_successes = sum(1 for r in seed24_results if r["success_rate"] >= 1.0)
    seed24_trigger_count = sum(r["residual_trigger_count"] for r in seed24_results)

    summary = {
        "policy": "seed24_guard",
        "total_runs": total,
        "successes": successes,
        "success_rate": round(successes / total, 4) if total else 0.0,
        "object_lifted_rate": round(lifted / total, 4) if total else 0.0,
        "object_oriented_rate": round(oriented / total, 4) if total else 0.0,
        "seed24_success_rate": round(seed24_successes / len(seed24_results), 4) if seed24_results else 0.0,
        "seed24_trigger_count": seed24_trigger_count,
        "normal_trigger_rate": round(normal_trigger_rate, 4),
        "per_seed_results": per_seed_results,
    }

    with (out_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with (out_dir / "per_seed_results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "seed", "repeat", "status", "success_rate", "object_lifted",
                "object_oriented", "residual_trigger_count", "trace_length",
            ],
        )
        writer.writeheader()
        for r in per_seed_results:
            writer.writerow({
                "seed": r["seed"],
                "repeat": r.get("repeat", 0),
                "status": r["status"],
                "success_rate": r["success_rate"],
                "object_lifted": r["object_lifted"],
                "object_oriented": r["object_oriented"],
                "residual_trigger_count": r["residual_trigger_count"],
                "trace_length": r["trace_length"],
            })

    return summary


def _run_slip_guard(
    task_path: str,
    policy_config: dict[str, Any],
    seeds: list[int],
    target_yaws: list[float],
    out_dir: Path,
    cleanup: bool,
) -> dict[str, Any]:
    """Run slip_guard: target_yaws x seeds 0:19."""
    out_dir.mkdir(parents=True, exist_ok=True)
    per_seed_results: list[dict[str, Any]] = []

    for yaw in target_yaws:
        yaw_out = out_dir / f"yaw_{yaw:.4f}"
        yaw_out.mkdir(parents=True, exist_ok=True)
        for seed in seeds:
            seed_out = yaw_out / f"seed_{seed}"
            seed_out.mkdir(parents=True, exist_ok=True)
            # Inject target_yaw_override into policy config for this run.
            policy_config_copy = dict(policy_config)
            pcd = dict(policy_config_copy.get("policy_config_dict", {}))
            pcd["target_yaw_override"] = yaw
            policy_config_copy["policy_config_dict"] = pcd
            result = _run_seed(task_path, policy_config_copy, seed, seed_out, cleanup)
            result["target_yaw"] = yaw
            per_seed_results.append(result)

    successes = sum(1 for r in per_seed_results if r["success_rate"] >= 1.0)
    lifted = sum(1 for r in per_seed_results if r["object_lifted"])
    oriented = sum(1 for r in per_seed_results if r["object_oriented"])
    total = len(per_seed_results)

    trigger_count = sum(r["residual_trigger_count"] for r in per_seed_results)
    trace_lengths = sum(r["trace_length"] for r in per_seed_results)
    trigger_rate = trigger_count / max(1, trace_lengths)

    # Per-yaw aggregates.
    yaw_summaries: dict[str, dict[str, Any]] = {}
    for yaw in target_yaws:
        yaw_results = [r for r in per_seed_results if r.get("target_yaw") == yaw]
        yaw_successes = sum(1 for r in yaw_results if r["success_rate"] >= 1.0)
        yaw_oriented = sum(1 for r in yaw_results if r["object_oriented"])
        yaw_summaries[str(yaw)] = {
            "success_rate": round(yaw_successes / len(yaw_results), 4) if yaw_results else 0.0,
            "orientation_achieved_rate": round(yaw_oriented / len(yaw_results), 4) if yaw_results else 0.0,
            "lifted_rate": round(sum(1 for r in yaw_results if r["object_lifted"]) / len(yaw_results), 4) if yaw_results else 0.0,
        }

    summary = {
        "policy": "slip_guard",
        "target_yaws": target_yaws,
        "total_runs": total,
        "successes": successes,
        "success_rate": round(successes / total, 4) if total else 0.0,
        "object_lifted_rate": round(lifted / total, 4) if total else 0.0,
        "object_oriented_rate": round(oriented / total, 4) if total else 0.0,
        "trigger_rate": round(trigger_rate, 4),
        "per_yaw_summary": yaw_summaries,
        "per_seed_results": per_seed_results,
    }

    with (out_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with (out_dir / "per_seed_results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "target_yaw", "seed", "status", "success_rate", "object_lifted",
                "object_oriented", "residual_trigger_count", "trace_length",
            ],
        )
        writer.writeheader()
        for r in per_seed_results:
            writer.writerow({
                "target_yaw": r.get("target_yaw", ""),
                "seed": r["seed"],
                "status": r["status"],
                "success_rate": r["success_rate"],
                "object_lifted": r["object_lifted"],
                "object_oriented": r["object_oriented"],
                "residual_trigger_count": r["residual_trigger_count"],
                "trace_length": r["trace_length"],
            })

    return summary


def main() -> int:
    args = parse_args()
    cleanup = args.cleanup and not args.no_cleanup

    task_path = args.task
    out_dir = args.out_dir / args.policy

    if args.policy == "seed24_guard":
        policy_config = _load_policy_config(_DEFAULT_SEED24_POLICY)
        seeds = [int(s) for s in args.seeds.split(",")] if args.seeds else [24] + list(range(100))
        if args.dry_run:
            print(f"[DRY RUN] seed24_guard: seeds={seeds}, repeat={args.repeat}")
            return 0
        summary = _run_seed24_guard(task_path, policy_config, seeds, out_dir, args.repeat, cleanup)
    else:
        policy_config = _load_policy_config(_DEFAULT_SLIP_POLICY)
        seeds = [int(s) for s in args.seeds.split(",")] if args.seeds else list(range(20))
        target_yaws = [float(y) for y in args.target_yaws.split(",")]
        if args.dry_run:
            print(f"[DRY RUN] slip_guard: seeds={seeds}, target_yaws={target_yaws}")
            return 0
        summary = _run_slip_guard(task_path, policy_config, seeds, target_yaws, out_dir, cleanup)

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

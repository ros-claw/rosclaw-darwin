#!/usr/bin/env python3
"""Seed 24 slip-fix ablation runner.

Runs a set of policy-config variations against the deterministic seed 24 failure
and reports which interventions restore success without overfitting.  The runner
is intentionally parameter-driven: it only overrides YAML policy parameters, so
no new state-machine code is required for the first screening pass.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.evaluation.slip_forensics import summarize_trace_for_forensics
from rosclaw_darwin.tdl.loader import TaskLoader

_DEFAULT_TASK = "configs/tasks/goal_pose_dex_cube_official.yaml"
_DEFAULT_POLICY = "configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml"
_DEFAULT_OUT_DIR = Path("data_v18/ablations/seed24_slip_fix")


# Parameter overrides for each ablation condition.  These are chosen to test the
# grasp-geometry hypotheses from the Sprint 1 forensics report.
CONDITION_OVERRIDES: dict[str, dict[str, Any]] = {
    "baseline": {},
    "tight_grasp_z_tolerance": {"grasp_z_tolerance": 0.001},
    "raise_grasp_target_z": {"grasp_offset_z": 0.015},
    "lower_grasp_target_z": {"grasp_offset_z": -0.010},
    "enable_pre_grasp_orient": {
        "pre_grasp_orient": True,
        "grasp_target_yaw_offset": 0.0,
    },
    "pre_grasp_yaw_align_v2": {
        "pre_grasp_yaw_align_v2": True,
        "grasp_target_yaw_offset": 0.0,
    },
    "grasp_verify_and_retry": {
        "enable_regrasp": True,
        "structural_regrasp": True,
        "max_regrasp_attempts": 2,
        "verify_lift_response_steps": 5,
        "min_lift_response_z": 0.01,
        "regrasp_xy_offsets": [[0.0, 0.01], [0.0, -0.01]],
    },
    "enable_pre_grasp_orient_v2": {
        "pre_grasp_orient": True,
        "grasp_target_yaw_offset": 0.0,
        "pre_grasp_orient_max_steps": 60,
    },
    "enable_pre_grasp_orient_v3": {
        "pre_grasp_orient": True,
        "grasp_target_yaw_offset": 0.0,
        "pre_grasp_orient_max_steps": 60,
    },
    "best_combined_v2": {
        "grasp_z_tolerance": 0.001,
        "grasp_offset_z": 0.015,
        "pre_grasp_orient": True,
        "grasp_target_yaw_offset": 0.0,
        "pre_grasp_orient_max_steps": 60,
    },
    "align_yaw_during_approach": {
        "align_yaw_during_approach": True,
        "approach_yaw_offset": 0.0,
        "pre_grasp_orient": False,
    },
    "align_yaw_during_approach_plus_pre_grasp": {
        "align_yaw_during_approach": True,
        "approach_yaw_offset": 0.0,
        "pre_grasp_orient": True,
        "grasp_target_yaw_offset": 0.0,
        "pre_grasp_orient_max_steps": 60,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed 24 slip-fix ablation")
    parser.add_argument("--task", default=_DEFAULT_TASK)
    parser.add_argument("--base-policy", default=_DEFAULT_POLICY)
    parser.add_argument("--seed", type=int, default=24)
    parser.add_argument("--repeat", type=int, default=10)
    parser.add_argument(
        "--conditions",
        type=str,
        default="baseline,tight_grasp_z_tolerance,raise_grasp_target_z,lower_grasp_target_z,enable_pre_grasp_orient,pre_grasp_yaw_align_v2,grasp_verify_and_retry,best_combined",
        help="Comma-separated list of conditions to run.",
    )
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    parser.add_argument("--cleanup", action="store_true", default=True)
    parser.add_argument("--no-cleanup", action="store_true", default=False)
    return parser.parse_args()


def _cleanup_arena_containers(image: str = "rosclaw-darwin:arena-base") -> int:
    try:
        result = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"ancestor={image}"],
            capture_output=True,
            text=True,
            check=False,
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


def _load_trace(trace_path: Path) -> list[dict[str, Any]]:
    if not trace_path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with trace_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        pass
    return records


def _run_repeat(
    task_path: str,
    policy_config: dict[str, Any],
    seed: int,
    condition: str,
    repeat_idx: int,
    out_dir: Path,
    cleanup: bool = False,
) -> dict[str, Any]:
    if cleanup:
        _cleanup_arena_containers()

    run_dir = out_dir / f"{condition}" / f"repeat{repeat_idx:02d}"
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

    trace = _load_trace(trace_path)
    metrics = result.metrics or {}
    env_success = metrics.get("success_rate") == 1.0
    forensics = (
        summarize_trace_for_forensics(trace, env_success=env_success)
        if trace
        else {"category": "unknown"}
    )

    if trace_path.exists():
        shutil.copy(trace_path, run_dir / "trace.jsonl")

    return {
        "condition": condition,
        "repeat": repeat_idx,
        "seed": seed,
        "status": result.status,
        "env_success_rate": metrics.get("success_rate"),
        "env_progress_mean": metrics.get("progress_mean"),
        "category": forensics.get("category", "unknown"),
        "max_object_z": forensics.get("max_object_z"),
        "final_object_z": forensics.get("final_object_z"),
        "drop_step": forensics.get("drop_step"),
        "gripper_pos_min_while_lifted": forensics.get("gripper_pos_min_while_lifted"),
        "gripper_blocked": forensics.get("gripper_blocked"),
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_condition: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_condition.setdefault(r["condition"], []).append(r)

    summaries: dict[str, Any] = {}
    for condition, reps in by_condition.items():
        valid = [r for r in reps if not str(r.get("status", "")).startswith("error")]
        successes = [r for r in valid if r.get("env_success_rate") == 1.0]
        categories: dict[str, int] = {}
        for r in valid:
            cat = r.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1

        def _mean(key: str) -> float | None:
            vals = [r[key] for r in valid if r.get(key) is not None]
            return sum(vals) / len(vals) if vals else None

        summaries[condition] = {
            "total_repeats": len(reps),
            "valid_repeats": len(valid),
            "success_repeats": len(successes),
            "success_rate": len(successes) / len(valid) if valid else 0.0,
            "category_counts": categories,
            "mean_max_object_z": _mean("max_object_z"),
            "mean_final_object_z": _mean("final_object_z"),
            "mean_drop_step": _mean("drop_step"),
            "mean_gripper_pos_min_while_lifted": _mean("gripper_pos_min_while_lifted"),
            "gripper_blocked_count": sum(1 for r in valid if r.get("gripper_blocked")),
        }

    return summaries


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for k in row.keys():
            if k not in seen:
                seen.add(k)
                keys.append(k)
    with path.open("w", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in keys})


def main() -> None:
    args = parse_args()
    out_dir: Path = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    cleanup = args.cleanup and not args.no_cleanup

    with open(args.base_policy, "r", encoding="utf-8") as f:
        base_config = yaml.safe_load(f) or {}
    base_config.setdefault("policy_id", Path(args.base_policy).stem)
    base_config["policy_source"] = args.base_policy

    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    unknown = [c for c in conditions if c not in CONDITION_OVERRIDES]
    if unknown:
        print(f"Unknown conditions: {unknown}", file=sys.stderr)
        sys.exit(1)

    rows: list[dict[str, Any]] = []
    for condition in conditions:
        overrides = CONDITION_OVERRIDES[condition]
        policy_config = json.loads(json.dumps(base_config))
        policy_config["policy_id"] = f"{base_config.get('policy_id', 'base')}_{condition}"
        policy_config.setdefault("policy_config_dict", {}).update(overrides)

        for i in range(args.repeat):
            print(
                f"\n=== condition={condition} repeat {i + 1}/{args.repeat} ===",
                file=sys.stderr,
            )
            try:
                row = _run_repeat(
                    args.task,
                    policy_config,
                    args.seed,
                    condition,
                    i,
                    out_dir,
                    cleanup=cleanup,
                )
            except Exception as exc:
                row = {
                    "condition": condition,
                    "repeat": i,
                    "seed": args.seed,
                    "status": f"error: {exc}",
                    "category": "error",
                }
            rows.append(row)
            print(json.dumps(row, indent=2, default=str))

    aggregate = _aggregate(rows)
    summary = {
        "target_seed": args.seed,
        "task": args.task,
        "base_policy": args.base_policy,
        "conditions": conditions,
        "repeats_per_condition": args.repeat,
        "per_condition": aggregate,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    csv_path = out_dir / "per_repeat_results.csv"
    json_path = out_dir / "aggregate_summary.json"
    _write_csv(rows, csv_path)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print("\n=== aggregate summary ===")
    print(json.dumps(summary, indent=2, default=str))
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")


if __name__ == "__main__":
    main()

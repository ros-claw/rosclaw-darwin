#!/usr/bin/env python3
"""Seed 24 conditional micro-recovery ablation runner.

Compares the promoted baseline against the grip-quality-triggered micro-recovery
policy on the deterministic seed-24 failure.  The candidate policy is loaded from
``heuristic_servo_goal_pose_v3_seed24_micro_recovery.yaml`` and only its recovery
strategy is varied across conditions.
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
from rosclaw_darwin.tdl.loader import TaskLoader

_DEFAULT_TASK = "configs/tasks/goal_pose_dex_cube_official.yaml"
_DEFAULT_BASE_POLICY = "configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml"
_DEFAULT_CANDIDATE_POLICY = "configs/policies/heuristic_servo_goal_pose_v3_seed24_micro_recovery.yaml"
_DEFAULT_OUT_DIR = Path("data_v19/ablations/seed24_micro_recovery")


CONDITION_STRATEGIES: dict[str, str | None] = {
    "baseline": None,
    "lower_reclose": "lower_reclose",
    "z_adjust": "z_adjust",
    "grip_verify": "grip_verify",
    "best_combined": "lower_reclose",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed 24 micro-recovery ablation")
    parser.add_argument("--task", default=_DEFAULT_TASK)
    parser.add_argument("--base-policy", default=_DEFAULT_BASE_POLICY)
    parser.add_argument("--candidate-policy", default=_DEFAULT_CANDIDATE_POLICY)
    parser.add_argument("--seed", type=int, default=24)
    parser.add_argument("--repeat", type=int, default=20)
    parser.add_argument(
        "--conditions",
        type=str,
        default="baseline,lower_reclose,z_adjust,grip_verify,best_combined",
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


def _policy_config_from_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("policy_id", Path(path).stem)
    cfg["policy_source"] = path
    return cfg


def _build_policy_config(
    base_config: dict[str, Any],
    candidate_config: dict[str, Any],
    condition: str,
) -> dict[str, Any]:
    if condition == "baseline":
        return json.loads(json.dumps(base_config))
    policy_config = json.loads(json.dumps(candidate_config))
    strategy = CONDITION_STRATEGIES.get(condition)
    if strategy is not None:
        policy_config.setdefault("policy_config_dict", {})["micro_recovery_strategy"] = strategy
    policy_config["policy_id"] = f"{candidate_config.get('policy_id', 'candidate')}_{condition}"
    return policy_config


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

    run_dir = out_dir / condition / f"repeat{repeat_idx:02d}"
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
    grip_quality_trigger = any(
        bool(r.get("grip_quality_trigger")) for r in trace
    )
    micro_recovery_triggered = any(
        bool(r.get("micro_recovery_triggered")) for r in trace
    )
    max_grip_quality_score = (
        max(
            (r.get("grip_quality_score") for r in trace if r.get("grip_quality_score") is not None),
            default=None,
        )
    )
    min_grip_quality_score = (
        min(
            (r.get("grip_quality_score") for r in trace if r.get("grip_quality_score") is not None),
            default=None,
        )
    )

    if trace_path.exists():
        shutil.copy(trace_path, run_dir / "trace.jsonl")

    metrics = result.metrics or {}
    return {
        "condition": condition,
        "repeat": repeat_idx,
        "seed": seed,
        "status": result.status,
        "env_success_rate": metrics.get("success_rate"),
        "env_progress_mean": metrics.get("progress_mean"),
        "grip_quality_trigger": grip_quality_trigger,
        "micro_recovery_triggered": micro_recovery_triggered,
        "max_grip_quality_score": max_grip_quality_score,
        "min_grip_quality_score": min_grip_quality_score,
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_condition: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_condition.setdefault(r["condition"], []).append(r)

    summaries: dict[str, Any] = {}
    for condition, reps in by_condition.items():
        valid = [r for r in reps if not str(r.get("status", "")).startswith("error")]
        successes = [r for r in valid if r.get("env_success_rate") == 1.0]
        trigger_count = sum(1 for r in valid if r.get("micro_recovery_triggered"))
        summaries[condition] = {
            "total_repeats": len(reps),
            "valid_repeats": len(valid),
            "success_repeats": len(successes),
            "success_rate": len(successes) / len(valid) if valid else 0.0,
            "trigger_count": trigger_count,
            "trigger_rate": trigger_count / len(valid) if valid else 0.0,
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

    base_config = _policy_config_from_yaml(args.base_policy)
    candidate_config = _policy_config_from_yaml(args.candidate_policy)

    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    unknown = [c for c in conditions if c not in CONDITION_STRATEGIES]
    if unknown:
        print(f"Unknown conditions: {unknown}", file=sys.stderr)
        sys.exit(1)

    rows: list[dict[str, Any]] = []
    for condition in conditions:
        policy_config = _build_policy_config(base_config, candidate_config, condition)
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
                }
            rows.append(row)
            print(json.dumps(row, indent=2, default=str))

    aggregate = _aggregate(rows)
    summary = {
        "target_seed": args.seed,
        "task": args.task,
        "base_policy": args.base_policy,
        "candidate_policy": args.candidate_policy,
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

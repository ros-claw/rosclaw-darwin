#!/usr/bin/env python3
"""Trigger audit for the seed-24 conditional micro-recovery policy.

Runs the micro-recovery candidate on the official 0:99 distribution and reports
how often the grip-quality monitor triggers.  The goal is to keep the trigger
rate on normal seeds below the 5% gate threshold.
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
_DEFAULT_POLICY = "configs/policies/heuristic_servo_goal_pose_v3_seed24_micro_recovery.yaml"
_DEFAULT_OUT_DIR = Path("data_v19/diagnostics/micro_recovery_trigger_audit")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Micro-recovery trigger audit")
    parser.add_argument("--task", default=_DEFAULT_TASK)
    parser.add_argument("--policy", default=_DEFAULT_POLICY)
    parser.add_argument("--seeds", type=str, default="0:99")
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    parser.add_argument("--cleanup", action="store_true", default=True)
    parser.add_argument("--no-cleanup", action="store_true", default=False)
    parser.add_argument(
        "--strategy",
        type=str,
        default=None,
        help="Override micro_recovery_strategy in the policy config (e.g. lower_reclose, z_adjust, lower_closed).",
    )
    parser.add_argument(
        "--lower-delta-z",
        type=float,
        default=None,
        help="Override micro_recovery_lower_delta_z in the policy config.",
    )
    parser.add_argument(
        "--z-adjust",
        type=float,
        default=None,
        help="Override micro_recovery_z_adjust in the policy config.",
    )
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


def _parse_seed_range(text: str) -> list[int]:
    parts = [p.strip() for p in text.split(",") if p.strip()]
    seeds: list[int] = []
    for p in parts:
        if ":" in p:
            start, end = p.split(":", 1)
            seeds.extend(range(int(start), int(end) + 1))
        else:
            seeds.append(int(p))
    return seeds


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


def _run_seed(
    task_path: str,
    policy_config: dict[str, Any],
    seed: int,
    out_dir: Path,
    cleanup: bool = False,
) -> dict[str, Any]:
    if cleanup:
        _cleanup_arena_containers()

    run_dir = out_dir / f"seed{seed:03d}"
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
    triggered = any(bool(r.get("micro_recovery_triggered")) for r in trace)
    grip_quality_trigger = any(bool(r.get("grip_quality_trigger")) for r in trace)
    max_grip_failure_risk = max(
        (r.get("grip_quality_failure_risk") for r in trace if r.get("grip_quality_failure_risk") is not None),
        default=None,
    )

    if trace_path.exists():
        shutil.copy(trace_path, run_dir / "trace.jsonl")

    metrics = result.metrics or {}
    return {
        "seed": seed,
        "status": result.status,
        "env_success_rate": metrics.get("success_rate"),
        "env_progress_mean": metrics.get("progress_mean"),
        "grip_quality_trigger": grip_quality_trigger,
        "micro_recovery_triggered": triggered,
        "max_grip_failure_risk": max_grip_failure_risk,
    }


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

    with open(args.policy, "r", encoding="utf-8") as f:
        policy_config = yaml.safe_load(f) or {}
    policy_config.setdefault("policy_id", Path(args.policy).stem)
    policy_config["policy_source"] = args.policy
    if args.strategy is not None:
        policy_config.setdefault("policy_config_dict", {})
        policy_config["policy_config_dict"]["micro_recovery_strategy"] = args.strategy
    if args.lower_delta_z is not None:
        policy_config.setdefault("policy_config_dict", {})
        policy_config["policy_config_dict"]["micro_recovery_lower_delta_z"] = args.lower_delta_z
    if args.z_adjust is not None:
        policy_config.setdefault("policy_config_dict", {})
        policy_config["policy_config_dict"]["micro_recovery_z_adjust"] = args.z_adjust

    seeds = _parse_seed_range(args.seeds)
    rows: list[dict[str, Any]] = []
    for seed in seeds:
        print(f"\n=== seed {seed} ===", file=sys.stderr)
        try:
            row = _run_seed(args.task, policy_config, seed, out_dir, cleanup=cleanup)
        except Exception as exc:
            row = {
                "seed": seed,
                "status": f"error: {exc}",
                "micro_recovery_triggered": False,
            }
        rows.append(row)
        print(json.dumps(row, indent=2, default=str))

    valid = [r for r in rows if not str(r.get("status", "")).startswith("error")]
    triggered = [r for r in valid if r.get("micro_recovery_triggered")]
    successes = [r for r in valid if r.get("env_success_rate") == 1.0]
    summary = {
        "task": args.task,
        "policy": args.policy,
        "seeds": args.seeds,
        "num_seeds": len(seeds),
        "valid_runs": len(valid),
        "success_runs": len(successes),
        "success_rate": len(successes) / len(valid) if valid else 0.0,
        "trigger_count": len(triggered),
        "trigger_rate": len(triggered) / len(valid) if valid else 0.0,
        "triggered_seeds": [r["seed"] for r in triggered],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    csv_path = out_dir / "per_seed_results.csv"
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

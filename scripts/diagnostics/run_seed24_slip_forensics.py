#!/usr/bin/env python3
"""Seed 24 post-lift slip forensics runner.

Runs the official dex_cube task repeatedly for seed 24, collects per-episode
traces, classifies the failure mode, and compares the failed trajectories to a
set of successful seeds from the frozen v1.7 official benchmark.
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
_DEFAULT_OUT_DIR = Path("data_v18/diagnostics/seed24_slip_forensics")
_DEFAULT_OFFICIAL_DIR = Path("data_v17/official/dex_cube_goal_pose_100_seed_post_reachability")


SEED24_CATEGORIES = [
    "vertical_slip_after_lift",
    "torsional_slip_after_lift",
    "hold_instability",
    "grip_force_insufficient",
    "lift_acceleration_too_high",
    "orientation_realign_induced_slip",
    "metric_false_negative",
    "unknown",
    "success",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed 24 post-lift slip forensics")
    parser.add_argument("--task", default=_DEFAULT_TASK)
    parser.add_argument("--policy", default=_DEFAULT_POLICY)
    parser.add_argument("--seed", type=int, default=24)
    parser.add_argument("--repeat", type=int, default=10)
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    parser.add_argument(
        "--comparison-seeds",
        type=str,
        nargs="+",
        default=["0:4"],
        help="Successful seeds to use as a baseline (supports ranges like 0:4).",
    )
    parser.add_argument(
        "--official-data-dir",
        type=Path,
        default=_DEFAULT_OFFICIAL_DIR,
        help="Directory containing the frozen v1.7 official benchmark artifacts.",
    )
    parser.add_argument("--cleanup", action="store_true", default=True)
    parser.add_argument("--no-cleanup", action="store_true", default=False)
    return parser.parse_args()


def _parse_seeds(tokens: list[str]) -> list[int]:
    seeds: set[int] = set()
    for token in tokens:
        for part in token.split(","):
            part = part.strip()
            if ":" in part:
                start, end = part.split(":")
                seeds.update(range(int(start), int(end) + 1))
            else:
                seeds.add(int(part))
    return sorted(seeds)


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


def _find_successful_seeds(official_dir: Path, comparison_seeds: list[int]) -> list[int]:
    """Return the subset of comparison seeds that succeeded in the official run."""
    csv_path = official_dir / "per_seed_results.csv"
    if not csv_path.exists():
        return comparison_seeds

    successes: set[int] = set()
    try:
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    seed = int(row["seed"])
                    success_rate = float(row.get("success_rate", "nan"))
                    if success_rate == 1.0:
                        successes.add(seed)
                except (ValueError, KeyError):
                    continue
    except Exception:
        pass

    available = [s for s in comparison_seeds if s in successes]
    # Fall back to the requested seeds if none matched (e.g. missing CSV).
    return available if available else comparison_seeds


def _run_repeat(
    task_path: str,
    policy_config: dict[str, Any],
    seed: int,
    repeat_idx: int,
    out_dir: Path,
    cleanup: bool = False,
) -> dict[str, Any]:
    if cleanup:
        _cleanup_arena_containers()

    run_dir = out_dir / f"seed{seed:03d}_repeat{repeat_idx:02d}"
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
        "repeat": repeat_idx,
        "seed": seed,
        "status": result.status,
        "env_success_rate": metrics.get("success_rate"),
        "env_progress_mean": metrics.get("progress_mean"),
        **forensics,
    }


def _load_comparison_trace(official_dir: Path, seed: int) -> list[dict[str, Any]]:
    trace_path = official_dir / f"seed_{seed:03d}" / "traces" / "episode_trace.jsonl"
    return _load_trace(trace_path)


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    valid = [r for r in rows if not str(r.get("status", "")).startswith("error")]
    category_counts: dict[str, int] = {}
    for r in valid:
        cat = r.get("category", "unknown")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    def _mean(key: str) -> float | None:
        vals = [r[key] for r in valid if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    return {
        "total_repeats": total,
        "valid_repeats": len(valid),
        "success_repeats": category_counts.get("success", 0),
        "category_counts": category_counts,
        "category_distribution": {
            cat: category_counts.get(cat, 0) / len(valid) if valid else 0.0
            for cat in SEED24_CATEGORIES
        },
        "deterministic": len(set(category_counts.keys()) - {"success"}) <= 1 if valid else False,
        "mean_max_object_z": _mean("max_object_z"),
        "mean_final_object_z": _mean("final_object_z"),
        "mean_drop_step": _mean("drop_step"),
        "mean_step_of_max_height": _mean("step_of_max_height"),
        "mean_gripper_pos_min": _mean("gripper_pos_min"),
        "mean_object_yaw_error_final": _mean("object_yaw_error_final"),
        "mean_max_object_z_velocity_down": _mean("max_object_z_velocity_down"),
    }


def _summarize_comparison(traces: list[list[dict[str, Any]]]) -> dict[str, Any]:
    summaries = [summarize_trace_for_forensics(t) for t in traces if t]

    def _mean(key: str) -> float | None:
        vals = [s[key] for s in summaries if s.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    return {
        "count": len(summaries),
        "mean_max_object_z": _mean("max_object_z"),
        "mean_final_object_z": _mean("final_object_z"),
        "mean_object_yaw_error_final": _mean("object_yaw_error_final"),
        "mean_object_yaw_error_min": _mean("object_yaw_error_min"),
        "mean_gripper_pos_min": _mean("gripper_pos_min"),
        "mean_object_eef_distance_min": _mean("object_eef_distance_min"),
        "mean_object_eef_distance_mean": _mean("object_eef_distance_mean"),
        "mean_max_action_norm": _mean("max_action_norm"),
        "mean_episode_steps": _mean("episode_steps"),
    }


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    # Flatten all keys present in any row.
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

    rows: list[dict[str, Any]] = []
    for i in range(args.repeat):
        print(f"\n=== seed {args.seed} repeat {i + 1}/{args.repeat} ===", file=sys.stderr)
        try:
            row = _run_repeat(
                args.task,
                policy_config,
                args.seed,
                i,
                out_dir,
                cleanup=cleanup,
            )
        except Exception as exc:
            row = {
                "repeat": i,
                "seed": args.seed,
                "status": f"error: {exc}",
                "category": "error",
            }
        rows.append(row)
        print(json.dumps(row, indent=2, default=str))

    # Load successful comparison seeds from the frozen official benchmark.
    comparison_seeds = _parse_seeds(args.comparison_seeds)
    successful_seeds = _find_successful_seeds(args.official_data_dir, comparison_seeds)
    comparison_traces = [_load_comparison_trace(args.official_data_dir, s) for s in successful_seeds]
    comparison_summary = _summarize_comparison(comparison_traces)

    # Per-seed aggregate for the target seed.
    aggregate = _aggregate(rows)
    aggregate["target_seed"] = args.seed
    aggregate["task"] = args.task
    aggregate["policy"] = args.policy
    aggregate["comparison_seeds"] = successful_seeds
    aggregate["comparison_summary"] = comparison_summary
    aggregate["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Highlight a representative failed run (first non-success valid run).
    representative = next(
        (r for r in rows if r.get("category") not in ("success", "unknown", "error")),
        None,
    )
    aggregate["representative_repeat"] = representative["repeat"] if representative else None

    csv_path = out_dir / "per_repeat_results.csv"
    json_path = out_dir / "aggregate_summary.json"
    _write_csv(rows, csv_path)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(aggregate, f, indent=2, default=str)

    print("\n=== aggregate summary ===")
    print(json.dumps(aggregate, indent=2, default=str))
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")


if __name__ == "__main__":
    main()

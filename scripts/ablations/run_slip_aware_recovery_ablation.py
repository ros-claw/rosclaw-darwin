#!/usr/bin/env python3
"""Closed-loop slip-aware recovery ablation (Sprint 6 v1.8).

Compares baseline (no monitor) with kinematic-slip-triggered recovery
strategies on the official dex_cube task at target yaws π/2 and 2π/3.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.evaluation.yaw_coupling import classify_large_yaw_failure
from rosclaw_darwin.tdl.loader import TaskLoader

_DEFAULT_TASK = "configs/tasks/goal_pose_dex_cube_official.yaml"
_DEFAULT_BASE_POLICY = "configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml"
_DEFAULT_OUT_DIR = Path("data_v18/ablations/slip_aware_recovery")

_CONDITION_STRATEGIES = {
    "baseline": None,
    "pause_stabilize": "pause_stabilize",
    "lower_regrip": "lower_regrip",
    "abort_residual_yaw": "abort_residual_yaw",
    "place_push_correct": "place_push_correct",
    "best_combined": "best_combined",
}



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Closed-loop slip-aware recovery ablation")
    parser.add_argument("--task", default=_DEFAULT_TASK)
    parser.add_argument("--base-policy", default=_DEFAULT_BASE_POLICY)
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    parser.add_argument(
        "--target-yaws",
        type=str,
        nargs="+",
        default=["1.5708", "2.0944"],
        help="Target yaw overrides in radians",
    )
    parser.add_argument(
        "--conditions",
        type=str,
        nargs="+",
        default=["baseline", "pause_stabilize", "lower_regrip", "abort_residual_yaw", "place_push_correct", "best_combined"],
        help="Recovery strategies to compare",
    )
    parser.add_argument(
        "--seeds",
        type=str,
        nargs="+",
        default=["0:19"],
        help="Seeds to evaluate (supports ranges like 0:19)",
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


def _load_policy_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    config.setdefault("policy_id", Path(path).stem)
    return config


def _recovery_triggered(trace: list[dict[str, Any]]) -> bool:
    recovery_phases = {"SLIP_RECOVER_PAUSE", "SLIP_RECOVER_LOWER", "SLIP_RECOVER_PLACE_PUSH"}
    for rec in trace:
        if rec.get("phase") in recovery_phases:
            return True
        if rec.get("slip_event_active"):
            return True
    return False


def _run_seed(
    task_path: str,
    task_yaml: str,
    condition: str,
    policy_config: dict[str, Any],
    seed: int,
    target_yaw: float,
    out_dir: Path,
    cleanup: bool = False,
) -> dict[str, Any]:
    if cleanup:
        _cleanup_arena_containers()

    task = TaskLoader().load(task_path)
    task.mutation.seed = seed

    run_dir = out_dir / condition / f"yaw_{target_yaw:.4f}" / f"seed_{seed:03d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / "episode_trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    policy_config = dict(policy_config)
    policy_config["policy_id"] = f"{policy_config.get('policy_id', 'policy')}_yaw{target_yaw:.4f}_seed{seed:03d}"
    policy_config.setdefault("policy_config_dict", {})["target_yaw_override"] = target_yaw

    adapter = ArenaAdapter(task)
    result = adapter.run_policy(
        policy_config,
        episodes=1,
        max_steps=None,
        trace_dir=trace_dir,
    )

    metrics = result.metrics or {}
    trace = _load_trace(trace_path)
    yaw_diag = classify_large_yaw_failure(trace) if trace else {"category": "no_trace"}

    if trace_path.exists():
        shutil.copy(trace_path, run_dir / "trace.jsonl")

    return {
        "seed": seed,
        "condition": condition,
        "target_yaw": target_yaw,
        "status": result.status,
        "env_success_rate": metrics.get("success_rate"),
        "progress_mean": metrics.get("progress_mean"),
        "recovery_triggered": _recovery_triggered(trace),
        **yaw_diag,
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_key: dict[tuple[str, float], list[dict[str, Any]]] = {}
    for r in rows:
        by_key.setdefault((r["condition"], r["target_yaw"]), []).append(r)

    summary: dict[str, Any] = {"per_condition_target": {}}
    for (condition, target_yaw), key_rows in by_key.items():
        valid = [r for r in key_rows if r.get("status") == "completed"]
        categories: dict[str, int] = {}
        for r in valid:
            cat = r.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1
        summary["per_condition_target"][f"{condition}__yaw_{target_yaw:.4f}"] = {
            "condition": condition,
            "target_yaw": target_yaw,
            "count": len(key_rows),
            "valid_count": len(valid),
            "env_success_rate": sum(1 for r in valid if r.get("env_success_rate") == 1.0) / len(valid) if valid else None,
            "lifted_rate": sum(1 for r in valid if r.get("lifted")) / len(valid) if valid else None,
            "orientation_achieved_rate": sum(1 for r in valid if r.get("orientation_achieved")) / len(valid) if valid else None,
            "recovery_triggered_rate": sum(1 for r in valid if r.get("recovery_triggered")) / len(valid) if valid else None,
            "category_distribution": categories,
            "mean_object_yaw_final_error": (
                sum(r["object_yaw_final_error"] for r in valid if r.get("object_yaw_final_error") is not None)
                / max(1, sum(1 for r in valid if r.get("object_yaw_final_error") is not None))
            ),
            "mean_yaw_coupling_score": (
                sum(r["yaw_coupling_score"] for r in valid if r.get("yaw_coupling_score") is not None)
                / max(1, sum(1 for r in valid if r.get("yaw_coupling_score") is not None))
            ),
        }
    return summary


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    keys = list(rows[0].keys())
    with path.open("w", encoding="utf-8") as f:
        f.write(",".join(keys) + "\n")
        for row in rows:
            f.write(",".join(str(row.get(k, "")) for k in keys) + "\n")


def main() -> None:
    args = parse_args()
    out_dir: Path = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    seeds = _parse_seeds(args.seeds)
    target_yaws = [float(y) for y in args.target_yaws]
    cleanup = args.cleanup and not args.no_cleanup

    with open(args.task, "r", encoding="utf-8") as f:
        task_yaml = f.read()

    base_config = _load_policy_config(args.base_policy)

    rows: list[dict[str, Any]] = []
    for condition in args.conditions:
        strategy = _CONDITION_STRATEGIES.get(condition)
        policy_config = dict(base_config)
        policy_config["policy_id"] = f"slip_recovery_{condition}"
        cfg_dict = policy_config.setdefault("policy_config_dict", {})
        if strategy is not None:
            cfg_dict["enable_slip_monitor"] = True
            cfg_dict["slip_recovery_strategy"] = strategy
        else:
            cfg_dict["enable_slip_monitor"] = False
            cfg_dict["slip_recovery_strategy"] = None

        for target_yaw in target_yaws:
            for seed in seeds:
                print(f"\n=== {condition} yaw {target_yaw:.4f} seed {seed} ===", file=sys.stderr)
                try:
                    row = _run_seed(
                        args.task,
                        task_yaml,
                        condition,
                        policy_config,
                        seed,
                        target_yaw,
                        out_dir,
                        cleanup=cleanup,
                    )
                except Exception as exc:
                    row = {
                        "seed": seed,
                        "condition": condition,
                        "target_yaw": target_yaw,
                        "status": f"error: {exc}",
                        "category": "error",
                        "recovery_triggered": False,
                    }
                rows.append(row)
                print(json.dumps(row, indent=2, default=str))

    summary = _aggregate(rows)
    summary["target_yaws"] = target_yaws
    summary["seeds"] = seeds
    summary["conditions"] = args.conditions
    summary["task"] = args.task
    summary["base_policy"] = args.base_policy
    summary["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    csv_path = out_dir / "per_run_results.csv"
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

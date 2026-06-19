#!/usr/bin/env python3
"""Cross-object / cross-yaw generalization matrix for goal_pose v1.6.

Runs the official dex_cube task across target yaws, or procedural object
variants, comparing policy conditions:

- baseline_v3
- v3_reachability
- v3_yaw_align
- v3_reachability_yaw_align
- object_geometry_adapter_structural (object mode only)

All runs are serial to avoid Arena Docker/GPU contention.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
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
_DEFAULT_POLICY = "configs/policies/heuristic_servo_goal_pose_v3.yaml"
_DEFAULT_OUT_DIR = Path("/tmp/rosclaw_data/cross_object_cross_yaw_matrix")
_ORIENTATION_THRESHOLD = 0.5

_CONDITION_OVERRIDES: dict[str, dict[str, Any]] = {
    "baseline_v3": {},
    "v3_reachability": {
        "reachability_strategy": "side_pregrasp_positive_y",
        "reachability_positive_y_threshold": 0.01,
        "reachability_positive_yaw_threshold": 0.0,
        "high_pregrasp_z_offset": 0.25,
        "side_pregrasp_y_offset": -0.05,
        "side_pregrasp_z_offset": 0.15,
    },
    "v3_yaw_align": {
        "pre_grasp_yaw_align_v2": True,
        "pre_grasp_yaw_strategy": "target_yaw_before_grasp",
        "pre_grasp_yaw_fraction": 0.8,
        "pre_grasp_yaw_max_step": 0.2,
        "pre_grasp_yaw_settle_steps": 3,
        "post_grasp_yaw_residual_fraction": 0.2,
    },
    "v3_reachability_yaw_align": {
        "reachability_strategy": "side_pregrasp_positive_y",
        "reachability_positive_y_threshold": 0.01,
        "reachability_positive_yaw_threshold": 0.0,
        "high_pregrasp_z_offset": 0.25,
        "side_pregrasp_y_offset": -0.05,
        "side_pregrasp_z_offset": 0.15,
        "pre_grasp_yaw_align_v2": True,
        "pre_grasp_yaw_strategy": "target_yaw_before_grasp",
        "pre_grasp_yaw_fraction": 0.8,
        "pre_grasp_yaw_max_step": 0.2,
        "pre_grasp_yaw_settle_steps": 3,
        "post_grasp_yaw_residual_fraction": 0.2,
    },
    "object_geometry_adapter_structural": {
        "enable_regrasp": True,
        "max_regrasp_attempts": 2,
        "regrasp_xy_offsets": [[0.005, 0.0], [-0.005, 0.0]],
        "verify_lift_response_steps": 10,
        "min_lift_response_z": 0.01,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cross-object / cross-yaw generalization matrix for goal_pose v1.6"
    )
    parser.add_argument(
        "--mode",
        choices=["yaw", "object"],
        default="yaw",
        help="Matrix mode: yaw sweep or object variant sweep.",
    )
    parser.add_argument("--task", default=_DEFAULT_TASK, help="Base task config path")
    parser.add_argument("--policy", default=_DEFAULT_POLICY, help="Base policy config path")
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    parser.add_argument(
        "--target-yaws",
        type=float,
        nargs="+",
        default=[0.0, 0.5236, 0.7854, 1.0472, 1.5708, 2.0944],
        help="Target yaw values (radians) for yaw mode.",
    )
    parser.add_argument(
        "--object-task-configs",
        type=str,
        nargs="+",
        default=None,
        help="Task config paths for object mode (each represents an object/size).",
    )
    parser.add_argument(
        "--conditions",
        type=str,
        default="baseline_v3,v3_reachability,v3_yaw_align,v3_reachability_yaw_align",
        help="Comma-separated conditions to test.",
    )
    parser.add_argument(
        "--seeds",
        type=str,
        nargs="+",
        default=["0:19"],
        help="Seeds to evaluate (supports ranges like 0:19).",
    )
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Kill any running rosclaw-darwin:arena-base containers before each run.",
    )
    return parser.parse_args()


def _parse_seeds(tokens: list[str]) -> list[int]:
    seeds: set[int] = set()
    for token in tokens:
        for part in token.split(","):
            part = part.strip()
            if not part:
                continue
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


def _first_record(trace_path: Path) -> dict[str, Any] | None:
    if not trace_path.exists():
        return None
    try:
        with trace_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    return json.loads(line)
    except Exception:
        pass
    return None


def _best_orientation_record(
    trace_path: Path, target_yaw: float
) -> tuple[dict[str, Any] | None, float | None]:
    """Return the lifted record with the smallest yaw error to the target."""
    if not trace_path.exists():
        return None, None
    try:
        with trace_path.open("r", encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]
    except Exception as exc:
        print(f"[WARN] Failed to read trace {trace_path}: {exc}", file=sys.stderr)
        return None, None

    best_record = None
    best_error = None
    lifted_count = 0
    for r in records:
        object_z = r.get("object_z")
        object_yaw = r.get("object_yaw")
        if object_z is None or object_yaw is None:
            continue
        if object_z < 0.25:
            continue
        lifted_count += 1
        err = abs(_angle_diff(target_yaw, object_yaw))
        if best_error is None or err < best_error:
            best_error = err
            best_record = r

    if lifted_count == 0:
        print(
            f"[WARN] No lifted records (object_z > 0.25) in {trace_path}; "
            "orientation achievement cannot be judged.",
            file=sys.stderr,
        )
    return best_record, best_error


def _angle_diff(a: float, b: float) -> float:
    """Signed angle difference in [-pi, pi)."""
    diff = a - b
    while diff > math.pi:
        diff -= 2.0 * math.pi
    while diff < -math.pi:
        diff += 2.0 * math.pi
    return diff


def _run(
    task_path: str,
    base_policy: dict[str, Any],
    seed: int,
    condition: str,
    target_label: str,
    target_yaw: float | None,
    episodes: int,
    run_dir: Path,
    cleanup: bool = False,
) -> dict[str, Any]:
    if cleanup:
        _cleanup_arena_containers()

    run_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / "episode_trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    task = TaskLoader().load(task_path)
    task.mutation.seed = seed

    cfg = copy.deepcopy(base_policy)
    cfg["policy_id"] = f"{cfg.get('policy_id', 'policy')}_{condition}_{target_label}"
    cfg.setdefault("policy_config_dict", {}).update(_CONDITION_OVERRIDES[condition])
    if target_yaw is not None:
        cfg["policy_config_dict"]["target_yaw_override"] = target_yaw

    adapter = ArenaAdapter(task)
    result = adapter.run_policy(
        cfg,
        episodes=episodes,
        max_steps=None,
        trace_dir=trace_dir,
    )

    first = _first_record(trace_path) or {}
    metrics = result.metrics or {}

    # Orientation achievement: compare lifted object yaw to the requested target.
    effective_target_yaw = target_yaw if target_yaw is not None else first.get("target_yaw")
    lifted_best, best_orientation_error = None, None
    if effective_target_yaw is not None:
        lifted_best, best_orientation_error = _best_orientation_record(trace_path, effective_target_yaw)

    object_yaw_final = lifted_best.get("object_yaw") if lifted_best else None
    object_height_max = metrics.get("object_height_max_mean")
    orientation_achieved = (
        best_orientation_error is not None
        and best_orientation_error < _ORIENTATION_THRESHOLD
        and object_height_max is not None
        and object_height_max > 0.25
    )

    row: dict[str, Any] = {
        "seed": seed,
        "condition": condition,
        "target_label": target_label,
        "target_yaw": effective_target_yaw,
        "status": result.status,
        "env_success_rate": metrics.get("success_rate"),
        "progress_mean": metrics.get("progress_mean"),
        "object_height_max_mean": object_height_max,
        "object_height_delta_mean": metrics.get("object_height_delta_mean"),
        "object_x_initial": first.get("object_x"),
        "object_y_initial": first.get("object_y"),
        "object_z_initial": first.get("object_z"),
        "object_yaw_initial": first.get("object_yaw"),
        "object_yaw_final": object_yaw_final,
        "orientation_error_final": best_orientation_error,
        "orientation_achieved": bool(orientation_achieved),
        "eef_to_object_distance_initial_mean": metrics.get("eef_to_object_distance_initial_mean"),
        "eef_to_object_distance_min_mean": metrics.get("eef_to_object_distance_min_mean"),
        "min_grasp_z_error_mean": metrics.get("min_grasp_z_error_mean"),
        "min_grasp_dist_mean": metrics.get("min_grasp_dist_mean"),
        "descend_exit_rate": metrics.get("descend_exit_rate"),
        "grasp_phase_reached_rate": metrics.get("grasp_phase_reached_rate"),
        "lift_phase_reached_rate": metrics.get("lift_phase_reached_rate"),
        "run_id": result.run_id,
    }

    if trace_path.exists():
        stamped = run_dir / f"{cfg['policy_id']}_seed{seed}_{int(time.time())}.jsonl"
        shutil.copy(trace_path, stamped)

    return row


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_condition_target: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        by_condition_target.setdefault((r["condition"], r["target_label"]), []).append(r)

    def _mean(key: str, subset: list[dict[str, Any]]) -> float | None:
        vals = [r[key] for r in subset if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    per_cell = {}
    for (condition, target), sub in sorted(by_condition_target.items()):
        total = len(sub)
        lifted = [r for r in sub if (r.get("object_height_max_mean") or 0) > 0.25]
        oriented = [r for r in sub if r.get("orientation_achieved")]
        env_success = [r for r in sub if r.get("env_success_rate") == 1.0]
        completed = [r for r in sub if r.get("status") == "completed"]
        per_cell[f"{condition}__{target}"] = {
            "condition": condition,
            "target": target,
            "count": total,
            "completed_rate": len(completed) / total if total else None,
            "lifted_rate": len(lifted) / total if total else None,
            "orientation_achieved_rate": len(oriented) / total if total else None,
            "env_success_rate": len(env_success) / total if total else None,
            "mean_progress": _mean("progress_mean", sub),
            "mean_object_height_delta": _mean("object_height_delta_mean", sub),
            "mean_final_orientation_error": _mean("orientation_error_final", sub),
        }

    return {
        "total_runs": len(rows),
        "per_condition_target": per_cell,
    }


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    keys = list(rows[0].keys())
    with path.open("w", encoding="utf-8") as f:
        f.write(",".join(keys) + "\n")
        for row in rows:
            f.write(",".join(_fmt(row.get(k, "")) for k in keys) + "\n")


def _fmt(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def main() -> None:
    args = parse_args()
    out_dir: Path = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    seeds = _parse_seeds(args.seeds)
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    invalid = [c for c in conditions if c not in _CONDITION_OVERRIDES]
    if invalid:
        print(f"Invalid conditions: {invalid}", file=sys.stderr)
        sys.exit(1)

    with open(args.policy, "r", encoding="utf-8") as f:
        base_policy = yaml.safe_load(f) or {}
    base_policy.setdefault("policy_id", Path(args.policy).stem)

    if args.mode == "yaw":
        targets = [(f"yaw_{yaw:.4f}", yaw, args.task) for yaw in args.target_yaws]
    else:
        object_configs = args.object_task_configs or [args.task]
        targets = []
        for cfg_path in object_configs:
            label = Path(cfg_path).stem
            targets.append((label, None, cfg_path))

    rows: list[dict[str, Any]] = []
    for target_label, target_yaw, task_path in targets:
        print(f"\n========== target = {target_label} ==========")
        for condition in conditions:
            print(f"\n--- condition {condition} ---")
            for seed in seeds:
                print(f"--- seed {seed} ---")
                run_dir = out_dir / target_label / condition / f"seed_{seed}"
                try:
                    row = _run(
                        task_path,
                        base_policy,
                        seed,
                        condition,
                        target_label,
                        target_yaw,
                        args.episodes,
                        run_dir,
                        args.cleanup,
                    )
                except Exception as exc:
                    row = {
                        "seed": seed,
                        "condition": condition,
                        "target_label": target_label,
                        "target_yaw": target_yaw,
                        "status": f"error: {exc}",
                        "env_success_rate": None,
                        "progress_mean": None,
                    }
                rows.append(row)
                print(json.dumps(row, indent=2, default=str))

    summary = _aggregate(rows)
    summary["seeds"] = seeds
    summary["conditions"] = conditions
    summary["targets"] = [t[0] for t in targets]
    summary["mode"] = args.mode
    summary["base_task"] = args.task
    summary["base_policy"] = args.policy
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

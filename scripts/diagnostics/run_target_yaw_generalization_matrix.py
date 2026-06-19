#!/usr/bin/env python3
"""Cross-target-yaw generalization diagnostic for goal_pose.

The Arena cube_goal_pose environment fixes target_yaw to pi/2 for all seeds, so
this script injects a ``target_yaw_override`` into the policy config.  The
policy then tries to align the object to the overridden yaw.  The environment's
own success criterion still uses the original pi/2 target, so the script also
computes a custom ``orientation_achieved`` metric from the episode trace.

Usage:
    PYTHONPATH="..." ROSCLAW_ARENA_MODE=docker \
      python scripts/diagnostics/run_target_yaw_generalization_matrix.py \
      --target-yaws 0.0 0.5236 0.7854 1.0472 1.5708 \
      --seeds $(seq 0 9) \
      --out-dir /tmp/rosclaw_data/target_yaw_generalization
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
_DEFAULT_OUT_DIR = Path("/tmp/rosclaw_data/target_yaw_generalization")
_ORIENTATION_THRESHOLD = 0.5  # radians, matches v3 policy default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cross-target-yaw generalization diagnostic"
    )
    parser.add_argument("--task", default=_DEFAULT_TASK, help="Task config path")
    parser.add_argument("--policy", default=_DEFAULT_POLICY, help="Base policy config")
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    parser.add_argument(
        "--target-yaws",
        type=float,
        nargs="+",
        default=[0.0, 0.5236, 0.7854, 1.0472, 1.5708],
        help="Target yaw values (radians) to test",
    )
    parser.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        default=list(range(10)),
        help="Seeds to evaluate per target yaw",
    )
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Kill any running rosclaw-darwin:arena-base containers before each seed.",
    )
    return parser.parse_args()


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
    """Return the lifted record with the smallest yaw error to the override target.

    The environment's own success metric appears to be dominated by lift/position,
    so we explicitly search for a step where the object is elevated (z > 0.25 m)
    and compute its yaw error to the overridden target.  This is a stricter and
    more meaningful orientation-achievement signal.
    """
    if not trace_path.exists():
        return None, None
    try:
        with trace_path.open("r", encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]
    except Exception as exc:
        print(
            f"[WARN] Failed to read trace {trace_path}: {exc}",
            file=sys.stderr,
        )
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
    """Signed angle difference in [-pi, pi), matching the policy's convention."""
    diff = a - b
    while diff > math.pi:
        diff -= 2.0 * math.pi
    while diff < -math.pi:
        diff += 2.0 * math.pi
    return diff


def _run_seed(
    task_path: str,
    policy_config: dict[str, Any],
    seed: int,
    target_yaw: float,
    episodes: int,
    out_dir: Path,
    cleanup: bool = False,
) -> dict[str, Any]:
    if cleanup:
        _cleanup_arena_containers()

    run_dir = out_dir / f"target_yaw_{target_yaw:.4f}" / f"seed_{seed}"
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / "episode_trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    task = TaskLoader().load(task_path)
    task.mutation.seed = seed

    cfg = copy.deepcopy(policy_config)
    cfg["policy_id"] = f"{cfg.get('policy_id', 'policy')}_yaw{target_yaw:.4f}"
    cfg.setdefault("policy_config_dict", {})
    cfg["policy_config_dict"]["target_yaw_override"] = target_yaw

    adapter = ArenaAdapter(task)
    result = adapter.run_policy(
        cfg,
        episodes=episodes,
        max_steps=None,
        trace_dir=trace_dir,
    )

    first = _first_record(trace_path) or {}
    lifted_best, best_orientation_error = _best_orientation_record(trace_path, target_yaw)
    metrics = result.metrics or {}

    object_yaw_final = lifted_best.get("object_yaw") if lifted_best else None
    object_height_max = metrics.get("object_height_max_mean")
    object_height_delta = metrics.get("object_height_delta_mean")
    orientation_error = best_orientation_error
    orientation_achieved = (
        orientation_error is not None
        and orientation_error < _ORIENTATION_THRESHOLD
        and object_height_max is not None
        and object_height_max > 0.25
    )

    row: dict[str, Any] = {
        "seed": seed,
        "target_yaw": target_yaw,
        "status": result.status,
        "env_success_rate": metrics.get("success_rate"),
        "progress_mean": metrics.get("progress_mean"),
        "object_height_max_mean": metrics.get("object_height_max_mean"),
        "object_height_delta_mean": object_height_delta,
        "object_yaw_initial": first.get("object_yaw"),
        "object_yaw_final": object_yaw_final,
        "orientation_error_final": orientation_error,
        "orientation_achieved": bool(orientation_achieved),
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
    by_target: dict[float, list[dict[str, Any]]] = {}
    for r in rows:
        by_target.setdefault(r["target_yaw"], []).append(r)

    def _mean(key: str, subset: list[dict[str, Any]]) -> float | None:
        vals = [r[key] for r in subset if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    per_target = {}
    for yaw, sub in sorted(by_target.items()):
        total = len(sub)
        lifted = [r for r in sub if (r.get("object_height_max_mean") or 0) > 0.25]
        oriented = [r for r in sub if r.get("orientation_achieved")]
        env_success = [r for r in sub if r.get("env_success_rate") == 1.0]
        per_target[f"{yaw:.4f}"] = {
            "count": total,
            "lifted_rate": len(lifted) / total,
            "orientation_achieved_rate": len(oriented) / total,
            "env_success_rate": len(env_success) / total,
            "mean_progress": _mean("progress_mean", sub),
            "mean_object_height_delta": _mean("object_height_delta_mean", sub),
            "mean_final_orientation_error": _mean("orientation_error_final", sub),
        }

    return {
        "total_runs": len(rows),
        "target_yaw_values": sorted(by_target.keys()),
        "per_target_yaw": per_target,
    }


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

    with open(args.policy, "r", encoding="utf-8") as f:
        base_policy = yaml.safe_load(f) or {}
    base_policy.setdefault("policy_id", Path(args.policy).stem)

    rows: list[dict[str, Any]] = []
    for target_yaw in args.target_yaws:
        print(f"\n========== target_yaw = {target_yaw:.4f} rad ==========")
        for seed in args.seeds:
            print(f"--- seed {seed} ---")
            try:
                row = _run_seed(
                    args.task,
                    base_policy,
                    seed,
                    target_yaw,
                    args.episodes,
                    out_dir,
                    args.cleanup,
                )
            except Exception as exc:
                row = {
                    "seed": seed,
                    "target_yaw": target_yaw,
                    "status": f"error: {exc}",
                    "env_success_rate": None,
                    "progress_mean": None,
                }
            rows.append(row)
            print(json.dumps(row, indent=2, default=str))

    summary = _aggregate(rows)
    summary["seeds"] = args.seeds
    summary["target_yaws"] = args.target_yaws
    summary["task"] = args.task
    summary["policy"] = args.policy
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

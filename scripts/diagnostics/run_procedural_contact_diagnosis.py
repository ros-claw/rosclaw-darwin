#!/usr/bin/env python3
"""Procedural-cube OOD contact diagnosis runner.

Runs the procedural OOD task with baseline v3 and with structural regrasp
enabled, then extracts the contact_proxy / grasp_effective / lift_response_z
fields from the episode traces.  This gives a concrete diagnosis of why the
procedural fallback object does not lift.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.tdl.loader import TaskLoader

_DEFAULT_TASK = "configs/tasks/goal_pose_procedural_cube_ood.yaml"
_DEFAULT_POLICY = "configs/policies/heuristic_servo_goal_pose_v3.yaml"
_DEFAULT_OUT_DIR = Path("data_v16/diagnostics/procedural_contact_diagnosis")

_CONDITION_OVERRIDES: dict[str, dict[str, Any]] = {
    "baseline": {"enable_regrasp": False},
    "regrasp": {
        "enable_regrasp": True,
        "max_regrasp_attempts": 2,
        "regrasp_xy_offsets": [[0.005, 0.0], [-0.005, 0.0]],
        "verify_lift_response_steps": 10,
        "min_lift_response_z": 0.01,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Contact-level diagnosis for procedural OOD goal_pose"
    )
    parser.add_argument("--task", default=_DEFAULT_TASK)
    parser.add_argument("--policy", default=_DEFAULT_POLICY)
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    parser.add_argument(
        "--seeds",
        type=str,
        nargs="+",
        default=["0", "1", "2", "3", "4"],
        help="Seeds to evaluate (supports ranges like 0:4)",
    )
    parser.add_argument(
        "--conditions",
        type=str,
        default="baseline,regrasp",
        help="Comma-separated conditions to run",
    )
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument(
        "--cleanup",
        action="store_true",
        default=True,
        help="Kill lingering Arena containers before each seed (default: True).",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        default=False,
        help="Disable container cleanup between runs.",
    )
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


def _diagnose_trace(records: list[dict[str, Any]]) -> dict[str, Any]:
    proxies = Counter()
    max_regrasp = 0
    lift_response_z = 0.0
    last_grasp_effective: bool | None = None
    for r in records:
        phase = r.get("phase")
        if phase in ("CONTACT_VERIFY", "LIFT_VERIFY", "REGRASP"):
            proxy = r.get("contact_proxy") or "unknown"
            proxies[proxy] += 1
            max_regrasp = max(max_regrasp, r.get("regrasp_attempt", 0))
            last_grasp_effective = r.get("grasp_effective")
            if phase == "LIFT_VERIFY":
                lift_response_z = max(lift_response_z, r.get("lift_response_z") or 0.0)
    return {
        "contact_proxy_distribution": dict(proxies),
        "max_regrasp_attempt": max_regrasp,
        "last_grasp_effective": last_grasp_effective,
        "max_lift_response_z": lift_response_z,
    }


def _run_condition(
    task_path: str,
    base_policy: dict[str, Any],
    seed: int,
    condition: str,
    episodes: int,
    out_dir: Path,
    cleanup: bool = False,
) -> dict[str, Any]:
    if cleanup:
        _cleanup_arena_containers()

    run_dir = out_dir / f"seed_{seed}" / condition
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / "episode_trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    cfg = dict(base_policy)
    cfg["policy_id"] = f"{cfg.get('policy_id', 'policy')}_{condition}"
    cfg.setdefault("policy_config_dict", {}).update(_CONDITION_OVERRIDES[condition])

    task = TaskLoader().load(task_path)
    task.mutation.seed = seed

    adapter = ArenaAdapter(task)
    result = adapter.run_policy(
        cfg,
        episodes=episodes,
        max_steps=None,
        trace_dir=trace_dir,
    )

    metrics = result.metrics or {}
    records = _load_trace(trace_path)
    diagnosis = _diagnose_trace(records)

    row: dict[str, Any] = {
        "seed": seed,
        "condition": condition,
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
    row.update(diagnosis)

    if trace_path.exists():
        stamped = run_dir / f"{cfg['policy_id']}_seed{seed}_{int(time.time())}.jsonl"
        shutil.copy(trace_path, stamped)
    return row


def _aggregate(rows: list[dict[str, Any]], conditions: list[str]) -> dict[str, Any]:
    by_condition: dict[str, list[dict[str, Any]]] = {c: [] for c in conditions}
    for r in rows:
        by_condition.setdefault(r["condition"], []).append(r)

    summary: dict[str, Any] = {}
    for condition in conditions:
        sub = by_condition.get(condition, [])
        valid = [r for r in sub if r.get("status") == "completed"]
        successes = [r for r in valid if r.get("success_rate") == 1.0]
        lifted = [r for r in valid if (r.get("object_height_delta_mean") or 0) > 0.03]
        progresses = [r.get("progress_mean") for r in valid if r.get("progress_mean") is not None]
        all_proxies: Counter[str] = Counter()
        for r in valid:
            all_proxies.update(r.get("contact_proxy_distribution") or {})
        summary[condition] = {
            "count": len(sub),
            "valid_count": len(valid),
            "success_rate": len(successes) / len(valid) if valid else None,
            "lifted_rate": len(lifted) / len(valid) if valid else None,
            "mean_progress": sum(progresses) / len(progresses) if progresses else None,
            "contact_proxy_distribution": dict(all_proxies),
        }
    return summary


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

    rows: list[dict[str, Any]] = []
    for seed in seeds:
        print(f"\n=== seed {seed} ===", file=sys.stderr)
        for condition in conditions:
            print(f"--- condition {condition} ---", file=sys.stderr)
            try:
                row = _run_condition(
                    args.task,
                    base_policy,
                    seed,
                    condition,
                    args.episodes,
                    out_dir,
                    args.cleanup and not args.no_cleanup,
                )
            except Exception as exc:
                row = {
                    "seed": seed,
                    "condition": condition,
                    "status": f"error: {exc}",
                    "success_rate": None,
                }
            rows.append(row)
            print(json.dumps(row, indent=2, default=str))

    summary = _aggregate(rows, conditions)
    summary["seeds"] = seeds
    summary["conditions"] = conditions
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

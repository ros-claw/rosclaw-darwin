#!/usr/bin/env python3
"""Large-yaw route-policy feasibility pilot (Sprint 8 v1.10).

Runs the promoted v3 baseline on the official dex_cube task with large target
yaws (π/2 and 2π/3).  A second ``route_diagnostic`` condition enables the
learned route classifier in the policy container; the classifier does **not**
change the action, but it logs a ``route_prediction`` field in every trace
frame.

Outputs:
- per_seed_results.csv
- aggregate_summary.json with success/lift/orientation/route-distribution metrics.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Dynamically load Sprint 6 runner helpers.
_SPRINT6_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "diagnostics"
    / "run_valid_ood_subtask_decomposition.py"
)
_spec = importlib.util.spec_from_file_location(
    "run_valid_ood_subtask_decomposition", _SPRINT6_PATH
)
_sprint6 = importlib.util.module_from_spec(_spec)
sys.modules["run_valid_ood_subtask_decomposition"] = _sprint6
_spec.loader.exec_module(_sprint6)

_SUBTASK_ORDER = _sprint6._SUBTASK_ORDER
_geometry_from_task = _sprint6._geometry_from_task
_parse_seeds = _sprint6._parse_seeds
_run_one = _sprint6._run_one
sprint6_aggregate = _sprint6._aggregate

_DEFAULT_TASK = "configs/tasks/goal_pose_dex_cube_official.yaml"
_DEFAULT_POLICY = (
    "configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml"
)
_DEFAULT_CONDITIONS = ["baseline_v3", "route_diagnostic"]
_DEFAULT_OUT_DIR = Path("data_v20/ablations/large_yaw_route_policy_pilot")

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Large-yaw route-policy feasibility pilot (Sprint 8 v1.10)"
    )
    parser.add_argument("--task", type=str, default=_DEFAULT_TASK)
    parser.add_argument("--policy", type=str, default=_DEFAULT_POLICY)
    parser.add_argument(
        "--conditions",
        type=str,
        nargs="+",
        default=_DEFAULT_CONDITIONS,
        help="Conditions to compare",
    )
    parser.add_argument(
        "--seeds",
        type=str,
        nargs="+",
        default=["0:19"],
        help="Seeds to evaluate (supports ranges like 0:19)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_DEFAULT_OUT_DIR,
    )
    parser.add_argument(
        "--route-classifier-path",
        type=Path,
        default=Path("data_v20/models/large_yaw_route_classifier/model.json"),
        help="Path to trained route classifier JSON",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print matrix size and exit without invoking Docker",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Kill lingering Arena containers before each seed",
    )
    return parser.parse_args()


def _build_policy_config(
    base_policy: dict[str, Any],
    condition: str,
    subtask: str,
    route_classifier_path: Path,
) -> dict[str, Any]:
    """Construct policy config for a Sprint 8 condition."""
    cfg = dict(base_policy)
    cfg["policy_id"] = f"{cfg.get('policy_id', 'policy')}_{condition}_{subtask}"
    policy_config_dict = cfg.setdefault("policy_config_dict", {})

    # Clean slate for residual / route switches.
    policy_config_dict["enable_residual_policy"] = False
    policy_config_dict.pop("residual_policy", None)
    policy_config_dict.pop("residual_policy_path", None)
    policy_config_dict.pop("trigger_model_path", None)
    policy_config_dict.pop("trigger_threshold", None)
    policy_config_dict["enable_route_classifier"] = False
    policy_config_dict.pop("route_classifier_path", None)

    if condition == "baseline_v3":
        pass
    elif condition == "route_diagnostic":
        policy_config_dict["enable_route_classifier"] = True
        policy_config_dict["route_classifier_path"] = str(route_classifier_path.resolve())
    else:
        raise ValueError(f"Unknown condition: {condition}")

    if subtask == "yaw_90":
        policy_config_dict["target_yaw_override"] = 1.5708
    elif subtask == "yaw_120":
        policy_config_dict["target_yaw_override"] = 2.0944

    return cfg


def _extract_route_distribution(trace_path: Path) -> dict[str, int]:
    """Count route_prediction labels in an episode trace."""
    counts: dict[str, int] = {}
    if not trace_path.exists():
        return counts
    try:
        with trace_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                route = record.get("route_prediction")
                if route is not None:
                    counts[route] = counts.get(route, 0) + 1
    except Exception as exc:
        logger.warning("Could not read trace %s: %s", trace_path, exc)
    return counts


def _aggregate_sprint8(
    rows: list[dict[str, Any]],
    task_path: str,
    subtasks: list[str],
    conditions: list[str],
    out_dir: Path,
) -> dict[str, Any]:
    """Wrap Sprint 6 aggregation and add route-distribution metrics."""
    summary = sprint6_aggregate(rows, [task_path], subtasks, conditions)

    by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in rows:
        by_key.setdefault((r["task_id"], r["subtask"], r["condition"]), []).append(r)

    route_distributions: dict[str, dict[str, int]] = {}
    for r in rows:
        if r.get("condition") != "route_diagnostic":
            continue
        trace_path = (
            out_dir
            / r["task_id"]
            / f"seed_{int(r['seed']):03d}"
            / r["subtask"]
            / r["condition"]
            / "trace.jsonl"
        )
        counts = _extract_route_distribution(trace_path)
        key = f"{r['task_id']}__{r['subtask']}__{r['condition']}__seed_{r['seed']}"
        route_distributions[key] = counts

    for task_id in sorted({r["task_id"] for r in rows}):
        for subtask in subtasks:
            for condition in conditions:
                entry_key = f"{task_id}__{subtask}__{condition}"
                entry = summary.get("by_task_subtask_condition", {}).get(entry_key)
                if entry is None:
                    continue
                if condition == "route_diagnostic":
                    sub_rows = by_key.get((task_id, subtask, condition), [])
                    merged: dict[str, int] = {}
                    for r in sub_rows:
                        trace_path = (
                            out_dir
                            / task_id
                            / f"seed_{int(r['seed']):03d}"
                            / subtask
                            / condition
                            / "trace.jsonl"
                        )
                        for route, count in _extract_route_distribution(trace_path).items():
                            merged[route] = merged.get(route, 0) + count
                    total = sum(merged.values())
                    entry["route_distribution_counts"] = merged
                    entry["route_distribution_fractions"] = {
                        k: v / total if total else 0.0 for k, v in merged.items()
                    }
                    entry["blocked_external_rate"] = (
                        merged.get("blocked_external", 0) / total if total else None
                    )

    summary["route_distributions_per_seed"] = route_distributions
    return summary


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    keys = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(keys)
        for row in rows:
            writer.writerow(_fmt(row.get(k, "")) for k in keys)


def _fmt(value: Any) -> str:
    if isinstance(value, (dict, list, bool)):
        return json.dumps(value)
    return str(value)


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    out_dir: Path = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    seeds = _parse_seeds(args.seeds)
    conditions = [c.strip() for c in args.conditions if c.strip()]
    invalid = [c for c in conditions if c not in _DEFAULT_CONDITIONS]
    if invalid:
        logger.error("Invalid conditions: %s", invalid)
        sys.exit(1)

    subtasks = ["yaw_90", "yaw_120"]

    if args.dry_run:
        total = len(subtasks) * len(conditions) * len(seeds)
        print(
            f"Dry-run: {len(subtasks)} subtasks x "
            f"{len(conditions)} conditions x {len(seeds)} seeds = {total} runs"
        )
        print(f"Subtasks: {subtasks}")
        print(f"Conditions: {conditions}")
        print(f"Seeds: {seeds}")
        print(f"Out dir: {out_dir}")
        sys.exit(0)

    with open(args.policy, "r", encoding="utf-8") as f:
        base_policy = yaml.safe_load(f) or {}
    base_policy.setdefault("policy_id", Path(args.policy).stem)
    base_policy["policy_source"] = args.policy

    from rosclaw_darwin.tdl.loader import TaskLoader

    task = TaskLoader().load(args.task)
    task_id = task.id

    rows: list[dict[str, Any]] = []
    for subtask in subtasks:
        for condition in conditions:
            logger.info("=== %s | subtask=%s | condition=%s ===", task_id, subtask, condition)
            policy_config = _build_policy_config(
                base_policy,
                condition,
                subtask,
                args.route_classifier_path,
            )

            for seed in seeds:
                logger.info("--- seed %d ---", seed)
                try:
                    row = _run_one(
                        args.task,
                        policy_config,
                        seed,
                        subtask,
                        condition,
                        out_dir / task_id,
                        args.cleanup,
                    )
                except Exception as exc:
                    logger.exception(
                        "Failed to run %s %s %s seed %d",
                        task_id,
                        subtask,
                        condition,
                        seed,
                    )
                    row = {
                        "task_id": task_id,
                        "variant": Path(args.task).stem,
                        "subtask": subtask,
                        "condition": condition,
                        "seed": seed,
                        "status": f"error: {exc}",
                        "success_rate": 0.0,
                        "object_lifted": False,
                        "grasp_reached": False,
                        "slip_detected": False,
                        "reachability_failure": False,
                        "gripper_aperture_limit": False,
                        "run_id": "",
                    }
                rows.append(row)
                print(json.dumps(row, indent=2, default=str))

    aggregated = _aggregate_sprint8(rows, args.task, subtasks, conditions, out_dir)
    aggregated["task"] = Path(args.task).stem
    aggregated["subtasks"] = subtasks
    aggregated["conditions"] = conditions
    aggregated["seeds"] = seeds
    aggregated["policy"] = args.policy
    aggregated["route_classifier_path"] = str(args.route_classifier_path.resolve())
    aggregated["timestamp"] = (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )

    csv_path = out_dir / "per_seed_results.csv"
    json_path = out_dir / "aggregate_summary.json"
    _write_csv(rows, csv_path)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(aggregated, f, indent=2, default=str)

    logger.info("Aggregate summary written to %s", json_path)
    print("\n=== aggregate summary ===")
    print(json.dumps(aggregated, indent=2, default=str))
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")


if __name__ == "__main__":
    main()

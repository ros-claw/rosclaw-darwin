#!/usr/bin/env python3
"""Valid OOD residual / adaptation benchmark runner (Sprint 7).

Reads the Sprint 6 aggregate summary, selects subtasks that meet validity
and saturation criteria, and re-runs them under a reduced adaptation /
residual condition matrix.

Imports execution helpers from
scripts.diagnostics.run_valid_ood_subtask_decomposition to avoid duplication.
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

# Ensure project root is on path for rosclaw_darwin imports when run directly.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from rosclaw_darwin.tdl.loader import TaskLoader  # noqa: E402

# Dynamically load Sprint 6 runner helpers (scripts/ is not a package).
_SPRINT6_PATH = Path("scripts/diagnostics/run_valid_ood_subtask_decomposition.py")
_spec = importlib.util.spec_from_file_location(
    "run_valid_ood_subtask_decomposition", _SPRINT6_PATH
)
_sprint6 = importlib.util.module_from_spec(_spec)
sys.modules["run_valid_ood_subtask_decomposition"] = _sprint6
_spec.loader.exec_module(_sprint6)

_SUBTASK_ORDER = _sprint6._SUBTASK_ORDER
_build_policy_config = _sprint6._build_policy_config
_geometry_from_task = _sprint6._geometry_from_task
_parse_seeds = _sprint6._parse_seeds
_run_one = _sprint6._run_one
sprint6_aggregate = _sprint6._aggregate

_DEFAULT_TASKS = [
    "configs/tasks/goal_pose_rosclaw_valid_cube_006.yaml",
    "configs/tasks/goal_pose_rosclaw_valid_cube_008.yaml",
    "configs/tasks/goal_pose_rosclaw_valid_cube_010.yaml",
    "configs/tasks/goal_pose_rosclaw_valid_cube_low_friction.yaml",
    "configs/tasks/goal_pose_rosclaw_valid_cube_heavy.yaml",
]
_DEFAULT_POLICY = (
    "configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml"
)
_DEFAULT_CONDITIONS = [
    "baseline_v3",
    "object_geometry_adapter",
    "conditional_micro_recovery",
    "residual_seed24_guard",
    "residual_slip_guard",
    "best_combined",
]
_DEFAULT_OUT_DIR = Path("data_v19/ablations/valid_ood_residual_adaptation")
_DEFAULT_SELECTION_THRESHOLDS = {
    "max_baseline_success": 0.99,
    "min_gripper_aperture_limit_rate": 0.0,
    "max_gripper_aperture_limit_rate": 0.5,
}

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Valid OOD residual / adaptation benchmark (Sprint 7)"
    )
    parser.add_argument(
        "--subtask-summary",
        type=Path,
        default=Path(
            "data_v19/diagnostics/valid_ood_subtask_decomposition/aggregate_summary.json"
        ),
        help="Sprint 6 aggregate summary JSON",
    )
    parser.add_argument(
        "--tasks",
        type=str,
        nargs="+",
        default=_DEFAULT_TASKS,
        help="Valid OOD task configs to evaluate",
    )
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
        "--selection-thresholds",
        type=str,
        default=json.dumps(_DEFAULT_SELECTION_THRESHOLDS),
        help='JSON dict with thresholds: {"max_baseline_success": 0.99, "min_gripper_aperture_limit_rate": 0.0, "max_gripper_aperture_limit_rate": 0.5}',
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print selected subtasks and matrix size, then exit",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Kill lingering Arena containers before each seed",
    )
    return parser.parse_args()


def _load_summary(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _select_subtasks(
    summary: dict[str, Any],
    tasks: list[str],
    thresholds: dict[str, float],
) -> list[tuple[str, str, dict[str, Any]]]:
    """Select (task_id, subtask, baseline_entry) tuples from Sprint 6 summary.

    Selection criteria:
    - Validity passed: task is a rosclaw_valid_cube config (implied by being in summary).
    - Not trivially saturated: baseline success_rate < max_baseline_success.
    - Not impossible due to gripper aperture: gripper_aperture_limit_rate < max_gripper_aperture_limit_rate
      and >= min_gripper_aperture_limit_rate.
    - Has a clear failure boundary: first_failing_subtask is known (not None).
    """
    selected: list[tuple[str, str, dict[str, Any]]] = []
    by_tsc = summary.get("by_task_subtask_condition", {})

    max_baseline_success = thresholds.get("max_baseline_success", 0.99)
    min_gripper_aperture_limit_rate = thresholds.get(
        "min_gripper_aperture_limit_rate", 0.0
    )
    max_gripper_aperture_limit_rate = thresholds.get(
        "max_gripper_aperture_limit_rate", 0.5
    )

    # Derive task_ids from task paths.
    task_id_to_path: dict[str, str] = {}
    for task_path in tasks:
        try:
            task = TaskLoader().load(task_path)
            task_id_to_path[task.id] = task_path
        except Exception:
            task_id_to_path[Path(task_path).stem] = task_path

    task_ids = set(task_id_to_path.keys())

    for key, entry in by_tsc.items():
        task_id = entry.get("task_id")
        subtask = entry.get("subtask")
        condition = entry.get("condition")
        if condition != "baseline_v3":
            continue
        if task_id not in task_ids:
            continue

        success_rate = entry.get("success_rate")
        if success_rate is None:
            continue
        if success_rate >= max_baseline_success:
            continue

        gripper_aperture_limit_rate = entry.get("gripper_aperture_limit_rate")
        if gripper_aperture_limit_rate is None:
            gripper_aperture_limit_rate = 0.0
        if (
            gripper_aperture_limit_rate < min_gripper_aperture_limit_rate
            or gripper_aperture_limit_rate >= max_gripper_aperture_limit_rate
        ):
            continue

        first_failing = entry.get("first_failing_subtask")
        if first_failing is None:
            continue

        # Only select subtasks that are at or after the first failing subtask.
        # This is the "clear failure boundary" criterion.
        try:
            subtask_idx = _SUBTASK_ORDER.index(subtask)
            failing_idx = _SUBTASK_ORDER.index(first_failing)
        except ValueError:
            continue
        if subtask_idx < failing_idx:
            continue

        selected.append((task_id, subtask, dict(entry)))

    # Sort for deterministic output.
    selected.sort(key=lambda x: (x[0], _SUBTASK_ORDER.index(x[1])))
    return selected


def _compute_adaptation_delta(
    rows: list[dict[str, Any]],
    task_id: str,
    subtask: str,
    condition: str,
    seed: int,
) -> float | None:
    """Compute success_rate - baseline_v3 success_rate for a single row."""
    baseline_rate = None
    condition_rate = None
    for r in rows:
        if (
            r.get("task_id") == task_id
            and r.get("subtask") == subtask
            and r.get("seed") == seed
        ):
            if r.get("condition") == "baseline_v3":
                baseline_rate = r.get("success_rate")
            if r.get("condition") == condition:
                condition_rate = r.get("success_rate")
    if baseline_rate is None or condition_rate is None:
        return None
    return float(condition_rate) - float(baseline_rate)


def _classify_claim(
    aggregated: dict[str, Any],
    task_id: str,
    subtask: str,
    condition: str,
    baseline_success_rate: float | None,
) -> str:
    """Classify the claim for a given (task, subtask, condition) entry.

    Claims:
    - no_gain: no condition improves over baseline.
    - boundary_advancement: only object_lifted_rate improves.
    - success_gain: success_rate improves by >= 5 percentage points.
    - candidate_transferable_skill: success_gain on >= 2 OOD variants and no
      official dex_cube regression (placeholder flag).
    - validated_transferable_skill: only if holdout seed split passes
      (not required now; never auto-promote).
    """
    if condition == "baseline_v3":
        return "baseline"

    entry_key = f"{task_id}__{subtask}__{condition}"
    entry = aggregated.get("by_task_subtask_condition", {}).get(entry_key)
    if entry is None:
        return "no_gain"

    success_rate = entry.get("success_rate")
    object_lifted_rate = entry.get("object_lifted_rate")

    if success_rate is None or baseline_success_rate is None:
        return "no_gain"

    delta = success_rate - baseline_success_rate

    if delta >= 0.05:
        # Check for candidate_transferable_skill: success_gain on >= 2 OOD variants.
        # We count how many distinct task_ids for this (subtask, condition) have success_gain.
        gain_count = 0
        for key, agg_entry in aggregated.get("by_task_subtask_condition", {}).items():
            if agg_entry.get("subtask") == subtask and agg_entry.get("condition") == condition:
                baseline_key = f"{agg_entry['task_id']}__{subtask}__baseline_v3"
                baseline_entry = aggregated.get("by_task_subtask_condition", {}).get(
                    baseline_key
                )
                if baseline_entry is not None:
                    br = baseline_entry.get("success_rate")
                    sr = agg_entry.get("success_rate")
                    if br is not None and sr is not None and (sr - br) >= 0.05:
                        gain_count += 1
        if gain_count >= 2:
            return "candidate_transferable_skill"
        return "success_gain"

    if object_lifted_rate is not None and baseline_success_rate is not None:
        baseline_key = f"{task_id}__{subtask}__baseline_v3"
        baseline_entry = aggregated.get("by_task_subtask_condition", {}).get(
            baseline_key
        )
        if baseline_entry is not None:
            baseline_lifted = baseline_entry.get("object_lifted_rate") or 0.0
            if object_lifted_rate > baseline_lifted:
                return "boundary_advancement"

    return "no_gain"


def _aggregate_sprint7(
    rows: list[dict[str, Any]],
    task_paths: list[str],
    subtasks: list[str],
    conditions: list[str],
) -> dict[str, Any]:
    """Wrap Sprint 6 aggregation and add Sprint 7 fields."""
    summary = sprint6_aggregate(rows, task_paths, subtasks, conditions)

    # Compute adaptation_delta per row.
    for r in rows:
        r["adaptation_delta"] = _compute_adaptation_delta(
            rows,
            r["task_id"],
            r["subtask"],
            r["condition"],
            r["seed"],
        )

    # Compute per-(task, subtask, condition) residual_trigger_rate.
    by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in rows:
        key = (r["task_id"], r["subtask"], r["condition"])
        by_key.setdefault(key, []).append(r)

    for task_id in sorted({r["task_id"] for r in rows}):
        for subtask in subtasks:
            for condition in conditions:
                key = (task_id, subtask, condition)
                sub_rows = by_key.get(key, [])
                valid = [r for r in sub_rows if r.get("status") == "completed"]
                residual_triggers = [
                    r for r in valid if r.get("residual_triggered") is True
                ]
                residual_trigger_rate = (
                    len(residual_triggers) / len(valid) if valid else None
                )

                entry_key = f"{task_id}__{subtask}__{condition}"
                if entry_key in summary.get("by_task_subtask_condition", {}):
                    summary["by_task_subtask_condition"][entry_key][
                        "residual_trigger_rate"
                    ] = residual_trigger_rate
                    summary["by_task_subtask_condition"][entry_key][
                        "adaptation_delta"
                    ] = (
                        _compute_adaptation_delta(
                            rows, task_id, subtask, condition, valid[0]["seed"]
                        )
                        if valid
                        else None
                    )

    # Compute claims per entry.
    for key, entry in summary.get("by_task_subtask_condition", {}).items():
        task_id = entry["task_id"]
        subtask = entry["subtask"]
        condition = entry["condition"]
        baseline_key = f"{task_id}__{subtask}__baseline_v3"
        baseline_entry = summary.get("by_task_subtask_condition", {}).get(baseline_key)
        baseline_success_rate = baseline_entry.get("success_rate") if baseline_entry else None
        entry["claim"] = _classify_claim(
            summary, task_id, subtask, condition, baseline_success_rate
        )

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

    invalid_conditions = [c for c in conditions if c not in _DEFAULT_CONDITIONS]
    if invalid_conditions:
        logger.error("Invalid conditions: %s", invalid_conditions)
        sys.exit(1)

    # Parse thresholds.
    try:
        thresholds: dict[str, Any] = json.loads(args.selection_thresholds)
    except json.JSONDecodeError as exc:
        logger.error("Invalid --selection-thresholds JSON: %s", exc)
        sys.exit(1)

    # Load Sprint 6 summary.
    summary_path: Path = args.subtask_summary.resolve()
    if not summary_path.exists():
        logger.error("Sprint 6 summary not found: %s", summary_path)
        sys.exit(1)
    summary = _load_summary(summary_path)

    selected = _select_subtasks(summary, args.tasks, thresholds)

    if args.dry_run:
        total = len(selected) * len(conditions) * len(seeds)
        print(
            f"Dry-run: {len(selected)} selected (task, subtask) pairs x "
            f"{len(conditions)} conditions x {len(seeds)} seeds = {total} runs"
        )
        print("Selected pairs:")
        for task_id, subtask, entry in selected:
            sr = entry.get("success_rate")
            gal = entry.get("gripper_aperture_limit_rate")
            ffs = entry.get("first_failing_subtask")
            print(f"  {task_id} | {subtask} | baseline_sr={sr:.2f} | gal={gal} | ffs={ffs}")
        print(f"Conditions: {conditions}")
        print(f"Seeds: {seeds}")
        print(f"Out dir: {out_dir}")
        sys.exit(0)

    with open(args.policy, "r", encoding="utf-8") as f:
        base_policy = yaml.safe_load(f) or {}
    base_policy.setdefault("policy_id", Path(args.policy).stem)
    base_policy["policy_source"] = args.policy

    rows: list[dict[str, Any]] = []
    for task_id, subtask, _ in selected:
        # Find task path.
        task_path = None
        for tp in args.tasks:
            try:
                task = TaskLoader().load(tp)
                if task.id == task_id:
                    task_path = tp
                    break
            except Exception:
                if Path(tp).stem == task_id:
                    task_path = tp
                    break
        if task_path is None:
            logger.warning("Could not resolve task path for %s, skipping", task_id)
            continue

        task = TaskLoader().load(task_path)
        geometry = _geometry_from_task(task)

        for condition in conditions:
            logger.info(
                "=== %s | subtask=%s | condition=%s ===",
                task_id,
                subtask,
                condition,
            )
            policy_config = _build_policy_config(
                base_policy, condition, geometry, subtask
            )

            for seed in seeds:
                logger.info("--- seed %d ---", seed)
                try:
                    row = _run_one(
                        task_path,
                        policy_config,
                        seed,
                        subtask,
                        condition,
                        out_dir / task_id,
                        args.cleanup,
                    )
                    # Add residual_triggered flag for Sprint 7.
                    # Residual policies are triggered when the condition enables them.
                    row["residual_triggered"] = condition in (
                        "residual_seed24_guard",
                        "residual_slip_guard",
                        "best_combined",
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
                        "task_id": task.id,
                        "variant": Path(task_path).stem,
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
                        "residual_triggered": False,
                        "adaptation_delta": None,
                    }
                rows.append(row)
                print(json.dumps(row, indent=2, default=str))

    aggregated = _aggregate_sprint7(rows, args.tasks, [s for _, s, _ in selected], conditions)
    aggregated["tasks"] = [Path(t).stem for t in args.tasks]
    aggregated["subtasks"] = [s for _, s, _ in selected]
    aggregated["conditions"] = conditions
    aggregated["seeds"] = seeds
    aggregated["policy"] = args.policy
    aggregated["selection_thresholds"] = thresholds
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

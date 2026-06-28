#!/usr/bin/env python3
"""Valid OOD learned adaptation benchmark (Sprint 7 v1.10).

Reads the Sprint 6 ``selected_tasks.yaml`` and re-runs the selected medium OOD
tasks under a v1.10 condition matrix:

- ``baseline_v3``
- ``rule_micro_recovery``
- ``learned_trigger_only``
- ``learned_trigger_plus_bounded_residual``
- ``FTH_v33_selected_route``

The runner computes per-seed paired deltas against baseline_v3 and emits an
aggregate summary with paired rescued / newly_failed counts, residual trigger
rates, and first-failing-subtask deltas.
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

from rosclaw_darwin.evaluation.object_geometry import ObjectGeometry  # noqa: E402
from rosclaw_darwin.evolution.hint_recipe import HintRecipeRegistry  # noqa: E402
from rosclaw_darwin.tdl.loader import TaskLoader  # noqa: E402

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
    "rule_micro_recovery",
    "learned_trigger_only",
    "learned_trigger_plus_bounded_residual",
    "FTH_v33_selected_route",
]
_DEFAULT_OUT_DIR = Path("data_v20/ablations/valid_ood_learned_adaptation")

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Valid OOD learned adaptation benchmark (Sprint 7 v1.10)"
    )
    parser.add_argument(
        "--selected-tasks",
        type=Path,
        default=Path(
            "data_v20/diagnostics/valid_ood_medium_task_mining/selected_tasks.yaml"
        ),
        help="Sprint 6 selected_tasks.yaml",
    )
    parser.add_argument(
        "--tasks",
        type=str,
        nargs="+",
        default=_DEFAULT_TASKS,
        help="Fallback task configs if selected_tasks.yaml is missing",
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
        default=["0:49"],
        help="Seeds to evaluate (supports ranges like 0:49)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_DEFAULT_OUT_DIR,
    )
    parser.add_argument(
        "--trigger-model-path",
        type=Path,
        default=Path("data_v20/models/trigger_model/model.json"),
        help="Path to learned trigger model JSON",
    )
    parser.add_argument(
        "--bounded-residual-model-path",
        type=Path,
        default=Path("data_v20/models/bounded_residual_policy/model.json"),
        help="Path to bounded residual model JSON",
    )
    parser.add_argument(
        "--trigger-threshold",
        type=float,
        default=0.5,
        help="Trigger probability threshold for gated conditions",
    )
    parser.add_argument(
        "--hint-rules",
        type=Path,
        default=Path("configs/skills/failure_signature_to_hint_rules_v33.yaml"),
        help="Path to FTH v3.3 hint rules YAML",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print selected tasks and matrix size, then exit",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Kill lingering Arena containers before each seed",
    )
    return parser.parse_args()


def _load_selected_tasks(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("selected_tasks", [])


def _select_tasks(
    selected_tasks: list[dict[str, Any]],
    fallback_tasks: list[str],
) -> list[tuple[str, str, dict[str, Any]]]:
    """Return (task_id, subtask, metadata) tuples to benchmark.

    If Sprint 6 selected tasks exist, use them. Otherwise fall back to the
    ``full`` subtask of all fallback tasks.
    """
    pairs: list[tuple[str, str, dict[str, Any]]] = []
    if selected_tasks:
        for task in selected_tasks:
            task_id = task.get("task_id")
            first_failing = task.get("first_failing_subtask", "full")
            subtask = first_failing if first_failing in _SUBTASK_ORDER else "full"
            pairs.append((task_id, subtask, dict(task)))
        return pairs

    for task_path in fallback_tasks:
        try:
            task = TaskLoader().load(task_path)
            pairs.append((task.id, "full", {"task_id": task.id}))
        except Exception as exc:
            logger.warning("Could not load fallback task %s: %s", task_path, exc)
    return pairs


def _build_policy_config(
    base_policy: dict[str, Any],
    condition: str,
    geometry: Any,
    subtask: str,
    trigger_model_path: Path,
    bounded_residual_model_path: Path,
    trigger_threshold: float,
    hint_registry: HintRecipeRegistry | None,
) -> dict[str, Any]:
    """Construct policy config for a Sprint 7 condition."""
    cfg = dict(base_policy)
    cfg["policy_id"] = f"{cfg.get('policy_id', 'policy')}_{condition}_{subtask}"
    policy_config_dict = cfg.setdefault("policy_config_dict", {})

    # Clean slate.
    policy_config_dict["use_object_geometry_adaptation"] = False
    policy_config_dict.pop("object_geometry", None)
    policy_config_dict["enable_grip_quality_monitor"] = False
    policy_config_dict.pop("micro_recovery_strategy", None)
    policy_config_dict["enable_residual_policy"] = False
    policy_config_dict.pop("residual_policy", None)
    policy_config_dict.pop("residual_policy_path", None)
    policy_config_dict.pop("trigger_model_path", None)
    policy_config_dict.pop("trigger_threshold", None)
    policy_config_dict.pop("residual_enabled_phases", None)
    policy_config_dict.pop("target_yaw_override", None)
    cfg.pop("skill_hints", None)

    if condition == "baseline_v3":
        pass

    elif condition == "rule_micro_recovery":
        policy_config_dict["enable_grip_quality_monitor"] = True
        policy_config_dict["micro_recovery_strategy"] = "lower_reclose"

    elif condition == "learned_trigger_only":
        # Trigger model gates the same rule micro-recovery action.
        policy_config_dict["enable_grip_quality_monitor"] = True
        policy_config_dict["micro_recovery_strategy"] = "lower_reclose"
        policy_config_dict["enable_residual_policy"] = True
        policy_config_dict["residual_policy"] = "triggered_rule"
        policy_config_dict["trigger_model_path"] = str(trigger_model_path.resolve())
        policy_config_dict["trigger_threshold"] = trigger_threshold

    elif condition == "learned_trigger_plus_bounded_residual":
        policy_config_dict["enable_residual_policy"] = True
        policy_config_dict["residual_policy"] = "triggered_bounded_learned"
        policy_config_dict["residual_policy_path"] = str(
            bounded_residual_model_path.resolve()
        )
        policy_config_dict["trigger_model_path"] = str(trigger_model_path.resolve())
        policy_config_dict["trigger_threshold"] = trigger_threshold

    elif condition == "FTH_v33_selected_route":
        policy_config_dict["use_object_geometry_adaptation"] = True
        policy_config_dict["object_geometry"] = ObjectGeometry(
            width=geometry.width,
            depth=geometry.depth,
            height=geometry.height,
            object_name=geometry.object_name,
            asset_source=geometry.asset_source,
        ).to_dict()
        if hint_registry is not None:
            selected_hints, _overrides, _matched, _, _, _ = hint_registry.select_hints(
                tags=[
                    "unstable_grasp",
                    "grasped_but_not_lifted",
                    "lifted_then_dropped",
                    "object_not_lifted",
                ],
                validated_only=False,
            )
            base_hints = cfg.get("skill_hints", [])
            merged = list(base_hints)
            for hint in selected_hints:
                if hint not in merged:
                    merged.append(hint)
            cfg["skill_hints"] = merged

    else:
        raise ValueError(f"Unknown condition: {condition}")

    if subtask == "yaw_0":
        policy_config_dict["target_yaw_override"] = 0.0
    elif subtask == "yaw_90":
        policy_config_dict["target_yaw_override"] = 1.5708

    return cfg


def _pair_outcomes(
    rows: list[dict[str, Any]],
    task_id: str,
    subtask: str,
    condition: str,
) -> dict[str, int]:
    """Compute paired outcome counts for condition vs baseline_v3."""
    baseline_by_seed: dict[int, bool] = {}
    condition_by_seed: dict[int, bool] = {}
    for r in rows:
        if r.get("task_id") != task_id or r.get("subtask") != subtask:
            continue
        if r.get("status") != "completed":
            continue
        seed = r.get("seed")
        success = (r.get("success_rate") or 0) >= 1.0
        if r.get("condition") == "baseline_v3":
            baseline_by_seed[seed] = success
        elif r.get("condition") == condition:
            condition_by_seed[seed] = success

    common = set(baseline_by_seed.keys()) & set(condition_by_seed.keys())
    rescued = 0
    newly_failed = 0
    unchanged_success = 0
    unchanged_failure = 0
    for seed in common:
        b = baseline_by_seed[seed]
        c = condition_by_seed[seed]
        if not b and c:
            rescued += 1
        elif b and not c:
            newly_failed += 1
        elif b and c:
            unchanged_success += 1
        else:
            unchanged_failure += 1

    return {
        "paired_rescued": rescued,
        "paired_newly_failed": newly_failed,
        "paired_unchanged_success": unchanged_success,
        "paired_unchanged_failure": unchanged_failure,
        "paired_valid_seeds": len(common),
    }


def _aggregate_sprint7(
    rows: list[dict[str, Any]],
    task_paths: list[str],
    subtasks: list[str],
    conditions: list[str],
) -> dict[str, Any]:
    """Wrap Sprint 6 aggregation and add Sprint 7 paired metrics."""
    summary = sprint6_aggregate(rows, task_paths, subtasks, conditions)

    by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in rows:
        by_key.setdefault(
            (r["task_id"], r["subtask"], r["condition"]), []
        ).append(r)

    for task_id in sorted({r["task_id"] for r in rows}):
        for subtask in subtasks:
            for condition in conditions:
                sub_rows = by_key.get((task_id, subtask, condition), [])
                valid = [r for r in sub_rows if r.get("status") == "completed"]
                triggered = [r for r in valid if r.get("residual_triggered") is True]
                trigger_rate = len(triggered) / len(valid) if valid else None

                entry_key = f"{task_id}__{subtask}__{condition}"
                entry = summary.get("by_task_subtask_condition", {}).get(entry_key)
                if entry is not None:
                    entry["residual_trigger_rate"] = trigger_rate
                    entry.update(_pair_outcomes(rows, task_id, subtask, condition))

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

    selected_tasks = _load_selected_tasks(args.selected_tasks)
    selected_pairs = _select_tasks(selected_tasks, args.tasks)

    if args.dry_run:
        total = len(selected_pairs) * len(conditions) * len(seeds)
        print(
            f"Dry-run: {len(selected_pairs)} selected (task, subtask) pairs x "
            f"{len(conditions)} conditions x {len(seeds)} seeds = {total} runs"
        )
        print("Selected pairs:")
        for task_id, subtask, meta in selected_pairs:
            print(f"  {task_id} | {subtask} | {meta.get('recommended_adaptation_axis')}")
        print(f"Conditions: {conditions}")
        print(f"Seeds: {seeds}")
        print(f"Out dir: {out_dir}")
        sys.exit(0)

    with open(args.policy, "r", encoding="utf-8") as f:
        base_policy = yaml.safe_load(f) or {}
    base_policy.setdefault("policy_id", Path(args.policy).stem)
    base_policy["policy_source"] = args.policy

    hint_registry: HintRecipeRegistry | None = None
    if "FTH_v33_selected_route" in conditions:
        if args.hint_rules is None or not args.hint_rules.exists():
            logger.error(
                "--hint-rules must point to an existing YAML file when FTH_v33_selected_route is used"
            )
            sys.exit(1)
        hint_registry = HintRecipeRegistry.from_yaml(args.hint_rules)

    rows: list[dict[str, Any]] = []
    for task_id, subtask, meta in selected_pairs:
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
                base_policy,
                condition,
                geometry,
                subtask,
                args.trigger_model_path,
                args.bounded_residual_model_path,
                args.trigger_threshold,
                hint_registry,
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
                    row["residual_triggered"] = condition in (
                        "learned_trigger_only",
                        "learned_trigger_plus_bounded_residual",
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
                    }
                rows.append(row)
                print(json.dumps(row, indent=2, default=str))

    subtasks = sorted(
        {s for _, s, _ in selected_pairs}, key=lambda x: _SUBTASK_ORDER.index(x)
    )
    aggregated = _aggregate_sprint7(rows, args.tasks, subtasks, conditions)
    aggregated["tasks"] = [Path(t).stem for t in args.tasks]
    aggregated["subtasks"] = subtasks
    aggregated["conditions"] = conditions
    aggregated["seeds"] = seeds
    aggregated["policy"] = args.policy
    aggregated["trigger_model_path"] = str(args.trigger_model_path.resolve())
    aggregated["bounded_residual_model_path"] = str(
        args.bounded_residual_model_path.resolve()
    )
    aggregated["trigger_threshold"] = args.trigger_threshold
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

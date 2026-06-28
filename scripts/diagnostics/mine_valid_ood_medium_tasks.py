#!/usr/bin/env python3
"""Mine valid OOD medium-difficulty tasks for learned adaptation.

Reads a valid OOD subtask decomposition aggregate summary (produced by
``run_valid_ood_subtask_decomposition.py``) and selects tasks whose
``baseline_v3`` success rate on the ``full`` subtask is in the medium-difficulty
range (default 20%--80%).

Output::

    <out-dir>/
      selected_tasks.yaml
      rejected_tasks.yaml
      difficulty_table.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import yaml

# Subtask used for difficulty mining.  The ``full`` subtask represents the
# complete goal_pose task.
_DIFFICULTY_SUBTASK = "full"
_BASELINE_CONDITION = "baseline_v3"

# Default thresholds.
_DEFAULT_SUCCESS_MIN = 0.2
_DEFAULT_SUCCESS_MAX = 0.8
_DEFAULT_MIN_SEEDS = 10
_DEFAULT_INVALID_GEOMETRY_THRESHOLD = 0.5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mine valid OOD medium-difficulty tasks for learned adaptation"
    )
    parser.add_argument(
        "--summary",
        type=Path,
        required=True,
        help="Path to aggregate_summary.json from run_valid_ood_subtask_decomposition.py",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data_v20/diagnostics/valid_ood_medium_task_mining"),
    )
    parser.add_argument(
        "--success-min",
        type=float,
        default=_DEFAULT_SUCCESS_MIN,
        help="Minimum baseline success rate for a medium task",
    )
    parser.add_argument(
        "--success-max",
        type=float,
        default=_DEFAULT_SUCCESS_MAX,
        help="Maximum baseline success rate for a medium task",
    )
    parser.add_argument(
        "--min-seeds",
        type=int,
        default=_DEFAULT_MIN_SEEDS,
        help="Minimum completed seeds required for selection",
    )
    parser.add_argument(
        "--invalid-geometry-threshold",
        type=float,
        default=_DEFAULT_INVALID_GEOMETRY_THRESHOLD,
        help="Rate above which a task is classified as invalid_geometry",
    )
    parser.add_argument(
        "--validity-file",
        type=Path,
        default=None,
        help="Optional JSON file with a list of task_ids that passed the validity gate",
    )
    return parser.parse_args()


def _load_validity_set(path: Path | None) -> set[str] | None:
    if path is None or not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return set(data)
    if isinstance(data, dict):
        return set(data.get("valid_tasks", []))
    raise ValueError(f"Unexpected validity file format: {path}")


def _classify_task(
    entry: dict[str, Any],
    success_min: float,
    success_max: float,
    min_seeds: int,
    invalid_threshold: float,
    validity_set: set[str] | None,
) -> tuple[str, str | None, dict[str, Any]]:
    """Return (status, reason, enriched_entry) for one full-baseline entry.

    Status is one of: selected, too_easy, too_hard, invalid_geometry,
    insufficient_data, invalid_validity.
    """
    task_id = entry["task_id"]
    count = entry.get("count", 0)
    success_rate = entry.get("success_rate")

    reachability_rate = entry.get("reachability_failure_rate") or 0.0
    aperture_rate = entry.get("gripper_aperture_limit_rate") or 0.0
    slip_rate = entry.get("slip_rate") or 0.0
    lifted_rate = entry.get("object_lifted_rate") or 0.0
    grasp_rate = entry.get("grasp_reached_rate") or 0.0

    if validity_set is not None and task_id not in validity_set:
        return "invalid_validity", "validity_gate_failed", {
            **entry,
            "validity_passed": False,
        }

    if count < min_seeds or success_rate is None:
        return "insufficient_data", f"only_{count}_completed_seeds", {
            **entry,
            "validity_passed": True,
        }

    if reachability_rate >= invalid_threshold or aperture_rate >= invalid_threshold:
        return "invalid_geometry", "reachability_or_aperture_dominant", {
            **entry,
            "validity_passed": True,
        }

    if success_rate >= success_max:
        return "too_easy", "baseline_saturated", {**entry, "validity_passed": True}

    if success_rate <= success_min:
        return "too_hard", "baseline_near_zero", {**entry, "validity_passed": True}

    # Medium difficulty.
    dominant_failure = _dominant_failure(
        slip_rate, lifted_rate, grasp_rate, reachability_rate, entry
    )
    recommended_axis = _recommended_axis(
        slip_rate, lifted_rate, grasp_rate, reachability_rate, dominant_failure
    )

    return "selected", None, {
        **entry,
        "validity_passed": True,
        "dominant_failure": dominant_failure,
        "recommended_adaptation_axis": recommended_axis,
    }


def _dominant_failure(
    slip_rate: float,
    lifted_rate: float,
    grasp_rate: float,
    reachability_rate: float,
    entry: dict[str, Any],
) -> str:
    """Heuristic dominant failure label based on aggregated rates."""
    # Failure on full task but object lifted in many seeds -> orientation/yaw slip.
    if slip_rate >= 0.2:
        return "in_hand_slip"
    if lifted_rate >= 0.5:
        return "orientation_misalignment"
    if reachability_rate >= 0.2:
        return "reachability_failure"
    if grasp_rate <= 0.5:
        return "grasp_failure"
    # Generic fallback based on first failing subtask.
    first = entry.get("first_failing_subtask")
    if first == "lift_only":
        return "object_not_lifted"
    if first == "lift_hold":
        return "lifted_then_dropped"
    if first in ("yaw_0", "yaw_90"):
        return "yaw_alignment_failure"
    return "unspecified"


def _recommended_axis(
    slip_rate: float,
    lifted_rate: float,
    grasp_rate: float,
    reachability_rate: float,
    dominant_failure: str,
) -> str:
    """Map dominant failure to an adaptation axis for Sprint 7."""
    if slip_rate >= 0.2 or dominant_failure == "in_hand_slip":
        return "slip_monitor / lower_speed_scale"
    if reachability_rate >= 0.2:
        return "reachability_aware_approach"
    if grasp_rate <= 0.5 or dominant_failure in ("grasp_failure", "object_not_lifted"):
        return "grip_quality / lower_reclose"
    if lifted_rate >= 0.5 or dominant_failure == "orientation_misalignment":
        return "orientation_alignment / residual_yaw"
    return "object_geometry_adapter"


def mine_medium_tasks(
    summary: dict[str, Any],
    success_min: float = _DEFAULT_SUCCESS_MIN,
    success_max: float = _DEFAULT_SUCCESS_MAX,
    min_seeds: int = _DEFAULT_MIN_SEEDS,
    invalid_threshold: float = _DEFAULT_INVALID_GEOMETRY_THRESHOLD,
    validity_set: set[str] | None = None,
) -> dict[str, Any]:
    """Select and reject tasks from an aggregate summary.

    Returns a dict with ``selected`` and ``rejected`` lists plus a
    ``difficulty_table``.
    """
    by_key = summary.get("by_task_subtask_condition", {})

    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    difficulty_table: list[dict[str, Any]] = []

    seen_tasks: set[str] = set()
    for key, entry in by_key.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("subtask") != _DIFFICULTY_SUBTASK:
            continue
        if entry.get("condition") != _BASELINE_CONDITION:
            continue

        task_id = entry.get("task_id")
        if not task_id or task_id in seen_tasks:
            continue
        seen_tasks.add(task_id)

        status, reason, enriched = _classify_task(
            entry,
            success_min,
            success_max,
            min_seeds,
            invalid_threshold,
            validity_set,
        )

        row = {
            "task_id": task_id,
            "baseline_success_rate": enriched.get("success_rate"),
            "first_failing_subtask": enriched.get("first_failing_subtask"),
            "count": enriched.get("count"),
            "status": status,
            "reason": reason,
            "dominant_failure": enriched.get("dominant_failure"),
            "recommended_adaptation_axis": enriched.get("recommended_adaptation_axis"),
        }
        difficulty_table.append(row)

        if status == "selected":
            selected.append(
                {
                    "task_id": task_id,
                    "baseline_success_rate": enriched.get("success_rate"),
                    "first_failing_subtask": enriched.get("first_failing_subtask"),
                    "dominant_failure": enriched.get("dominant_failure"),
                    "validity_passed": enriched.get("validity_passed"),
                    "recommended_adaptation_axis": enriched.get(
                        "recommended_adaptation_axis"
                    ),
                    "count": enriched.get("count"),
                }
            )
        else:
            rejected.append(
                {
                    "task_id": task_id,
                    "baseline_success_rate": enriched.get("success_rate"),
                    "first_failing_subtask": enriched.get("first_failing_subtask"),
                    "status": status,
                    "reason": reason,
                    "count": enriched.get("count"),
                }
            )

    selected.sort(key=lambda x: x["baseline_success_rate"] or 0.0, reverse=True)
    rejected.sort(key=lambda x: x["baseline_success_rate"] if x["baseline_success_rate"] is not None else -1.0, reverse=True)
    difficulty_table.sort(
        key=lambda x: x["baseline_success_rate"] if x["baseline_success_rate"] is not None else -1.0,
        reverse=True,
    )

    return {
        "selected": selected,
        "rejected": rejected,
        "difficulty_table": difficulty_table,
        "parameters": {
            "success_min": success_min,
            "success_max": success_max,
            "min_seeds": min_seeds,
            "invalid_geometry_threshold": invalid_threshold,
            "difficulty_subtask": _DIFFICULTY_SUBTASK,
            "baseline_condition": _BASELINE_CONDITION,
        },
    }


def _write_yaml(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _write_csv(table: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not table:
        path.write_text("task_id,baseline_success_rate,first_failing_subtask,count,status,reason,dominant_failure,recommended_adaptation_axis\n", encoding="utf-8")
        return
    keys = [
        "task_id",
        "baseline_success_rate",
        "first_failing_subtask",
        "count",
        "status",
        "reason",
        "dominant_failure",
        "recommended_adaptation_axis",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in table:
            writer.writerow({k: row.get(k, "") for k in keys})


def main() -> None:
    args = parse_args()

    if not args.summary.exists():
        print(f"Summary file not found: {args.summary}", file=sys.stderr)
        sys.exit(1)

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    validity_set = _load_validity_set(args.validity_file)

    result = mine_medium_tasks(
        summary,
        success_min=args.success_min,
        success_max=args.success_max,
        min_seeds=args.min_seeds,
        invalid_threshold=args.invalid_geometry_threshold,
        validity_set=validity_set,
    )

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    _write_yaml({"selected_tasks": result["selected"]}, out_dir / "selected_tasks.yaml")
    _write_yaml({"rejected_tasks": result["rejected"]}, out_dir / "rejected_tasks.yaml")
    _write_csv(result["difficulty_table"], out_dir / "difficulty_table.csv")

    # Persist the full result including parameters for downstream benchmark runners.
    full_result = {**result, "source_summary": str(args.summary.resolve())}
    (out_dir / "mining_result.json").write_text(
        json.dumps(full_result, indent=2, default=str), encoding="utf-8"
    )

    print(f"Selected: {len(result['selected'])}  Rejected: {len(result['rejected'])}")
    print(f"Outputs written to {out_dir}")


if __name__ == "__main__":
    main()

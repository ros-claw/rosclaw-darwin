#!/usr/bin/env python3
"""Valid OOD subtask decomposition runner.

Runs the promoted v3 policy across valid OOD cube variants under multiple
subtasks (lift_only, lift_hold, yaw_0, yaw_90, full) and conditions
(baseline_v3, object_geometry_adapter, conditional_micro_recovery,
residual_seed24_guard, residual_slip_guard, best_combined).

Collects per-seed metrics and aggregates by (task, subtask, condition).
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.evaluation.object_geometry import ObjectGeometry
from rosclaw_darwin.tdl.loader import TaskLoader
from rosclaw_darwin.tdl.schema import Primitive

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
_DEFAULT_OUT_DIR = Path("data_v19/diagnostics/valid_ood_subtask_decomposition")
_DEFAULT_SUBTASKS = ["lift_only", "lift_hold", "yaw_0", "yaw_90", "full"]
_DEFAULT_CONDITIONS = [
    "baseline_v3",
    "object_geometry_adapter",
    "conditional_micro_recovery",
    "residual_seed24_guard",
    "residual_slip_guard",
    "best_combined",
]

# Canonical subtask order for first_failing_subtask computation.
_SUBTASK_ORDER = ["lift_only", "lift_hold", "yaw_0", "yaw_90", "full"]

# Object height must increase by more than this to count as "lifted".
LIFTED_HEIGHT_DELTA_M = 0.03

# Safe Docker image name pattern (alphanumerics and common registry/delimiters).
_DOCKER_IMAGE_RE = re.compile(r"^[a-zA-Z0-9_.\-/:]+$")

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Valid OOD subtask decomposition matrix"
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
        "--subtasks",
        type=str,
        nargs="+",
        default=_DEFAULT_SUBTASKS,
        help="Subtasks to evaluate",
    )
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
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print matrix size and exit without running Docker",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Kill lingering Arena containers before each seed",
    )
    return parser.parse_args()


def _parse_seeds(tokens: list[str]) -> list[int]:
    seeds: set[int] = set()
    for token in tokens:
        for part in token.split(","):
            part = part.strip()
            if ":" in part:
                start, end = part.split(":")
                start_i, end_i = int(start), int(end)
                if start_i < 0 or end_i < 0:
                    raise ValueError(
                        f"Seed range bounds must be non-negative: {part}"
                    )
                if start_i > end_i:
                    raise ValueError(
                        f"Seed range start must be <= end: {part}"
                    )
                seeds.update(range(start_i, end_i + 1))
            else:
                seed_i = int(part)
                if seed_i < 0:
                    raise ValueError(f"Seed must be non-negative: {part}")
                seeds.add(seed_i)
    return sorted(seeds)


def _cleanup_arena_containers(image: str = "rosclaw-darwin:arena-base") -> int:
    if not _DOCKER_IMAGE_RE.fullmatch(image):
        raise ValueError(
            f"Refusing to cleanup containers for unsafe image name: {image!r}"
        )
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
            ["docker", "kill", cid],
            capture_output=True,
            text=True,
            check=False,
        )
        if kill_result.returncode == 0:
            killed += 1
        else:
            logger.warning(
                "Failed to kill container %s: %s",
                cid,
                kill_result.stderr.strip(),
            )
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
                    except json.JSONDecodeError as exc:
                        logger.warning(
                            "Skipping malformed trace line in %s: %s",
                            trace_path,
                            exc,
                        )
    except OSError as exc:
        logger.warning("Could not read trace %s: %s", trace_path, exc)
    return records


def _geometry_from_task(task: Any) -> ObjectGeometry:
    """Build ObjectGeometry from task physics_ablation metadata."""
    metadata = getattr(task, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
    physics = metadata.get("physics_ablation", {})
    if not isinstance(physics, dict):
        physics = {}
    size = physics.get("size")
    mass = physics.get("mass")
    static_friction = physics.get("static_friction")

    if size is not None and len(size) >= 3:
        return ObjectGeometry(
            width=float(size[0]),
            depth=float(size[1]),
            height=float(size[2]),
            object_name="object",
            asset_source="rosclaw_valid_cube",
            mass=float(mass) if mass is not None else None,
            static_friction=float(static_friction)
            if static_friction is not None
            else None,
        )

    return ObjectGeometry(
        object_name="object",
        asset_source="rosclaw_valid_cube",
        mass=float(mass) if mass is not None else None,
        static_friction=float(static_friction)
        if static_friction is not None
        else None,
    )


def _size_only_geometry(geometry: ObjectGeometry) -> ObjectGeometry:
    """Return a geometry copy that retains only size fields."""
    return ObjectGeometry(
        width=geometry.width,
        depth=geometry.depth,
        height=geometry.height,
        object_name=geometry.object_name,
        asset_source=geometry.asset_source,
    )


def _apply_subtask(task: Any, subtask: str) -> None:
    """Modify task primitives and success conditions in-memory for a subtask."""
    if subtask == "lift_only":
        task.primitives = [Primitive(name="Lift", args={"target": "cube"})]
        task.eval.success_conditions = ["object_lifted"]
    elif subtask == "lift_hold":
        task.primitives = [
            Primitive(name="Lift", args={"target": "cube"}),
            Primitive(name="Hold", args={"target": "cube"}),
        ]
        task.eval.success_conditions = ["object_lifted"]
    elif subtask in ("yaw_0", "yaw_90", "yaw_120", "full"):
        task.primitives = [Primitive(name="Orient", args={"target": "cube"})]
        task.eval.success_conditions = ["pose_reached"]
    else:
        raise ValueError(f"Unknown subtask: {subtask}")


def _build_policy_config(
    base_policy: dict[str, Any],
    condition: str,
    geometry: ObjectGeometry,
    subtask: str,
) -> dict[str, Any]:
    """Construct the policy config for a given matrix condition and subtask."""
    cfg = dict(base_policy)
    cfg["policy_id"] = f"{cfg.get('policy_id', 'policy')}_{condition}_{subtask}"
    policy_config_dict = cfg.setdefault("policy_config_dict", {})

    # Reset condition-specific flags to clean slate.
    policy_config_dict["use_object_geometry_adaptation"] = False
    policy_config_dict.pop("object_geometry", None)
    policy_config_dict["enable_grip_quality_monitor"] = False
    policy_config_dict.pop("micro_recovery_strategy", None)
    policy_config_dict["enable_residual_policy"] = False
    policy_config_dict.pop("residual_policy", None)
    policy_config_dict.pop("residual_enabled_phases", None)
    policy_config_dict.pop("target_yaw_override", None)

    if condition == "baseline_v3":
        pass  # All disabled above.

    elif condition == "object_geometry_adapter":
        policy_config_dict["use_object_geometry_adaptation"] = True
        policy_config_dict["object_geometry"] = (
            _size_only_geometry(geometry).to_dict()
        )

    elif condition == "conditional_micro_recovery":
        policy_config_dict["enable_grip_quality_monitor"] = True
        policy_config_dict["micro_recovery_strategy"] = "lower_reclose"

    elif condition == "residual_seed24_guard":
        policy_config_dict["enable_residual_policy"] = True
        policy_config_dict["residual_policy"] = "seed24_guard"
        policy_config_dict["residual_enabled_phases"] = [
            "GRASP",
            "CONTACT_VERIFY",
            "PRE_LIFT",
        ]

    elif condition == "residual_slip_guard":
        policy_config_dict["enable_residual_policy"] = True
        policy_config_dict["residual_policy"] = "slip_guard"
        policy_config_dict["residual_enabled_phases"] = [
            "LIFT",
            "REORIENT",
            "ALIGN",
            "HOLD",
        ]

    elif condition == "best_combined":
        policy_config_dict["use_object_geometry_adaptation"] = True
        policy_config_dict["object_geometry"] = (
            _size_only_geometry(geometry).to_dict()
        )
        policy_config_dict["enable_grip_quality_monitor"] = True
        policy_config_dict["micro_recovery_strategy"] = "lower_reclose"
        policy_config_dict["enable_residual_policy"] = True
        policy_config_dict["residual_policy"] = "seed24_guard"
        policy_config_dict["residual_enabled_phases"] = [
            "GRASP",
            "CONTACT_VERIFY",
            "PRE_LIFT",
        ]

    else:
        raise ValueError(f"Unknown condition: {condition}")

    # Subtask yaw overrides.
    if subtask == "yaw_0":
        policy_config_dict["target_yaw_override"] = 0.0
    elif subtask == "yaw_90":
        policy_config_dict["target_yaw_override"] = 1.5708
    elif subtask == "yaw_120":
        policy_config_dict["target_yaw_override"] = 2.0944

    return cfg


def _compute_trace_bools(trace: list[dict[str, Any]]) -> dict[str, bool]:
    """Compute boolean metrics from trace records."""
    object_lifted = False
    grasp_reached = False
    slip_detected = False
    reachability_failure = False
    gripper_aperture_limit = False

    initial_object_z: float | None = None
    max_object_z: float | None = None

    for record in trace:
        # Object lifted: z increase > 0.03 m.
        obj_z = record.get("object_z")
        if obj_z is not None:
            if initial_object_z is None:
                initial_object_z = float(obj_z)
            max_object_z = max(max_object_z or float(obj_z), float(obj_z))

        # Grasp reached.
        phase = record.get("phase") or record.get("policy_phase") or ""
        if phase and "GRASP" in str(phase).upper():
            grasp_reached = True

        # Slip detected.
        slip_score = record.get("slip_score")
        if slip_score is not None and float(slip_score) > 0.5:
            slip_detected = True

        # Reachability failure.
        if phase and "REACHABILITY_FAILURE" in str(phase).upper():
            reachability_failure = True
        reason = record.get("reason") or record.get("failure_reason") or ""
        if reason and "reachability" in str(reason).lower():
            reachability_failure = True

        # Gripper aperture limit.
        if reason and (
            "aperture" in str(reason).lower()
            or "too wide" in str(reason).lower()
        ):
            gripper_aperture_limit = True

    if (
        initial_object_z is not None
        and max_object_z is not None
        and (max_object_z - initial_object_z) > LIFTED_HEIGHT_DELTA_M
    ):
        object_lifted = True

    return {
        "object_lifted": object_lifted,
        "grasp_reached": grasp_reached,
        "slip_detected": slip_detected,
        "reachability_failure": reachability_failure,
        "gripper_aperture_limit": gripper_aperture_limit,
    }


def _run_one(
    task_path: str,
    policy_config: dict[str, Any],
    seed: int,
    subtask: str,
    condition: str,
    out_dir: Path,
    cleanup: bool = False,
) -> dict[str, Any]:
    """Run one task/seed/subtask/condition and return a result row."""
    if cleanup:
        _cleanup_arena_containers()

    run_dir = out_dir / f"seed_{seed:03d}" / subtask / condition
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / "episode_trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    task = TaskLoader().load(task_path)
    if task.mutation is None:
        task.mutation = SimpleNamespace()
    task.mutation.seed = seed
    if not isinstance(task.metadata, dict):
        task.metadata = {}
    task.metadata.setdefault("asset_policy", {})
    task.metadata["asset_policy"]["allow_procedural_fallback"] = True
    task.metadata["asset_policy"]["require_official_asset"] = False
    task.metadata["asset_policy"]["diagnostic_variant"] = True

    # Apply subtask modifications in-memory.
    _apply_subtask(task, subtask)

    adapter = ArenaAdapter(task)
    result = adapter.run_policy(
        policy_config,
        episodes=1,
        max_steps=None,
        trace_dir=trace_dir,
    )

    metrics = result.metrics or {}
    trace = _load_trace(trace_path)
    trace_bools = _compute_trace_bools(trace)

    # Success rate from metrics.
    success_rate = metrics.get("success_rate")
    if success_rate is None:
        success_rate = 1.0 if result.status == "completed" else 0.0

    record: dict[str, Any] = {
        "task_id": task.id,
        "variant": Path(task_path).stem,
        "subtask": subtask,
        "condition": condition,
        "seed": seed,
        "status": result.status,
        "success_rate": success_rate,
        "object_lifted": trace_bools["object_lifted"],
        "grasp_reached": trace_bools["grasp_reached"],
        "slip_detected": trace_bools["slip_detected"],
        "reachability_failure": trace_bools["reachability_failure"],
        "gripper_aperture_limit": trace_bools["gripper_aperture_limit"],
        "run_id": result.run_id,
    }

    # Persist trace for later forensics.
    if trace_path.exists():
        shutil.copy(trace_path, run_dir / "trace.jsonl")

    return record


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
    """Serialize a CSV cell value."""
    if isinstance(value, (dict, list, bool)):
        return json.dumps(value)
    return str(value)


def _aggregate(
    rows: list[dict[str, Any]],
    task_paths: list[str],
    subtasks: list[str],
    conditions: list[str],
) -> dict[str, Any]:
    """Aggregate per-seed rows into per-(task,subtask,condition) summaries."""
    # Build a map from task_id to task_path for lookups.
    task_id_to_path: dict[str, str] = {}
    for task_path in task_paths:
        try:
            task = TaskLoader().load(task_path)
            task_id_to_path[task.id] = task_path
        except Exception:
            # If task_path is not a valid file, treat it as a raw task_id.
            task_id_to_path[task_path] = task_path

    # Group by key.
    by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in rows:
        key = (r["task_id"], r["subtask"], r["condition"])
        by_key.setdefault(key, []).append(r)

    summary: dict[str, Any] = {"by_task_subtask_condition": {}}

    for task_id in sorted({r["task_id"] for r in rows}):
        for subtask in subtasks:
            for condition in conditions:
                key = (task_id, subtask, condition)
                sub_rows = by_key.get(key, [])
                valid = [r for r in sub_rows if r.get("status") == "completed"]

                def _rate(field: str) -> float | None:
                    vals = [r.get(field) for r in valid if r.get(field) is not None]
                    if not vals:
                        return None
                    return sum(1 for v in vals if v) / len(vals)

                success_rate = None
                if valid:
                    success_rate = sum(
                        1.0
                        for r in valid
                        if (r.get("success_rate") or 0) >= 1.0
                    ) / len(valid)

                summary["by_task_subtask_condition"][
                    f"{task_id}__{subtask}__{condition}"
                ] = {
                    "task_id": task_id,
                    "subtask": subtask,
                    "condition": condition,
                    "count": len(valid),
                    "success_rate": success_rate,
                    "object_lifted_rate": _rate("object_lifted"),
                    "grasp_reached_rate": _rate("grasp_reached"),
                    "slip_rate": _rate("slip_detected"),
                    "reachability_failure_rate": _rate("reachability_failure"),
                    "gripper_aperture_limit_rate": _rate(
                        "gripper_aperture_limit"
                    ),
                }

    # Compute first_failing_subtask per task for baseline_v3.
    all_task_ids = sorted({r["task_id"] for r in rows})
    for task_id in all_task_ids:
        first_failing = None
        for subtask in _SUBTASK_ORDER:
            key = (task_id, subtask, "baseline_v3")
            sub_rows = by_key.get(key, [])
            valid = [r for r in sub_rows if r.get("status") == "completed"]
            if valid:
                sr = sum(1.0 for r in valid if (r.get("success_rate") or 0) >= 1.0) / len(valid)
                if sr < 1.0:
                    first_failing = subtask
                    break
        # Attach to each condition summary for this task.
        for condition in conditions:
            for subtask in subtasks:
                entry_key = f"{task_id}__{subtask}__{condition}"
                if entry_key in summary["by_task_subtask_condition"]:
                    summary["by_task_subtask_condition"][entry_key][
                        "first_failing_subtask"
                    ] = first_failing

    return summary


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    out_dir: Path = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    seeds = _parse_seeds(args.seeds)
    subtasks = [s.strip() for s in args.subtasks if s.strip()]
    conditions = [c.strip() for c in args.conditions if c.strip()]

    invalid_subtasks = [s for s in subtasks if s not in _DEFAULT_SUBTASKS]
    if invalid_subtasks:
        logger.error("Invalid subtasks: %s", invalid_subtasks)
        sys.exit(1)

    invalid_conditions = [c for c in conditions if c not in _DEFAULT_CONDITIONS]
    if invalid_conditions:
        logger.error("Invalid conditions: %s", invalid_conditions)
        sys.exit(1)

    # Dry-run: print matrix size and exit.
    if args.dry_run:
        total = len(args.tasks) * len(subtasks) * len(conditions) * len(seeds)
        print(
            f"Dry-run matrix: {len(args.tasks)} tasks x {len(subtasks)} subtasks x "
            f"{len(conditions)} conditions x {len(seeds)} seeds = {total} runs"
        )
        print(f"Tasks: {[Path(t).stem for t in args.tasks]}")
        print(f"Subtasks: {subtasks}")
        print(f"Conditions: {conditions}")
        print(f"Seeds: {seeds}")
        print(f"Out dir: {out_dir}")
        sys.exit(0)

    with open(args.policy, "r", encoding="utf-8") as f:
        base_policy = yaml.safe_load(f) or {}
    base_policy.setdefault("policy_id", Path(args.policy).stem)
    base_policy["policy_source"] = args.policy

    rows: list[dict[str, Any]] = []
    for task_path in args.tasks:
        task = TaskLoader().load(task_path)
        geometry = _geometry_from_task(task)

        for subtask in subtasks:
            for condition in conditions:
                logger.info(
                    "=== %s | subtask=%s | condition=%s ===",
                    task.id,
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
                            out_dir / task.id,
                            args.cleanup,
                        )
                    except Exception as exc:
                        logger.exception(
                            "Failed to run %s %s %s seed %d",
                            task.id,
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
                        }
                    rows.append(row)
                    print(json.dumps(row, indent=2, default=str))

    summary = _aggregate(rows, args.tasks, subtasks, conditions)
    summary["tasks"] = [Path(t).stem for t in args.tasks]
    summary["subtasks"] = subtasks
    summary["conditions"] = conditions
    summary["seeds"] = seeds
    summary["policy"] = args.policy
    summary["timestamp"] = (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )

    csv_path = out_dir / "per_seed_results.csv"
    json_path = out_dir / "aggregate_summary.json"
    _write_csv(rows, csv_path)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    logger.info("Aggregate summary written to %s", json_path)
    print("\n=== aggregate summary ===")
    print(json.dumps(summary, indent=2, default=str))
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Valid OOD cube baseline vs ObjectGeometryAdapter matrix.

Runs the promoted v1.7 policy across the seven rosclaw-validated OOD cube
variants under four conditions:

- baseline_no_adapter      : geometry adaptation disabled
- object_geometry_adapter  : size-only geometry adaptation
- adapter_mass_friction    : geometry + mass/friction-aware adaptation
- adapter_structural       : size-only geometry + structural FailureToHint hints

The purpose is to measure whether the ObjectGeometryAdapter and structural
hints actually improve performance on objects that differ in size, mass, and
friction, now that the object-validity gate has passed.
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
from rosclaw_darwin.evaluation.progress_metrics import compute_episode_metrics, summarize_episodes
from rosclaw_darwin.evolution.hint_recipe import HintRecipeRegistry
from rosclaw_darwin.tdl.loader import TaskLoader

_DEFAULT_TASKS = [
    "configs/tasks/goal_pose_rosclaw_valid_cube_004.yaml",
    "configs/tasks/goal_pose_rosclaw_valid_cube_005.yaml",
    "configs/tasks/goal_pose_rosclaw_valid_cube_006.yaml",
    "configs/tasks/goal_pose_rosclaw_valid_cube_008.yaml",
    "configs/tasks/goal_pose_rosclaw_valid_cube_010.yaml",
    "configs/tasks/goal_pose_rosclaw_valid_cube_low_friction.yaml",
    "configs/tasks/goal_pose_rosclaw_valid_cube_heavy.yaml",
]
_DEFAULT_POLICY = "configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml"
_DEFAULT_OUT_DIR = Path("data_v18/ablations/valid_ood_cube_matrix")
_DEFAULT_CONDITIONS = [
    "baseline_no_adapter",
    "object_geometry_adapter",
    "adapter_mass_friction",
    "adapter_structural",
]
_STRUCTURAL_HINT_TAGS = [
    "unstable_grasp",
    "grasped_but_not_lifted",
    "lifted_then_dropped",
    "object_not_lifted",
]

# Object height must increase by more than this to count as "lifted".
LIFTED_HEIGHT_DELTA_M = 0.03

# Safe Docker image name pattern (alphanumerics and common registry/delimiters).
_DOCKER_IMAGE_RE = re.compile(r"^[a-zA-Z0-9_.\-/:]+$")

logger = logging.getLogger(__name__)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Valid OOD cube baseline vs ObjectGeometryAdapter matrix"
    )
    parser.add_argument(
        "--tasks",
        type=str,
        nargs="+",
        default=_DEFAULT_TASKS,
        help="Valid OOD task configs to evaluate",
    )
    parser.add_argument("--policy", type=str, default=_DEFAULT_POLICY)
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    parser.add_argument(
        "--seeds",
        type=str,
        nargs="+",
        default=["0:19"],
        help="Seeds to evaluate (supports ranges like 0:19)",
    )
    parser.add_argument(
        "--conditions",
        type=str,
        nargs="+",
        default=_DEFAULT_CONDITIONS,
        help="Conditions to compare",
    )
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument(
        "--episodes-per-run",
        type=int,
        default=1,
        help="Run this many seeds/episodes in a single Arena container (amortizes startup).",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Kill lingering Arena containers before each seed.",
    )
    parser.add_argument(
        "--hint-rules",
        type=Path,
        default=Path("configs/skills/failure_signature_to_hint_rules.yaml"),
        help="Path to failure-signature-to-hint rules YAML (default: builtin v3.1 rules)",
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
                    raise ValueError(f"Seed range bounds must be non-negative: {part}")
                if start_i > end_i:
                    raise ValueError(f"Seed range start must be <= end: {part}")
                seeds.update(range(start_i, end_i + 1))
            else:
                seed_i = int(part)
                if seed_i < 0:
                    raise ValueError(f"Seed must be non-negative: {part}")
                seeds.add(seed_i)
    return sorted(seeds)


def _cleanup_arena_containers(image: str = "rosclaw-darwin:arena-base") -> int:
    if not _DOCKER_IMAGE_RE.fullmatch(image):
        raise ValueError(f"Refusing to cleanup containers for unsafe image name: {image!r}")
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
        else:
            logger.warning("Failed to kill container %s: %s", cid, kill_result.stderr.strip())
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
                        logger.warning("Skipping malformed trace line in %s: %s", trace_path, exc)
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
            static_friction=float(static_friction) if static_friction is not None else None,
        )

    return ObjectGeometry(
        object_name="object",
        asset_source="rosclaw_valid_cube",
        mass=float(mass) if mass is not None else None,
        static_friction=float(static_friction) if static_friction is not None else None,
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


def _build_policy_config(
    base_policy: dict[str, Any],
    condition: str,
    geometry: ObjectGeometry,
    hint_registry: HintRecipeRegistry | None,
) -> dict[str, Any]:
    """Construct the policy config for a given matrix condition."""
    cfg = dict(base_policy)
    cfg["policy_id"] = f"{cfg.get('policy_id', 'policy')}_{condition}"
    policy_config_dict = cfg.setdefault("policy_config_dict", {})

    if condition == "baseline_no_adapter":
        policy_config_dict["use_object_geometry_adaptation"] = False
        policy_config_dict.pop("object_geometry", None)

    elif condition == "object_geometry_adapter":
        policy_config_dict["use_object_geometry_adaptation"] = True
        policy_config_dict["object_geometry"] = _size_only_geometry(geometry).to_dict()

    elif condition == "adapter_mass_friction":
        policy_config_dict["use_object_geometry_adaptation"] = True
        policy_config_dict["object_geometry"] = geometry.to_dict()

    elif condition == "adapter_structural":
        policy_config_dict["use_object_geometry_adaptation"] = True
        policy_config_dict["object_geometry"] = _size_only_geometry(geometry).to_dict()
        if hint_registry is not None:
            selected_hints, _overrides, _, _, _, _ = hint_registry.select_hints(
                tags=_STRUCTURAL_HINT_TAGS,
                validated_only=False,
            )
            # NOTE: We intentionally do NOT merge recipe parameter_overrides here.
            # Several v3 recipe overrides (e.g. "squeeze_steps") do not map 1:1 to
            # the promoted policy's dataclass fields and would cause a config
            # validation crash.  The structural hints themselves already trigger
            # parameter adjustments inside the policy's __init__.
            base_hints = cfg.get("skill_hints", [])
            merged_hints = list(base_hints)
            for hint in selected_hints:
                if hint not in merged_hints:
                    merged_hints.append(hint)
            cfg["skill_hints"] = merged_hints

    return cfg


def _run_condition(
    task_path: str,
    policy_config: dict[str, Any],
    seed: int,
    condition: str,
    episodes: int,
    out_dir: Path,
    cleanup: bool = False,
) -> dict[str, Any]:
    """Run one task/seed/condition and return a result row."""
    if cleanup:
        _cleanup_arena_containers()

    run_dir = out_dir / f"seed_{seed:03d}" / condition
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

    adapter = ArenaAdapter(task)
    result = adapter.run_policy(
        policy_config,
        episodes=episodes,
        max_steps=None,
        trace_dir=trace_dir,
    )

    metrics = result.metrics or {}
    trace = _load_trace(trace_path)
    episode_metrics = compute_episode_metrics(trace) if trace else {}

    # Lifted = object height increased by more than the configured threshold.
    lifted = False
    if episode_metrics:
        lifted = (episode_metrics.get("object_height_delta") or 0) > LIFTED_HEIGHT_DELTA_M
    elif metrics.get("object_height_delta_mean") is not None:
        lifted = metrics["object_height_delta_mean"] > LIFTED_HEIGHT_DELTA_M

    record: dict[str, Any] = {
        "task_id": task.id,
        "condition": condition,
        "seed": seed,
        "status": result.status,
        "success": bool(episode_metrics.get("success")) if episode_metrics else (metrics.get("success_rate") == 1.0),
        "success_rate": metrics.get("success_rate"),
        "progress_mean": metrics.get("progress_mean"),
        "object_height_max_mean": metrics.get("object_height_max_mean"),
        "object_height_delta_mean": metrics.get("object_height_delta_mean"),
        "lifted": lifted,
        "eef_to_object_distance_min_mean": metrics.get("eef_to_object_distance_min_mean"),
        "grasp_phase_reached": episode_metrics.get("grasp_phase_reached") if episode_metrics else None,
        "lift_phase_reached": episode_metrics.get("lift_phase_reached") if episode_metrics else None,
        "target_reached": episode_metrics.get("target_reached") if episode_metrics else None,
        "failure_type": episode_metrics.get("failure_type") if episode_metrics else None,
        "episode_metrics": episode_metrics,
        "run_id": result.run_id,
    }

    # Persist trace and per-episode metrics for later forensics.
    if trace_path.exists():
        shutil.copy(trace_path, run_dir / "trace.jsonl")
        (run_dir / "episode_metrics.json").write_text(
            json.dumps(episode_metrics, indent=2, default=str)
        )

    return record


def _row_from_episode(
    task_id: str,
    condition: str,
    seed: int,
    status: str,
    ep_metrics: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    """Build a per-seed result row from a single episode metric dict."""
    # Lifted = object height increased by more than the configured threshold.
    lifted = (ep_metrics.get("object_height_delta") or 0) > LIFTED_HEIGHT_DELTA_M
    return {
        "task_id": task_id,
        "condition": condition,
        "seed": seed,
        "status": status,
        "success": bool(ep_metrics.get("success")),
        "success_rate": 1.0 if ep_metrics.get("success") else 0.0,
        "progress_mean": ep_metrics.get("progress"),
        "object_height_max_mean": ep_metrics.get("object_height_max"),
        "object_height_delta_mean": ep_metrics.get("object_height_delta"),
        "lifted": lifted,
        "eef_to_object_distance_min_mean": ep_metrics.get("eef_to_object_distance_min"),
        "grasp_phase_reached": ep_metrics.get("grasp_phase_reached"),
        "lift_phase_reached": ep_metrics.get("lift_phase_reached"),
        "target_reached": ep_metrics.get("target_reached"),
        "failure_type": ep_metrics.get("failure_type"),
        "episode_metrics": ep_metrics,
        "run_id": run_id,
    }


def _run_batch(
    task_path: str,
    policy_config: dict[str, Any],
    chunk_start: int,
    chunk_size: int,
    condition: str,
    out_dir: Path,
    cleanup: bool = False,
) -> list[dict[str, Any]]:
    """Run ``chunk_size`` seeds in one Arena container and return per-seed rows."""
    if cleanup:
        _cleanup_arena_containers()

    chunk_end = chunk_start + chunk_size - 1
    run_dir = out_dir / f"seed_{chunk_start:03d}_{chunk_end:03d}" / condition
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / "episode_trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    task = TaskLoader().load(task_path)
    if task.mutation is None:
        task.mutation = SimpleNamespace()
    task.mutation.seed = chunk_start
    if not isinstance(task.metadata, dict):
        task.metadata = {}
    task.metadata.setdefault("asset_policy", {})
    task.metadata["asset_policy"]["allow_procedural_fallback"] = True
    task.metadata["asset_policy"]["require_official_asset"] = False
    task.metadata["asset_policy"]["diagnostic_variant"] = True

    adapter = ArenaAdapter(task)
    result = adapter.run_policy(
        policy_config,
        episodes=chunk_size,
        max_steps=None,
        trace_dir=trace_dir,
    )

    # Persist the combined trace for the chunk.
    if trace_path.exists():
        shutil.copy(trace_path, run_dir / "trace.jsonl")

    episode_metrics_list = (result.metadata or {}).get("episode_metrics")
    if isinstance(episode_metrics_list, list) and len(episode_metrics_list) == chunk_size:
        rows = []
        for i, ep_metrics in enumerate(episode_metrics_list):
            (run_dir / f"episode_metrics_seed_{chunk_start + i:03d}.json").write_text(
                json.dumps(ep_metrics, indent=2, default=str)
            )
            rows.append(
                _row_from_episode(
                    task.id,
                    condition,
                    chunk_start + i,
                    result.status,
                    ep_metrics,
                    result.run_id,
                )
            )
        return rows

    # Fallback: if per-episode metrics are unavailable, emit one row for the chunk.
    return [
        {
            "task_id": task.id,
            "condition": condition,
            "seed": chunk_start,
            "status": result.status,
            "success": False,
            "success_rate": None,
            "lifted": False,
            "episode_metrics": {},
            "run_id": result.run_id,
            "note": f"expected {chunk_size} episode_metrics, got {len(episode_metrics_list) if isinstance(episode_metrics_list, list) else None}",
        }
    ]


def _aggregate(rows: list[dict[str, Any]], conditions: list[str]) -> dict[str, Any]:
    """Aggregate per-seed rows into per-condition and per-task summaries."""
    by_condition: dict[str, list[dict[str, Any]]] = {c: [] for c in conditions}
    by_task_condition: dict[tuple[str, str], list[dict[str, Any]]] = {}
    episode_metrics_by_condition: dict[str, list[dict[str, Any]]] = {c: [] for c in conditions}

    for r in rows:
        condition = r["condition"]
        task_id = r["task_id"]
        by_condition.setdefault(condition, []).append(r)
        by_task_condition.setdefault((task_id, condition), []).append(r)
        if r.get("episode_metrics"):
            episode_metrics_by_condition.setdefault(condition, []).append(r["episode_metrics"])

    summary: dict[str, Any] = {
        "by_condition": {},
        "by_task_condition": {},
        "episode_summary_by_condition": {},
    }

    for condition in conditions:
        sub = [r for r in by_condition.get(condition, []) if r.get("status") == "completed"]
        successes = [r for r in sub if r.get("success")]
        lifted = [r for r in sub if r.get("lifted")]
        progresses = [r.get("progress_mean") for r in sub if r.get("progress_mean") is not None]
        summary["by_condition"][condition] = {
            "count": len(sub),
            "success_rate": len(successes) / len(sub) if sub else None,
            "lifted_rate": len(lifted) / len(sub) if sub else None,
            "mean_progress": sum(progresses) / len(progresses) if progresses else None,
        }
        if episode_metrics_by_condition.get(condition):
            summary["episode_summary_by_condition"][condition] = summarize_episodes(
                episode_metrics_by_condition[condition]
            )

    for (task_id, condition), sub in by_task_condition.items():
        valid = [r for r in sub if r.get("status") == "completed"]
        successes = [r for r in valid if r.get("success")]
        lifted = [r for r in valid if r.get("lifted")]
        summary["by_task_condition"][f"{task_id}__{condition}"] = {
            "task_id": task_id,
            "condition": condition,
            "count": len(valid),
            "success_rate": len(successes) / len(valid) if valid else None,
            "lifted_rate": len(lifted) / len(valid) if valid else None,
        }

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
    """Serialize a CSV cell value."""
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

    with open(args.policy, "r", encoding="utf-8") as f:
        base_policy = yaml.safe_load(f) or {}
    base_policy.setdefault("policy_id", Path(args.policy).stem)
    base_policy["policy_source"] = args.policy

    if "adapter_structural" in conditions:
        if args.hint_rules is None or not args.hint_rules.exists():
            logger.error(
                "--hint-rules must point to an existing YAML file when adapter_structural is used"
            )
            sys.exit(1)

    hint_registry: HintRecipeRegistry | None = None
    if "adapter_structural" in conditions:
        hint_registry = HintRecipeRegistry.from_yaml(args.hint_rules)

    rows: list[dict[str, Any]] = []
    for task_path in args.tasks:
        task = TaskLoader().load(task_path)
        geometry = _geometry_from_task(task)

        for condition in conditions:
            logger.info("=== %s condition %s ===", task.id, condition)
            policy_config = _build_policy_config(
                base_policy, condition, geometry, hint_registry
            )

            if args.episodes_per_run <= 1:
                for seed in seeds:
                    logger.info("--- seed %d ---", seed)
                    try:
                        row = _run_condition(
                            task_path,
                            policy_config,
                            seed,
                            condition,
                            args.episodes,
                            out_dir / task.id,
                            args.cleanup,
                        )
                    except Exception as exc:
                        logger.exception("Failed to run %s %s seed %d", task.id, condition, seed)
                        row = {
                            "task_id": task.id,
                            "condition": condition,
                            "seed": seed,
                            "status": f"error: {exc}",
                            "success": False,
                            "success_rate": None,
                            "lifted": False,
                        }
                    rows.append(row)
                    print(json.dumps(row, indent=2, default=str))
            else:
                for i in range(0, len(seeds), args.episodes_per_run):
                    chunk = seeds[i : i + args.episodes_per_run]
                    chunk_start = chunk[0]
                    chunk_end = chunk[-1]
                    logger.info(
                        "--- seeds %d:%d (%d episodes) ---",
                        chunk_start,
                        chunk_end,
                        len(chunk),
                    )
                    try:
                        chunk_rows = _run_batch(
                            task_path,
                            policy_config,
                            chunk_start,
                            len(chunk),
                            condition,
                            out_dir / task.id,
                            args.cleanup,
                        )
                    except Exception as exc:
                        logger.exception(
                            "Failed to run %s %s seeds %d:%d",
                            task.id,
                            condition,
                            chunk_start,
                            chunk_end,
                        )
                        chunk_rows = [
                            {
                                "task_id": task.id,
                                "condition": condition,
                                "seed": chunk_start,
                                "status": f"error: {exc}",
                                "success": False,
                                "success_rate": None,
                                "lifted": False,
                            }
                        ]
                    rows.extend(chunk_rows)
                    for row in chunk_rows:
                        print(json.dumps(row, indent=2, default=str))

    summary = _aggregate(rows, conditions)
    summary["tasks"] = [Path(t).stem for t in args.tasks]
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

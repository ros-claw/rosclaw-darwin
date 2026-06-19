#!/usr/bin/env python3
"""Closed-loop FailureToHint v3 demo on procedural OOD seeds.

For each seed the script:
  1. Runs the base v3 policy on the procedural adaptive task.
  2. Infers a FailureSignature v3 from the saved trace.
  3. Queries FailureToHintEngine for hints + parameter overrides.
  4. Re-runs the same seed with the hinted config.
  5. Records base vs hinted metrics.

This is intentionally sequential because concurrent Arena Docker runs still
suffer from GPU/container resource contention.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import time
from pathlib import Path
from typing import Any

import yaml

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.evaluation.failure_signature import infer_failure_signature
from rosclaw_darwin.evaluation.result import EvaluationResult
from rosclaw_darwin.evolution.failure_to_hint import FailureToHintEngine
from rosclaw_darwin.evolution.hint_recipe import HintRecipeRegistry
from rosclaw_darwin.tdl.loader import TaskLoader

_DEFAULT_TASK = "configs/tasks/goal_pose_procedural_cube_adaptive.yaml"
_DEFAULT_BASE_POLICY = "configs/policies/heuristic_servo_goal_pose_v3.yaml"
_DEFAULT_OUT_DIR = Path("/tmp/rosclaw_data/failure_to_hint_procedural_loop")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FailureToHint v3 closed-loop demo on procedural OOD seeds"
    )
    parser.add_argument("--task", default=_DEFAULT_TASK, help="Procedural adaptive task config")
    parser.add_argument("--base-policy", default=_DEFAULT_BASE_POLICY, help="Base policy config")
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR, help="Output directory")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(10)), help="Seeds")
    parser.add_argument("--rules", default=None, help="Optional failure_to_hint_rules.yaml path")
    parser.add_argument("--recipes", default=None, help="Optional hint_recipes.yaml path")
    return parser.parse_args()


def _load_trace(trace_path: Path) -> list[dict[str, Any]]:
    if not trace_path.exists():
        return []
    records: list[dict[str, Any]] = []
    with trace_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    return records


def _run_seed(
    task_path: str,
    policy_config: dict[str, Any],
    seed: int,
    out_dir: Path,
) -> tuple[EvaluationResult, Path]:
    run_dir = out_dir / f"seed_{seed}"
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = run_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / "episode_trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    task = TaskLoader().load(task_path)
    task.mutation.seed = seed

    adapter = ArenaAdapter(task)
    result = adapter.run_policy(
        policy_config,
        episodes=1,
        max_steps=None,
        trace_dir=trace_dir,
    )

    if trace_path.exists():
        policy_name = Path(policy_config.get("policy_id", "policy")).stem
        stamped = run_dir / f"{policy_name}_seed{seed}_{int(time.time())}.jsonl"
        shutil.copy(trace_path, stamped)

    return result, trace_path


def _build_episode_metrics(result: EvaluationResult) -> dict[str, Any]:
    metrics = result.metrics or {}
    success = bool(metrics.get("success_rate") == 1.0)
    return {
        "episode_id": 0,
        "success": success,
        "failure_type": "unknown_failure" if not success else "success",
        "progress": metrics.get("progress_mean", 0.0),
        "eef_to_object_distance_min": metrics.get("eef_to_object_distance_min_mean"),
        "eef_to_object_distance_final": metrics.get("eef_to_object_distance_final_mean"),
        "object_height_initial": metrics.get("object_height_initial_mean"),
        "object_height_max": metrics.get("object_height_max_mean"),
        "object_height_final": metrics.get("object_height_final_mean"),
        "object_height_delta": metrics.get("object_height_delta_mean"),
        "gripper_pos_min": metrics.get("gripper_pos_min_mean"),
        "gripper_pos_final": metrics.get("gripper_pos_final_mean"),
        "object_to_target_distance_final": metrics.get("object_to_target_distance_final_mean"),
        "orientation_error_final": metrics.get("orientation_error_final_mean"),
    }


def _extract_hints(
    task: Any,
    result: EvaluationResult,
    trace: list[dict[str, Any]],
    engine: FailureToHintEngine,
    recipe_registry: HintRecipeRegistry,
) -> list[Any]:
    episode_metrics = _build_episode_metrics(result)
    phase_trace = [r.get("phase") for r in trace if r.get("phase") is not None]
    signature = infer_failure_signature(
        task=task,
        episode_metrics=episode_metrics,
        phase_trace=phase_trace,
        trace=trace,
    )
    return engine.suggest_from_signatures(
        [signature],
        recipe_registry=recipe_registry,
        task_id=task.id,
    )


# Recipe parameter names are generic; map them to the actual policy config keys
# used by HeuristicServoGoalPosePolicy so the overrides are consumed instead of
# causing unknown-field errors.
_RECIPE_PARAM_MAP: dict[str, str] = {
    "squeeze_steps": "grasp_squeeze_steps",
    "grip_hold_strength": "gripper_close_threshold",
    "lift_xy_gain": "lift_horizontal_scale",
    "final_align_speed": "align_max_delta",
    "hold_steps": "min_release_steps",
    "rotate_before_lift": "pre_grasp_orient",
}


def _apply_hints(
    base_config: dict[str, Any],
    hints: list[Any],
) -> dict[str, Any]:
    hinted = copy.deepcopy(base_config)
    hinted["policy_id"] = f"{hinted.get('policy_id', 'policy')}_hinted"
    hinted.setdefault("skill_hints", [])
    policy_dict = hinted.setdefault("policy_config_dict", {})

    for hint in hints:
        name = hint.name
        overrides = hint.parameter_overrides
        if name and name not in hinted["skill_hints"]:
            hinted["skill_hints"].append(name)
        if overrides:
            for key, value in overrides.items():
                mapped_key = _RECIPE_PARAM_MAP.get(key, key)
                policy_dict[mapped_key] = value

    return hinted


def _summarize(result: EvaluationResult) -> dict[str, Any]:
    metrics = result.metrics or {}
    return {
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


def main() -> None:
    args = parse_args()
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(args.base_policy, "r", encoding="utf-8") as f:
        base_policy = yaml.safe_load(f) or {}
    base_policy.setdefault("policy_id", Path(args.base_policy).stem)

    engine = FailureToHintEngine.from_yaml(args.rules)
    recipe_registry = HintRecipeRegistry.from_yaml(args.recipes)
    task = TaskLoader().load(args.task)

    rows: list[dict[str, Any]] = []
    for seed in args.seeds:
        print(f"\n=== seed {seed} ===")
        row: dict[str, Any] = {"seed": seed}

        # Base run.
        base_result, trace_path = _run_seed(args.task, base_policy, seed, out_dir)
        base_trace = _load_trace(trace_path)
        row["base"] = _summarize(base_result)

        hints = _extract_hints(task, base_result, base_trace, engine, recipe_registry)
        row["hints"] = [
            {
                "name": h.name,
                "source": h.source,
                "source_recipe": h.source_recipe,
                "confidence": h.confidence,
                "rationale": h.rationale,
                "parameter_overrides": h.parameter_overrides,
            }
            for h in hints
        ]

        if not hints:
            row["hinted"] = {"status": "skipped_no_hints"}
            rows.append(row)
            print(json.dumps(row, indent=2, default=str))
            continue

        hinted_policy = _apply_hints(base_policy, hints)
        hinted_result, _ = _run_seed(args.task, hinted_policy, seed, out_dir)
        row["hinted"] = _summarize(hinted_result)

        base_success = row["base"].get("success_rate") == 1.0
        hinted_success = row["hinted"].get("success_rate") == 1.0
        base_lifted = (row["base"].get("object_height_delta_mean") or 0) > 0.02
        hinted_lifted = (row["hinted"].get("object_height_delta_mean") or 0) > 0.02
        row["comparison"] = {
            "success_improved": hinted_success and not base_success,
            "lifted_improved": hinted_lifted and not base_lifted,
            "progress_delta": (row["hinted"].get("progress_mean") or 0)
            - (row["base"].get("progress_mean") or 0),
        }

        rows.append(row)
        print(json.dumps(row, indent=2, default=str))

    summary = {
        "seeds": args.seeds,
        "task": args.task,
        "base_policy": args.base_policy,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total": len(rows),
        "success_improved_count": sum(1 for r in rows if r.get("comparison", {}).get("success_improved")),
        "lifted_improved_count": sum(1 for r in rows if r.get("comparison", {}).get("lifted_improved")),
        "mean_progress_delta": sum(
            r.get("comparison", {}).get("progress_delta", 0) for r in rows
        )
        / len(rows)
        if rows
        else None,
        "rows": rows,
    }

    summary_path = out_dir / "closed_loop_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print("\n=== closed-loop summary ===")
    print(json.dumps(summary, indent=2, default=str))
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()

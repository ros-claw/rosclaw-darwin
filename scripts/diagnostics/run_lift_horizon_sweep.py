#!/usr/bin/env python3
"""Diagnostic horizon sweep for lift_object.

Runs the same policy with increasing rollout lengths to determine whether the
policy is making progress or is fundamentally stuck. Results are marked as
``comparable_to_official=false`` because the horizon is intentionally varied.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.evaluation.report import save_run_result
from rosclaw_darwin.tdl.loader import TaskLoader
from rosclaw_darwin.utils.paths import ensure_dir


def _load_policy_config(path: str) -> dict[str, Any]:
    import yaml

    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("policy_id", Path(path).stem)
    return cfg


def _extract_progress(result: Any) -> dict[str, Any]:
    metrics = result.metrics or {}
    meta = result.metadata or {}
    arena_output = meta.get("arena_metrics_output", {})
    return {
        "run_id": result.run_id,
        "success_rate": metrics.get("success_rate", arena_output.get("success_rate", 0.0)),
        "progress_mean": metrics.get("progress_mean", arena_output.get("progress_mean", 0.0)),
        "eef_to_object_distance_min_mean": metrics.get(
            "eef_to_object_distance_min_mean",
            arena_output.get("eef_to_object_distance_min_mean"),
        ),
        "eef_to_object_distance_final_mean": metrics.get(
            "eef_to_object_distance_final_mean",
            arena_output.get("eef_to_object_distance_final_mean"),
        ),
        "object_height_max_mean": metrics.get(
            "object_height_max_mean",
            arena_output.get("object_height_max_mean"),
        ),
        "object_height_delta_mean": metrics.get(
            "object_height_delta_mean",
            arena_output.get("object_height_delta_mean"),
        ),
        "failure_counts": arena_output.get("failure_counts", {}),
        "num_episodes_observed": arena_output.get("num_episodes", metrics.get("num_episodes", 0)),
    }


def _mean(values: list[float | None]) -> float | None:
    numeric = [v for v in values if v is not None]
    return round(sum(numeric) / len(numeric), 4) if numeric else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Horizon sweep diagnostic for lift_object")
    parser.add_argument("--task", default="examples/tasks/native/lift_object.yaml")
    parser.add_argument("--policy", default="configs/policies/heuristic_servo_lift.yaml")
    parser.add_argument("--steps", default="100,200,400,800")
    parser.add_argument("--episodes", type=int, default=3)
    parser.add_argument("--out", default="/tmp/rosclaw_data/diagnostics/lift_horizon_sweep")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    out_dir = ensure_dir(args.out)
    task = TaskLoader().load(args.task)
    policy_config = _load_policy_config(args.policy)
    if args.dry_run:
        policy_config["dry_run"] = True

    adapter = ArenaAdapter(task)
    steps_list = [int(s.strip()) for s in args.steps.split(",") if s.strip()]

    sweep_results: list[dict[str, Any]] = []
    run_records: list[dict[str, Any]] = []

    for steps in steps_list:
        group_records: list[dict[str, Any]] = []
        console_msg = f"[horizon sweep] steps={steps}, episodes={args.episodes}"
        print(console_msg)
        for ep in range(args.episodes):
            result = adapter.run_policy(policy_config, episodes=None, max_steps=steps)
            run_dir = out_dir / result.run_id
            save_run_result(
                run_dir=run_dir,
                result=result,
                task_yaml=task.to_yaml(),
                policy_config=policy_config,
            )
            record = {
                "steps": steps,
                "episode_index": ep,
                **_extract_progress(result),
                "status": result.status,
                "metric_scope": result.metric_scope.value,
                "claim_level": result.claim_level.value,
                "leaderboard_excluded": result.leaderboard_excluded,
            }
            group_records.append(record)
            run_records.append(record)
            print(f"  run={result.run_id} success_rate={record['success_rate']} progress={record['progress_mean']} status={result.status}")

        sweep_results.append({
            "steps": steps,
            "eval_setting": "diagnostic_horizon_sweep",
            "comparable_to_official": False,
            "success_rate_mean": _mean([r["success_rate"] for r in group_records]),
            "progress_mean": _mean([r["progress_mean"] for r in group_records]),
            "eef_to_object_distance_min_mean": _mean([r["eef_to_object_distance_min_mean"] for r in group_records]),
            "eef_to_object_distance_final_mean": _mean([r["eef_to_object_distance_final_mean"] for r in group_records]),
            "object_height_max_mean": _mean([r["object_height_max_mean"] for r in group_records]),
            "object_height_delta_mean": _mean([r["object_height_delta_mean"] for r in group_records]),
            "failure_counts": _merge_failure_counts([r["failure_counts"] for r in group_records]),
            "runs": group_records,
        })

    summary = {
        "sweep_id": f"horizon_sweep_{int(time.time())}",
        "task_id": task.id,
        "policy_id": policy_config["policy_id"],
        "steps_list": steps_list,
        "episodes_per_step": args.episodes,
        "eval_setting": "diagnostic_horizon_sweep",
        "comparable_to_official": False,
        "groups": sweep_results,
        "all_runs": run_records,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    report_path = Path("reports/LIFT_OBJECT_HORIZON_SWEEP_REPORT.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(summary))
    print(f"[horizon sweep] summary saved to {out_dir / 'summary.json'}")
    print(f"[horizon sweep] report saved to {report_path}")


def _merge_failure_counts(counts_list: list[dict[str, int]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for counts in counts_list:
        for k, v in counts.items():
            merged[k] = merged.get(k, 0) + v
    return merged


def _render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Lift Object Horizon Sweep Report",
        "",
        "## Purpose",
        "",
        "Determine whether ``heuristic_servo_lift`` fails because the default Arena",
        "episode horizon is too short, or because the policy/controller is",
        "fundamentally unable to reach the object.",
        "",
        "## Settings",
        "",
        f"- Task: ``{summary['task_id']}``",
        f"- Policy: ``{summary['policy_id']}``",
        f"- Steps per rollout: {summary['steps_list']}",
        f"- Rollouts per step count: {summary['episodes_per_step']}",
        f"- Eval setting: ``{summary['eval_setting']}``",
        f"- Comparable to official benchmark: ``{summary['comparable_to_official']}``",
        "",
        "## Results",
        "",
        "| steps | success_rate | progress | eef_min ↓ | eef_final ↓ | object_height_max ↑ | object_height_delta ↑ | dominant_failure |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for group in summary["groups"]:
        failures = group["failure_counts"]
        dominant = max(failures, key=failures.get) if failures else "n/a"
        lines.append(
            f"| {group['steps']} | {group['success_rate_mean']} | {group['progress_mean']} | "
            f"{group['eef_to_object_distance_min_mean']} | {group['eef_to_object_distance_final_mean']} | "
            f"{group['object_height_max_mean']} | {group['object_height_delta_mean']} | {dominant} |"
        )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "- If ``progress`` and ``eef_min`` improve monotonically with longer rollouts,",
        "  the default 5 s / ~100-step horizon is the limiting factor.",
        "- If ``eef_min`` stays large even at 800 steps, the action mapping or",
        "  controller damping prevents the arm from reaching the object.",
        "- If the arm reaches the object but ``object_height_delta`` stays near zero,",
        "  the problem is grasp/contact physics rather than horizon.",
        "",
        "## Conclusion",
        "",
        "This is a diagnostic sweep. It must not be reported as an official benchmark",
        "result because the episode length was intentionally varied.",
        "",
    ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()

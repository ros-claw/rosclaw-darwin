#!/usr/bin/env python3
"""With-hint / without-hint ablation for lift_object.

Compares three conditions:
  A. heuristic_servo_lift without hints
  B. heuristic_servo_lift with manual hints
  C. heuristic_servo_lift with auto-generated hints from Loop 1 failure

Produces transfer-gain metrics and an honest conclusion.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.evaluation.policy_metadata import load_policy_metadata
from rosclaw_darwin.evaluation.report import save_run_result
from rosclaw_darwin.evolution.failure_to_hint import FailureToHintEngine
from rosclaw_darwin.tdl.loader import TaskLoader
from rosclaw_darwin.utils.paths import ensure_dir


def _extract(result: Any) -> dict[str, Any]:
    m = result.metrics or {}
    am = result.metadata.get("arena_metrics_output", {})
    return {
        "success_rate": m.get("success_rate", am.get("success_rate", 0.0)),
        "progress": m.get("progress_mean", am.get("progress_mean", 0.0)),
        "eef_to_object_distance_initial": m.get(
            "eef_to_object_distance_initial_mean",
            am.get("eef_to_object_distance_initial_mean"),
        ),
        "eef_to_object_distance_min": m.get(
            "eef_to_object_distance_min_mean",
            am.get("eef_to_object_distance_min_mean"),
        ),
        "eef_to_object_distance_final": m.get(
            "eef_to_object_distance_final_mean",
            am.get("eef_to_object_distance_final_mean"),
        ),
        "eef_to_object_distance_delta": (
            (m.get("eef_to_object_distance_initial_mean") or 0)
            - (m.get("eef_to_object_distance_final_mean") or 0)
        ),
        "object_height_max": m.get("object_height_max_mean", am.get("object_height_max_mean")),
        "object_height_delta": m.get("object_height_delta_mean", am.get("object_height_delta_mean")),
        "failure_counts": result.failure_types or am.get("failure_counts", {}),
        "num_episodes": m.get("num_episodes", am.get("num_episodes", 0)),
        "run_id": result.run_id,
        "status": result.status,
        "metric_scope": result.metric_scope.value,
        "claim_level": result.claim_level.value,
        "leaderboard_excluded": result.leaderboard_excluded,
    }


def _run_condition(label: str, adapter: ArenaAdapter, base_config: dict, episodes: int, max_steps: int | None, extra: dict) -> Any:
    config = dict(base_config)
    config.update(extra)
    print(f"[ablation] {label}")
    result = adapter.run_policy(config, episodes=episodes, max_steps=max_steps)
    print(f"  success_rate={result.metrics.get('success_rate')} progress={result.metrics.get('progress_mean')} failure={result.failure_types}")
    # Brief pause between Docker runs to avoid HDF5 recording lock collisions.
    time.sleep(5)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Skill hint ablation for lift_object")
    parser.add_argument("--task", default="examples/tasks/native/lift_object.yaml")
    parser.add_argument("--policy", default="configs/policies/heuristic_servo_lift.yaml")
    parser.add_argument("--episodes", type=int, default=20)
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--manual-hints", default="grasp_adjust,efficient_execution,adaptive_skill")
    parser.add_argument("--manual-policy", default=None, help="Optional policy config YAML to use for the manual-hints condition (overrides --manual-hints).")
    parser.add_argument("--out", default="/tmp/rosclaw_data/ablations/lift_skill_hints")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    out_dir = ensure_dir(args.out)
    task = TaskLoader().load(args.task)
    import yaml

    with open(args.policy, "r", encoding="utf-8") as f:
        base_config = yaml.safe_load(f) or {}
    base_config.setdefault("policy_id", Path(args.policy).stem)
    if args.dry_run:
        base_config["dry_run"] = True

    # Clear any stale HDF5 recording locks from previous Arena Docker runs.
    hdf5_dir = Path("/tmp/rosclaw_data/hdf5")
    if hdf5_dir.exists():
        for child in hdf5_dir.iterdir():
            try:
                if child.is_dir():
                    import shutil

                    shutil.rmtree(child)
                else:
                    child.unlink()
            except Exception:
                pass

    adapter = ArenaAdapter(task)
    policy_metadata = load_policy_metadata(base_config)

    # A. Without hints
    result_no = _run_condition("without_hints", adapter, base_config, args.episodes, args.max_steps, {})

    # B. With manual hints (either an explicit tuned config or skill-hint overrides)
    if args.manual_policy:
        with open(args.manual_policy, "r", encoding="utf-8") as f:
            manual_config = yaml.safe_load(f) or {}
        manual_config.setdefault("policy_id", Path(args.manual_policy).stem)
        if args.dry_run:
            manual_config["dry_run"] = True
        result_manual = _run_condition(
            "manual_hints",
            adapter,
            manual_config,
            args.episodes,
            args.max_steps,
            {},
        )
    else:
        manual_hints = [h.strip() for h in args.manual_hints.split(",") if h.strip()]
        result_manual = _run_condition(
            "manual_hints",
            adapter,
            base_config,
            args.episodes,
            args.max_steps,
            {"skill_hints": manual_hints},
        )

    # C. Auto hints: generate from no-hint failure counts, then rerun.
    engine = FailureToHintEngine.from_yaml()
    auto_hints = [h.name for h in engine.suggest_from_result(result_no)]
    result_auto = _run_condition(
        "auto_hints",
        adapter,
        base_config,
        args.episodes,
        args.max_steps,
        {"skill_hints": auto_hints},
    )

    for res in (result_no, result_manual, result_auto):
        run_dir = out_dir / res.run_id
        save_run_result(
            run_dir=run_dir,
            result=res,
            task_yaml=task.to_yaml(),
            policy_config=base_config,
        )

    no = _extract(result_no)
    manual = _extract(result_manual)
    auto = _extract(result_auto)

    transfer = {
        "manual": _compute_transfer_gain(no, manual),
        "auto": _compute_transfer_gain(no, auto),
    }

    summary = {
        "ablation_id": f"skill_hint_ablation_{int(time.time())}",
        "task_id": task.id,
        "policy_id": base_config["policy_id"],
        "episodes": args.episodes,
        "max_steps": args.max_steps,
        "eval_setting": "ablation",
        "comparable_to_official": args.max_steps is None,
        "without_hints": no,
        "manual_hints": manual,
        "auto_hints": {
            **auto,
            "generated_hint_names": auto_hints,
            "generation_source": "failure_to_hint",
        },
        "transfer_gain": transfer,
        "policy_metadata": policy_metadata.model_dump(mode="json"),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    report_path = Path("reports/SKILL_HINT_PROGRESS_ABLATION_REPORT.md")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(summary))
    print(f"[ablation] summary saved to {out_dir / 'summary.json'}")
    print(f"[ablation] report saved to {report_path}")


def _compute_transfer_gain(baseline: dict, variant: dict) -> dict[str, Any]:
    def _delta(key: str) -> float | None:
        b = baseline.get(key)
        v = variant.get(key)
        if b is None or v is None:
            return None
        return round(float(v) - float(b), 4)

    return {
        "transfer_gain_success": _delta("success_rate"),
        "transfer_gain_progress": _delta("progress"),
        "transfer_gain_distance": _delta("eef_to_object_distance_delta"),
        "transfer_gain_height": _delta("object_height_delta"),
    }


def _render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Skill Hint Progress Ablation Report",
        "",
        f"- Task: ``{summary['task_id']}``",
        f"- Policy: ``{summary['policy_id']}``",
        f"- Episodes per condition: {summary['episodes']}",
        f"- Max steps per episode: {summary['max_steps']}",
        f"- Comparable to official benchmark: ``{summary['comparable_to_official']}``",
        "",
        "## Results",
        "",
        "| condition | success_rate | progress | eef_min ↓ | object_height_delta ↑ | failure_counts |",
        "|---|---|---|---|---|---|",
    ]
    for cond in ("without_hints", "manual_hints", "auto_hints"):
        r = summary[cond]
        lines.append(
            f"| {cond} | {r['success_rate']} | {r['progress']} | {r['eef_to_object_distance_min']} | "
            f"{r['object_height_delta']} | {r['failure_counts']} |"
        )
    lines.extend([
        "",
        "## Transfer Gain (variant - baseline)",
        "",
        "| comparison | Δsuccess | Δprogress | Δdistance | Δheight |",
        "|---|---|---|---|---|",
    ])
    for comp, gains in summary["transfer_gain"].items():
        lines.append(
            f"| {comp} | {gains['transfer_gain_success']} | {gains['transfer_gain_progress']} | "
            f"{gains['transfer_gain_distance']} | {gains['transfer_gain_height']} |"
        )
    lines.extend([
        "",
        "## Honest Conclusion",
        "",
        "If transfer gains are positive, the consumed hints produced measurable progress.",
        "If all gains are zero or negative, the hints were consumed but did not transfer",
        "to improved performance on this task within the evaluated horizon.",
        "",
    ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()

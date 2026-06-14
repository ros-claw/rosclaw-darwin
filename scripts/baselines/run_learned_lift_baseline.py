#!/usr/bin/env python3
"""Run pretrained RSL-RL baselines on the real Arena lift_object task.

This script compares the existing heuristic servo baseline with available
learned RSL-RL checkpoints. It is the next concrete step after the follow-up
outline's infrastructure work: a faster controller that can actually close the
loop and produce real evolution evidence.

Usage:
    export ROSCLAW_ARENA_MODE=docker
    python scripts/baselines/run_learned_lift_baseline.py \
        --episodes 5 --out /tmp/rosclaw_data/baselines/learned_lift
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.evaluation.result import EvaluationResult
from rosclaw_darwin.tdl.loader import TaskLoader

REPO_ROOT = Path(__file__).parents[2]
TASK_PATH = REPO_ROOT / "examples" / "tasks" / "native" / "lift_object.yaml"

# Learned checkpoints mounted into the Arena container.
# `lift_object_model.pt` in test_data is a TorchScript export, not an RSL-RL
# checkpoint, so it is intentionally omitted here.
DEFAULT_VARIANTS: list[dict[str, Any]] = [
    {
        "policy_id": "rsl_rl_lift_object_rsl_rl",
        "type": "rsl_rl",
        "policy_config_dict": {
            "checkpoint_path": "/workspace/isaaclab_arena/logs/rsl_rl/lift_object_rsl_rl/2026-06-07_14-35-00_run_001/model_999.pt",
            "device": "cuda:0",
        },
    },
    {
        "policy_id": "rsl_rl_lift_object_joint_pos",
        "type": "rsl_rl",
        "policy_config_dict": {
            "checkpoint_path": "/workspace/isaaclab_arena/logs/rsl_rl/lift_object_joint_pos/2026-06-09_00-39-14/model_13400.pt",
            "device": "cuda:0",
        },
    },
]


@dataclass
class VariantResult:
    """Result for a single policy variant."""

    policy_id: str
    checkpoint: str
    status: str
    success_rate: float
    progress_mean: float
    eef_to_object_distance_min_mean: float | None
    object_height_delta_mean: float | None
    failure_types: dict[str, int]
    error: str | None
    result: EvaluationResult | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "checkpoint": self.checkpoint,
            "status": self.status,
            "success_rate": self.success_rate,
            "progress_mean": self.progress_mean,
            "eef_to_object_distance_min_mean": self.eef_to_object_distance_min_mean,
            "object_height_delta_mean": self.object_height_delta_mean,
            "failure_types": self.failure_types,
            "error": self.error,
            "metrics": self.result.metrics if self.result else {},
            "metadata": self.result.metadata if self.result else {},
        }


def _run_variant(
    task: Any,
    policy_config: dict[str, Any],
    episodes: int,
    headless: bool,
) -> VariantResult:
    """Run one policy variant and return a normalized summary."""
    policy_id = policy_config["policy_id"]
    checkpoint = policy_config.get("policy_config_dict", {}).get("checkpoint_path", "unknown")

    adapter = ArenaAdapter(task, mode="docker", headless=headless)
    result = adapter.run_policy(policy_config, episodes=episodes, max_steps=None)

    if result is None:
        return VariantResult(
            policy_id=policy_id,
            checkpoint=checkpoint,
            status="no_result",
            success_rate=0.0,
            progress_mean=0.0,
            eef_to_object_distance_min_mean=None,
            object_height_delta_mean=None,
            failure_types={},
            error="Adapter returned None",
            result=None,
        )

    metrics = result.metrics or {}
    failure_types = result.failure_types or {}

    return VariantResult(
        policy_id=policy_id,
        checkpoint=checkpoint,
        status=result.status,
        success_rate=float(metrics.get("success_rate", 0.0)),
        progress_mean=float(metrics.get("progress_mean", 0.0)),
        eef_to_object_distance_min_mean=metrics.get("eef_to_object_distance_min_mean"),
        object_height_delta_mean=metrics.get("object_height_delta_mean"),
        failure_types=dict(failure_types),
        error=result.metadata.get("error") if result.status != "completed" else None,
        result=result,
    )


def _write_report(results: list[VariantResult], out_dir: Path) -> None:
    """Write JSON summary and markdown report."""
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "task_id": "darwin_mvp_03_lift_object",
        "mode": "docker",
        "variants": [r.to_dict() for r in results],
    }
    summary_path = out_dir / "baseline_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))

    report_path = REPO_ROOT / "reports" / "LEARNED_LIFT_BASELINE_REPORT.md"
    report = _render_markdown(results)
    report_path.write_text(report)

    print(f"\nSummary written to: {summary_path}")
    print(f"Report written to: {report_path}")


def _render_markdown(results: list[VariantResult]) -> str:
    lines: list[str] = [
        "# Learned Lift Baseline Report",
        "",
        "## Goal",
        "",
        "Run pretrained RSL-RL policies on the real Arena `lift_object` task to",
        "determine whether a learned controller can produce non-zero success/progress",
        "where the damped DifferentialIK servo heuristic currently fails.",
        "",
        "## Method",
        "",
        "- Task: `darwin_mvp_03_lift_object` (Arena Docker, `franka_ik` embodiment).",
        "- Policies: pretrained RSL-RL checkpoints mounted into the Arena container.",
        "- Metrics: success_rate, progress_mean, min eef-to-object distance, object height delta.",
        "- Failure types are inferred from per-episode traces.",
        "",
        "## Results",
        "",
        "| Policy | Checkpoint | Status | success_rate | progress_mean | min_dist_mean | height_delta_mean |",
        "|--------|------------|--------|-------------:|--------------:|--------------:|------------------:|",
    ]

    for r in results:
        min_dist = f"{r.eef_to_object_distance_min_mean:.4f}" if r.eef_to_object_distance_min_mean is not None else "n/a"
        height_delta = f"{r.object_height_delta_mean:.4f}" if r.object_height_delta_mean is not None else "n/a"
        lines.append(
            f"| {r.policy_id} | `{r.checkpoint}` | {r.status} | "
            f"{r.success_rate:.4f} | {r.progress_mean:.4f} | {min_dist} | {height_delta} |"
        )

    lines.extend([
        "",
        "## Failure-type breakdown",
        "",
    ])

    for r in results:
        lines.append(f"### {r.policy_id}")
        if r.error:
            lines.append(f"- **Error**: {r.error}")
        if r.failure_types:
            for ft, count in r.failure_types.items():
                lines.append(f"- {ft}: {count}")
        else:
            lines.append("- No failure-type metadata captured.")
        lines.append("")

    any_success = any(r.success_rate > 0 for r in results)
    lines.extend([
        "## Conclusion",
        "",
    ])
    if any_success:
        lines.append(
            "At least one learned policy achieved **non-zero success** on the real Arena task. "
            "This satisfies the capability baseline requirement and can be used as the control "
            "condition in future with/without-hint ablations."
        )
    else:
        lines.append(
            "No learned checkpoint produced non-zero success on `lift_object` in this run. "
            "Possible reasons: checkpoint/observation-space mismatch, embodiment mismatch, "
            "or the checkpoint was trained in a different environment variant. "
            "The next step is to verify checkpoint compatibility or train/fine-tune a policy "
            "directly in the current Arena container configuration."
        )

    lines.extend([
        "",
        "## Honest claim status",
        "",
        "- These policies are **not** oracle/cheat; they can claim real capability if success > 0.",
        "- Evolution evidence still requires a measurable improvement after consuming auto skill hints.",
    ])

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run learned RSL-RL lift baselines in Arena Docker")
    parser.add_argument("--episodes", type=int, default=5, help="Number of episodes per variant")
    parser.add_argument("--out", type=str, default="/tmp/rosclaw_data/baselines/learned_lift", help="Output directory")
    parser.add_argument("--headless", action="store_true", default=True, help="Run headless")
    parser.add_argument(
        "--variants",
        type=str,
        default="all",
        help="Comma-separated policy_ids to run, or 'all'",
    )
    args = parser.parse_args()

    os.environ.setdefault("ROSCLAW_ARENA_MODE", "docker")

    task_dict = yaml.safe_load(TASK_PATH.read_text())
    task = TaskLoader().load(task_dict)

    selected = [v for v in DEFAULT_VARIANTS if args.variants == "all" or v["policy_id"] in args.variants.split(",")]
    if not selected:
        print("No variants selected.")
        return

    out_dir = Path(args.out)
    results: list[VariantResult] = []

    for variant in selected:
        print(f"\n=== Running {variant['policy_id']} ===")
        try:
            result = _run_variant(task, variant, episodes=args.episodes, headless=args.headless)
        except Exception as exc:
            checkpoint = variant.get("policy_config_dict", {}).get("checkpoint_path", "unknown")
            result = VariantResult(
                policy_id=variant["policy_id"],
                checkpoint=checkpoint,
                status="error",
                success_rate=0.0,
                progress_mean=0.0,
                eef_to_object_distance_min_mean=None,
                object_height_delta_mean=None,
                failure_types={},
                error=str(exc),
                result=None,
            )
        results.append(result)
        print(
            f"status={result.status} success={result.success_rate:.4f} "
            f"progress={result.progress_mean:.4f}"
        )

    _write_report(results, out_dir)

    success_count = sum(1 for r in results if r.success_rate > 0)
    print(f"\nDone. {success_count}/{len(results)} variants achieved non-zero success.")


if __name__ == "__main__":
    main()

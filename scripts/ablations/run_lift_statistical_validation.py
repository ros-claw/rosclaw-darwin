#!/usr/bin/env python3
"""Large-N statistical validation of skill-hint transfer on lift_object.

Runs each condition across multiple seeds, persists full reproducibility
artifacts for every run, and reports success-rate CIs plus Fisher exact tests.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import yaml

from rosclaw_darwin.adapters.arena import ArenaAdapter
from rosclaw_darwin.analysis.statistics import (
    bootstrap_delta_ci,
    fisher_exact_test,
    summarize_binary_condition,
    summarize_continuous_condition,
)
from rosclaw_darwin.evaluation.failure_signature import infer_failure_signatures_for_run
from rosclaw_darwin.evaluation.policy_metadata import load_policy_metadata
from rosclaw_darwin.evaluation.reproducibility import persist_run_artifacts
from rosclaw_darwin.evolution.failure_to_hint import FailureToHintEngine
from rosclaw_darwin.tdl.loader import TaskLoader
from rosclaw_darwin.tdl.schema import Task
from rosclaw_darwin.utils.paths import ensure_dir


def _extract_episodes(result: Any) -> list[dict[str, Any]]:
    """Return per-episode metrics from Arena output."""
    episodes = result.metadata.get("episode_metrics")
    if isinstance(episodes, list):
        return episodes
    am = result.metadata.get("arena_metrics_output", {})
    episodes = am.get("episode_metrics")
    if isinstance(episodes, list):
        return episodes
    return []


def _extract_phase_traces(result: Any) -> list[dict[str, Any]]:
    """Return per-episode phase traces if available."""
    traces = result.metadata.get("phase_traces")
    if isinstance(traces, list):
        return traces
    am = result.metadata.get("arena_metrics_output", {})
    traces = am.get("phase_traces")
    if isinstance(traces, list):
        return traces
    return []


def _make_failure_signatures(task: Task, episodes: list[dict[str, Any]], phase_traces: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Infer FailureSignature v2 records for each episode."""
    signatures = infer_failure_signatures_for_run(task, episodes, phase_traces=phase_traces)
    return [s.model_dump(mode="json") for s in signatures]


def _run_condition(
    label: str,
    adapter: ArenaAdapter,
    base_config: dict[str, Any],
    episodes: int,
    extra: dict[str, Any],
    seed: int,
    out_dir: Path,
    max_retries: int = 1,
) -> Any:
    config = dict(base_config)
    config.update(extra)
    print(f"[statistical_validation] seed={seed} condition={label}")

    # Clear any stale per-step trace so the episode-level metrics belong to this run.
    try:
        stale_trace = Path("/tmp/rosclaw_data/traces/episode_trace.jsonl")
        if stale_trace.exists():
            stale_trace.unlink()
    except Exception:
        pass

    result = None
    for attempt in range(max_retries + 1):
        result = adapter.run_policy(config, episodes=episodes)
        extracted = _extract_episodes(result)
        if extracted:
            break
        if result.status == "dry_run":
            break
        if attempt < max_retries:
            print(f"  [attempt {attempt + 1}] no per-episode metrics; retrying...")
            time.sleep(5)

    assert result is not None
    extracted_episodes = _extract_episodes(result)
    phase_traces = _extract_phase_traces(result)
    failure_signatures = _make_failure_signatures(adapter.task, extracted_episodes, phase_traces)

    # Persist full reproducibility artifacts.
    run_dir = out_dir / f"seed{seed}" / label / result.run_id
    persist_run_artifacts(
        run_dir=run_dir,
        result=result,
        task_yaml=adapter.task.to_yaml(),
        policy_config=config,
        command=result.command or [],
        seed=seed,
        episode_metrics=extracted_episodes,
        phase_traces=phase_traces,
        failure_signatures=failure_signatures,
        stdout=result.metadata.get("stdout_preview", ""),
        stderr=result.metadata.get("stderr_preview", ""),
    )

    print(
        f"  success_rate={result.metrics.get('success_rate')} "
        f"progress={result.metrics.get('progress_mean', result.metrics.get('progress'))} "
        f"episodes={len(extracted_episodes)} "
        f"failure={result.failure_types}"
    )
    time.sleep(5)  # brief pause between Docker runs
    return result


def _condition_summary(results: list[Any], expected_episodes: int) -> dict[str, Any]:
    successes: list[bool] = []
    progress_values: list[float] = []
    failure_counts: dict[str, int] = {}
    observed_episodes = 0
    for r in results:
        episodes = _extract_episodes(r)
        if episodes:
            observed_episodes += len(episodes)
            for ep in episodes:
                successes.append(bool(ep.get("success", False)))
                progress_values.append(float(ep.get("progress", 0.0)))
        else:
            # Fallback to aggregate metrics when per-episode export failed.
            n = int(r.metrics.get("num_episodes", expected_episodes))
            observed_episodes += n
            success_rate = r.metrics.get("success_rate", 0.0)
            n_success = int(round(success_rate * n))
            successes.extend([True] * n_success + [False] * (n - n_success))
            mean_progress = float(r.metrics.get("progress_mean", r.metrics.get("progress", 0.0)))
            progress_values.extend([mean_progress] * n)

        for ft, count in (r.failure_types or {}).items():
            failure_counts[ft] = failure_counts.get(ft, 0) + count

    # Conservatively pad missing episodes (metric export dropped some episodes)
    # as failures with zero progress so that CIs are honest.
    total_expected = expected_episodes * len(results)
    while len(successes) < total_expected:
        successes.append(False)
        progress_values.append(0.0)

    return {
        "n_total": len(successes),
        "n_observed": observed_episodes,
        "success_summary": summarize_binary_condition(successes),
        "progress_summary": summarize_continuous_condition(progress_values),
        "failure_counts": failure_counts,
        "progress_values": progress_values,
        "successes": successes,
    }


def _compare_conditions(
    baseline_summary: dict[str, Any],
    variant_summary: dict[str, Any],
) -> dict[str, Any]:
    b = baseline_summary["success_summary"]
    v = variant_summary["success_summary"]
    fisher = fisher_exact_test(
        v["n_success"],
        v["n_total"] - v["n_success"],
        b["n_success"],
        b["n_total"] - b["n_success"],
    )
    progress_delta = bootstrap_delta_ci(
        baseline_summary.get("progress_values", []),
        variant_summary.get("progress_values", []),
    )
    return {
        "delta_success_rate": round(v["rate"] - b["rate"], 4),
        "delta_progress": round(variant_summary["progress_summary"]["mean"] - baseline_summary["progress_summary"]["mean"], 4),
        "fisher_exact": fisher,
        "progress_delta_ci": [round(progress_delta[0], 4), round(progress_delta[1], 4)],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Statistical validation of skill hints on lift_object")
    parser.add_argument("--task", default="examples/tasks/native/lift_object.yaml")
    parser.add_argument("--policy", default="configs/policies/heuristic_servo_lift.yaml")
    parser.add_argument("--episodes", type=int, default=50)
    parser.add_argument("--seeds", default="0,1,2")
    parser.add_argument("--conditions", default="without_hints,manual_hints,auto_hints")
    parser.add_argument("--manual-hints", default="grasp_adjust,efficient_execution,adaptive_skill")
    parser.add_argument("--out", default="data/ablations/lift_object_statistical_validation")
    parser.add_argument("--report-path", default="reports/LIFT_OBJECT_STATISTICAL_VALIDATION_REPORT.md")
    args = parser.parse_args()

    out_dir = ensure_dir(args.out)
    task = TaskLoader().load(args.task)
    with open(args.policy, "r", encoding="utf-8") as f:
        base_config = yaml.safe_load(f) or {}
    base_config.setdefault("policy_id", Path(args.policy).stem)

    seeds = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]

    adapter = ArenaAdapter(task)
    policy_metadata = load_policy_metadata(base_config)

    # Run all condition x seed combinations.
    results_by_condition: dict[str, list[Any]] = {c: [] for c in conditions}
    for seed in seeds:
        for condition in conditions:
            extra: dict[str, Any] = {}
            if condition == "manual_hints":
                extra["skill_hints"] = [h.strip() for h in args.manual_hints.split(",") if h.strip()]
            elif condition == "auto_hints":
                # Generate auto hints from the no-hint result for this seed.
                no_hint_result = results_by_condition["without_hints"][-1] if results_by_condition["without_hints"] else None
                if no_hint_result is None:
                    raise RuntimeError("without_hints must run before auto_hints for each seed")
                engine = FailureToHintEngine.from_yaml()
                auto_hints = [h.name for h in engine.suggest_from_result(no_hint_result)]
                extra["skill_hints"] = auto_hints
                print(f"  auto_hints generated: {auto_hints}")
            result = _run_condition(
                label=condition,
                adapter=adapter,
                base_config=base_config,
                episodes=args.episodes,
                extra=extra,
                seed=seed,
                out_dir=out_dir,
            )
            results_by_condition[condition].append(result)

    # Aggregate across seeds.
    summaries = {c: _condition_summary(results, args.episodes) for c, results in results_by_condition.items()}

    # Pairwise comparisons.
    comparisons: dict[str, dict[str, Any]] = {}
    baseline = summaries["without_hints"]
    for condition in conditions:
        if condition == "without_hints":
            continue
        comparisons[f"{condition}_vs_without_hints"] = _compare_conditions(baseline, summaries[condition])

    summary = {
        "ablation_id": f"lift_object_statistical_validation_{int(time.time())}",
        "task_id": task.id,
        "policy_id": base_config["policy_id"],
        "episodes_per_seed": args.episodes,
        "seeds": seeds,
        "conditions": conditions,
        "summaries": summaries,
        "comparisons": comparisons,
        "policy_metadata": policy_metadata.model_dump(mode="json"),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    report_path = Path(args.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_report(summary))
    print(f"[statistical_validation] summary saved to {out_dir / 'summary.json'}")
    print(f"[statistical_validation] report saved to {report_path}")


def _render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Lift Object Statistical Validation Report",
        "",
        f"- Task: ``{summary['task_id']}``",
        f"- Policy: ``{summary['policy_id']}``",
        f"- Episodes per seed per condition: {summary['episodes_per_seed']}",
        f"- Seeds: {summary['seeds']}",
        "",
        "## Per-condition summary (aggregated across seeds)",
        "",
        "| condition | n_expected | n_observed | success_rate | 95% CI | progress (mean ± std) | progress 95% CI |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    n_expected = summary["episodes_per_seed"] * len(summary["seeds"])
    for cond, s in summary["summaries"].items():
        ss = s["success_summary"]
        ps = s["progress_summary"]
        lines.append(
            f"| {cond} | {n_expected} | {s.get('n_observed', ss['n_total'])} | {ss['rate']} | "
            f"[{ss['ci_lower']}, {ss['ci_upper']}] | "
            f"{ps['mean']} ± {ps['std']} | "
            f"[{ps['ci_lower']}, {ps['ci_upper']}] |"
        )

    lines.extend([
        "",
        "## Pairwise comparisons vs. without_hints",
        "",
        "| comparison | Δsuccess | Δprogress | Fisher exact p | odds_ratio | progress Δ CI |",
        "|---|---|---|---|---|---|---|",
    ])
    for comp, c in summary["comparisons"].items():
        fisher = c["fisher_exact"]
        lines.append(
            f"| {comp} | {c['delta_success_rate']} | {c['delta_progress']} | "
            f"{fisher.get('p_value')} | {fisher.get('odds_ratio')} | "
            f"{c['progress_delta_ci']} |"
        )

    lines.extend([
        "",
        "## Failure counts (aggregated across seeds)",
        "",
    ])
    for cond, s in summary["summaries"].items():
        lines.append(f"- **{cond}**: {s['failure_counts']}")

    lines.extend([
        "",
        "## Honest conclusion",
        "",
        "This report aggregates multiple seeds with confidence intervals and Fisher",
        "exact tests.  Missing per-episode metrics are conservatively treated as",
        "failures with zero progress, so the reported success rate is a lower bound.",
        "A positive Δsuccess whose CI is mostly above zero and whose p-value is small",
        "provides stronger evidence than a single-seed point estimate.",
        "",
    ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()

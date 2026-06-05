"""Report generation for evaluation and evolution runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rosclaw_darwin.evaluation.result import EvaluationResult


def save_run_result(
    run_dir: Path,
    result: EvaluationResult,
    task_yaml: str,
    policy_config: dict[str, Any],
    stdout: str | None = None,
    stderr: str | None = None,
) -> None:
    """Save a run result following Darwin data spec."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(result.model_dump_json(indent=2))
    (run_dir / "task.yaml").write_text(task_yaml)
    (run_dir / "policy.yaml").write_text(json.dumps(policy_config, indent=2))
    (run_dir / "metrics.json").write_text(json.dumps(result.metrics, indent=2))
    if stdout is not None:
        (run_dir / "stdout.log").write_text(stdout)
    if stderr is not None:
        (run_dir / "stderr.log").write_text(stderr)
    (run_dir / "artifacts").mkdir(exist_ok=True)


def save_evolution_report(
    run_dir: Path,
    report: dict[str, Any],
    task_yaml: str,
    policy_config: dict[str, Any],
) -> None:
    """Save an evolution report following Darwin data spec."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evolution_report.json").write_text(json.dumps(report, indent=2))
    (run_dir / "task.yaml").write_text(task_yaml)
    (run_dir / "policy.yaml").write_text(json.dumps(policy_config, indent=2))

    for i, loop in enumerate(report.get("loop_results", []), 1):
        loop_dir = run_dir / f"loop_{i}"
        loop_dir.mkdir(exist_ok=True)
        (loop_dir / "result.json").write_text(json.dumps(loop, indent=2))
        (loop_dir / "artifacts").mkdir(exist_ok=True)

    skills = report.get("discovered_skills", [])
    if skills:
        (run_dir / "discovered_skills.json").write_text(json.dumps(skills, indent=2))

    generated = report.get("generated_tasks", [])
    if generated:
        gt_dir = run_dir / "generated_tasks"
        gt_dir.mkdir(exist_ok=True)
        (gt_dir / "index.json").write_text(json.dumps(generated, indent=2))

    summary = _make_summary_md(report)
    (run_dir / "summary.md").write_text(summary)


def _make_summary_md(report: dict[str, Any]) -> str:
    evo = report.get("evolution_metrics", {})
    lines = [
        "# Evolution Report",
        "",
        f"- **Task**: {report.get('task_id')}",
        f"- **Policy**: {report.get('policy_id')}",
        f"- **Run ID**: {report.get('run_id')}",
        "",
        "## Evolution Metrics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| evolution_score | {evo.get('evolution_score', 0):.4f} |",
        f"| delta_success_rate | {evo.get('delta_success_rate', 0):.4f} |",
        f"| memory_integration_efficiency_score | {evo.get('memory_integration_efficiency_score', 0):.4f} |",
        f"| memory_integration_efficiency_available | {evo.get('memory_integration_efficiency_available', False)} |",
        f"| skill_discovery_rate | {evo.get('skill_discovery_rate', 0):.4f} |",
        f"| robustness_gain | {evo.get('robustness_gain', 0):.4f} |",
        "",
        "## Loop Results",
        "",
    ]
    for i, loop in enumerate(report.get("loop_results", []), 1):
        m = loop.get("metrics", {})
        lines.append(f"### Loop {i}")
        lines.append(f"- success_rate: {m.get('success_rate', 0):.2%}")
        lines.append(f"- num_episodes: {m.get('num_episodes', 0)}")
        lines.append("")
    lines.append("## Discovered Skills")
    lines.append("")
    for skill in report.get("discovered_skills", []):
        lines.append(f"- **{skill.get('name')}** ({skill.get('fingerprint')})")
    if not report.get("discovered_skills"):
        lines.append("No new skills discovered in this run.")
    lines.append("")
    return "\n".join(lines)

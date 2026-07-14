"""Darwin v1.0 product CLI subcommands.

These commands expose the evidence pipeline through a unified surface:
validate-env, run, diagnose, pair-eval, promote, card, registry, report, eval.
Every command supports a --mock mode so the CLI can be exercised without
Arena Docker runs.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console

from rosclaw_darwin.cli.eval_app import eval_app
from rosclaw_darwin.evaluation.object_validity import (
    ObjectValidityReport,
    check_object_validity,
)
from rosclaw_darwin.evaluation.paired_evaluation import PairedEvaluationSummary
from rosclaw_darwin.evidence import CardGenerator, generate_all_demo_cards
from rosclaw_darwin.evolution.evidence_level import (
    EvidenceType,
    infer_evidence_level,
    infer_evidence_type,
    is_runtime_eligible,
)
from rosclaw_darwin.evolution.evolution_ledger import EvolutionLedger, EvolutionLedgerEntry
from rosclaw_darwin.evolution.hint_recipe import HintRecipe
from rosclaw_darwin.evolution.promotion_manager import PromotionManager
from rosclaw_darwin.registry import PromotionRegistry, get_claims
from rosclaw_darwin.schemas.evidence_card import EvidenceCard
from rosclaw_darwin.schemas.intervention import CandidateIntervention
from rosclaw_darwin.schemas.promotion_decision import PromotionDecision
from rosclaw_darwin.schemas.run_artifact import RunArtifact
from rosclaw_darwin.schemas.task_validity import TaskValidity
from rosclaw_darwin.tdl.loader import TaskLoader
from rosclaw_darwin.tdl.schema import Task
from rosclaw_darwin.utils.paths import ensure_dir

darwin_app = typer.Typer(help="ROSClaw-Darwin v1.0 evidence engine")
console = Console()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_yaml(path: str) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _parse_seed_range(text: str) -> list[int]:
    """Parse a seed range such as '0:4' or '0,1,2'."""
    parts = [p.strip() for p in text.replace(",", " ").split() if p.strip()]
    seeds: set[int] = set()
    for p in parts:
        if ":" in p:
            start, end = p.split(":", 1)
            seeds.update(range(int(start), int(end) + 1))
        else:
            seeds.add(int(p))
    return sorted(seeds)


def _merge_http_trace(step_trace_path: Path, http_trace_path: Path, output_path: Path) -> None:
    """Merge per-step HTTP sidecar metadata into the episode trace.

    The container-side ``ExternalHTTPPolicy`` writes an ``external_http_trace.jsonl``
    sidecar with latency/guard/raw-action fields. This function enriches the main
    ``episode_trace.jsonl`` so downstream reports see a single trace that contains
    both environment state and HTTP policy metadata.
    """
    http_by_step: dict[int, dict[str, Any]] = {}
    if http_trace_path.exists():
        try:
            with http_trace_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        step = int(rec.get("step", -1))
                        if step >= 0:
                            http_by_step[step] = rec
                    except Exception:
                        pass
        except Exception:
            pass

    with step_trace_path.open("r", encoding="utf-8") as src, output_path.open("w", encoding="utf-8") as dst:
        for line in src:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue
            step = int(record.get("step", -1))
            http = http_by_step.get(step, {})
            if http:
                record["http_request_sent"] = True
                record["http_response_received"] = http.get("http_status") == 200
                record["latency_ms"] = http.get("latency_ms")
                record["raw_policy_action"] = http.get("raw_policy_action")
                record["adapted_action"] = http.get("guarded_action")
                record["guarded_action"] = http.get("guarded_action")
                record["action_guard_triggered"] = http.get("action_guard_triggered")
                record["action_guard_reason"] = http.get("action_guard_reason")
                record["action_valid"] = http.get("action_valid")
            else:
                record["http_request_sent"] = False
                record["http_response_received"] = False
            dst.write(json.dumps(record, default=str) + "\n")


def _aggregate_http_sidecars(out_dir: Path, seed_list: list[int]) -> None:
    """Concatenate per-seed HTTP sidecars and roll up metrics at the run level.

    The container-side ``ExternalHTTPPolicy`` writes ``external_http_trace.jsonl``
    and ``external_http_metrics.json`` inside each seed's trace directory.  This
    function produces top-level copies so gates and evidence cards can reference
    a single sidecar per run.
    """
    all_http_records: list[dict[str, Any]] = []
    agg: dict[str, Any] = {
        "http_request_count": 0,
        "http_success_count": 0,
        "http_timeout_count": 0,
        "http_error_count": 0,
        "action_guard_trigger_count": 0,
        "invalid_action_count": 0,
        "latencies_ms": [],
    }

    for seed in seed_list:
        seed_dir = out_dir / f"seed_{seed:03d}"
        http_trace = seed_dir / "external_http_trace.jsonl"
        http_metrics = seed_dir / "external_http_metrics.json"

        if http_trace.exists():
            try:
                with http_trace.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                            rec["seed"] = seed
                            all_http_records.append(rec)
                        except Exception:
                            pass
            except Exception:
                pass

        if http_metrics.exists():
            try:
                metrics = json.loads(http_metrics.read_text(encoding="utf-8"))
                agg["http_request_count"] += int(
                    metrics.get("http_request_count", 0)
                )
                agg["http_success_count"] += int(
                    metrics.get("http_success_count", 0)
                )
                agg["http_timeout_count"] += int(
                    metrics.get("http_timeout_count", 0)
                )
                agg["http_error_count"] += int(
                    metrics.get("http_error_count", 0)
                )
                agg["action_guard_trigger_count"] += int(
                    metrics.get("action_guard_trigger_count", 0)
                )
                agg["invalid_action_count"] += int(
                    metrics.get("invalid_action_count", 0)
                )
                lat = metrics.get("latency_mean_ms")
                if isinstance(lat, (int, float)):
                    agg["latencies_ms"].append(float(lat))
            except Exception:
                pass

    top_http_trace = out_dir / "external_http_trace.jsonl"
    if all_http_records:
        top_http_trace.write_text(
            "\n".join(json.dumps(r, default=str) for r in all_http_records) + "\n",
            encoding="utf-8",
        )

    top_http_metrics = out_dir / "external_http_metrics.json"
    total = max(1, agg["http_request_count"])
    summary = {
        "http_request_count": agg["http_request_count"],
        "http_success_count": agg["http_success_count"],
        "http_timeout_count": agg["http_timeout_count"],
        "http_error_count": agg["http_error_count"],
        "http_success_rate": round(agg["http_success_count"] / total, 4),
        "action_guard_trigger_count": agg["action_guard_trigger_count"],
        "invalid_action_count": agg["invalid_action_count"],
    }
    if agg["latencies_ms"]:
        summary["latency_mean_ms"] = round(
            sum(agg["latencies_ms"]) / len(agg["latencies_ms"]), 4
        )
    top_http_metrics.write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )


def _run_libero_live(
    task: Task,
    policy_config: dict[str, Any],
    policy_name: str,
    seed_list: list[int],
    max_steps: int,
    out_dir: Path,
) -> None:
    """Run a live LIBERO evaluation natively (no Docker).

    Dispatches through :class:`LiberoAdapter` and writes per-seed run artifacts
    plus a top-level ``run_artifact.json`` with the aggregated success rate.
    """
    from rosclaw_darwin.adapters import get_adapter

    seed_results: list[dict[str, Any]] = []
    for seed in seed_list:
        console.print(f"[cyan]Running LIBERO seed {seed} ...[/cyan]")
        seed_dir = out_dir / f"seed_{seed:03d}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        trace_dir = seed_dir / "traces"
        trace_dir.mkdir(parents=True, exist_ok=True)

        task_copy = copy.deepcopy(task)
        if task_copy.mutation is None:
            from rosclaw_darwin.tdl.schema import MutationSpec

            task_copy.mutation = MutationSpec(seed=seed)
        else:
            task_copy.mutation.seed = seed

        env_adapter = get_adapter("libero", task_copy)
        eval_result = env_adapter.run_policy(
            policy_config,
            episodes=1,
            max_steps=max_steps,
            trace_dir=trace_dir,
        )

        artifact_path = seed_dir / "run_artifact.json"
        artifact_path.write_text(
            json.dumps(eval_result.model_dump(mode="json"), indent=2, default=str),
            encoding="utf-8",
        )
        seed_results.append(
            {
                "seed": seed,
                "status": eval_result.status,
                "metrics": dict(eval_result.metrics),
            }
        )

    completed = sum(1 for r in seed_results if r["status"] == "completed")
    successes = sum(int(r["metrics"].get("success", 0)) for r in seed_results)
    summary: dict[str, Any] = {
        "run_id": f"{task.id}_{policy_name}_live",
        "task_id": task.id,
        "policy_id": policy_name,
        "adapter": policy_config.get("type", "libero"),
        "mode": "live",
        "status": "completed" if completed == len(seed_list) else "partial",
        "seeds": seed_list,
        "steps_per_episode": max_steps,
        "seed_results": seed_results,
        "metrics": {
            "num_seeds": len(seed_list),
            "completed_seeds": completed,
            "successes": successes,
            "success_rate": (successes / len(seed_list) if seed_list else 0.0),
        },
        "started_at": _now(),
        "finished_at": _now(),
    }
    (out_dir / "run_artifact.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )

    console.print(f"[green]LIBERO live run completed[/green] for {policy_name}")
    console.print(f"  Seeds: {len(seed_list)}")
    console.print(f"  Successes: {successes}/{len(seed_list)}")
    console.print(f"  Output: {out_dir / 'run_artifact.json'}")


@darwin_app.command(name="validate-env")
def validate_env(
    task: str = typer.Option(..., "--task", help="Path to task YAML"),
    out: str = typer.Option("data/darwin/validity", "--out", help="Output directory"),
    mock: bool = typer.Option(True, "--mock/--live", help="Use synthetic validity data"),
) -> None:
    """Validate a benchmark environment and emit a TaskValidity verdict."""
    out_dir = ensure_dir(out)
    t = TaskLoader().load(task)

    if mock:
        is_official = "dex_cube_official" in t.id
        is_procedural_fallback = "procedural_cube_fallback" in t.id
        is_rosclaw_valid = "rosclaw_valid_cube" in t.id

        if is_procedural_fallback:
            obj = ObjectValidityReport(
                task_id=t.id,
                object_name="procedural_cube",
                collision_enabled=False,
                bbox_extent=[0.0, 0.0, 0.0],
                rigid_body_enabled=False,
            )
            scope = "invalid_environment"
            status = "invalid"
            reasons = ["collision_disabled", "invalid_bbox", "rigid_body_disabled"]
        elif is_rosclaw_valid:
            obj = ObjectValidityReport(
                task_id=t.id,
                object_name="rosclaw_valid_cube",
                collision_enabled=True,
                bbox_extent=[0.05, 0.05, 0.05],
                rigid_body_enabled=True,
                object_above_table=True,
            )
            scope = "rosclaw_ood_diagnostic"
            status = "valid"
            reasons = []
        else:
            obj = ObjectValidityReport(
                task_id=t.id,
                object_name="dex_cube",
                collision_enabled=True,
                bbox_extent=[0.05, 0.05, 0.05],
                rigid_body_enabled=True,
                object_above_table=True,
            )
            scope = "official_arena_asset"
            status = "valid"
            reasons = []

        obj = check_object_validity(obj)
        validity = TaskValidity(
            task_id=t.id,
            benchmark_scope=scope,
            validity_status=status,
            official_asset=is_official,
            asset_fallback_used=False,
            can_claim_official_benchmark=is_official and status == "valid",
            can_claim_ood_diagnostic=(scope == "rosclaw_ood_diagnostic") and status == "valid",
            object_validity=obj,
            reason=reasons,
        )
    else:
        console.print("[red]Live validate-env requires the object-validity audit runner.[/red]")
        raise typer.Exit(1)

    (out_dir / "task_validity.json").write_text(
        json.dumps(validity.model_dump(mode="json"), indent=2)
    )
    console.print(f"[green]Validity for {t.id}:[/green] {validity.validity_status}")
    console.print(f"  Scope: {validity.benchmark_scope}")
    console.print(f"  Output: {out_dir / 'task_validity.json'}")


@darwin_app.command()
def run(
    task: str = typer.Option(..., "--task", help="Path to task YAML"),
    policy: str = typer.Option(..., "--policy", help="Path to policy config YAML"),
    seeds: str = typer.Option("0:4", "--seeds", help="Seed range, e.g. 0:4"),
    steps: int = typer.Option(20, "--steps", help="Max steps per episode"),
    out: str = typer.Option("data/darwin/runs", "--out", help="Output directory"),
    mock: bool = typer.Option(True, "--mock/--live", help="Use synthetic run artifacts"),
    adapter: str = typer.Option("arena", "--adapter", help="Environment adapter: arena, libero"),
) -> None:
    """Run a policy and emit a RunArtifact."""
    out_dir = ensure_dir(out)
    t = TaskLoader().load(task)
    policy_name = Path(policy).stem
    policy_config = _load_yaml(policy)
    adapter_type = policy_config.get("type", "mock")
    seed_list = _parse_seed_range(seeds)

    if mock:
        is_official = "dex_cube_official" in t.id
        success_rate = 0.99 if is_official else 0.0
        result = RunArtifact(
            run_id=f"{t.id}_{policy_name}_mock",
            task_id=t.id,
            policy_id=policy_name,
            adapter=adapter_type,
            status="completed",
            metrics={"success_rate": success_rate, "num_episodes": len(seed_list)},
            started_at=_now(),
            finished_at=_now(),
        )
        run_dir = out_dir / result.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run_artifact.json").write_text(
            json.dumps(result.model_dump(mode="json"), indent=2)
        )
        console.print(f"[green]Run {result.run_id} completed[/green]")
        console.print(f"  Success rate: {result.metrics.get('success_rate', 0.0):.2%}")
        console.print(f"  Output: {run_dir / 'run_artifact.json'}")
        return

    # Live path: drive real env steps through the selected adapter.
    if adapter == "libero":
        _run_libero_live(t, policy_config, policy_name, seed_list, steps, out_dir)
        return

    from rosclaw_darwin.adapters.arena import ArenaAdapter

    seed_results: list[dict[str, Any]] = []
    all_trace_records: list[dict[str, Any]] = []

    for seed in seed_list:
        console.print(f"[cyan]Running seed {seed} ...[/cyan]")
        seed_dir = out_dir / f"seed_{seed:03d}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        trace_dir = seed_dir / "traces"
        trace_dir.mkdir(parents=True, exist_ok=True)

        try:
            task_copy = copy.deepcopy(t)
            if task_copy.mutation is None:
                from rosclaw_darwin.tdl.schema import MutationSpec
                task_copy.mutation = MutationSpec(seed=seed)
            else:
                task_copy.mutation.seed = seed
        except Exception:
            # If the task schema does not expose mutation, rely on the adapter
            # to forward the seed via environment variables.
            task_copy = t

        env_adapter = ArenaAdapter(
            task_copy,
            robot="franka",
            headless=True,
            mode="docker",
            num_envs=1,
        )
        eval_result = env_adapter.run_policy(
            policy_config,
            episodes=1,
            max_steps=steps,
            trace_dir=trace_dir,
        )

        artifact_path = seed_dir / "run_artifact.json"
        artifact_path.write_text(
            json.dumps(eval_result.model_dump(mode="json"), indent=2, default=str),
            encoding="utf-8",
        )

        container_trace = trace_dir / "episode_trace.jsonl"
        container_http_trace = trace_dir / "external_http_trace.jsonl"
        container_http_metrics = trace_dir / "external_http_metrics.json"
        merged_trace = seed_dir / "trace.jsonl"
        top_trace = seed_dir / "episode_trace.jsonl"

        if container_trace.exists():
            _merge_http_trace(container_trace, container_http_trace, merged_trace)
            shutil.copy2(merged_trace, top_trace)
            records: list[dict[str, Any]] = []
            with merged_trace.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except Exception:
                            pass
            all_trace_records.extend(records)

        if container_http_trace.exists():
            shutil.copy2(container_http_trace, seed_dir / "external_http_trace.jsonl")
        if container_http_metrics.exists():
            shutil.copy2(container_http_metrics, seed_dir / "external_http_metrics.json")

        seed_results.append(
            {
                "seed": seed,
                "status": eval_result.status,
                "artifact_dir": str(seed_dir),
                "metrics": dict(eval_result.metrics),
            }
        )

    # Aggregate top-level run artifact.
    completed = sum(1 for r in seed_results if r["status"] == "completed")
    total_steps = len(all_trace_records)
    http_requests = sum(1 for r in all_trace_records if r.get("http_request_sent"))
    http_successes = sum(
        1 for r in all_trace_records if r.get("http_response_received")
    )
    latencies = [
        float(r["latency_ms"])
        for r in all_trace_records
        if isinstance(r.get("latency_ms"), (int, float))
    ]
    guard_triggers = sum(1 for r in all_trace_records if r.get("action_guard_triggered"))
    invalid_actions = sum(
        1 for r in all_trace_records if r.get("action_valid") is False
    )
    non_mock_count = sum(1 for r in all_trace_records if r.get("mode") == "non_mock")
    summary = {
        "run_id": f"{t.id}_{policy_name}_live",
        "task_id": t.id,
        "policy_id": policy_name,
        "adapter": adapter_type,
        "mode": "live",
        "status": "completed" if completed == len(seed_list) else "partial",
        "seeds": seed_list,
        "steps_per_episode": steps,
        "seed_results": seed_results,
        "metrics": {
            "num_seeds": len(seed_list),
            "completed_seeds": completed,
            "total_trace_records": total_steps,
            "real_env_step_count": total_steps,
            "http_request_count": http_requests,
            "http_success_count": http_successes,
            "http_success_rate": (http_successes / http_requests if http_requests else 0.0),
            "mean_http_latency_ms": (sum(latencies) / len(latencies) if latencies else 0.0),
            "action_guard_trigger_count": guard_triggers,
            "action_invalid_count": invalid_actions,
            "mode_non_mock_count": non_mock_count,
        },
        "started_at": _now(),
        "finished_at": _now(),
    }
    (out_dir / "run_artifact.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )

    # Also emit a consolidated episode_trace.jsonl at the top level.
    if all_trace_records:
        (out_dir / "episode_trace.jsonl").write_text(
            "\n".join(json.dumps(r, default=str) for r in all_trace_records) + "\n",
            encoding="utf-8",
        )

    # Aggregate per-seed HTTP sidecars so gates/cards have a single run-level copy.
    _aggregate_http_sidecars(out_dir, seed_list)

    console.print(f"[green]Live run completed[/green] for {policy_name}")
    console.print(f"  Seeds: {len(seed_list)} ({seeds})")
    console.print(f"  Completed: {completed}/{len(seed_list)}")
    console.print(f"  Total trace records: {total_steps}")
    console.print(f"  Output: {out_dir / 'run_artifact.json'}")


@darwin_app.command()
def diagnose(
    run_dir: str = typer.Option(..., "--run", help="Path to a run directory"),
    out: str | None = typer.Option(None, "--out", help="Output directory"),
    mock: bool = typer.Option(True, "--mock/--live", help="Use synthetic diagnosis"),
) -> None:
    """Diagnose a run and emit a FailureSignature."""
    run_path = Path(run_dir)
    out_path = ensure_dir(out) if out else run_path

    if mock:
        from rosclaw_darwin.evaluation.failure_signature import FailureSignature

        signature = FailureSignature(
            task_id="unknown",
            episode_id=24,
            failure_type="post_lift_slip",
            success=False,
            signature_tags=["lifted_then_dropped", "hold_instability"],
        )
    else:
        console.print("[red]Live diagnose is not implemented in the Darwin CLI.[/red]")
        raise typer.Exit(1)

    (out_path / "failure_signature.json").write_text(
        json.dumps(signature.model_dump(mode="json"), indent=2)
    )
    console.print(f"[green]Diagnosis:[/green] {signature.failure_type}")
    console.print(f"  Tags: {signature.signature_tags}")
    console.print(f"  Output: {out_path / 'failure_signature.json'}")


@darwin_app.command(name="pair-eval")
def pair_eval(
    task: str | None = typer.Option(None, "--task", help="Path to task YAML"),
    baseline: str | None = typer.Option(None, "--baseline", help="Path to baseline policy config"),
    candidate: str | None = typer.Option(None, "--candidate", help="Path to candidate policy config"),
    baseline_run: str | None = typer.Option(None, "--baseline-run", help="Path to baseline run directory"),
    candidate_run: str | None = typer.Option(None, "--candidate-run", help="Path to candidate run directory"),
    seeds: str = typer.Option("0:4", "--seeds", help="Seed range"),
    out: str = typer.Option("data/darwin/paired", "--out", help="Output directory"),
    metric: str = typer.Option("eef_to_object_distance", "--metric", help="Metric for offline pair classification"),
    improvement_threshold: float = typer.Option(0.05, "--improvement-threshold", help="Improvement threshold for metric-positive classification"),
    mock: bool = typer.Option(True, "--mock/--live", help="Use synthetic paired outcomes"),
) -> None:
    """Run paired no-regression evaluation and emit a paired summary."""
    out_dir = ensure_dir(out)

    # Offline mode: compare pre-run directories produced by ``darwin run --live``.
    if baseline_run and candidate_run:
        script = (
            Path(__file__).resolve().parents[2]
            / "scripts"
            / "proof"
            / "run_offline_paired_evaluation.py"
        )
        cmd = [
            sys.executable,
            str(script),
            "--baseline-run", str(Path(baseline_run).resolve()),
            "--candidate-run", str(Path(candidate_run).resolve()),
            "--out", str(out_dir),
            "--metric", metric,
            "--improvement-threshold", str(improvement_threshold),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        console.print(result.stdout)
        if result.returncode != 0:
            console.print(f"[red]Offline paired evaluation failed:[/red] {result.stderr}")
            raise typer.Exit(result.returncode)

        summary_path = out_dir / "paired_summary.json"
        if summary_path.exists():
            summary_data = json.loads(summary_path.read_text())
            console.print("[green]Offline paired evaluation complete[/green]")
            console.print(f"  Valid pairs: {summary_data.get('valid_pairs', 0)}")
            console.print(f"  Metric: {summary_data.get('metric', metric)}")
            console.print(f"  Metric improved: {summary_data.get('metric_improved_count', 0)}")
            console.print(f"  Metric regressed: {summary_data.get('metric_regressed_count', 0)}")
            console.print(f"  Output: {summary_path}")
        else:
            console.print(f"[yellow]No paired summary found at {summary_path}[/yellow]")
        return

    if mock:
        script = (
            Path(__file__).resolve().parents[2]
            / "scripts"
            / "diagnostics"
            / "run_paired_policy_evaluation.py"
        )
        if not task or not baseline or not candidate:
            console.print("[red]--mock pair-eval requires --task, --baseline, and --candidate.[/red]")
            raise typer.Exit(1)
        cmd = [
            sys.executable,
            str(script),
            "--task", task,
            "--baseline-policy", baseline,
            "--candidate-policy", candidate,
            "--seeds", seeds,
            "--out-dir", str(out_dir),
            "--mock",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            console.print(f"[red]Paired evaluation failed:[/red] {result.stderr}")
            raise typer.Exit(result.returncode)
    else:
        console.print("[red]Live pair-eval requires --baseline-run and --candidate-run for offline mode.[/red]")
        raise typer.Exit(1)

    summary_path = out_dir / "paired_summary.json"
    if summary_path.exists():
        summary = PairedEvaluationSummary.model_validate(
            json.loads(summary_path.read_text())["summary"]
        )
        console.print("[green]Paired evaluation complete[/green]")
        console.print(f"  Baseline rate: {summary.baseline_success_rate:.3f}")
        console.print(f"  Candidate rate: {summary.candidate_success_rate:.3f}")
        console.print(f"  Rescued: {summary.rescued_count}, Newly failed: {summary.newly_failed_count}")
        console.print(f"  Output: {summary_path}")
    else:
        console.print(f"[yellow]No paired summary found at {summary_path}[/yellow]")


@darwin_app.command()
def promote(
    candidate: str = typer.Option(..., "--candidate", help="Candidate name"),
    paired_summary: str = typer.Option(..., "--paired", help="Path to paired_summary.json"),
    recipe: str | None = typer.Option(None, "--recipe", help="Optional HintRecipe YAML"),
    out: str = typer.Option("data/darwin/promotions", "--out", help="Output directory"),
    promotion_scope: str | None = typer.Option(None, "--promotion-scope", help="Promotion scope: adapter_fix, evaluation_recipe, safety_wrapper, diagnostic_ablation"),
    baseline_real: bool = typer.Option(False, "--baseline-real", help="Baseline was evaluated in real environment"),
    candidate_real: bool = typer.Option(False, "--candidate-real", help="Candidate was evaluated in real environment"),
    candidate_metrics_synthetic: bool = typer.Option(False, "--candidate-metrics-synthetic", help="Candidate metrics are synthetic/offline"),
    min_seeds: int | None = typer.Option(None, "--min-seeds", help="Minimum valid pairs for continuous-metric rescue gate"),
    min_improved_seeds: int | None = typer.Option(None, "--min-improved-seeds", help="Minimum metric-improved seeds for rescue gate"),
    max_newly_regressed: int | None = typer.Option(None, "--max-newly-regressed", help="Maximum metric-regressed seeds for rescue gate"),
) -> None:
    """Evaluate promotion evidence and emit a PromotionDecision."""
    out_dir = ensure_dir(out)
    summary_data = json.loads(Path(paired_summary).read_text())

    use_continuous_gate = (
        min_seeds is not None or min_improved_seeds is not None or max_newly_regressed is not None
    )

    if recipe:
        recipe_obj = HintRecipe.model_validate(_load_yaml(recipe))
    elif use_continuous_gate:
        recipe_obj = HintRecipe(
            name=candidate,
            source="auto_rule",
            trigger_tags=[],
            hints=[],
            route_selection="conditional_micro_recovery",
            evidence_gate={
                "gate_type": "continuous_metric_rescue",
                "min_seeds": min_seeds if min_seeds is not None else 1,
                "min_improved_seeds": min_improved_seeds if min_improved_seeds is not None else 1,
                "max_newly_regressed": max_newly_regressed if max_newly_regressed is not None else 0,
            },
        )
    else:
        recipe_obj = HintRecipe(
            name=candidate,
            source="auto_rule",
            trigger_tags=[],
            hints=[],
            route_selection="conditional_micro_recovery",
            evidence_gate={
                "gate_type": "paired_no_regression",
                "min_rescued_count": 1,
                "max_newly_failed_count": 0,
            },
        )

    if use_continuous_gate:
        manager = PromotionManager(paired_summary_dict=summary_data)
    else:
        summary = PairedEvaluationSummary.model_validate(
            summary_data.get("summary", summary_data)
        )
        manager = PromotionManager(paired_eval=summary)
    fth_status = manager.evaluate(recipe_obj)

    seed_count = len(_parse_seed_range(summary_data.get("seed_range", "0:0")))
    if seed_count == 0 and "per_seed" in summary_data:
        seed_count = len(summary_data["per_seed"])
    evidence_type = infer_evidence_type(
        baseline_real=baseline_real,
        candidate_real=candidate_real,
        candidate_metrics_synthetic=candidate_metrics_synthetic,
    )
    scale_validated = fth_status.evidence_gate_passed and seed_count >= 10
    evidence_level = infer_evidence_level(
        evidence_type=evidence_type,
        baseline_real=baseline_real,
        candidate_real=candidate_real,
        candidate_metrics_synthetic=candidate_metrics_synthetic,
        promotion_status=fth_status.promotion_status,
        seed_count=seed_count,
        scale_validated=scale_validated,
    )

    runtime_eligible = is_runtime_eligible(evidence_level, evidence_type) and scale_validated

    decision = PromotionDecision(
        candidate_name=candidate,
        status=fth_status.promotion_status,
        claim_level=fth_status.promotion_status,
        passed_gates=list(fth_status.required_evidence.keys()) if fth_status.evidence_gate_passed else [],
        failed_gates=[] if fth_status.evidence_gate_passed else list(fth_status.required_evidence.keys()),
        limitations=["evaluated seed set only"],
        allowed_claims=[f"{fth_status.promotion_status} on evaluated seeds"],
        disallowed_claims=["validated_transferable_skill"],
        next_required_evidence=["independent hold-out replication"],
        fth_status=fth_status,
        evidence_level=evidence_level,
        evidence_type=evidence_type,
        runtime_eligible=runtime_eligible,
        promotion_scope=promotion_scope,
        scale_validated=scale_validated,
        seed_count=seed_count,
    )

    (out_dir / f"{candidate}_promotion_decision.json").write_text(
        json.dumps(decision.model_dump(mode="json"), indent=2)
    )
    console.print(f"[green]Promotion decision for {candidate}:[/green] {decision.status}")
    console.print(f"  Gate passed: {fth_status.evidence_gate_passed}")
    console.print(f"  Evidence level: {decision.evidence_level}")
    console.print(f"  Runtime eligible: {decision.runtime_eligible}")
    console.print(f"  Reason: {fth_status.gate_reason}")


@darwin_app.command()
def card(
    candidate: str = typer.Option(..., "--candidate", help="Candidate name"),
    out: str = typer.Option("cards", "--out", help="Output directory"),
    mock: bool = typer.Option(True, "--mock/--live", help="Generate from built-in demo mapping"),
) -> None:
    """Generate an evidence card for a candidate."""
    generator = CardGenerator(out)
    if mock:
        card_obj = generator.generate_demo_card(candidate)
    else:
        console.print("[red]Live card generation requires evidence artifacts.[/red]")
        raise typer.Exit(1)
    yaml_path, md_path = generator.save_card(card_obj, override=True)
    console.print(f"[green]Evidence card created:[/green] {yaml_path}")


@darwin_app.command(name="generate-demo-cards")
def generate_demo_cards(
    out: str = typer.Option("cards", "--out", help="Output directory"),
) -> None:
    """Generate all five v1.0 demo evidence cards."""
    paths = generate_all_demo_cards(out)
    console.print(f"[green]Generated {len(paths)} demo card files[/green]")
    for p in paths:
        console.print(f"  {p}")


@darwin_app.command()
def registry(
    action: str = typer.Argument(..., help="list, show, add, or recoveries"),
    registry_dir: str = typer.Option("data/darwin/registry", "--registry", help="Registry directory"),
    name: str | None = typer.Option(None, "--name", help="Skill/candidate name"),
    card_path: str | None = typer.Option(None, "--card", help="Evidence card path for add"),
    status: str | None = typer.Option(None, "--status", help="Status for add (default inferred from card)"),
    task_id: str | None = typer.Option(None, "--task", help="Task filter for recoveries"),
    failure_type: str | None = typer.Option(None, "--failure", help="Failure type filter for recoveries"),
) -> None:
    """Query or update the promotion registry."""
    reg = PromotionRegistry(registry_dir)

    if action == "list":
        items = reg.list_items()
        console.print(f"[green]Registry entries:[/green] {len(items)}")
        for item in items:
            console.print(
                f"  {item.id} ({item.kind}) - {item.status} "
                f"runtime={item.enabled_for_runtime}"
            )
    elif action == "recoveries":
        recoveries = reg.list_recoveries(task_id=task_id, failure_type=failure_type)
        console.print(f"[green]Enabled recoveries:[/green] {len(recoveries)}")
        for item in recoveries:
            console.print(f"  {item.id} - {item.status} card={item.card}")
    elif action == "show":
        if not name:
            console.print("[red]--name required for show[/red]")
            raise typer.Exit(1)
        item = reg.get(name)
        if item is None:
            console.print(f"[yellow]No registry entry for {name}[/yellow]")
            raise typer.Exit(1)
        console.print(json.dumps(item.model_dump(mode="json"), indent=2))
        claims = get_claims(item.status)
        console.print("\n[green]Allowed claims:[/green]")
        for claim in claims["allowed"]:
            console.print(f"  - {claim}")
        console.print("\n[red]Disallowed claims:[/red]")
        for claim in claims["disallowed"]:
            console.print(f"  - {claim}")
    elif action == "add":
        if not name or not card_path:
            console.print("[red]--name and --card required for add[/red]")
            raise typer.Exit(1)
        card_obj = EvidenceCard.model_validate(_load_yaml(card_path))
        item_status = status or card_obj.promotion_decision.status
        item = reg.add(
            item_id=name,
            kind=card_obj.type if card_obj.type in {"recovery", "policy", "diagnostic", "blocked"} else "recovery",
            status=item_status,
            card=card_path,
        )
        console.print(f"[green]Added {name} to registry[/green] status={item.status}")
    else:
        console.print(f"[red]Unknown registry action: {action}[/red]")
        raise typer.Exit(1)


@darwin_app.command()
def report(
    out: str = typer.Option("reports/darwin_v1", "--out", help="Output directory"),
    cards_dir: str = typer.Option("cards", "--cards", help="Directory containing evidence cards"),
) -> None:
    """Bundle evidence cards into a product report."""
    out_dir = ensure_dir(out)
    cards_path = Path(cards_dir)
    card_files = sorted(cards_path.glob("*.card.yaml")) if cards_path.exists() else []
    index = {
        "generated_at": _now(),
        "card_count": len(card_files),
        "cards": [str(p) for p in card_files],
    }
    (out_dir / "report_index.json").write_text(json.dumps(index, indent=2))
    console.print(f"[green]Report index generated[/green] with {len(card_files)} cards")
    console.print(f"  Output: {out_dir / 'report_index.json'}")


# -----------------------------------------------------------------------------
# Evolution sub-commands: candidate-vs-baseline cycles + ledger
# -----------------------------------------------------------------------------

evolution_app = typer.Typer(help="Continuous evolution engine")
darwin_app.add_typer(evolution_app, name="evolution")

# -----------------------------------------------------------------------------
# Evaluation sub-commands: native benchmark backends
# -----------------------------------------------------------------------------
darwin_app.add_typer(eval_app, name="eval")


def _default_recipe(candidate_id: str) -> HintRecipe:
    return HintRecipe(
        name=candidate_id,
        source="paired_no_regression_default",
        trigger_tags=[],
        hints=[],
        route_selection="conditional_micro_recovery",
        evidence_gate={
            "gate_type": "paired_no_regression",
            "min_rescued_count": 1,
            "max_newly_failed_count": 0,
        },
    )


@evolution_app.command(name="run")
def evolution_run(
    task: str = typer.Option(..., "--task", help="Path to task YAML"),
    candidates: str = typer.Option(..., "--candidates", help="Path to candidate queue YAML"),
    seeds: str = typer.Option("0:0", "--seeds", help="Seed range, e.g. 0:4"),
    episodes: int = typer.Option(1, "--episodes", help="Episodes per seed"),
    max_steps: int = typer.Option(720, "--max-steps", help="Max steps per episode"),
    out: str = typer.Option("data/darwin/evolution", "--out", help="Output directory"),
    adapter: str = typer.Option("libero", "--adapter", help="Environment adapter"),
    suite: str | None = typer.Option(None, "--suite", help="Optional suite name for ledger"),
    registry_dir: str = typer.Option("data/darwin/registry", "--registry", help="Registry directory"),
    ledger_path: str = typer.Option("data/darwin/evolution_ledger.jsonl", "--ledger", help="Ledger path"),
    cards_dir: str = typer.Option("cards", "--cards", help="Evidence cards directory"),
    no_promote: bool = typer.Option(False, "--no-promote", help="Skip registry promotion"),
) -> None:
    """Run baseline-vs-candidate evolution cycles and append to the ledger."""
    candidates_data = _load_yaml(candidates)
    baseline_id = candidates_data["baseline"]["id"]
    baseline_policy = candidates_data["baseline"]["policy"]
    task_path = candidates_data.get("task", task)
    candidate_list = candidates_data.get("candidates", [])

    if not candidate_list:
        console.print("[red]No candidates in queue[/red]")
        raise typer.Exit(1)

    out_root = ensure_dir(out)
    ledger = EvolutionLedger(ledger_path)
    registry = PromotionRegistry(registry_dir) if not no_promote else None
    generator = CardGenerator(cards_dir)
    task_obj = TaskLoader().load(task_path)

    script = Path(__file__).resolve().parents[2] / "scripts" / "proof" / "run_libero_paired_evaluation.py"

    for candidate in candidate_list:
        candidate_id = candidate["id"]
        candidate_policy = candidate["policy"]
        expected_status = candidate.get("expected_status", "experimental_only")
        cycle_id = f"{task_obj.id}_{baseline_id}_vs_{candidate_id}_{_now()}"
        cycle_id = cycle_id.replace(":", "-").replace(".", "-")
        cycle_out = out_root / candidate_id
        cycle_out.mkdir(parents=True, exist_ok=True)

        console.print(f"[cyan]Evolution cycle {cycle_id}[/cyan]")

        if adapter == "libero":
            cmd = [
                sys.executable,
                str(script),
                "--task", task_path,
                "--baseline-policy", baseline_policy,
                "--candidate-policy", candidate_policy,
                "--seeds", seeds,
                "--episodes", str(episodes),
                "--max-steps", str(max_steps),
                "--out-dir", str(cycle_out),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            console.print(result.stdout)
            if result.returncode != 0:
                console.print(f"[red]Paired evaluation failed for {candidate_id}:[/red] {result.stderr}")
                continue
        else:
            console.print(f"[red]Adapter {adapter} not yet supported by evolution run[/red]")
            continue

        summary_path = cycle_out / "paired_summary.json"
        if not summary_path.exists():
            console.print(f"[yellow]No paired summary for {candidate_id}[/yellow]")
            continue

        summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
        summary = PairedEvaluationSummary.model_validate(summary_data.get("summary", summary_data))

        recipe = _default_recipe(candidate_id)
        manager = PromotionManager(paired_eval=summary)
        fth_status = manager.evaluate(recipe)

        seed_list = _parse_seed_range(seeds)
        baseline_real_flag = bool(candidates_data.get("baseline", {}).get("real", False))
        candidate_real_flag = bool(candidate.get("real", False))
        candidate_metrics_synthetic_flag = bool(candidate.get("metrics_synthetic", False))
        promotion_scope = candidate.get("promotion_scope") or candidates_data.get("baseline", {}).get("promotion_scope")

        evidence_type = infer_evidence_type(
            baseline_real=baseline_real_flag,
            candidate_real=candidate_real_flag,
            candidate_metrics_synthetic=candidate_metrics_synthetic_flag,
        )
        evidence_level = infer_evidence_level(
            evidence_type=evidence_type,
            baseline_real=baseline_real_flag,
            candidate_real=candidate_real_flag,
            candidate_metrics_synthetic=candidate_metrics_synthetic_flag,
            promotion_status=fth_status.promotion_status,
            seed_count=len(seed_list),
        )
        runtime_eligible = is_runtime_eligible(evidence_level, evidence_type)

        decision = PromotionDecision(
            candidate_name=candidate_id,
            status=fth_status.promotion_status,
            claim_level=fth_status.promotion_status,
            passed_gates=["paired_no_regression"] if fth_status.evidence_gate_passed else [],
            failed_gates=[] if fth_status.evidence_gate_passed else ["paired_no_regression"],
            limitations=["evaluated seed set only"],
            allowed_claims=[f"{fth_status.promotion_status} on evaluated seeds"],
            disallowed_claims=["validated_transferable_skill"],
            next_required_evidence=["independent hold-out replication"],
            fth_status=fth_status,
            evidence_level=evidence_level,
            evidence_type=evidence_type,
            runtime_eligible=runtime_eligible,
            promotion_scope=promotion_scope,
        )
        decision_path = cycle_out / "promotion_decision.json"
        decision_path.write_text(json.dumps(decision.model_dump(mode="json"), indent=2), encoding="utf-8")

        card = generator.generate_card(
            candidate_name=candidate_id,
            promotion_decision=decision,
            candidate=CandidateIntervention(
                name=candidate_id,
                intervention_type="policy_patch",
                policy_config_path=candidate_policy,
                status=fth_status.promotion_status,
            ),
            artifacts={
                "paired_summary": str(summary_path),
                "promotion_decision": str(decision_path),
            },
            summary=(
                f"LIBERO evolution cycle: {baseline_id} vs {candidate_id}. "
                f"Baseline SR {summary.baseline_success_rate:.2%}, "
                f"candidate SR {summary.candidate_success_rate:.2%}, "
                f"expected_status={expected_status}."
            ),
            evidence_level=evidence_level,
            evidence_type=evidence_type,
            runtime_eligible=runtime_eligible,
            promotion_scope=promotion_scope,
        )
        yaml_path, md_path = generator.save_card(card, override=True)

        registry_item_id: str | None = None
        if registry is not None:
            try:
                item = registry.add(
                    item_id=candidate_id,
                    kind="policy",
                    status=fth_status.promotion_status,
                    card=str(yaml_path),
                    evidence_level=evidence_level,
                    evidence_type=evidence_type,
                    runtime_eligible=runtime_eligible,
                    promotion_scope=promotion_scope,
                )
                registry_item_id = item.id
            except ValueError as e:
                console.print(f"[yellow]Registry add skipped: {e}[/yellow]")

        entry = EvolutionLedgerEntry(
            cycle_id=cycle_id,
            backend=adapter,
            suite=suite,
            task_id=task_obj.id,
            baseline_policy_id=baseline_id,
            candidate_policy_id=candidate_id,
            seed_range=seeds,
            paired_summary_path=str(summary_path),
            summary_snapshot=summary_data,
            promotion_status=fth_status.promotion_status,
            gate_passed=fth_status.evidence_gate_passed,
            card_path=str(yaml_path),
            registry_item_id=registry_item_id,
            metrics={
                "baseline_success_rate": summary.baseline_success_rate,
                "candidate_success_rate": summary.candidate_success_rate,
                "rescued_count": summary.rescued_count,
                "newly_failed_count": summary.newly_failed_count,
                "net_delta": summary.net_delta,
                "mcnemar_p_value": summary.mcnemar_p_value or -1.0,
            },
            notes=[
                f"expected_status={expected_status}",
                f"gate_reason={fth_status.gate_reason}",
                f"baseline_metrics_real={baseline_real_flag}",
                f"candidate_metrics_real={candidate_real_flag}",
                "real_environment=true" if evidence_type == "real_environment" else "real_environment=false",
            ],
            evidence_level=evidence_level,
            evidence_type=evidence_type,
            runtime_eligible=runtime_eligible,
            promotion_scope=promotion_scope,
            baseline_real=baseline_real_flag,
            candidate_real=candidate_real_flag,
            candidate_metrics_synthetic=candidate_metrics_synthetic_flag,
        )
        ledger.add_entry(entry)

        console.print(f"[green]Cycle {cycle_id}[/green] status={fth_status.promotion_status}")
        console.print(f"  Baseline SR: {summary.baseline_success_rate:.3f}")
        console.print(f"  Candidate SR: {summary.candidate_success_rate:.3f}")
        console.print(f"  Rescued: {summary.rescued_count}, Newly failed: {summary.newly_failed_count}")
        console.print(f"  Card: {yaml_path}")


@evolution_app.command(name="ledger-show")
def evolution_ledger_show(
    cycle: str = typer.Option(..., "--cycle", help="Cycle ID"),
    ledger_path: str = typer.Option("data/darwin/evolution_ledger.jsonl", "--ledger", help="Ledger path"),
) -> None:
    """Show one evolution ledger entry."""
    ledger = EvolutionLedger(ledger_path)
    entry = ledger.show(cycle)
    if entry is None:
        console.print(f"[yellow]Cycle {cycle} not found[/yellow]")
        raise typer.Exit(1)
    console.print(json.dumps(entry.model_dump(mode="json"), indent=2))


@evolution_app.command(name="ledger-add")
def evolution_ledger_add(
    promotion_json: str = typer.Argument(..., help="Path to promotion_decision.json"),
    ledger_path: str = typer.Option("data/darwin/evolution_ledger.jsonl", "--ledger", help="Ledger path"),
    task_id: str = typer.Option("unknown", "--task", help="Task ID"),
    baseline_policy_id: str = typer.Option("unknown", "--baseline", help="Baseline policy ID"),
    candidate_policy_id: str = typer.Option("unknown", "--candidate", help="Candidate policy ID"),
) -> None:
    """Manually append a ledger entry from a promotion decision."""
    decision_data = json.loads(Path(promotion_json).read_text(encoding="utf-8"))
    status = decision_data.get("status", "experimental_only")
    entry = EvolutionLedgerEntry(
        cycle_id=f"manual_{_now()}".replace(":", "-").replace(".", "-"),
        backend="manual",
        task_id=task_id,
        baseline_policy_id=baseline_policy_id,
        candidate_policy_id=candidate_policy_id,
        seed_range="manual",
        promotion_status=status,
        gate_passed=bool(decision_data.get("passed_gates")),
        summary_snapshot=decision_data,
    )
    EvolutionLedger(ledger_path).add_entry(entry)
    console.print(f"[green]Ledger entry added[/green] status={status}")


@evolution_app.command(name="ledger-validate")
def evolution_ledger_validate(
    ledger_path: str = typer.Option("data/darwin/evolution_ledger.jsonl", "--ledger", help="Ledger path"),
    cards_dir: str = typer.Option("cards", "--cards", help="Evidence cards directory"),
) -> None:
    """Validate ledger entries against the v1.4 evidence taxonomy."""
    from rosclaw_darwin.evolution.evidence_level import (
        REAL_EVIDENCE_LEVELS,
        RUNTIME_ELIGIBLE_LEVELS,
    )

    ledger = EvolutionLedger(ledger_path)
    entries = ledger.list_entries()
    errors: list[str] = []
    card_dir = Path(cards_dir)

    for entry in entries:
        if entry.evidence_level in REAL_EVIDENCE_LEVELS and entry.evidence_type == EvidenceType.SYNTHETIC.value:
            errors.append(
                f"{entry.cycle_id}: real evidence_level {entry.evidence_level} but evidence_type is synthetic"
            )
        if entry.runtime_eligible:
            if entry.evidence_level not in RUNTIME_ELIGIBLE_LEVELS:
                errors.append(
                    f"{entry.cycle_id}: runtime_eligible=True but level {entry.evidence_level} is not eligible"
                )
            if entry.evidence_type != EvidenceType.REAL_ENVIRONMENT.value:
                errors.append(
                    f"{entry.cycle_id}: runtime_eligible=True but evidence_type is {entry.evidence_type}"
                )
        if entry.card_path and not (card_dir / Path(entry.card_path).name).exists():
            # card_path may be absolute or relative; try both.
            if not Path(entry.card_path).exists():
                errors.append(f"{entry.cycle_id}: card_path {entry.card_path} not found")

    if errors:
        console.print(f"[red]Ledger validation failed with {len(errors)} error(s):[/red]")
        for err in errors:
            console.print(f"  - {err}")
        raise typer.Exit(1)

    console.print(f"[green]Ledger validation passed[/green] for {len(entries)} entries")


@evolution_app.command(name="ledger-export")
def evolution_ledger_export(
    out: str = typer.Option(..., "--out", help="Output path"),
    fmt: str = typer.Option("markdown", "--fmt", help="Export format: json, csv, markdown"),
    ledger_path: str = typer.Option("data/darwin/evolution_ledger.jsonl", "--ledger", help="Ledger path"),
) -> None:
    """Export the evolution ledger."""
    ledger = EvolutionLedger(ledger_path)
    exported = ledger.export(out, fmt=fmt)
    console.print(f"[green]Ledger exported[/green] to {exported}")


# -----------------------------------------------------------------------------
# Evidence sub-commands: validation of cards, ledger, and claim boundaries
# -----------------------------------------------------------------------------

evidence_app = typer.Typer(help="Evidence validation")
darwin_app.add_typer(evidence_app, name="evidence")


@evidence_app.command(name="validate")
def evidence_validate(
    cards_dir: str = typer.Option("cards", "--cards", help="Directory containing evidence cards"),
    ledger_path: str = typer.Option("data/darwin/evolution_ledger.jsonl", "--ledger", help="Ledger path"),
    reports_dir: str = typer.Option("reports", "--reports", help="Directory containing reports"),
    strict: bool = typer.Option(True, "--strict/--no-strict", help="Treat warnings as errors"),
) -> None:
    """Validate evidence cards, evolution ledger, and report claim boundaries."""
    import subprocess

    errors: list[str] = []

    # 1. Claim boundaries
    claim_script = Path(__file__).resolve().parents[2] / "scripts" / "quality" / "check_claim_boundaries.py"
    if claim_script.exists():
        result = subprocess.run(
            [sys.executable, str(claim_script), "--reports-dir", reports_dir],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            errors.append("Claim boundary lint failed.\n" + result.stdout + result.stderr)
        else:
            console.print("[green]Claim boundaries OK[/green]")
    else:
        console.print(f"[yellow]Claim boundary script not found: {claim_script}[/yellow]")

    # 2. Evidence card linter
    card_script = Path(__file__).resolve().parents[2] / "scripts" / "quality" / "check_evidence_cards.py"
    if card_script.exists():
        cmd = [sys.executable, str(card_script), "--cards-dir", cards_dir]
        if ledger_path:
            cmd.extend(["--ledger", ledger_path])
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            errors.append("Evidence card lint failed.\n" + result.stdout + result.stderr)
        else:
            console.print("[green]Evidence cards OK[/green]")
    else:
        console.print(f"[yellow]Evidence card linter not found: {card_script}[/yellow]")

    # 3. Ledger validator
    ledger_script = Path(__file__).resolve().parents[2] / "scripts" / "quality" / "validate_evolution_ledger.py"
    if ledger_script.exists() and Path(ledger_path).exists():
        cmd = [sys.executable, str(ledger_script), "--ledger", ledger_path, "--cards-dir", cards_dir]
        if strict:
            cmd.append("--strict")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            errors.append("Ledger validation failed.\n" + result.stdout + result.stderr)
        else:
            console.print("[green]Evolution ledger OK[/green]")
    elif not ledger_script.exists():
        console.print(f"[yellow]Ledger validator not found: {ledger_script}[/yellow]")
    else:
        console.print(f"[yellow]Ledger file not found: {ledger_path}[/yellow]")

    if errors:
        console.print(f"[red]Evidence validation failed with {len(errors)} error(s):[/red]")
        for err in errors:
            console.print(err)
        raise typer.Exit(1)

    console.print("[green]Evidence validation passed[/green]")


# -----------------------------------------------------------------------------
# Suite sub-commands: create and run task suites
# -----------------------------------------------------------------------------

suite_app = typer.Typer(help="Task suite commands")
darwin_app.add_typer(suite_app, name="suite")


@suite_app.command(name="run")
def suite_run(
    suite: str = typer.Option(..., "--suite", help="Path to suite YAML"),
    adapter: str = typer.Option("libero", "--adapter", help="Adapter for run"),
    policy: str = typer.Option("configs/policies/zero_action.yaml", "--policy", help="Path to policy config"),
    episodes: int = typer.Option(1, "--episodes", help="Episodes per task"),
    out: str | None = typer.Option(None, "--out", help="Output directory"),
    resume: bool = typer.Option(False, "--resume", help="Skip already-completed tasks"),
) -> None:
    """Run a task suite."""
    suite_path = Path(suite)
    if not suite_path.exists():
        console.print(f"[red]Suite file not found: {suite}[/red]")
        raise typer.Exit(1)

    suite_data = yaml.safe_load(suite_path.read_text(encoding="utf-8")) or {}
    raw_tasks = suite_data.get("tasks", [])
    task_entries: list[tuple[str | None, str]] = []
    for entry in raw_tasks:
        if isinstance(entry, dict):
            task_entries.append((entry.get("name"), entry.get("task")))
        elif isinstance(entry, str):
            task_entries.append((None, entry))
        else:
            console.print(f"[yellow]Skipping unknown suite task entry: {entry}[/yellow]")

    policy_config = _load_yaml(policy)
    policy_config.setdefault("policy_id", Path(policy).stem)

    if adapter == "libero":
        from rosclaw_darwin.cli.main import _run_libero_suite
        _run_libero_suite(
            suite_data=suite_data,
            task_entries=task_entries,
            policy_config=policy_config,
            episodes=episodes,
            out=out,
            resume=resume,
        )
        return

    console.print(f"[red]Adapter {adapter} is not supported by `darwin suite run`.[/red]")
    raise typer.Exit(1)



# -----------------------------------------------------------------------------
# Arena official workflow sub-commands
# -----------------------------------------------------------------------------

arena_app = typer.Typer(help="Arena official workflow commands")
darwin_app.add_typer(arena_app, name="arena")

arena_official_app = typer.Typer(help="Official GR1 Open Microwave workflow")
arena_app.add_typer(arena_official_app, name="official")


@arena_official_app.command(name="run")
def arena_official_run(
    task: str = typer.Option("configs/tasks/arena/gr1_open_microwave_official.yaml", "--task", help="Task config"),
    policy: str = typer.Option("configs/policies/arena_gr1_gn1x_official.yaml", "--policy", help="Policy config"),
    probe_dir: str = typer.Option("data_darwin_arena/official_gr1_assets", "--probe-dir", help="Asset probe directory"),
    runner_dir: str = typer.Option("data_darwin_arena/official_gr1_policy_runner/single_env", "--runner-dir", help="Runner output directory"),
    cards_dir: str = typer.Option("cards", "--cards", help="Cards directory"),
    skip_probe: bool = typer.Option(False, "--skip-probe", help="Skip asset probe/download steps"),
    skip_replay: bool = typer.Option(False, "--skip-replay", help="Skip dataset replay"),
    skip_server: bool = typer.Option(False, "--skip-server", help="Skip GR00T server launch"),
) -> None:
    """Run the official Arena GR1 Open Microwave workflow end-to-end."""
    from rosclaw_darwin.adapters.arena_official_runner_adapter import (
        ArenaOfficialRunnerAdapter,
        write_wrapper_card,
    )

    adapter = ArenaOfficialRunnerAdapter(
        probe_dir=Path(probe_dir),
        runner_dir=Path(runner_dir),
        cards_dir=Path(cards_dir),
    )
    wrapper, result = adapter.run_official_workflow(
        task_id=Path(task).stem,
        policy_id=Path(policy).stem,
        run_probe=not skip_probe,
        run_download=not skip_probe,
        run_replay=not skip_replay,
        run_server=not skip_server,
        run_runner=True,
    )
    yaml_path, md_path = write_wrapper_card(Path(runner_dir), wrapper, Path(cards_dir))
    console.print(f"[cyan]Workflow status:[/cyan] {result.status}")
    console.print(f"[cyan]Card:[/cyan] {yaml_path}")
    if wrapper.get("blocked"):
        console.print(f"[yellow]Blocked: {wrapper.get('failure_classification')}[/yellow]")
        raise typer.Exit(2)
    console.print(f"[green]success_rate={wrapper.get('metrics', {}).get('success_rate')}, "
                  f"door_moved_rate={wrapper.get('metrics', {}).get('door_moved_rate')}[/green]")

@darwin_app.command()
def dashboard(
    data_dir: str = typer.Option("data", "--data", help="Data directory"),
    port: int = typer.Option(8080, "--port", help="Port"),
    host: str = typer.Option("0.0.0.0", "--host", help="Host"),
) -> None:
    """Start the evolution dashboard."""
    from rosclaw_darwin.dashboard.app import DashboardApp
    app_obj = DashboardApp(data_dir=data_dir)
    console.print(f"[green]Starting dashboard on http://{host}:{port}[/green]")
    app_obj.run(host=host, port=port)

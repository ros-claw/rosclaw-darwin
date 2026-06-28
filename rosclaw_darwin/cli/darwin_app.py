"""Darwin v1.0 product CLI subcommands.

These commands expose the evidence pipeline through a unified surface:
validate-env, run, diagnose, pair-eval, promote, card, registry, report.
Every command supports a --mock mode so the CLI can be exercised without
Arena Docker runs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console

from rosclaw_darwin.evaluation.object_validity import (
    ObjectValidityReport,
    check_object_validity,
)
from rosclaw_darwin.evaluation.paired_evaluation import PairedEvaluationSummary
from rosclaw_darwin.evidence import CardGenerator, generate_all_demo_cards
from rosclaw_darwin.evolution.hint_recipe import HintRecipe
from rosclaw_darwin.evolution.promotion_manager import PromotionManager
from rosclaw_darwin.registry import PromotionRegistry, get_claims
from rosclaw_darwin.schemas.evidence_card import EvidenceCard
from rosclaw_darwin.schemas.promotion_decision import PromotionDecision
from rosclaw_darwin.schemas.run_artifact import RunArtifact
from rosclaw_darwin.schemas.task_validity import TaskValidity
from rosclaw_darwin.tdl.loader import TaskLoader
from rosclaw_darwin.utils.paths import ensure_dir

darwin_app = typer.Typer(help="ROSClaw-Darwin v1.0 evidence engine")
console = Console()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_yaml(path: str) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


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
    out: str = typer.Option("data/darwin/runs", "--out", help="Output directory"),
    mock: bool = typer.Option(True, "--mock/--live", help="Use synthetic run artifacts"),
) -> None:
    """Run a policy and emit a RunArtifact."""
    out_dir = ensure_dir(out)
    t = TaskLoader().load(task)
    policy_name = Path(policy).stem

    if mock:
        is_official = "dex_cube_official" in t.id
        success_rate = 0.99 if is_official else 0.0
        result = RunArtifact(
            run_id=f"{t.id}_{policy_name}_mock",
            task_id=t.id,
            policy_id=policy_name,
            adapter="mock",
            status="completed",
            metrics={"success_rate": success_rate, "num_episodes": 100},
            started_at=_now(),
            finished_at=_now(),
        )
    else:
        console.print("[red]Live run is not implemented in the Darwin CLI. Use rosclaw run.[/red]")
        raise typer.Exit(1)

    run_dir = out_dir / result.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_artifact.json").write_text(
        json.dumps(result.model_dump(mode="json"), indent=2)
    )
    console.print(f"[green]Run {result.run_id} completed[/green]")
    console.print(f"  Success rate: {result.metrics.get('success_rate', 0.0):.2%}")
    console.print(f"  Output: {run_dir / 'run_artifact.json'}")


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
    task: str = typer.Option(..., "--task", help="Path to task YAML"),
    baseline: str = typer.Option(..., "--baseline", help="Path to baseline policy config"),
    candidate: str = typer.Option(..., "--candidate", help="Path to candidate policy config"),
    seeds: str = typer.Option("0:4", "--seeds", help="Seed range"),
    out: str = typer.Option("data/darwin/paired", "--out", help="Output directory"),
    mock: bool = typer.Option(True, "--mock/--live", help="Use synthetic paired outcomes"),
) -> None:
    """Run paired no-regression evaluation and emit a paired summary."""
    out_dir = ensure_dir(out)

    if mock:
        script = (
            Path(__file__).resolve().parents[2]
            / "scripts"
            / "diagnostics"
            / "run_paired_policy_evaluation.py"
        )
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
        console.print("[red]Live pair-eval requires the paired evaluation runner.[/red]")
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
) -> None:
    """Evaluate promotion evidence and emit a PromotionDecision."""
    out_dir = ensure_dir(out)
    summary_data = json.loads(Path(paired_summary).read_text())
    summary = PairedEvaluationSummary.model_validate(
        summary_data.get("summary", summary_data)
    )

    if recipe:
        recipe_obj = HintRecipe.model_validate(_load_yaml(recipe))
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

    manager = PromotionManager(paired_eval=summary)
    fth_status = manager.evaluate(recipe_obj)

    decision = PromotionDecision(
        candidate_name=candidate,
        status=fth_status.promotion_status,
        claim_level=fth_status.promotion_status,
        passed_gates=["paired_no_regression"] if fth_status.evidence_gate_passed else [],
        failed_gates=[] if fth_status.evidence_gate_passed else ["paired_no_regression"],
        limitations=["evaluated seed set only"],
        allowed_claims=[f"{fth_status.promotion_status} on evaluated seeds"],
        disallowed_claims=["validated_transferable_skill"],
        next_required_evidence=["independent hold-out replication"],
        fth_status=fth_status,
    )

    (out_dir / f"{candidate}_promotion_decision.json").write_text(
        json.dumps(decision.model_dump(mode="json"), indent=2)
    )
    console.print(f"[green]Promotion decision for {candidate}:[/green] {decision.status}")
    console.print(f"  Gate passed: {fth_status.evidence_gate_passed}")
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

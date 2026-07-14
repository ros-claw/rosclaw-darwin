"""Darwin ``eval`` subcommands: native benchmark evaluation backends.

These commands expose the P3 evaluation backend through ``darwin eval *``.
They never import ``torch`` or ``lerobot`` directly; heavy dependencies are
executed inside the registered runtime.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.table import Table

from rosclaw_darwin.evaluation.backends.lerobot import LeRobotEvalBackend
from rosclaw_darwin.evaluation.parsers.lerobot_eval import parse_eval_info
from rosclaw_darwin.evaluation.result_v2 import EvaluationResultV2
from rosclaw_darwin.evaluation.runtime import (
    EvalRuntime,
    get_runtime,
    list_runtimes,
    register_runtime,
)
from rosclaw_darwin.evaluation.spec import EvaluationSpec
from rosclaw_darwin.utils.paths import ensure_dir


eval_app = typer.Typer(help="Native benchmark evaluation backends")
runtime_app = typer.Typer(help="Evaluation runtime registry")
eval_app.add_typer(runtime_app, name="runtime")

console = Console()


def _load_spec(path: str) -> EvaluationSpec:
    return EvaluationSpec.from_path(path)


def _spec_to_dict(spec: EvaluationSpec) -> dict[str, Any]:
    return spec.model_dump(mode="json")


def _build_inline_spec(
    backend: str,
    runtime: str | None,
    policy: str,
    env_type: str,
    env_task: str | None,
    episodes: int,
    batch_size: int,
    device: str,
    allow_network: bool,
    out: str,
) -> dict[str, Any]:
    return {
        "id": f"{env_type}_inline",
        "backend": backend,
        "runtime": runtime or {
            "python": sys.executable,
            "lerobot_eval": shutil.which("lerobot-eval"),
        },
        "policy": {
            "path": policy,
            "device": device,
            "allow_network": allow_network,
            "use_amp": False,
        },
        "environment": {
            "type": env_type,
            "task": env_task,
            "batch_size": batch_size,
        },
        "evaluation": {
            "n_episodes": episodes,
            "start_seed": 42,
            "timeout_sec": 1800,
        },
        "output": {
            "root": out,
            "keep_raw": True,
            "keep_videos": True,
            "keep_worker_dir": False,
        },
    }


def _redact_text(text: str) -> str:
    """Mask likely secret values before printing or writing log excerpts."""
    pattern = re.compile(
        r"(?P<key>\b(?:HF_TOKEN|hf_token|HUGGINGFACE_TOKEN|API_KEY|api_key|"
        r"PASSWORD|password|SECRET|secret|TOKEN|token|PRIVATE_KEY)\b)"
        r"\s*[:=]\s*[^\s\"']+",
        re.IGNORECASE,
    )
    return pattern.sub(lambda m: f"{m.group('key')}=***", text)


# ------------------------------------------------------------------------------
# Runtime commands
# ------------------------------------------------------------------------------

@runtime_app.command(name="list")
def runtime_list() -> None:
    """List registered evaluation runtimes."""
    runtimes = list_runtimes()
    if not runtimes:
        console.print("[yellow]No evaluation runtimes registered.[/yellow]")
        return

    table = Table(title="Evaluation Runtimes")
    table.add_column("Name", style="cyan")
    table.add_column("Mode", style="green")
    table.add_column("Python / Image", style="dim")
    table.add_column("Tags")
    for name, rt in runtimes.items():
        loc = rt.python or rt.image or "-"
        table.add_row(name, rt.mode, loc, ", ".join(rt.tags))
    console.print(table)


@runtime_app.command(name="register")
def runtime_register(
    name: str = typer.Option(..., "--name", help="Runtime name"),
    mode: str = typer.Option("external", "--mode", help="external or docker"),
    python: str | None = typer.Option(None, "--python", help="Python executable"),
    lerobot_eval: str | None = typer.Option(None, "--lerobot-eval", help="lerobot-eval executable"),
    image: str | None = typer.Option(None, "--image", help="Docker image"),
    workdir: str | None = typer.Option(None, "--workdir", help="Working directory"),
    gpu: bool = typer.Option(False, "--gpu", help="GPU required"),
    env: list[str] | None = typer.Option(None, "--env", help="KEY=VALUE environment variables"),
    tag: list[str] | None = typer.Option(None, "--tag", help="Runtime tags"),
) -> None:
    """Register or update an evaluation runtime."""
    environment: dict[str, str] = {}
    for item in env or []:
        if "=" not in item:
            console.print(f"[red]Invalid env value (expected KEY=VALUE): {item}[/red]")
            raise typer.Exit(1)
        key, value = item.split("=", 1)
        environment[key] = value

    runtime = EvalRuntime(
        name=name,
        mode=mode,  # type: ignore[arg-type]
        python=python,
        lerobot_eval=lerobot_eval,
        image=image,
        workdir=workdir,
        gpu=gpu,
        environment=environment,
        tags=list(tag or []),
    )
    register_runtime(name, runtime)
    console.print(f"[green]Registered runtime:[/green] {name} ({mode})")


@runtime_app.command(name="show")
def runtime_show(name: str = typer.Argument(..., help="Runtime name")) -> None:
    """Show details for a registered runtime."""
    try:
        rt = get_runtime(name)
    except KeyError:
        console.print(f"[red]Runtime not found: {name}[/red]")
        raise typer.Exit(1)
    console.print(json.dumps(rt.model_dump(mode="json"), indent=2))


@runtime_app.command(name="remove")
def runtime_remove(name: str = typer.Argument(..., help="Runtime name")) -> None:
    """Remove a registered runtime."""
    from rosclaw_darwin.evaluation.runtime import load_eval_runtimes, save_eval_runtimes

    runtimes = load_eval_runtimes()
    if name not in runtimes:
        console.print(f"[red]Runtime not found: {name}[/red]")
        raise typer.Exit(1)
    del runtimes[name]
    save_eval_runtimes(runtimes)
    console.print(f"[green]Removed runtime:[/green] {name}")


@runtime_app.command(name="doctor")
def runtime_doctor(
    name: str = typer.Argument(..., help="Runtime name"),
    env_type: str = typer.Option("pusht", "--env-type", help="Environment type to probe"),
    device: str = typer.Option("cpu", "--device", help="Device to probe"),
    policy: str = typer.Option("", "--policy", help="Policy path to probe"),
    allow_network: bool = typer.Option(False, "--allow-network", help="Allow Hub downloads"),
) -> None:
    """Probe a registered runtime and print a structured readiness report."""
    try:
        rt = get_runtime(name)
    except KeyError:
        console.print(f"[red]Runtime not found: {name}[/red]")
        raise typer.Exit(1)

    backend = LeRobotEvalBackend()
    spec_dict = {
        "backend": "lerobot_eval",
        "runtime": name,
        "policy": {"path": policy, "device": device, "allow_network": allow_network},
        "environment": {"type": env_type},
        "evaluation": {"n_episodes": 1},
        "output": {"root": "data/eval_runs"},
    }
    probe = backend.probe(spec_dict)
    report = {
        "runtime": rt.model_dump(mode="json"),
        "probe": {
            "status": probe.status,
            "messages": probe.messages,
            "device": probe.device,
            "policy": probe.policy,
            "environment": probe.environment,
        },
    }
    console.print(json.dumps(report, indent=2, default=str))
    if probe.status == "error":
        raise typer.Exit(2)


# ------------------------------------------------------------------------------
# Doctor
# ------------------------------------------------------------------------------

@eval_app.command(name="doctor")
def eval_doctor(
    runtime: str | None = typer.Option(None, "--runtime", help="Runtime name to probe"),
    spec: str | None = typer.Option(None, "--spec", help="Optional evaluation spec YAML"),
) -> None:
    """Probe evaluation runtimes or a specific evaluation spec."""
    backend = LeRobotEvalBackend()

    if runtime:
        try:
            rt = get_runtime(runtime)
        except KeyError:
            console.print(f"[red]Runtime not found: {runtime}[/red]")
            raise typer.Exit(1)
        spec_dict: dict[str, Any]
        if spec:
            spec_dict = _spec_to_dict(_load_spec(spec))
        else:
            spec_dict = {
                "backend": "lerobot_eval",
                "runtime": runtime,
                "policy": {"path": "", "device": "cpu", "allow_network": False},
                "environment": {"type": ""},
                "evaluation": {"n_episodes": 1},
                "output": {"root": "data/eval_runs"},
            }
        probe_result = backend.probe(spec_dict)
        table = Table(title=f"Runtime Probe: {runtime}")
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Mode", rt.mode)
        table.add_row("Status", probe_result.status)
        table.add_row("LeRobot version", str(probe_result.environment.get("lerobot_version", "unknown")))
        table.add_row("Policy exists", str(probe_result.policy.get("local_exists", False)))
        table.add_row("Env registered", str(probe_result.environment.get("registered", "unknown")))
        table.add_row("Device available", str(probe_result.device.get("available", "unknown")))
        if probe_result.messages:
            table.add_row("Messages", "\n".join(probe_result.messages))
        console.print(table)
        if probe_result.status == "error":
            raise typer.Exit(2)
        return

    # No runtime requested: list all runtimes and their static configuration.
    runtimes = list_runtimes()
    if not runtimes:
        console.print("[yellow]No evaluation runtimes registered.[/yellow]")
        console.print("Use [cyan]darwin eval runtime register[/cyan] to add one.")
        return
    table = Table(title="Registered Evaluation Runtimes")
    table.add_column("Name", style="cyan")
    table.add_column("Mode", style="green")
    table.add_column("Location", style="dim")
    table.add_column("Tags")
    for name, rt in runtimes.items():
        loc = rt.python or rt.image or "-"
        table.add_row(name, rt.mode, loc, ", ".join(rt.tags))
    console.print(table)


# ------------------------------------------------------------------------------
# Plan
# ------------------------------------------------------------------------------

@eval_app.command(name="plan")
def eval_plan(
    spec: str = typer.Option(..., "--spec", help="Path to evaluation spec YAML"),
    out: str | None = typer.Option(None, "--out", help="Optional output JSON path"),
) -> None:
    """Generate an immutable evaluation plan without executing it."""
    spec_obj = _load_spec(spec)
    spec_dict = _spec_to_dict(spec_obj)

    backend = LeRobotEvalBackend()
    plan = backend.plan(spec_dict)

    plan_data = {
        "schema_version": "rosclaw.darwin.eval_plan.v1",
        "run_id": plan.run_id,
        "spec_hash": plan.spec_hash,
        "backend": plan.backend,
        "runtime": plan.runtime,
        "command": plan.command,
        "environment": plan.environment,
        "policy": plan.policy,
        "benchmark": plan.benchmark,
        "expected_tasks": plan.expected_tasks,
        "expected_episodes": plan.expected_episodes,
        "output_dir": plan.output_dir,
        "timeout_sec": plan.timeout_sec,
    }

    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(plan_data, indent=2), encoding="utf-8")
        console.print(f"[green]Plan written to[/green] {out}")
    else:
        console.print(json.dumps(plan_data, indent=2))


# ------------------------------------------------------------------------------
# Run helper
# ------------------------------------------------------------------------------

def _run_spec_dict(
    spec_dict: dict[str, Any],
    backend_obj: LeRobotEvalBackend,
    skip_probe: bool = False,
    dry_run: bool = False,
) -> tuple[Any | None, EvaluationResultV2 | None]:
    """Run a single spec dict through probe, plan, execute, and normalize."""
    if not skip_probe:
        console.print("[cyan]Probing runtime...[/cyan]")
        probe_result = backend_obj.probe(spec_dict)
        if probe_result.status == "error":
            console.print(f"[red]Probe failed:[/red] {'; '.join(probe_result.messages)}")
            raise typer.Exit(2)
        if probe_result.status == "degraded":
            console.print(f"[yellow]Probe degraded:[/yellow] {'; '.join(probe_result.messages)}")
        else:
            console.print(
                f"[green]Probe ok[/green] (LeRobot {probe_result.environment.get('lerobot_version', '?')})"
            )
        plan = backend_obj.plan(spec_dict)
        checks_dir = Path(plan.output_dir) / "checks"
        checks_dir.mkdir(parents=True, exist_ok=True)
        preflight = {
            "schema_version": "rosclaw.darwin.eval_preflight.v1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": probe_result.status,
            "messages": probe_result.messages,
            "device": probe_result.device,
            "policy": probe_result.policy,
            "environment": probe_result.environment,
        }
        (checks_dir / "preflight.json").write_text(
            json.dumps(preflight, indent=2, default=str),
            encoding="utf-8",
        )
    else:
        plan = backend_obj.plan(spec_dict)

    if dry_run:
        console.print("[cyan]Dry-run plan:[/cyan]")
        console.print(json.dumps(plan.command, indent=2))
        return None, None

    console.print(f"[cyan]Running evaluation[/cyan] {plan.run_id}")
    console.print(f"  Command: {' '.join(plan.command)}")

    raw_run = backend_obj.execute(plan)
    result = backend_obj.normalize(raw_run, spec_dict)

    console.print(f"[green]Evaluation {result.run_id} status:[/green] {result.status}")
    console.print(f"  Success rate: {result.metrics.get('success_rate', float('nan')):.2%}")
    console.print(f"  Micro SR: {result.metrics.get('micro_success_rate', float('nan')):.2%}")
    console.print(f"  Macro SR: {result.metrics.get('macro_task_success_rate', float('nan')):.2%}")
    console.print(f"  Validity gate: {result.validity_gate.get('status')}")
    console.print(f"  Performance gate: {result.performance_gate.get('status')}")
    console.print(f"  Output: {raw_run.output_dir}")
    return raw_run, result


# ------------------------------------------------------------------------------
# Run
# ------------------------------------------------------------------------------

@eval_app.command(name="run")
def eval_run(
    spec: str | None = typer.Option(None, "--spec", help="Path to evaluation spec YAML"),
    backend: str = typer.Option("lerobot_eval", "--backend", help="Backend name"),
    runtime: str | None = typer.Option(None, "--runtime", help="Runtime name or inline runtime config"),
    policy: str | None = typer.Option(None, "--policy", help="Policy path or Hub id"),
    env_type: str | None = typer.Option(None, "--env-type", help="Environment type"),
    env_task: str | None = typer.Option(None, "--env-task", help="Environment task"),
    episodes: int = typer.Option(2, "--episodes", help="Number of episodes"),
    batch_size: int = typer.Option(2, "--batch-size", help="Evaluation batch size"),
    device: str = typer.Option("cuda", "--device", help="Policy device"),
    allow_network: bool = typer.Option(False, "--allow-network", help="Allow Hub downloads"),
    out: str = typer.Option("data/eval_runs", "--out", help="Output root directory"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan only, do not execute"),
    skip_probe: bool = typer.Option(False, "--skip-probe", help="Skip preflight probe"),
) -> None:
    """Run a native benchmark evaluation."""
    if spec:
        spec_obj = _load_spec(spec)
        spec_dict = _spec_to_dict(spec_obj)
    else:
        if not policy or not env_type:
            console.print("[red]--spec or both --policy and --env-type are required.[/red]")
            raise typer.Exit(1)
        spec_dict = _build_inline_spec(
            backend=backend,
            runtime=runtime,
            policy=policy,
            env_type=env_type,
            env_task=env_task,
            episodes=episodes,
            batch_size=batch_size,
            device=device,
            allow_network=allow_network,
            out=out,
        )

    backend_obj = LeRobotEvalBackend()
    raw_run, result = _run_spec_dict(spec_dict, backend_obj, skip_probe=skip_probe, dry_run=dry_run)
    if result is None:
        return

    if result.status == "backend_process_failed":
        raise typer.Exit(3)
    if result.status == "invalid":
        raise typer.Exit(4)


# ------------------------------------------------------------------------------
# Inspect
# ------------------------------------------------------------------------------

@eval_app.command(name="inspect")
def eval_inspect(
    run_dir: str = typer.Argument(..., help="Path to an evaluation run directory"),
) -> None:
    """Print a run manifest, result summary, gates, and metric confidence intervals."""
    run_path = Path(run_dir)
    manifest_path = run_path / "manifest.yaml"
    result_path = run_path / "normalized" / "evaluation_result.json"

    if manifest_path.exists():
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        console.print("[cyan]Manifest[/cyan]")
        console.print(json.dumps(manifest, indent=2, default=str))
    else:
        console.print("[yellow]No manifest.yaml found.[/yellow]")

    if result_path.exists():
        result = EvaluationResultV2.model_validate(
            json.loads(result_path.read_text(encoding="utf-8"))
        )
        console.print("\n[cyan]Result summary[/cyan]")
        console.print(f"  Run ID: {result.run_id}")
        console.print(f"  Status: {result.status}")
        console.print(f"  Primary metric: {result.primary_metric}")
        console.print(f"  Success rate: {result.metrics.get('success_rate', float('nan')):.2%}")
        console.print(f"  Validity gate: {result.validity_gate.get('status')}")
        console.print(f"  Performance gate: {result.performance_gate.get('status')}")
        sr_ci = result.confidence_intervals.get("success_rate", {})
        if sr_ci:
            console.print(
                f"  Success-rate 95% CI: [{sr_ci.get('low', float('nan')):.2%}, "
                f"{sr_ci.get('high', float('nan')):.2%}]"
            )
        task_ci = result.confidence_intervals.get("task_success_rate", {})
        if task_ci:
            console.print("  Per-task 95% CIs:")
            for task_id, ci in task_ci.items():
                console.print(
                    f"    {task_id}: [{ci.get('low', float('nan')):.2%}, "
                    f"{ci.get('high', float('nan')):.2%}]"
                )
    else:
        console.print("[yellow]No normalized result found.[/yellow]")


# ------------------------------------------------------------------------------
# Suite
# ------------------------------------------------------------------------------

@eval_app.command(name="suite")
def eval_suite(
    suite: str = typer.Option(..., "--suite", help="Path to a suite YAML file"),
    skip_probe: bool = typer.Option(False, "--skip-probe", help="Skip preflight probe"),
) -> None:
    """Run a suite of evaluation specs sequentially and compare the results."""
    suite_path = Path(suite)
    if not suite_path.exists():
        console.print(f"[red]Suite file not found: {suite}[/red]")
        raise typer.Exit(1)

    raw = yaml.safe_load(suite_path.read_text(encoding="utf-8")) or {}
    if isinstance(raw, list):
        spec_paths = [Path(p) for p in raw]
    elif isinstance(raw, dict):
        entries = raw.get("specs", [])
        if not isinstance(entries, list):
            console.print("[red]Suite 'specs' must be a list.[/red]")
            raise typer.Exit(1)
        spec_paths = [Path(p) for p in entries]
    else:
        console.print("[red]Suite YAML must be a list of spec paths or a dict with 'specs'.[/red]")
        raise typer.Exit(1)

    backend_obj = LeRobotEvalBackend()
    results: list[tuple[str, EvaluationResultV2]] = []
    for spec_path in spec_paths:
        if not spec_path.exists():
            console.print(f"[yellow]Skipping missing spec:[/yellow] {spec_path}")
            continue
        console.print(f"\n[cyan]Running spec[/cyan] {spec_path}")
        spec_obj = _load_spec(str(spec_path))
        spec_dict = _spec_to_dict(spec_obj)
        raw_run, result = _run_spec_dict(
            spec_dict, backend_obj, skip_probe=skip_probe, dry_run=False
        )
        if result is not None:
            results.append((Path(raw_run.output_dir).name, result))

    if len(results) < 2:
        console.print("[yellow]Need at least two successful runs to compare.[/yellow]")
        return

    table = Table(title="Suite Comparison")
    table.add_column("Run", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Success rate", style="green")
    table.add_column("Micro SR", style="green")
    table.add_column("Macro SR", style="green")
    for name, res in results:
        table.add_row(
            name,
            res.status,
            f"{res.metrics.get('success_rate', float('nan')):.2%}",
            f"{res.metrics.get('micro_success_rate', float('nan')):.2%}",
            f"{res.metrics.get('macro_task_success_rate', float('nan')):.2%}",
        )
    console.print(table)


# ------------------------------------------------------------------------------
# Validate
# ------------------------------------------------------------------------------

@eval_app.command(name="validate")
def eval_validate(
    run_dir: str = typer.Argument(..., help="Path to an evaluation run directory"),
) -> None:
    """Validate raw evidence and normalized results for a run."""
    run_path = Path(run_dir)
    result_path = run_path / "normalized" / "evaluation_result.json"

    if result_path.exists():
        result = EvaluationResultV2.model_validate(json.loads(result_path.read_text(encoding="utf-8")))
        console.print(f"[green]Validated run[/green] {result.run_id}")
        console.print(f"  Status: {result.status}")
        console.print(f"  Validity gate: {result.validity_gate.get('status')}")
        console.print(f"  Performance gate: {result.performance_gate.get('status')}")
        console.print(f"  Success rate: {result.metrics.get('success_rate', float('nan')):.2%}")
        return

    # Fallback: parse raw eval_info directly.
    eval_info_dir = run_path / "raw"
    if not eval_info_dir.exists():
        eval_info_dir = run_path
    try:
        info = parse_eval_info(eval_info_dir)
    except Exception as exc:
        console.print(f"[red]Failed to parse eval_info.json:[/red] {exc}")
        raise typer.Exit(1)

    console.print(f"[green]Raw eval_info parsed[/green]")
    console.print(f"  Episodes: {len(info.episodes)}")
    console.print(f"  Success rate: {info.success_rate}")


# ------------------------------------------------------------------------------
# Compare
# ------------------------------------------------------------------------------

@eval_app.command(name="compare")
def eval_compare(
    run_a: str = typer.Argument(..., help="First run directory"),
    run_b: str = typer.Argument(..., help="Second run directory"),
) -> None:
    """Compare two normalized evaluation runs."""
    paths = {
        "a": Path(run_a) / "normalized" / "evaluation_result.json",
        "b": Path(run_b) / "normalized" / "evaluation_result.json",
    }
    results: dict[str, EvaluationResultV2] = {}
    for key, path in paths.items():
        if not path.exists():
            console.print(f"[red]No normalized result found at {path}[/red]")
            raise typer.Exit(1)
        results[key] = EvaluationResultV2.model_validate(json.loads(path.read_text(encoding="utf-8")))

    ra, rb = results["a"], results["b"]
    sa = ra.metrics.get("success_rate", float("nan"))
    sb = rb.metrics.get("success_rate", float("nan"))
    delta = sb - sa

    table = Table(title="Run Comparison")
    table.add_column("Metric", style="cyan")
    table.add_column(f"{Path(run_a).name}", style="green")
    table.add_column(f"{Path(run_b).name}", style="green")
    table.add_column("Delta", style="yellow")
    table.add_row("Status", ra.status, rb.status, "-")
    table.add_row("Success rate", f"{sa:.2%}", f"{sb:.2%}", f"{delta:+.2%}")
    table.add_row(
        "Micro SR",
        f"{ra.metrics.get('micro_success_rate', float('nan')):.2%}",
        f"{rb.metrics.get('micro_success_rate', float('nan')):.2%}",
        "-",
    )
    table.add_row(
        "Macro SR",
        f"{ra.metrics.get('macro_task_success_rate', float('nan')):.2%}",
        f"{rb.metrics.get('macro_task_success_rate', float('nan')):.2%}",
        "-",
    )
    console.print(table)

"""ROSClaw-Darwin CLI."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.table import Table

from rosclaw_darwin.adapters.mock import MockAdapter
from rosclaw_darwin.dashboard.app import DashboardApp
from rosclaw_darwin.evaluation.report import save_evolution_report, save_run_result
from rosclaw_darwin.evolution.composer import TaskComposer
from rosclaw_darwin.evolution.mutators import MUTATOR_REGISTRY
from rosclaw_darwin.evolution.runner import EvolutionRunner
from rosclaw_darwin.sources.behavior1k import Behavior1KImporter
from rosclaw_darwin.sources.lw_benchhub import LWBenchHubImporter
from rosclaw_darwin.sources.robotwin import RoboTwinImporter
from rosclaw_darwin.tdl.exporter import TaskExporter
from rosclaw_darwin.tdl.loader import TaskLoader
from rosclaw_darwin.tdl.validator import TaskValidator
from rosclaw_darwin.utils.paths import ensure_dir

app = typer.Typer(help="ROSClaw-Darwin: Evolutionary Embodied Intelligence Benchmark")
console = Console()


@app.command()
def doctor() -> None:
    """Check environment health."""
    table = Table(title="ROSClaw-Darwin Environment")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Detail", style="dim")

    # Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    table.add_row("Python", "OK" if sys.version_info >= (3, 10) else "FAIL", py_ver)

    # Package version
    try:
        from rosclaw_darwin import __version__
        table.add_row("rosclaw-darwin", "OK", __version__)
    except Exception as e:
        table.add_row("rosclaw-darwin", "FAIL", str(e))

    # External repos
    for name, env_vars in [
        ("IsaacLab-Arena", ["ROSCLAW_ARENA_REPO", "ARENA_REPO"]),
        ("LW-BenchHub", ["ROSCLAW_LW_BENCHHUB_REPO", "LW_BENCHHUB_REPO"]),
        ("RoboTwin", ["ROSCLAW_ROBOTWIN_REPO", "ROBOTWIN_REPO"]),
        ("BEHAVIOR-1K", ["ROSCLAW_BEHAVIOR1K_REPO", "BEHAVIOR1K_REPO"]),
    ]:
        path = None
        used_var = env_vars[0]
        for env_var in env_vars:
            path = os.getenv(env_var)
            if path:
                used_var = env_var
                break
        status = "OK" if path and Path(path).exists() else "NOT FOUND"
        table.add_row(name, status, path or f"Set {used_var}")

    # CUDA
    try:
        import subprocess
        result = subprocess.run(["nvidia-smi"], capture_output=True, text=True)
        cuda_ok = result.returncode == 0
        table.add_row("CUDA", "OK" if cuda_ok else "NOT FOUND", "nvidia-smi available" if cuda_ok else "")
    except Exception:
        table.add_row("CUDA", "NOT FOUND", "nvidia-smi not in PATH")

    # Docker
    try:
        import subprocess
        result = subprocess.run(["docker", "--version"], capture_output=True, text=True)
        docker_ok = result.returncode == 0
        table.add_row("Docker", "OK" if docker_ok else "NOT FOUND", result.stdout.strip() if docker_ok else "")
    except Exception:
        table.add_row("Docker", "NOT FOUND", "docker not in PATH")

    console.print(table)


@app.command()
def validate_task(path: str) -> None:
    """Validate a TDL task file."""
    validator = TaskValidator()
    ok, errors = validator.validate_file(path)
    if ok:
        console.print(f"[green]✓[/green] {path} is valid")
    else:
        console.print(f"[red]✗[/red] {path} has errors:")
        for e in errors:
            console.print(f"  - {e}")
        raise typer.Exit(1)


@app.command(name="import")
def import_tasks(
    source: str = typer.Argument(..., help="Source name: lw, robotwin, behavior1k"),
    repo: str = typer.Option(..., "--repo", help="Path to source repository"),
    out: str = typer.Option("data/tasks", "--out", help="Output directory"),
    limit: int | None = typer.Option(None, "--limit", help="Max tasks to import"),
    semantic_only: bool = typer.Option(False, "--semantic-only", help="Semantic import only (behavior1k)"),
) -> None:
    """Import tasks from external repositories."""
    repo_path = Path(repo)
    if not repo_path.exists():
        console.print(f"[red]Repository not found: {repo}[/red]")
        raise typer.Exit(1)

    importers = {
        "lw": LWBenchHubImporter,
        "robotwin": RoboTwinImporter,
        "behavior1k": Behavior1KImporter,
    }
    importer_cls = importers.get(source)
    if not importer_cls:
        console.print(f"[red]Unknown source: {source}[/red]")
        raise typer.Exit(1)

    importer = importer_cls(repo_path=repo_path)
    tasks = importer.import_all(limit=limit)

    out_dir = ensure_dir(out) / source
    TaskExporter.export_batch(tasks, out_dir, fmt="yaml")

    # Write index
    index = {"source": source, "count": len(tasks), "tasks": [t.id for t in tasks]}
    (out_dir / f"{source}_task_index.json").write_text(json.dumps(index, indent=2))

    console.print(f"[green]Imported {len(tasks)} tasks to {out_dir}[/green]")


@app.command()
def mutate(
    task: str = typer.Option(..., "--task", help="Path to task YAML"),
    out: str = typer.Option("data/tasks/mutated", "--out", help="Output directory"),
    n: int = typer.Option(10, "--n", help="Number of variations"),
    mutators: str = typer.Option("spatial,object,distractor,instruction", "--mutators", help="Comma-separated mutator names"),
    seed: int | None = typer.Option(None, "--seed", help="Random seed"),
) -> None:
    """Generate task variations via mutation."""
    loader = TaskLoader()
    t = loader.load(task)
    out_dir = ensure_dir(out)

    mutator_names = [m.strip() for m in mutators.split(",")]
    all_variants: list[Any] = []
    rng_seed = seed or 42

    for i in range(n):
        variant = t
        for mname in mutator_names:
            mutator_cls = MUTATOR_REGISTRY.get(mname)
            if mutator_cls:
                variant = mutator_cls().mutate(variant, seed=rng_seed + i)
        variant.id = f"{t.id}_mut_{i:03d}"
        variant.parents = [t.id]
        all_variants.append(variant)

    TaskExporter.export_batch(all_variants, out_dir, fmt="yaml")
    console.print(f"[green]Generated {n} variants in {out_dir}[/green]")


@app.command()
def compose(
    tasks: list[str] = typer.Argument(..., help="Paths to task YAMLs to compose"),
    out: str = typer.Option(..., "--out", help="Output path for composed task"),
) -> None:
    """Compose multiple tasks into a long-horizon task."""
    loader = TaskLoader()
    task_objs = [loader.load(t) for t in tasks]
    composer = TaskComposer()
    composed = composer.compose(task_objs)
    TaskExporter.to_yaml(composed, out)
    console.print(f"[green]Composed task saved to {out}[/green]")


@app.command()
def run(
    adapter: str = typer.Option("mock", "--adapter", help="Adapter: mock, arena"),
    task: str = typer.Option(..., "--task", help="Path to task YAML"),
    policy: str = typer.Option("configs/policies/zero_action.yaml", "--policy", help="Path to policy config"),
    episodes: int = typer.Option(20, "--episodes", help="Number of episodes"),
    out: str = typer.Option("data/runs", "--out", help="Output directory"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Dry run (arena only: generate command without executing)"),
) -> None:
    """Run evaluation for a task."""
    loader = TaskLoader()
    t = loader.load(task)

    policy_config = _load_policy_config(policy)
    policy_config.setdefault("policy_id", Path(policy).stem)
    if dry_run:
        policy_config["dry_run"] = True

    if adapter == "mock":
        env = MockAdapter(t)
    elif adapter == "arena":
        try:
            from rosclaw_darwin.adapters.arena import ArenaAdapter
            env = ArenaAdapter(t)
        except ImportError as e:
            console.print(f"[red]Arena adapter not available: {e}[/red]")
            console.print("[yellow]Tip: Set ROSCLAW_ARENA_REPO=/path/to/IsaacLab-Arena and install IsaacLab-Arena dependencies[/yellow]")
            raise typer.Exit(1)
    else:
        console.print(f"[red]Unknown adapter: {adapter}[/red]")
        raise typer.Exit(1)

    result = env.run_policy(policy_config, episodes=episodes)

    run_dir = ensure_dir(out) / result.run_id
    save_run_result(
        run_dir=run_dir,
        result=result,
        task_yaml=t.to_yaml(),
        policy_config=policy_config,
    )

    console.print(f"[green]Run {result.run_id} completed[/green]")
    console.print(f"  Success rate: {result.metrics.get('success_rate', 0.0):.2%}")
    console.print(f"  Episodes: {result.metrics.get('num_episodes', 0)}")


@app.command()
def evolve(
    adapter: str = typer.Option("mock", "--adapter", help="Adapter: mock, arena"),
    task: str = typer.Option(..., "--task", help="Path to task YAML"),
    policy: str = typer.Option("configs/policies/zero_action.yaml", "--policy", help="Path to policy config"),
    loops: int = typer.Option(2, "--loops", help="Number of evolution loops"),
    episodes: int = typer.Option(20, "--episodes", help="Number of episodes per loop"),
    out: str = typer.Option("data/evolution_runs", "--out", help="Output directory"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Dry run (arena only: generate command without executing)"),
    seed: int | None = typer.Option(None, "--seed", help="Random seed for deterministic mock evolution"),
) -> None:
    """Run evolution evaluation for a task."""
    loader = TaskLoader()
    t = loader.load(task)
    if seed is not None:
        t.mutation.seed = seed
    policy_config = _load_policy_config(policy)
    policy_config.setdefault("policy_id", Path(policy).stem)
    if dry_run:
        policy_config["dry_run"] = True

    if adapter == "mock":
        env = MockAdapter(t)
    elif adapter == "arena":
        try:
            from rosclaw_darwin.adapters.arena import ArenaAdapter
            env = ArenaAdapter(t)
        except ImportError as e:
            console.print(f"[red]Arena adapter not available: {e}[/red]")
            raise typer.Exit(1)
    else:
        console.print(f"[red]Unknown adapter: {adapter}[/red]")
        raise typer.Exit(1)

    runner = EvolutionRunner(env)
    report = runner.evolve(t, policy_config, loops=loops, episodes=episodes)

    run_dir = ensure_dir(out) / report["run_id"]
    save_evolution_report(
        run_dir=run_dir,
        report=report,
        task_yaml=t.to_yaml(),
        policy_config=policy_config,
    )

    runner.memory.finalize(run_dir)

    # Summary
    evo = report["evolution_metrics"]
    console.print(f"[green]Evolution {report['run_id']} completed[/green]")
    console.print(f"  delta_success_rate: {evo.get('delta_success_rate', 0.0):.3f}")
    console.print(f"  memory_integration_efficiency_score: {evo.get('memory_integration_efficiency_score', 0.0):.3f}")
    console.print(f"  skill_discovery_rate: {evo.get('skill_discovery_rate', 0.0):.3f}")
    console.print(f"  evolution_score: {evo.get('evolution_score', 0.0):.3f}")


@app.command()
def suite(
    action: str = typer.Argument(..., help="create or run"),
    name: str = typer.Option(None, "--name", help="Suite name"),
    task_patterns: list[str] = typer.Option(None, "--tasks", help="Task glob patterns"),
    suite_file: str = typer.Option(None, "--suite", help="Path to suite YAML"),
    out: str = typer.Option(None, "--out", help="Output path"),
    adapter: str = typer.Option("mock", "--adapter", help="Adapter for run"),
    policy: str = typer.Option("configs/policies/zero_action.yaml", "--policy", help="Policy config for run"),
) -> None:
    """Create or run a task suite."""
    if action == "create":
        if not task_patterns or not out:
            console.print("[red]--tasks and --out required for create[/red]")
            raise typer.Exit(1)
        from pathlib import Path as _Path
        all_tasks = []
        for pattern in task_patterns:
            p = _Path(pattern)
            if p.is_dir():
                all_tasks.extend(str(f) for f in p.rglob("*.yaml"))
                all_tasks.extend(str(f) for f in p.rglob("*.yml"))
            else:
                import glob
                all_tasks.extend(glob.glob(pattern, recursive="**" in pattern))
        all_tasks = sorted(set(all_tasks))
        suite_data = {
            "name": name or "unnamed_suite",
            "tasks": all_tasks,
        }
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(yaml.dump(suite_data, sort_keys=False))
        console.print(f"[green]Suite with {len(all_tasks)} tasks saved to {out}[/green]")
    elif action == "run":
        if not suite_file:
            console.print("[red]--suite required for run[/red]")
            raise typer.Exit(1)
        suite_data = yaml.safe_load(Path(suite_file).read_text())
        console.print(f"[cyan]Running suite: {suite_data.get('name')}[/cyan]")
        for task_path in suite_data.get("tasks", []):
            console.print(f"  Running {task_path}...")
            # Delegate to run command logic
            # (simplified for MVP)
    else:
        console.print(f"[red]Unknown suite action: {action}[/red]")
        raise typer.Exit(1)


@app.command()
def dashboard(
    data_dir: str = typer.Option("data", "--data", help="Data directory"),
    port: int = typer.Option(8080, "--port", help="Port"),
    host: str = typer.Option("0.0.0.0", "--host", help="Host"),
) -> None:
    """Start the evolution dashboard."""
    app_obj = DashboardApp(data_dir=data_dir)
    console.print(f"[green]Starting dashboard on http://{host}:{port}[/green]")
    app_obj.run(host=host, port=port)


def _load_policy_config(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"type": "zero", "strength": 0.5}
    if p.suffix in (".yaml", ".yml"):
        return yaml.safe_load(p.read_text()) or {}
    if p.suffix == ".json":
        return json.loads(p.read_text())
    return {}


if __name__ == "__main__":
    app()

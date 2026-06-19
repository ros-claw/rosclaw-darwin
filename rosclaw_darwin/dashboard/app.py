"""Dashboard using FastAPI + Jinja2."""

from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from rosclaw_darwin.dashboard import charts


class SVGResponse(Response):
    media_type = "image/svg+xml"


class DashboardApp:
    """FastAPI-based Darwin dashboard with Jinja2 templates."""

    def __init__(self, data_dir: str | None = None):
        self.app = FastAPI(title="ROSClaw-Darwin", version="0.1.0")
        self.data_dir = Path(data_dir) if data_dir else Path.cwd() / "data"
        self.templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
        self._setup_routes()

    def _setup_routes(self) -> None:
        @self.app.get("/", response_class=HTMLResponse)
        async def index(request: Request) -> Any:
            return self.templates.TemplateResponse(request, "overview.html", {
                "runs": self._load_runs(),
                "evolution_runs": self._load_evolution_runs(),
                "tasks": self._load_tasks(),
                "skills": self._load_skills(),
                "candidates": self._load_candidates(),
                "leaderboard": self._load_leaderboard(),
                "memories": self._load_memory(),
            })

        @self.app.get("/runs", response_class=HTMLResponse)
        async def runs_page(request: Request, metric_scope: str = "all") -> Any:
            runs = self._load_runs()
            if metric_scope != "all":
                runs = [r for r in runs if r.get("metadata", {}).get("metric_scope") == metric_scope]
            return self.templates.TemplateResponse(request, "runs.html", {
                "runs": runs,
                "metric_scope": metric_scope,
            })

        @self.app.get("/evolution", response_class=HTMLResponse)
        async def evolution_page(request: Request) -> Any:
            return self.templates.TemplateResponse(request, "evolution.html", {
                "evolution_runs": self._load_evolution_runs(),
            })

        @self.app.get("/tasks", response_class=HTMLResponse)
        async def tasks_page(request: Request, execution_filter: str = "all") -> Any:
            tasks = self._load_tasks()
            filtered = tasks
            if execution_filter != "all":
                filtered = [t for t in tasks if self._task_matches_execution_filter(t, execution_filter)]
            return self.templates.TemplateResponse(request, "tasks.html", {
                "tasks": filtered,
                "execution_filter": execution_filter,
            })

        @self.app.get("/task-graph", response_class=HTMLResponse)
        async def task_graph_page(request: Request) -> Any:
            return self.templates.TemplateResponse(request, "task_graph.html", {
                "graph": self._load_task_graph(),
            })

        @self.app.get("/arena-matches", response_class=HTMLResponse)
        async def arena_matches_page(request: Request) -> Any:
            return self.templates.TemplateResponse(request, "arena_matches.html", {
                "matches": self._load_arena_matches(),
            })

        @self.app.get("/skills", response_class=HTMLResponse)
        async def skills_page(request: Request) -> Any:
            return self.templates.TemplateResponse(request, "skills.html", {
                "skills": self._load_skills(),
                "candidates": self._load_candidates(),
            })

        @self.app.get("/failures", response_class=HTMLResponse)
        async def failures_page(request: Request) -> Any:
            return self.templates.TemplateResponse(request, "failures.html", {
                "failures": self._load_failures(),
            })

        @self.app.get("/skill-hint-traces", response_class=HTMLResponse)
        async def skill_hint_traces_page(request: Request) -> Any:
            return self.templates.TemplateResponse(request, "skill_hint_traces.html", {
                "traces": self._load_skill_hint_traces(),
            })

        @self.app.get("/ablations", response_class=HTMLResponse)
        async def ablations_page(request: Request) -> Any:
            return self.templates.TemplateResponse(request, "ablations.html", {
                "ablations": self._load_ablations(),
            })

        @self.app.get("/lift-progress", response_class=HTMLResponse)
        async def lift_progress_page(request: Request) -> Any:
            return self.templates.TemplateResponse(request, "lift_progress.html", {
                "runs": self._load_progress_runs(),
            })

        @self.app.get("/diagnostics/horizon-sweep", response_class=HTMLResponse)
        async def horizon_sweep_page(request: Request) -> Any:
            return self.templates.TemplateResponse(request, "horizon_sweep.html", {
                "sweeps": self._load_horizon_sweeps(),
            })

        @self.app.get("/lift-progress/{run_id}/chart.svg", response_class=SVGResponse)
        async def lift_progress_chart(run_id: str) -> Any:
            run = self._find_progress_run_by_id(run_id)
            if run is None:
                return SVGResponse(content=charts.plot_lift_progress({}), status_code=404)
            return SVGResponse(content=charts.plot_lift_progress(run))

        @self.app.get("/ablations/chart.svg", response_class=SVGResponse)
        async def ablations_chart() -> Any:
            return SVGResponse(content=charts.plot_ablations(self._load_ablations()))

        @self.app.get("/failures/chart.svg", response_class=SVGResponse)
        async def failures_chart() -> Any:
            return SVGResponse(content=charts.plot_failure_signature_distribution(self._load_progress_runs()))

        @self.app.get("/transfer", response_class=HTMLResponse)
        async def transfer_page(request: Request) -> Any:
            return self.templates.TemplateResponse(request, "transfer.html", {
                "ablations": self._load_ablations(),
            })

        @self.app.get("/transfer/chart.svg", response_class=SVGResponse)
        async def transfer_chart() -> Any:
            return SVGResponse(content=charts.plot_transfer_matrix(self._load_ablations()))

        @self.app.get("/leaderboard", response_class=HTMLResponse)
        async def leaderboard_page(request: Request) -> Any:
            entries = self._load_leaderboard()
            return self.templates.TemplateResponse(request, "leaderboard.html", {
                "leaderboard": entries,
            })

        @self.app.get("/official-benchmark", response_class=HTMLResponse)
        async def official_benchmark_page(request: Request) -> Any:
            data = self._load_official_benchmark()
            return self.templates.TemplateResponse(request, "official_benchmark.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/official-benchmark/chart.svg", response_class=SVGResponse)
        async def official_benchmark_chart() -> Any:
            data = self._load_official_benchmark()
            if data is None:
                return SVGResponse(content=charts.plot_official_benchmark(0.0, {}), status_code=404)
            return SVGResponse(
                content=charts.plot_official_benchmark(
                    data.get("success_rate", 0.0),
                    data.get("failure_distribution", {}),
                )
            )

        @self.app.get("/official-post-reachability", response_class=HTMLResponse)
        async def official_post_reachability_page(request: Request) -> Any:
            data = self._load_official_post_reachability()
            return self.templates.TemplateResponse(request, "official_post_reachability.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/official-post-reachability/chart.svg", response_class=SVGResponse)
        async def official_post_reachability_chart() -> Any:
            data = self._load_official_post_reachability()
            if data is None:
                return SVGResponse(content=charts.plot_official_post_reachability(0.82, None, None), status_code=404)
            return SVGResponse(
                content=charts.plot_official_post_reachability(
                    data.get("old_success_rate", 0.82),
                    data.get("regression_success_rate"),
                    data.get("new_success_rate"),
                )
            )

        @self.app.get("/procedural-validity", response_class=HTMLResponse)
        async def procedural_validity_page(request: Request) -> Any:
            data = self._load_procedural_validity()
            return self.templates.TemplateResponse(request, "procedural_validity.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/procedural-validity/chart.svg", response_class=SVGResponse)
        async def procedural_validity_chart() -> Any:
            data = self._load_procedural_validity()
            if data is None:
                return SVGResponse(content=charts.plot_procedural_validity({}), status_code=404)
            return SVGResponse(content=charts.plot_procedural_validity(data.get("per_task", {})))

        @self.app.get("/large-yaw-slip", response_class=HTMLResponse)
        async def large_yaw_slip_page(request: Request) -> Any:
            data = self._load_large_yaw_slip()
            return self.templates.TemplateResponse(request, "large_yaw_slip.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/large-yaw-slip/chart.svg", response_class=SVGResponse)
        async def large_yaw_slip_chart() -> Any:
            data = self._load_large_yaw_slip()
            if data is None:
                return SVGResponse(content=charts.plot_large_yaw_slip({}), status_code=404)
            return SVGResponse(content=charts.plot_large_yaw_slip(data.get("per_yaw", {})))

        @self.app.get("/ood-adaptation", response_class=HTMLResponse)
        async def ood_adaptation_page(request: Request) -> Any:
            validity = self._load_procedural_validity()
            blocked = validity is not None and not validity.get("any_valid", False)
            data = self._load_ood_adaptation()
            return self.templates.TemplateResponse(request, "ood_adaptation.html", {
                "has_data": data is not None and not blocked,
                "blocked": blocked,
                "data": data or {},
            })

        @self.app.get("/ood-adaptation/chart.svg", response_class=SVGResponse)
        async def ood_adaptation_chart() -> Any:
            data = self._load_ood_adaptation()
            if data is None:
                return SVGResponse(content=charts.plot_ood_adaption({}), status_code=404)
            return SVGResponse(
                content=charts.plot_ood_adaption(data.get("conditions", {}))
            )

        @self.app.get("/failure-boundary", response_class=HTMLResponse)
        async def failure_boundary_page(request: Request) -> Any:
            data = self._load_failure_boundary()
            return self.templates.TemplateResponse(request, "failure_boundary.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/failure-boundary/chart.svg", response_class=SVGResponse)
        async def failure_boundary_chart() -> Any:
            data = self._load_failure_boundary()
            if data is None:
                return SVGResponse(content=charts.plot_failure_boundary(None), status_code=404)
            return SVGResponse(
                content=charts.plot_failure_boundary(
                    fba_result=data.get("fba_result"),
                    phase_scores=data.get("phase_scores"),
                )
            )

        @self.app.get("/target-yaw-matrix", response_class=HTMLResponse)
        async def target_yaw_matrix_page(request: Request) -> Any:
            data = self._load_target_yaw_matrix()
            return self.templates.TemplateResponse(request, "target_yaw_matrix.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/target-yaw-matrix/chart.svg", response_class=SVGResponse)
        async def target_yaw_matrix_chart() -> Any:
            data = self._load_target_yaw_matrix()
            if data is None:
                return SVGResponse(content=charts.plot_target_yaw_matrix({}), status_code=404)
            return SVGResponse(
                content=charts.plot_target_yaw_matrix(data.get("per_target_yaw", {}))
            )

        @self.app.get("/memory", response_class=HTMLResponse)
        async def memory_page(request: Request) -> Any:
            return self.templates.TemplateResponse(request, "memory.html", {
                "memories": self._load_memory(),
            })

        @self.app.get("/api/memory")
        async def api_memory() -> JSONResponse:
            return JSONResponse(content={"memories": self._load_memory()})

        # JSON API endpoints
        @self.app.get("/api/leaderboard")
        async def api_leaderboard() -> JSONResponse:
            return JSONResponse(content={"entries": self._load_leaderboard()})

        @self.app.get("/api/runs")
        async def api_runs() -> JSONResponse:
            return JSONResponse(content={"runs": self._load_runs()})

    def _load_runs(self) -> list[dict]:
        runs: list[dict] = []
        for f in glob.glob(str(self.data_dir / "runs" / "*" / "run.json")):
            try:
                runs.append(json.loads(Path(f).read_text()))
            except Exception:
                pass
        return runs

    def _load_evolution_runs(self) -> list[dict]:
        runs: list[dict] = []
        for f in glob.glob(str(self.data_dir / "evolution_runs" / "*" / "evolution_report.json")):
            try:
                runs.append(json.loads(Path(f).read_text()))
            except Exception:
                pass
        return runs

    def _load_tasks(self) -> list[dict]:
        tasks: list[dict] = []
        for f in glob.glob(str(self.data_dir / "tasks" / "**" / "*.yaml"), recursive=True):
            try:
                import yaml
                tasks.append(yaml.safe_load(Path(f).read_text()))
            except Exception:
                pass
        return tasks

    def _load_task_graph(self) -> dict:
        nodes = []
        edges = []
        for t in self._load_tasks():
            nodes.append({"id": t.get("id"), "name": t.get("name")})
            for p in t.get("parents", []):
                edges.append({"source": p, "target": t.get("id")})
        return {"nodes": nodes, "edges": edges}

    def _load_skills(self) -> list[dict]:
        skills: list[dict] = []
        # 1. Load persisted registry
        path = self.data_dir / "skills" / "registry.json"
        if path.exists():
            try:
                skills = json.loads(path.read_text()).get("skills", [])
            except Exception:
                pass
        # 2. Aggregate discovered skills from evolution runs
        for evo in self._load_evolution_runs():
            for s in evo.get("discovered_skills", []):
                if s.get("fingerprint") not in {x.get("fingerprint") for x in skills}:
                    skills.append(s)
        return skills

    def _load_candidates(self) -> list[dict]:
        """Load skill candidates that have not yet been validated."""
        validated_fps = {s.get("fingerprint") for s in self._load_skills()}
        candidates: list[dict] = []
        # 1. Load persisted registry candidates
        path = self.data_dir / "skills" / "registry.json"
        if path.exists():
            try:
                for c in json.loads(path.read_text()).get("candidates", []):
                    if c.get("fingerprint") not in validated_fps:
                        candidates.append(c)
            except Exception:
                pass
        # 2. Aggregate candidates from evolution runs
        for evo in self._load_evolution_runs():
            for s in evo.get("candidate_skills", []):
                fp = s.get("fingerprint")
                if fp not in validated_fps and fp not in {x.get("fingerprint") for x in candidates}:
                    candidates.append(s)
        return candidates

    def _load_memory(self) -> list[dict]:
        """Load persisted experiences from the global memory store and per-run dirs."""
        records: list[dict] = []
        seen: set[str] = set()

        # Global store (relative to data_dir)
        global_path = self.data_dir / "memory" / "experiences.jsonl"
        if global_path.exists():
            for line in global_path.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    rec = __import__("json").loads(line)
                    key = rec.get("run_id", "") + "|" + rec.get("timestamp", "")
                    if key not in seen:
                        records.append(rec)
                        seen.add(key)
                except Exception:
                    continue

        # Per-run memory
        for evo in self._load_evolution_runs():
            run_id = evo.get("run_id")
            if not run_id:
                continue
            run_mem = self.data_dir / "evolution_runs" / run_id / "memory" / "experiences.jsonl"
            if run_mem.exists():
                for line in run_mem.read_text().splitlines():
                    if not line.strip():
                        continue
                    try:
                        rec = __import__("json").loads(line)
                        key = rec.get("run_id", "") + "|" + rec.get("timestamp", "")
                        if key not in seen:
                            records.append(rec)
                            seen.add(key)
                    except Exception:
                        continue
        return records

    def _load_failures(self) -> dict[str, int]:
        failures: dict[str, int] = {}
        for run in self._load_runs() + self._load_evolution_runs():
            for ft, count in run.get("failure_types", {}).items():
                failures[ft] = failures.get(ft, 0) + count
        return failures

    def _load_leaderboard(self) -> list[dict]:
        entries: list[dict] = []
        for evo in self._load_evolution_runs():
            loops = evo.get("loop_results", [])
            # Skip evolution runs whose final loop is excluded from leaderboard.
            if loops and loops[-1].get("leaderboard_excluded"):
                continue
            metrics = evo.get("evolution_metrics", {})
            success_rate = loops[-1].get("metrics", {}).get("success_rate", 0) if loops else 0
            entries.append({
                "task_id": evo.get("task_id"),
                "evolution_score": metrics.get("evolution_score", 0),
                "delta_success_rate": metrics.get("delta_success_rate", 0),
                "memory_integration_efficiency_score": metrics.get("memory_integration_efficiency_score", 0),
                "memory_integration_efficiency_available": metrics.get("memory_integration_efficiency_available", False),
                "success_rate": success_rate,
                "skill_transfer_gain": metrics.get("skill_transfer_gain", 0),
                "skill_candidate_count": metrics.get("skill_candidate_count", 0),
                "skill_validated_count": metrics.get("skill_validated_count", 0),
                "metric_scope": loops[-1].get("metric_scope") if loops else None,
                "claim_level": loops[-1].get("claim_level") if loops else None,
            })
        entries.sort(key=lambda x: (
            x.get("evolution_score", 0),
            x.get("delta_success_rate", 0),
            x.get("memory_integration_efficiency_score", 0),
            x.get("success_rate", 0),
        ), reverse=True)
        return entries

    def _task_matches_execution_filter(self, task: dict, execution_filter: str) -> bool:
        execution = task.get("execution") or {}
        if execution_filter == "executable":
            return execution.get("executable") is True
        if execution_filter == "semantic_only":
            return execution.get("semantic_only") is True
        if execution_filter == "arena":
            return execution.get("backend") == "arena"
        if execution_filter == "robotwin_replay":
            return execution.get("backend") == "robotwin_replay"
        if execution_filter == "mock":
            return execution.get("backend") == "mock"
        return True

    def _load_arena_matches(self) -> list[dict]:
        from rosclaw_darwin.arena_bridge.task_matcher import TaskArenaMatcher
        from rosclaw_darwin.tdl.loader import TaskLoader

        matcher = TaskArenaMatcher()
        matches = []
        for task_dict in self._load_tasks():
            task_id = task_dict.get("id")
            try:
                task = TaskLoader().load(task_dict)
                best = matcher.best_match(task)
                matches.append({
                    "task_id": task_id,
                    "best_env": best.env_name if best else None,
                    "score": best.score if best else 0.0,
                    "matched_primitives": best.matched_primitives if best else [],
                    "missing_primitives": best.missing_required_primitives if best else [],
                    "warnings": best.warnings if best else [],
                })
            except Exception:
                continue
        return matches

    def _load_skill_hint_traces(self) -> list[dict]:
        traces = []
        for evo in self._load_evolution_runs():
            hint_source = evo.get("hint_source", {})
            loops = evo.get("loop_results", [])
            if not loops or not hint_source.get("auto"):
                continue
            loop1 = loops[0]
            loop2 = loops[-1]
            metrics = evo.get("evolution_metrics", {})
            traces.append({
                "run_id": evo.get("run_id"),
                "task_id": evo.get("task_id"),
                "policy_id": evo.get("policy_id"),
                "loop1_failure_types": loop1.get("failure_types", {}),
                "auto_hints": hint_source.get("auto", []),
                "manual_hints": hint_source.get("manual", []),
                "loop2_metrics": loop2.get("metrics", {}),
                "skill_transfer_gain": metrics.get("skill_transfer_gain", 0.0),
            })
        return traces

    def _load_ablations(self) -> list[dict]:
        """Group evolution runs by task_id and compare no-hint vs auto-hint runs."""
        by_task: dict[str, dict[str, dict]] = {}
        for evo in self._load_evolution_runs():
            task_id = evo.get("task_id")
            hint_source = evo.get("hint_source", {})
            key = "with_auto_hints" if hint_source.get("auto") else "without_hints"
            by_task.setdefault(task_id, {})[key] = evo
        ablations = []
        for task_id, variants in by_task.items():
            without = variants.get("without_hints", {})
            with_auto = variants.get("with_auto_hints", {})
            without_metrics = without.get("evolution_metrics", {})
            with_metrics = with_auto.get("evolution_metrics", {})
            ablations.append({
                "task_id": task_id,
                "without_hints_sr": without_metrics.get("delta_success_rate", 0.0),
                "with_auto_hints_sr": with_metrics.get("delta_success_rate", 0.0),
                "skill_transfer_gain": with_metrics.get("skill_transfer_gain", 0.0),
                "without_run_id": without.get("run_id"),
                "with_run_id": with_auto.get("run_id"),
            })
        return ablations

    def _data_search_paths(self) -> list[Path]:
        """Return directories that may contain Darwin run artifacts."""
        paths = [self.data_dir, Path("/tmp/rosclaw_data")]
        return [p for p in paths if p.exists()]

    def _find_run_json_files(self) -> list[Path]:
        """Search common output directories for run.json files."""
        found: list[Path] = []
        for base in self._data_search_paths():
            for pattern in (
                "runs/*/run.json",
                "evolution_runs/*/run.json",
                "ablations/*/*/run.json",
                "diagnostics/*/*/run.json",
            ):
                found.extend(base.glob(pattern))
        return found

    def _load_progress_runs(self) -> list[dict[str, Any]]:
        """Load runs that contain per-episode progress metrics."""
        runs: list[dict[str, Any]] = []
        for path in self._find_run_json_files():
            try:
                data = json.loads(path.read_text())
                arena_output = data.get("metadata", {}).get("arena_metrics_output", {})
                episode_metrics = arena_output.get("episode_metrics")
                if not episode_metrics:
                    continue
                runs.append({
                    "run_id": data.get("run_id"),
                    "task_id": data.get("task_id"),
                    "policy_id": data.get("policy_id"),
                    "status": data.get("status"),
                    "metric_scope": data.get("metric_scope"),
                    "claim_level": data.get("claim_level"),
                    "leaderboard_excluded": data.get("leaderboard_excluded"),
                    "success_rate": arena_output.get("success_rate"),
                    "progress_mean": arena_output.get("progress_mean"),
                    "failure_counts": arena_output.get("failure_counts", {}),
                    "num_episodes": arena_output.get("num_episodes", len(episode_metrics)),
                    "path": str(path),
                    "episode_metrics": episode_metrics,
                })
            except Exception:
                continue
        return runs

    def _find_progress_run_by_id(self, run_id: str) -> dict[str, Any] | None:
        for run in self._load_progress_runs():
            if run.get("run_id") == run_id:
                return run
        return None

    def _load_horizon_sweeps(self) -> list[dict[str, Any]]:
        """Load horizon sweep summaries from diagnostics output directories."""
        sweeps: list[dict[str, Any]] = []
        for base in self._data_search_paths():
            for path in base.glob("diagnostics/*/summary.json"):
                try:
                    data = json.loads(path.read_text())
                    if "groups" in data and "sweep_id" in data:
                        sweeps.append({**data, "path": str(path)})
                except Exception:
                    continue
        return sweeps

    def _load_ablations(self) -> list[dict[str, Any]]:
        """Load ablation evidence from both evolution runs and ablation scripts."""
        ablations: list[dict[str, Any]] = []

        # Source 1: dedicated ablation summaries written by scripts/ablations/*.
        for base in self._data_search_paths():
            for path in base.glob("ablations/*/summary.json"):
                try:
                    data = json.loads(path.read_text())
                    without = data.get("without_hints", {})
                    manual = data.get("manual_hints", {})
                    auto = data.get("auto_hints", {})
                    ablations.append({
                        "source": "ablation_script",
                        "task_id": data.get("task_id"),
                        "policy_id": data.get("policy_id"),
                        "episodes": data.get("episodes"),
                        "without_hints_sr": without.get("success_rate", 0.0),
                        "without_hints_progress": without.get("progress", 0.0),
                        "manual_hints_sr": manual.get("success_rate", 0.0),
                        "manual_hints_progress": manual.get("progress", 0.0),
                        "with_auto_hints_sr": auto.get("success_rate", 0.0),
                        "with_auto_hints_progress": auto.get("progress", 0.0),
                        "skill_transfer_gain": data.get("transfer_gain", {}).get("auto", {}).get("transfer_gain_success", 0.0),
                        "auto_hint_names": auto.get("generated_hint_names", []),
                        "path": str(path),
                        "without_run_id": without.get("run_id"),
                        "with_run_id": auto.get("run_id"),
                    })
                except Exception:
                    continue

        # Source 2: evolution runs grouped by task_id.
        by_task: dict[str, dict[str, dict]] = {}
        for evo in self._load_evolution_runs():
            task_id = evo.get("task_id")
            hint_source = evo.get("hint_source", {})
            key = "with_auto_hints" if hint_source.get("auto") else "without_hints"
            by_task.setdefault(task_id, {})[key] = evo

        for task_id, variants in by_task.items():
            without = variants.get("without_hints", {})
            with_auto = variants.get("with_auto_hints", {})
            without_metrics = without.get("evolution_metrics", {})
            with_metrics = with_auto.get("evolution_metrics", {})
            ablations.append({
                "source": "evolution_runner",
                "task_id": task_id,
                "policy_id": with_auto.get("policy_id") or without.get("policy_id"),
                "episodes": None,
                "without_hints_sr": without_metrics.get("delta_success_rate", 0.0),
                "without_hints_progress": 0.0,
                "manual_hints_sr": 0.0,
                "manual_hints_progress": 0.0,
                "with_auto_hints_sr": with_metrics.get("delta_success_rate", 0.0),
                "with_auto_hints_progress": 0.0,
                "skill_transfer_gain": with_metrics.get("skill_transfer_gain", 0.0),
                "auto_hint_names": [h.get("name") for h in with_auto.get("hint_source", {}).get("auto", [])],
                "path": None,
                "without_run_id": without.get("run_id"),
                "with_run_id": with_auto.get("run_id"),
            })
        return ablations

    def _load_official_benchmark(self) -> dict[str, Any] | None:
        """Load the latest official dex_cube benchmark aggregate summaries."""
        paths = [
            Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v16/arena_real/dex_cube_goal_pose_100_seed_v16/aggregate_summary.json"),
            Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v16/arena_real/dex_cube_goal_pose_reachability_regression/aggregate_summary.json"),
        ]
        for p in paths:
            if p.exists():
                try:
                    data = json.loads(p.read_text())
                    data["_source_path"] = str(p)
                    return data
                except Exception:
                    continue
        return None

    def _load_ood_adaptation(self) -> dict[str, Any] | None:
        """Load procedural OOD diagnostic aggregate."""
        paths = [
            Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v16/diagnostics/procedural_contact_diagnosis/aggregate_summary.json"),
            Path("/tmp/rosclaw_data/procedural_ood_adaptive_recovery/aggregate_summary.json"),
        ]
        for p in paths:
            if p.exists():
                try:
                    data = json.loads(p.read_text())
                    data["_source_path"] = str(p)
                    return data
                except Exception:
                    continue
        return None

    def _load_failure_boundary(self) -> dict[str, Any] | None:
        """Load contact-diagnosis / adaptive-recovery aggregate."""
        p = Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v16/diagnostics/procedural_contact_diagnosis/aggregate_summary.json")
        if p.exists():
            try:
                data = json.loads(p.read_text())
                data["_source_path"] = str(p)
                return data
            except Exception:
                pass
        return None

    def _load_target_yaw_matrix(self) -> dict[str, Any] | None:
        """Load target-yaw generalization aggregate.

        Prefer the v1.6 cross-yaw matrix output; fall back to the older
        target_yaw_generalization run if the matrix has not completed yet.
        """
        for p in (
            Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v16/ablations/cross_yaw_matrix_v16/aggregate_summary.json"),
            Path("/tmp/rosclaw_data/target_yaw_generalization_v3_grasp_hold/aggregate_summary.json"),
        ):
            if p.exists():
                try:
                    data = json.loads(p.read_text())
                    data["_source_path"] = str(p)
                    return data
                except Exception:
                    pass
        return None

    def _load_official_post_reachability(self) -> dict[str, Any] | None:
        """Load official benchmark trajectory: old, regression, post-reachability."""
        old_path = Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v16/arena_real/dex_cube_goal_pose_100_seed_v16/aggregate_summary.json")
        regression_path = Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v16/arena_real/dex_cube_goal_pose_reachability_regression/aggregate_summary.json")
        new_path = Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v17/official/dex_cube_goal_pose_100_seed_post_reachability/aggregate_summary.json")

        old_sr: float | None = None
        if old_path.exists():
            try:
                old_sr = float(json.loads(old_path.read_text()).get("overall_success_rate", 0.82))
            except Exception:
                pass

        regression_sr: float | None = None
        if regression_path.exists():
            try:
                regression_sr = float(json.loads(regression_path.read_text()).get("overall_success_rate"))
            except Exception:
                pass

        new_sr: float | None = None
        failure_distribution: dict[str, int] = {}
        if new_path.exists():
            try:
                data = json.loads(new_path.read_text())
                new_sr = float(data.get("overall_success_rate"))
                failure_distribution = data.get("failure_distribution", {})
            except Exception:
                pass

        if old_sr is None and regression_sr is None and new_sr is None:
            return None
        return {
            "old_success_rate": old_sr or 0.82,
            "regression_success_rate": regression_sr,
            "new_success_rate": new_sr,
            "failure_distribution": failure_distribution,
            "_source_path": str(new_path) if new_path.exists() else None,
        }

    def _load_procedural_validity(self) -> dict[str, Any] | None:
        """Load procedural object validity audit aggregate."""
        p = self._resolve_data_v17_path("diagnostics/procedural_object_validity_audit/aggregate_summary.json")
        if p is None or not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
            per_task = data.get("per_task", {})
            any_valid = any(
                (t.get("valid_rate") or 0.0) >= 1.0 for t in per_task.values()
            )
            return {
                "per_task": per_task,
                "any_valid": any_valid,
                "_source_path": str(p),
            }
        except Exception:
            return None

    def _load_large_yaw_slip(self) -> dict[str, Any] | None:
        """Load large-yaw slip diagnosis aggregate."""
        p = self._resolve_data_v17_path("diagnostics/large_yaw_slip/aggregate_summary.json")
        if p is None or not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
            return {
                "per_yaw": data,
                "_source_path": str(p),
            }
        except Exception:
            return None

    def _resolve_data_v17_path(self, relative_path: str) -> Path | None:
        """Resolve a v1.7 data path, preferring the canonical project location."""
        canonical = Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v17") / relative_path
        if canonical.exists():
            return canonical
        fallback = self.data_dir.parent / "data_v17" / relative_path
        if fallback.exists():
            return fallback
        return None

    def run(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        import uvicorn
        uvicorn.run(self.app, host=host, port=port)

"""Dashboard using FastAPI + Jinja2."""

from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates


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

        @self.app.get("/leaderboard", response_class=HTMLResponse)
        async def leaderboard_page(request: Request) -> Any:
            entries = self._load_leaderboard()
            return self.templates.TemplateResponse(request, "leaderboard.html", {
                "leaderboard": entries,
            })

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
            metrics = evo.get("evolution_metrics", {})
            loops = evo.get("loop_results", [])
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

    def run(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        import uvicorn
        uvicorn.run(self.app, host=host, port=port)

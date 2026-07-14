"""Dashboard using FastAPI + Jinja2."""

from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from rosclaw_darwin.dashboard import charts
from rosclaw_darwin.dashboard.darwinbench_routes import create_router


class SVGResponse(Response):
    media_type = "image/svg+xml"


class DashboardApp:
    """FastAPI-based Darwin dashboard with Jinja2 templates."""

    def __init__(self, data_dir: str | None = None):
        self.app = FastAPI(title="ROSClaw-Darwin", version="0.1.0")
        self.data_dir = Path(data_dir) if data_dir else Path.cwd() / "data"
        self.templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
        self.app.include_router(create_router(self.templates))
        self._setup_routes()

    def _setup_routes(self) -> None:
        @self.app.get("/", response_class=HTMLResponse)
        async def index(request: Request) -> Any:
            cards = self._load_evidence_cards()
            registry = self._load_registry()
            blocked = self._load_blocked_external()
            return self.templates.TemplateResponse(request, "overview.html", {
                "runs": self._load_runs(),
                "evolution_runs": self._load_evolution_runs(),
                "tasks": self._load_tasks(),
                "skills": self._load_skills(),
                "candidates": self._load_candidates(),
                "leaderboard": self._load_leaderboard(),
                "memories": self._load_memory(),
                "cards": cards,
                "registry_count": len(registry),
                "blocked_count": len(blocked),
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

        @self.app.get("/dashboard/arena", response_class=HTMLResponse)
        async def arena_dashboard_page(request: Request) -> Any:
            return self.templates.TemplateResponse(request, "arena_dashboard.html", {
                "data": self._load_arena_dashboard(),
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

        @self.app.get("/large-yaw-intervention", response_class=HTMLResponse)
        async def large_yaw_intervention_page(request: Request) -> Any:
            data = self._load_large_yaw_intervention()
            return self.templates.TemplateResponse(request, "large_yaw_intervention.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/large-yaw-intervention/chart.svg", response_class=SVGResponse)
        async def large_yaw_intervention_chart() -> Any:
            data = self._load_large_yaw_intervention()
            if data is None:
                return SVGResponse(content=charts.plot_large_yaw_intervention({}), status_code=404)
            return SVGResponse(content=charts.plot_large_yaw_intervention(data.get("per_condition", {})))

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

        @self.app.get("/official-v18", response_class=HTMLResponse)
        async def official_v18_page(request: Request) -> Any:
            data = self._load_official_v18()
            return self.templates.TemplateResponse(request, "official_v18.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/official-v18/chart.svg", response_class=SVGResponse)
        async def official_v18_chart() -> Any:
            data = self._load_official_v18()
            if data is None:
                return SVGResponse(content=charts.plot_official_v18(0.82, None, None), status_code=404)
            return SVGResponse(
                content=charts.plot_official_v18(
                    data.get("old_success_rate", 0.82),
                    data.get("post_reachability_success_rate"),
                    data.get("seed24_fix_success_rate"),
                )
            )

        @self.app.get("/valid-ood", response_class=HTMLResponse)
        async def valid_ood_page(request: Request) -> Any:
            validity = self._load_valid_ood_validity()
            matrix = self._load_valid_ood_matrix()
            return self.templates.TemplateResponse(request, "valid_ood.html", {
                "has_validity": validity is not None,
                "validity": validity or {},
                "has_matrix": matrix is not None,
                "matrix": matrix or {},
            })

        @self.app.get("/official-v19", response_class=HTMLResponse)
        async def official_v19_page(request: Request) -> Any:
            data = self._load_official_v19()
            return self.templates.TemplateResponse(request, "official_v19.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/official-v19/chart.svg", response_class=SVGResponse)
        async def official_v19_chart() -> Any:
            data = self._load_official_v19()
            if data is None:
                return SVGResponse(content=charts.plot_official_v19(None), status_code=404)
            return SVGResponse(content=charts.plot_official_v19(data))

        @self.app.get("/contact-signal", response_class=HTMLResponse)
        async def contact_signal_page(request: Request) -> Any:
            data = self._load_contact_signal_trace()
            return self.templates.TemplateResponse(request, "contact_signal.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/contact-signal/chart.svg", response_class=SVGResponse)
        async def contact_signal_chart() -> Any:
            data = self._load_contact_signal_trace()
            if data is None:
                return SVGResponse(content=charts.plot_contact_signal_timeline(None), status_code=404)
            return SVGResponse(content=charts.plot_contact_signal_timeline(data.get("trace")))

        @self.app.get("/residual-policy", response_class=HTMLResponse)
        async def residual_policy_page(request: Request) -> Any:
            data = self._load_residual_policy_stats()
            return self.templates.TemplateResponse(request, "residual_policy.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/residual-policy/chart.svg", response_class=SVGResponse)
        async def residual_policy_chart() -> Any:
            data = self._load_residual_policy_stats()
            if data is None:
                return SVGResponse(content=charts.plot_residual_policy_stats(None), status_code=404)
            return SVGResponse(content=charts.plot_residual_policy_stats(data))

        @self.app.get("/valid-ood-subtasks", response_class=HTMLResponse)
        async def valid_ood_subtasks_page(request: Request) -> Any:
            data = self._load_valid_ood_subtasks()
            return self.templates.TemplateResponse(request, "valid_ood_subtasks.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/valid-ood-subtasks/chart.svg", response_class=SVGResponse)
        async def valid_ood_subtasks_chart() -> Any:
            data = self._load_valid_ood_subtasks()
            if data is None:
                return SVGResponse(content=charts.plot_valid_ood_subtasks_matrix(None), status_code=404)
            return SVGResponse(content=charts.plot_valid_ood_subtasks_matrix(data))

        @self.app.get("/fth-v33", response_class=HTMLResponse)
        async def fth_v33_page(request: Request) -> Any:
            data = self._load_fth_v33()
            return self.templates.TemplateResponse(request, "fth_v33.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/fth-v33/chart.svg", response_class=SVGResponse)
        async def fth_v33_chart() -> Any:
            data = self._load_fth_v33()
            if data is None:
                return SVGResponse(content=charts.plot_fth_v33_route_distribution(None), status_code=404)
            return SVGResponse(content=charts.plot_fth_v33_route_distribution(data.get("routes")))

        # v1.10 dashboard views -------------------------------------------------
        @self.app.get("/paired-evaluation", response_class=HTMLResponse)
        async def paired_evaluation_page(request: Request) -> Any:
            data = self._load_paired_evaluation()
            return self.templates.TemplateResponse(request, "paired_evaluation.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/paired-evaluation/chart.svg", response_class=SVGResponse)
        async def paired_evaluation_chart() -> Any:
            data = self._load_paired_evaluation()
            if data is None:
                return SVGResponse(content=charts.plot_paired_evaluation_summary(None), status_code=404)
            return SVGResponse(content=charts.plot_paired_evaluation_summary(data))

        @self.app.get("/contact-signal-v2", response_class=HTMLResponse)
        async def contact_signal_v2_page(request: Request) -> Any:
            data = self._load_contact_signal_v2()
            return self.templates.TemplateResponse(request, "contact_signal_v2.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/contact-signal-v2/chart.svg", response_class=SVGResponse)
        async def contact_signal_v2_chart() -> Any:
            data = self._load_contact_signal_v2()
            if data is None:
                return SVGResponse(content=charts.plot_contact_signal_v2_coverage(None), status_code=404)
            return SVGResponse(content=charts.plot_contact_signal_v2_coverage(data.get("coverage")))

        @self.app.get("/learned-trigger", response_class=HTMLResponse)
        async def learned_trigger_page(request: Request) -> Any:
            data = self._load_learned_trigger()
            return self.templates.TemplateResponse(request, "learned_trigger.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/learned-trigger/chart.svg", response_class=SVGResponse)
        async def learned_trigger_chart() -> Any:
            data = self._load_learned_trigger()
            if data is None:
                return SVGResponse(content=charts.plot_learned_trigger_metrics(None), status_code=404)
            return SVGResponse(content=charts.plot_learned_trigger_metrics(data))

        @self.app.get("/residual-policy-v2", response_class=HTMLResponse)
        async def residual_policy_v2_page(request: Request) -> Any:
            data = self._load_residual_policy_v2()
            return self.templates.TemplateResponse(request, "residual_policy_v2.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/residual-policy-v2/chart.svg", response_class=SVGResponse)
        async def residual_policy_v2_chart() -> Any:
            data = self._load_residual_policy_v2()
            if data is None:
                return SVGResponse(content=charts.plot_residual_policy_v2_stats(None), status_code=404)
            return SVGResponse(content=charts.plot_residual_policy_v2_stats(data))

        @self.app.get("/valid-ood-medium", response_class=HTMLResponse)
        async def valid_ood_medium_page(request: Request) -> Any:
            data = self._load_valid_ood_medium()
            return self.templates.TemplateResponse(request, "valid_ood_medium.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/valid-ood-medium/chart.svg", response_class=SVGResponse)
        async def valid_ood_medium_chart() -> Any:
            data = self._load_valid_ood_medium()
            if data is None:
                return SVGResponse(content=charts.plot_valid_ood_medium_tasks(None, None), status_code=404)
            return SVGResponse(content=charts.plot_valid_ood_medium_tasks(data.get("selected"), data.get("rejected")))

        @self.app.get("/fth-v34", response_class=HTMLResponse)
        async def fth_v34_page(request: Request) -> Any:
            data = self._load_fth_v34()
            return self.templates.TemplateResponse(request, "fth_v34.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/fth-v34/chart.svg", response_class=SVGResponse)
        async def fth_v34_chart() -> Any:
            data = self._load_fth_v34()
            if data is None:
                return SVGResponse(content=charts.plot_fth_v34_evidence_status(None), status_code=404)
            return SVGResponse(content=charts.plot_fth_v34_evidence_status(data.get("statuses")))

        @self.app.get("/valid-ood/validity-chart.svg", response_class=SVGResponse)
        async def valid_ood_validity_chart() -> Any:
            data = self._load_valid_ood_validity()
            if data is None:
                return SVGResponse(content=charts.plot_valid_ood_validity({}), status_code=404)
            return SVGResponse(content=charts.plot_valid_ood_validity(data.get("per_task", {})))

        @self.app.get("/valid-ood/matrix-chart.svg", response_class=SVGResponse)
        async def valid_ood_matrix_chart() -> Any:
            data = self._load_valid_ood_matrix()
            if data is None:
                return SVGResponse(content=charts.plot_valid_ood_matrix({}), status_code=404)
            return SVGResponse(content=charts.plot_valid_ood_matrix(data.get("by_condition", {})))

        @self.app.get("/slip-monitor", response_class=HTMLResponse)
        async def slip_monitor_page(request: Request) -> Any:
            data = self._load_slip_monitor_validation()
            return self.templates.TemplateResponse(request, "slip_monitor.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/slip-monitor/chart.svg", response_class=SVGResponse)
        async def slip_monitor_chart() -> Any:
            data = self._load_slip_monitor_validation()
            if data is None:
                return SVGResponse(content=charts.plot_slip_monitor_summary({}), status_code=404)
            return SVGResponse(content=charts.plot_slip_monitor_summary(data.get("by_yaw", {})))

        @self.app.get("/slip-recovery", response_class=HTMLResponse)
        async def slip_recovery_page(request: Request) -> Any:
            data = self._load_slip_recovery_ablation()
            return self.templates.TemplateResponse(request, "slip_recovery.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/slip-recovery/chart.svg", response_class=SVGResponse)
        async def slip_recovery_chart() -> Any:
            data = self._load_slip_recovery_ablation()
            if data is None:
                return SVGResponse(content=charts.plot_slip_recovery_ablation({}), status_code=404)
            return SVGResponse(
                content=charts.plot_slip_recovery_ablation(data.get("per_condition_target", {}))
            )

        @self.app.get("/external-blockers", response_class=HTMLResponse)
        async def external_blockers_page(request: Request) -> Any:
            text = self._load_arena_issue_tracker_text()
            return self.templates.TemplateResponse(request, "external_blockers.html", {
                "has_data": text is not None,
                "text": text or "Arena issue tracker not available.",
            })

        # v1.0 product views -----------------------------------------------------
        @self.app.get("/validity", response_class=HTMLResponse)
        async def validity_page(request: Request) -> Any:
            data = self._load_validity_summary()
            return self.templates.TemplateResponse(request, "validity.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/baselines", response_class=HTMLResponse)
        async def baselines_page(request: Request) -> Any:
            data = self._load_official_benchmark()
            return self.templates.TemplateResponse(request, "baselines.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/paired-evaluations", response_class=HTMLResponse)
        async def paired_evaluations_page(request: Request) -> Any:
            data = self._load_paired_evaluation()
            return self.templates.TemplateResponse(request, "paired_evaluations.html", {
                "has_data": data is not None,
                "data": data.get("summary", {}) if data else {},
            })

        @self.app.get("/promotions", response_class=HTMLResponse)
        async def promotions_page(request: Request) -> Any:
            data = self._load_promotions()
            return self.templates.TemplateResponse(request, "promotions.html", {
                "has_data": data is not None,
                "data": data or {},
            })

        @self.app.get("/evidence-cards", response_class=HTMLResponse)
        async def evidence_cards_page(request: Request) -> Any:
            return self.templates.TemplateResponse(request, "evidence_cards.html", {
                "cards": self._load_evidence_cards(),
            })

        @self.app.get("/registry", response_class=HTMLResponse)
        async def registry_page(request: Request) -> Any:
            return self.templates.TemplateResponse(request, "registry.html", {
                "items": self._load_registry(),
            })

        @self.app.get("/blocked-external", response_class=HTMLResponse)
        async def blocked_external_page(request: Request) -> Any:
            return self.templates.TemplateResponse(request, "blocked_external.html", {
                "blocked": self._load_blocked_external(),
            })

        @self.app.get("/demos", response_class=HTMLResponse)
        async def demos_page(request: Request) -> Any:
            return self.templates.TemplateResponse(request, "demos.html", {})

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
            # Top-level keys are task IDs; metadata keys (tasks, seeds, timestamp)
            # are not task summaries.
            per_task = {
                k: v
                for k, v in data.items()
                if isinstance(v, dict) and "valid_rate" in v
            }
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

    def _load_large_yaw_intervention(self) -> dict[str, Any] | None:
        """Load large-yaw targeted intervention ablation aggregate."""
        p = self._resolve_data_v17_path("ablations/large_yaw_intervention/aggregate_summary.json")
        if p is None or not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
            per_condition = data.get("per_condition_target", {})
            verdict = self._compute_large_yaw_intervention_verdict(per_condition)
            return {
                "per_condition": per_condition,
                "target_yaws": data.get("target_yaws", []),
                "conditions": data.get("conditions", []),
                "verdict": verdict,
                "_source_path": str(p),
            }
        except Exception:
            return None

    @staticmethod
    def _compute_large_yaw_intervention_verdict(
        per_condition: dict[str, Any],
    ) -> dict[str, Any]:
        """Compare table_push_align to baseline on each target yaw.

        Minimum pass criterion: at least one target yaw shows >=20% relative
        improvement in orientation_achieved_rate versus baseline.
        """
        baseline_yaws: dict[float, float] = {}
        table_yaws: dict[float, float] = {}
        for key, summary in per_condition.items():
            cond = summary.get("condition", "")
            yaw = float(summary.get("target_yaw", 0.0))
            rate = float(summary.get("orientation_achieved_rate", 0.0))
            if cond == "baseline":
                baseline_yaws[yaw] = rate
            elif cond in ("table_push_align", "table_push_align_tuned"):
                table_yaws[yaw] = max(table_yaws.get(yaw, 0.0), rate)

        per_yaw: dict[str, Any] = {}
        any_pass = False
        for yaw in sorted(set(baseline_yaws) | set(table_yaws)):
            base_rate = baseline_yaws.get(yaw, 0.0)
            table_rate = table_yaws.get(yaw, 0.0)
            if base_rate > 0:
                rel_improvement = (table_rate - base_rate) / base_rate
            else:
                rel_improvement = float("inf") if table_rate > 0 else 0.0
            passed = rel_improvement >= 0.20
            any_pass = any_pass or passed
            per_yaw[f"{yaw:.4f}"] = {
                "baseline_rate": base_rate,
                "table_rate": table_rate,
                "relative_improvement": rel_improvement,
                "passed": passed,
            }

        return {
            "status": "pass" if any_pass else "reject",
            "message": (
                "table_push_align meets the minimum ≥20% relative improvement criterion on at least one target yaw."
                if any_pass
                else "Neither table_push_align nor the earlier interventions improved orientation_achieved_rate by ≥20% relative on π/2 or 2π/3. Large-yaw slip remains unresolved in the open-loop state-machine space."
            ),
            "per_yaw": per_yaw,
        }

    def _load_official_v18(self) -> dict[str, Any] | None:
        """Load official benchmark trajectory for the v1.8 dashboard view."""
        old_path = Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v16/arena_real/dex_cube_goal_pose_100_seed_v16/aggregate_summary.json")
        post_reach_path = Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v17/official/dex_cube_goal_pose_100_seed_post_reachability/aggregate_summary.json")
        seed24_fix_path = Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v18/official/dex_cube_100_seed_seed24_fix_v3/aggregate_summary.json")

        old_sr: float | None = None
        if old_path.exists():
            try:
                old_sr = float(json.loads(old_path.read_text()).get("overall_success_rate", 0.82))
            except Exception:
                pass

        post_sr: float | None = None
        if post_reach_path.exists():
            try:
                post_sr = float(json.loads(post_reach_path.read_text()).get("overall_success_rate"))
            except Exception:
                pass

        seed24_sr: float | None = None
        if seed24_fix_path.exists():
            try:
                seed24_sr = float(json.loads(seed24_fix_path.read_text()).get("overall_success_rate"))
            except Exception:
                pass

        if old_sr is None and post_sr is None and seed24_sr is None:
            return None
        return {
            "old_success_rate": old_sr or 0.82,
            "post_reachability_success_rate": post_sr,
            "seed24_fix_success_rate": seed24_sr,
            "seed24_fix_path": str(seed24_fix_path) if seed24_fix_path.exists() else None,
            "post_reachability_path": str(post_reach_path) if post_reach_path.exists() else None,
        }

    def _load_valid_ood_validity(self) -> dict[str, Any] | None:
        """Load valid OOD cube validity audit aggregate."""
        p = self._resolve_data_v18_path("diagnostics/valid_ood_cube_validity_audit/aggregate_summary.json")
        if p is None or not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
            per_task = {
                k: v
                for k, v in data.items()
                if isinstance(v, dict) and "valid_rate" in v
            }
            any_valid = any((t.get("valid_rate") or 0.0) >= 1.0 for t in per_task.values())
            return {
                "per_task": per_task,
                "any_valid": any_valid,
                "_source_path": str(p),
            }
        except Exception:
            return None

    def _load_valid_ood_matrix(self) -> dict[str, Any] | None:
        """Load valid OOD cube adaptation matrix aggregate."""
        p = self._resolve_data_v18_path("ablations/valid_ood_cube_matrix/aggregate_summary.json")
        if p is None or not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
            data["_source_path"] = str(p)
            return data
        except Exception:
            return None

    def _load_slip_monitor_validation(self) -> dict[str, Any] | None:
        """Load slip monitor validation aggregate."""
        p = self._resolve_data_v18_path("diagnostics/slip_monitor_validation/aggregate_summary.json")
        if p is None or not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
            data["_source_path"] = str(p)
            return data
        except Exception:
            return None

    def _load_arena_issue_tracker_text(self) -> str | None:
        """Load the Arena issue tracker markdown for the external blockers view."""
        p = Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/reports/ARENA_ISSUE_TRACKER.md")
        if not p.exists():
            return None
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            return None

    def _load_slip_recovery_ablation(self) -> dict[str, Any] | None:
        """Load slip-aware recovery ablation aggregate.

        Prefer the final serial run; fall back to the pilot or any gpu subdir.
        """
        for p in (
            self._resolve_data_v18_path("ablations/slip_aware_recovery/aggregate_summary.json"),
            self._resolve_data_v18_path("ablations/slip_aware_recovery_pilot/aggregate_summary.json"),
        ):
            if p is None or not p.exists():
                continue
            try:
                data = json.loads(p.read_text())
                # If this is a per-gpu split without a merged aggregate, recurse.
                if "per_condition_target" not in data:
                    gpu_dirs = sorted(d for d in p.parent.iterdir() if d.is_dir() and d.name.startswith("gpu"))
                    if gpu_dirs:
                        merged: dict[str, Any] = {"per_condition_target": {}}
                        for gpu_dir in gpu_dirs:
                            gpu_data = json.loads((gpu_dir / "aggregate_summary.json").read_text())
                            merged["per_condition_target"].update(gpu_data.get("per_condition_target", {}))
                            for key in ("target_yaws", "conditions", "seeds", "task", "base_policy"):
                                if gpu_data.get(key) is not None:
                                    merged[key] = gpu_data[key]
                        data = merged
                data["_source_path"] = str(p)
                return data
            except Exception:
                continue
        return None

    def _resolve_data_v18_path(self, relative_path: str) -> Path | None:
        """Resolve a v1.8 data path, preferring the canonical project location."""
        canonical = Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v18") / relative_path
        if canonical.exists():
            return canonical
        fallback = self.data_dir.parent / "data_v18" / relative_path
        if fallback.exists():
            return fallback
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

    def _resolve_data_v19_path(self, relative_path: str) -> Path | None:
        """Resolve a v1.9 data path, preferring the canonical project location."""
        canonical = Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v19") / relative_path
        if canonical.exists():
            return canonical
        fallback = self.data_dir.parent / "data_v19" / relative_path
        if fallback.exists():
            return fallback
        return None

    def _load_official_v19(self) -> dict[str, Any] | None:
        """Load v1.9 official baseline + seed24 micro-recovery gate status."""
        p = self._resolve_data_v19_path("diagnostics/micro_recovery_trigger_audit_gated_v2_full_rerun/aggregate_summary.json")
        if p is None or not p.exists():
            p = self._resolve_data_v19_path("diagnostics/micro_recovery_trigger_audit_gated_v2/aggregate_summary.json")
        if p is None or not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
            return {
                "success_rate": float(data.get("overall_success_rate", 0.0)),
                "trigger_rate": float(data.get("trigger_rate", 0.0)),
                "gate_success": float(data.get("gate_success", 0.99)),
                "gate_trigger": float(data.get("gate_trigger", 0.05)),
                "num_episodes": data.get("num_episodes"),
                "_source_path": str(p),
            }
        except Exception:
            return None

    def _load_contact_signal_trace(self) -> dict[str, Any] | None:
        """Find any trace.jsonl under data_v19/diagnostics/ with contact_state records."""
        base = self._resolve_data_v19_path("diagnostics")
        if base is None or not base.exists():
            return None
        try:
            for path in sorted(base.rglob("trace.jsonl")):
                records: list[dict[str, Any]] = []
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            rec = json.loads(line)
                            if "contact_state" in rec or "contact_confidence" in rec:
                                records.append(rec)
                        except Exception:
                            continue
                if records:
                    timeline = [
                        {
                            "step": i,
                            "contact_state": rec.get("contact_state", "unknown"),
                            "contact_confidence": rec.get("contact_confidence", 0.0),
                            "notes": rec.get("notes", ""),
                        }
                        for i, rec in enumerate(records)
                    ]
                    return {
                        "trace": records,
                        "timeline": timeline,
                        "num_steps": len(records),
                        "_source_path": str(path),
                    }
        except Exception:
            pass
        return None

    def _load_residual_policy_stats(self) -> dict[str, Any] | None:
        """Load residual policy statistics from metadata.yaml and residual_stats.json."""
        metadata_path = self._resolve_data_v19_path("datasets/residual_learning/metadata.yaml")
        stats_path = self._resolve_data_v19_path("ablations/residual_policy_pilot/residual_stats.json")
        if stats_path is None or not stats_path.exists():
            # Search for any residual_stats.json in the residual_policy_pilot dir
            pilot_dir = self._resolve_data_v19_path("ablations/residual_policy_pilot")
            if pilot_dir is not None and pilot_dir.exists():
                candidates = sorted(pilot_dir.rglob("residual_stats.json"))
                if candidates:
                    stats_path = candidates[0]
        if stats_path is None or not stats_path.exists():
            return None
        try:
            stats = json.loads(stats_path.read_text())
            result = {
                "trigger_rate": float(stats.get("trigger_rate", 0.0)),
                "clamp_rate": float(stats.get("clamp_rate", 0.0)),
                "success_frames": int(stats.get("success_frames", 0)),
                "failure_frames": int(stats.get("failure_frames", 0)),
                "total_frames": int(stats.get("total_frames", 0)),
                "stats_path": str(stats_path),
                "metadata_path": str(metadata_path) if metadata_path and metadata_path.exists() else None,
            }
            return result
        except Exception:
            return None

    def _load_valid_ood_subtasks(self) -> dict[str, Any] | None:
        """Load valid OOD subtask decomposition summary."""
        p = self._resolve_data_v19_path("diagnostics/valid_ood_subtask_decomposition/summary.json")
        if p is None or not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
            data["_source_path"] = str(p)
            return data
        except Exception:
            return None

    def _load_fth_v33(self) -> dict[str, Any] | None:
        """Load FailureToHint v3.3 route distribution."""
        p = self._resolve_data_v19_path("evolution/fth_v33_route_distribution.json")
        if p is not None and p.exists():
            try:
                data = json.loads(p.read_text())
                routes = data.get("routes", {})
                return {
                    "routes": routes,
                    "total": sum(routes.values()) if routes else 0,
                    "_source_path": str(p),
                }
            except Exception:
                pass
        # Fallback: parse YAML config to count route types
        config_path = Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/configs/skills/failure_signature_to_hint_rules_v33.yaml")
        if not config_path.exists():
            config_path = self.data_dir.parent / "configs" / "skills" / "failure_signature_to_hint_rules_v33.yaml"
        if not config_path.exists():
            return None
        try:
            import yaml
            config = yaml.safe_load(config_path.read_text())
            routes: dict[str, int] = {}
            for rule in config.get("rules", []):
                route_type = rule.get("route_type", "unknown")
                routes[route_type] = routes.get(route_type, 0) + 1
            return {
                "routes": routes,
                "total": sum(routes.values()) if routes else 0,
                "_source_path": str(config_path),
            }
        except Exception:
            return None

    def _load_paired_evaluation(self) -> dict[str, Any] | None:
        """Load paired no-regression evaluation summary for seed24 micro-recovery."""
        for p in (
            Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v20/paired/official_seed24_micro_recovery_0_199/paired_summary.json"),
            Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v20/paired/official_seed24_micro_recovery_0_4_real/paired_summary.json"),
            self.data_dir.parent / "data_v20" / "paired" / "official_seed24_micro_recovery_0_199" / "paired_summary.json",
        ):
            if p is None or not p.exists():
                continue
            try:
                data = json.loads(p.read_text())
                data["_source_path"] = str(p)
                return data
            except Exception:
                continue
        return None

    def _load_contact_signal_v2(self) -> dict[str, Any] | None:
        """Load ContactSignal reliability audit coverage."""
        for p in (
            Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v20/diagnostics/contact_signal_reliability_audit_from_v19_v2/aggregate_summary.json"),
            Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v20/diagnostics/contact_signal_reliability_audit/aggregate_summary.json"),
            self.data_dir.parent / "data_v20" / "diagnostics" / "contact_signal_reliability_audit" / "aggregate_summary.json",
        ):
            if p is None or not p.exists():
                continue
            try:
                data = json.loads(p.read_text())
                coverage = {
                    phase: float(info.get("coverage_rate", 0.0) or 0.0)
                    for phase, info in data.get("phases", {}).items()
                }
                return {
                    "coverage": coverage,
                    "overall_coverage_rate": float(data.get("overall_coverage_rate", 0.0) or 0.0),
                    "_source_path": str(p),
                }
            except Exception:
                continue
        return None

    def _load_learned_trigger(self) -> dict[str, Any] | None:
        """Load learned trigger model evaluation metrics."""
        for p in (
            Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v20/models/trigger_model/evaluation.json"),
            self.data_dir.parent / "data_v20" / "models" / "trigger_model" / "evaluation.json",
        ):
            if p is None or not p.exists():
                continue
            try:
                data = json.loads(p.read_text())
                data["_source_path"] = str(p)
                return data
            except Exception:
                continue
        return None

    def _load_residual_policy_v2(self) -> dict[str, Any] | None:
        """Load bounded residual policy v2 safety statistics."""
        for p in (
            Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v20/ablations/learned_residual_pilot/residual_stats.json"),
            Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v20/ablations/bounded_residual_policy/residual_stats.json"),
            self.data_dir.parent / "data_v20" / "ablations" / "learned_residual_pilot" / "residual_stats.json",
        ):
            if p is None or not p.exists():
                continue
            try:
                data = json.loads(p.read_text())
                data["_source_path"] = str(p)
                return data
            except Exception:
                continue
        return None

    def _load_valid_ood_medium(self) -> dict[str, Any] | None:
        """Load valid OOD medium-task selection results."""
        for p in (
            Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v20/diagnostics/valid_ood_medium_task_mining/selected_tasks.yaml"),
            self.data_dir.parent / "data_v20" / "diagnostics" / "valid_ood_medium_task_mining" / "selected_tasks.yaml",
        ):
            if p is None or not p.exists():
                continue
            try:
                import yaml
                selected = yaml.safe_load(p.read_text()) or {}
                rejected_path = p.parent / "rejected_tasks.yaml"
                rejected = {}
                if rejected_path.exists():
                    rejected = yaml.safe_load(rejected_path.read_text()) or {}
                return {
                    "selected": selected,
                    "rejected": rejected,
                    "_source_path": str(p),
                }
            except Exception:
                continue
        return None

    def _load_fth_v34(self) -> dict[str, Any] | None:
        """Load FailureToHint v3.4 evidence status list."""
        for p in (
            Path("/code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v20/evolution/fth_v34_evidence_status.json"),
            self.data_dir.parent / "data_v20" / "evolution" / "fth_v34_evidence_status.json",
        ):
            if p is None or not p.exists():
                continue
            try:
                data = json.loads(p.read_text())
                data["_source_path"] = str(p)
                return data
            except Exception:
                continue
        return None

    def _load_evidence_cards(self) -> list[dict[str, Any]]:
        """Load generated evidence cards from cards/ directory."""
        cards: list[dict[str, Any]] = []
        cards_dir = Path.cwd() / "cards"
        if not cards_dir.exists():
            cards_dir = self.data_dir.parent / "cards"
        if not cards_dir.exists():
            return cards
        for f in sorted(cards_dir.glob("*.card.yaml")):
            try:
                import yaml
                cards.append(yaml.safe_load(f.read_text()))
            except Exception:
                continue
        return cards

    def _load_registry(self) -> list[dict[str, Any]]:
        """Load promotion registry items."""
        from rosclaw_darwin.registry import PromotionRegistry

        candidates = [
            self.data_dir / "darwin" / "registry",
            Path("data/darwin/registry"),
            Path("registry"),
            Path("data_darwin_arena/registry"),
        ]
        registry_dir = None
        for candidate in candidates:
            if candidate.exists() and (candidate / "registry.json").exists():
                registry_dir = candidate
                break
        if registry_dir is None:
            return []
        try:
            reg = PromotionRegistry(registry_dir)
            return [item.model_dump(mode="json") for item in reg.list_items()]
        except Exception:
            return []

    def _load_arena_dashboard(self) -> dict[str, Any]:
        """Aggregate Arena real-learned-policy evidence for the dashboard."""
        matrix_path = Path("configs/backends/capability_matrix.yaml")
        arena: dict[str, Any] = {}
        if matrix_path.exists():
            try:
                matrix = yaml.safe_load(matrix_path.read_text()) or {}
                arena = next(
                    (b for b in matrix.get("backends", []) if b.get("id") == "arena"),
                    {},
                )
            except Exception:
                arena = {}

        registry = self._load_registry()
        arena_items = [item for item in registry if item.get("id", "").startswith("arena_")]
        evidence_levels = {item.get("evidence_level") for item in arena_items}

        real_env_status = "unknown"
        if arena.get("real_reset_step"):
            real_env_status = "L1_REAL_ENV_SMOKE" if "L2_REAL_BASELINE_EVALUATED" not in evidence_levels else "L2+"
        learned_policy_status = "L0_SYNTHETIC_PIPELINE_DEMO"
        if "L2_REAL_BASELINE_EVALUATED" in evidence_levels:
            learned_policy_status = "L2_REAL_BASELINE_EVALUATED"
        candidate_eval_status = "not_demonstrated"
        if "L3_REAL_NEGATIVE_REJECTION" in evidence_levels:
            candidate_eval_status = "L3_REAL_NEGATIVE_REJECTION"
        positive_rescue_status = "not_demonstrated"
        if "L5_REAL_POSITIVE_RESCUE" in evidence_levels:
            positive_rescue_status = "L5_REAL_POSITIVE_RESCUE"

        # v1.6 supplement: scale metadata from evidence cards
        scale_summary: dict[str, Any] = {"l2": {}, "l3": {}, "l5": {}}
        for card in self._load_evidence_cards():
            name = card.get("name", "")
            level = card.get("evidence_level")
            if level == "L2_REAL_BASELINE_EVALUATED" and "tiny_bc" in name:
                scale_summary["l2"] = {
                    "card": name,
                    "seed_count": card.get("seed_count"),
                    "scale_validated": card.get("scale_validated"),
                }
            elif level == "L3_REAL_NEGATIVE_REJECTION" and "wrong_action_scale" in name:
                scale_summary["l3"] = {
                    "card": name,
                    "seed_count": card.get("seed_count"),
                    "scale_validated": card.get("scale_validated"),
                }
            elif level in {"L5_REAL_POSITIVE_RESCUE", "L5_REAL_POSITIVE_RESCUE_CANDIDATE"} and "action_scale_fix" in name:
                scale_summary["l5"] = {
                    "card": name,
                    "seed_count": card.get("seed_count"),
                    "scale_validated": card.get("scale_validated"),
                    "runtime_eligible": card.get("runtime_eligible"),
                }

        # Demo dataset quality
        demo_audit_path = Path("data_darwin_arena/cube_goal_pose/demos_scripted_v2_100eps/audit.json")
        demo_dataset: dict[str, Any] = {"available": False}
        if demo_audit_path.exists():
            try:
                audit = json.loads(demo_audit_path.read_text())
                demo_dataset = {
                    "available": True,
                    "unique_seeds": audit.get("num_unique_seeds"),
                    "unique_episodes": audit.get("num_unique_episodes"),
                    "transitions": audit.get("num_records"),
                    "invalid_action_rate": audit.get("invalid_action_rate"),
                    "episode_collapse": audit.get("episode_collapse_detected"),
                }
            except Exception:
                pass

        # Official workflow probe (legacy v1.6)
        probe_path = Path("data_darwin_arena/official_workflow_probe_v2/probe.json")
        official_workflow: dict[str, Any] = {"available": False}
        if probe_path.exists():
            try:
                probe = json.loads(probe_path.read_text())
                official_workflow = {
                    "available": True,
                    "workflow": probe.get("workflow"),
                    "classification": probe.get("classification", "unknown"),
                    "runnable": probe.get("official_policy_workflow_runnable"),
                    "checkpoints": len(probe.get("checkpoint_files", [])),
                }
            except Exception:
                pass

        # v1.7 official GR1 Open Microwave path
        def _load_json(path: Path) -> dict[str, Any]:
            if not path.exists():
                return {}
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}

        asset_probe = _load_json(Path("data_darwin_arena/official_gr1_assets/asset_probe.json"))
        download_report = _load_json(Path("data_darwin_arena/official_gr1_assets/download_report.json"))
        replay_artifact = _load_json(Path("data_darwin_arena/official_gr1_replay/replay_run_artifact.json"))
        server_start = _load_json(Path("data_darwin_arena/official_gr1_server/server_start.json"))
        runner_artifact = _load_json(Path("data_darwin_arena/official_gr1_policy_runner/single_env/official_runner_artifact.json"))

        official_path: dict[str, Any] = {
            "asset_probe": {
                "status": asset_probe.get("status", "missing"),
                "failure_classification": asset_probe.get("failure_classification"),
                "dataset_reachable": asset_probe.get("dataset", {}).get("reachable"),
                "checkpoint_reachable": asset_probe.get("checkpoint", {}).get("reachable"),
            },
            "download": {
                "status": download_report.get("overall_status", "missing"),
                "failure_classification": download_report.get("failure_classification"),
            },
            "replay": {
                "status": replay_artifact.get("status", "missing"),
                "failure_classification": replay_artifact.get("failure_classification"),
            },
            "server": {
                "status": server_start.get("status", "missing"),
                "failure_classification": server_start.get("failure_classification"),
            },
            "runner": {
                "status": runner_artifact.get("status", "missing"),
                "failure_classification": runner_artifact.get("failure_classification"),
                "metrics": runner_artifact.get("parsed_metrics", {}),
            },
        }
        official_path["blocked"] = not all(
            official_path[k]["status"] == "completed" for k in ("asset_probe", "download", "replay", "server", "runner")
        )

        blockers: list[str] = []
        if not arena.get("real_reset_step"):
            blockers.append("Arena real env reset/step not yet demonstrated")
        if not arena.get("real_learned_policy"):
            blockers.append("Real learned-policy baseline not yet demonstrated")
        if not arena.get("real_candidate_paired_eval"):
            blockers.append("Real candidate paired evaluation not yet demonstrated")
        if not arena.get("positive_rescue_pilot") and not arena.get("positive_rescue_scaled"):
            blockers.append("Positive adapter-fix rescue not yet demonstrated")
        if not any(item.get("status") == "arena_real_learned_policy_baseline_evaluated" for item in arena_items):
            blockers.append("No arena baseline registry item")
        if not any(item.get("status") == "rejected" for item in arena_items):
            blockers.append("No arena rejection registry item")
        if not any(item.get("status") in {"real_adapter_fix_recovery", "real_adapter_fix_recovery_pilot"} for item in arena_items):
            blockers.append("No arena adapter-fix recovery registry item")

        if official_path.get("blocked"):
            fc = (
                official_path.get("asset_probe", {}).get("failure_classification")
                or official_path.get("download", {}).get("failure_classification")
                or official_path.get("runner", {}).get("failure_classification")
                or "unknown"
            )
            blockers.append(f"Official GR1 Open Microwave workflow blocked: {fc}")

        report_dir = Path("reports")
        latest_reports: list[dict[str, str]] = []
        if report_dir.exists():
            for report in sorted(report_dir.glob("DARWIN_ARENA_*.md")) + sorted(report_dir.glob("DARWIN_V1_6_*.md")) + sorted(report_dir.glob("DARWIN_V1_8_*.md")) + sorted(report_dir.glob("ARENA_*.md")):
                latest_reports.append({"name": report.name, "path": str(report)})

        # v1.7.1 official GR1 Open Microwave hardening artifacts
        server_health = _load_json(Path("data_darwin_arena/official_gr1_server_v171/server_health.json"))
        rotation_fix_card = next(
            (c for c in self._load_evidence_cards() if c.get("name") == "arena_gr1_microwave_rotation_alignment_fix"),
            {},
        )
        scale_card = next(
            (c for c in self._load_evidence_cards() if c.get("name") == "arena_gr1_open_microwave_official_baseline_scale_v171"),
            {},
        )
        wrapper_card = next(
            (c for c in self._load_evidence_cards() if c.get("name") == "arena_gr1_official_wrapper_configs_prepared"),
            {},
        )
        official_path["server_health"] = {
            "status": "verified" if server_health.get("checkpoint_loaded") and server_health.get("port_open") else "missing",
            "checkpoint_loaded": server_health.get("checkpoint_loaded"),
            "port_open": server_health.get("port_open"),
            "inference_smoke_passed": server_health.get("inference_smoke_passed"),
        }
        official_path["rotation_fix"] = {
            "status": "validated" if rotation_fix_card else "missing",
            "card": rotation_fix_card.get("name") if rotation_fix_card else None,
        }
        official_path["baseline_scale"] = {
            "status": "validated" if scale_card else "missing",
            "card": scale_card.get("name") if scale_card else None,
            "total_episodes": scale_card.get("artifacts", {}).get("total_episodes") if scale_card else None,
        }
        official_path["candidate_wrapper"] = {
            "status": "prepared" if wrapper_card else "not_started",
            "card": wrapper_card.get("name") if wrapper_card else None,
        }

        # v1.8 official candidate-wrapper evolution
        reference_baseline_v18 = next(
            (c for c in self._load_evidence_cards() if c.get("name") == "arena_gr1_gn1x_official_reference_baseline_v18"),
            {},
        )
        smoke_v18 = next(
            (c for c in self._load_evidence_cards() if c.get("name") == "arena_gr1_official_wrapper_smoke_v18"),
            {},
        )
        negative_v18 = next(
            (c for c in self._load_evidence_cards() if c.get("name") == "arena_gr1_official_candidate_arena_gr1_door_lock_v18"),
            {},
        )
        rescue_v18 = next(
            (c for c in self._load_evidence_cards() if c.get("name") == "arena_gr1_official_candidate_arena_gr1_rollback_v18"),
            {},
        )


        negative_metrics = _load_json(Path("data_darwin_arena/official_gr1_v18/candidates/door_lock_20ep_negative/candidate_metrics.json"))
        rescue_metrics = _load_json(Path("data_darwin_arena/official_gr1_v18/candidates/rollback_20ep/candidate_metrics.json"))

        official_path["reference_baseline_v18"] = {
            "status": "frozen" if reference_baseline_v18 else "missing",
            "card": reference_baseline_v18.get("name") if reference_baseline_v18 else None,
            "metrics": reference_baseline_v18.get("artifacts", {}).get("aggregate") if reference_baseline_v18 else None,
        }
        official_path["wrapper_smoke_v18"] = {
            "status": "passed" if smoke_v18 else "missing",
            "card": smoke_v18.get("name") if smoke_v18 else None,
        }
        official_path["negative_candidate_v18"] = {
            "status": negative_v18.get("promotion_decision", {}).get("status") if negative_v18 else "missing",
            "card": negative_v18.get("name") if negative_v18 else None,
            "classification": "diagnostic metric guard",
            "candidate_kind": negative_v18.get("candidate_kind") if negative_v18 else None,
            "wrapper_scope": negative_v18.get("wrapper_scope") if negative_v18 else None,
            "diagnostic_note": negative_v18.get("diagnostic_note") if negative_v18 else None,
            "allowed_claims": negative_v18.get("allowed_claims", []) if negative_v18 else [],
            "blocked_claims": negative_v18.get("blocked_claims", []) if negative_v18 else [],
            "success_rate": negative_metrics.get("success_rate"),
            "door_moved_rate": negative_metrics.get("door_moved_rate"),
            "delta_success_rate": negative_metrics.get("delta_success_rate"),
        }
        official_path["rescue_candidate_v18"] = {
            "status": rescue_v18.get("promotion_decision", {}).get("status") if rescue_v18 else "missing",
            "card": rescue_v18.get("name") if rescue_v18 else None,
            "classification": "diagnostic metric-guard rollback",
            "candidate_kind": rescue_v18.get("candidate_kind") if rescue_v18 else None,
            "wrapper_scope": rescue_v18.get("wrapper_scope") if rescue_v18 else None,
            "recovered_from": rescue_v18.get("recovered_from") if rescue_v18 else None,
            "diagnostic_note": rescue_v18.get("diagnostic_note") if rescue_v18 else None,
            "allowed_claims": rescue_v18.get("allowed_claims", []) if rescue_v18 else [],
            "blocked_claims": rescue_v18.get("blocked_claims", []) if rescue_v18 else [],
            "success_rate": rescue_metrics.get("success_rate"),
            "door_moved_rate": rescue_metrics.get("door_moved_rate"),
            "delta_success_rate": rescue_metrics.get("delta_success_rate"),
        }

        # v1.8.1 causal wrapper evolution
        drift_summary_v181 = _load_json(Path("data_darwin_arena/official_gr1_v181/passive_drift/matrix_20ep/passive_drift_summary.json"))
        negative_matrix_v181 = _load_json(Path("data_darwin_arena/official_gr1_v181/candidates/negative_matrix_20ep/negative_matrix_summary.json"))
        effect_validation_card_v181 = next(
            (c for c in self._load_evidence_cards() if c.get("name") == "arena_gr1_action_wrapper_effect_validation_v181"),
            {},
        )
        rollback_rescue_card_v181 = next(
            (c for c in self._load_evidence_cards() if c.get("name") == "arena_gr1_action_wrapper_rollback_recovery_v181"),
            {},
        )
        rollback_rescue_metrics_v181 = _load_json(Path("data_darwin_arena/official_gr1_v181/candidates/rollback_rescue_20ep/candidate_metrics.json"))
        noop_drift = drift_summary_v181.get("matrix", {}).get("noop_policy", {})
        action_zero_drift = drift_summary_v181.get("matrix", {}).get("action_zero", {})

        official_path["v181_causal_wrapper"] = {
            "passive_drift": {
                "summary_exists": bool(drift_summary_v181),
                "severity": drift_summary_v181.get("passive_drift_severity"),
                "noop_success_rate": noop_drift.get("success_rate"),
                "noop_max_openness_mean": noop_drift.get("max_openness_mean"),
                "action_zero_success_rate": action_zero_drift.get("success_rate"),
                "action_zero_max_openness_mean": action_zero_drift.get("max_openness_mean"),
                "official_metric_causal_risk": drift_summary_v181.get("official_success_metric_causal_risk"),
            },
            "wrapper_effect_validation": {
                "card": effect_validation_card_v181.get("name") if effect_validation_card_v181 else None,
                "status": effect_validation_card_v181.get("promotion_decision", {}).get("status") if effect_validation_card_v181 else "missing",
                "evidence_level": effect_validation_card_v181.get("evidence_level") if effect_validation_card_v181 else None,
            },
            "negative_rejection_matrix": {
                "summary_exists": bool(negative_matrix_v181),
                "l3_found": negative_matrix_v181.get("l3_found") if negative_matrix_v181 else False,
                "degraded_count": len(negative_matrix_v181.get("degraded_candidates", [])) if negative_matrix_v181 else 0,
            },
            "rollback_rescue": {
                "card": rollback_rescue_card_v181.get("name") if rollback_rescue_card_v181 else None,
                "status": rollback_rescue_card_v181.get("promotion_decision", {}).get("status") if rollback_rescue_card_v181 else "not_attempted",
                "success_rate": rollback_rescue_metrics_v181.get("success_rate"),
                "door_moved_rate": rollback_rescue_metrics_v181.get("door_moved_rate"),
            },
        }

        official_path["status"] = {
            "official_workflow_status": "verified" if not official_path.get("blocked") else "blocked",
            "local_metric_match": bool(runner_artifact.get("parsed_metrics", {}).get("success_rate", 0) >= 0.8),
            "leaderboard_status": "not_submitted",
            "candidate_wrapper_status": "evaluated" if (negative_v18 and rescue_v18) else ("prepared" if wrapper_card else "not_started"),
            "rotation_fix_status": "validated" if rotation_fix_card else "missing",
            "server_health_status": official_path["server_health"]["status"],
            "v181_causal_status": (
                "negative_found"
                if official_path["v181_causal_wrapper"]["negative_rejection_matrix"]["l3_found"]
                else "evaluating"
                if official_path["v181_causal_wrapper"]["wrapper_effect_validation"]["status"] != "missing"
                else "not_started"
            ),
        }

        return {
            "matrix": arena,
            "registry": arena_items,
            "status": {
                "real_env_status": real_env_status,
                "learned_policy_status": learned_policy_status,
                "candidate_eval_status": candidate_eval_status,
                "positive_rescue_status": positive_rescue_status,
                "max_evidence_level": arena.get("max_confirmed_evidence_level", arena.get("max_evidence_level", "unknown")),
                "pilot_evidence_level": arena.get("max_pilot_evidence_level", "unknown"),
                "backend_status": arena.get("status", "unknown"),
                "runtime_enabled_routes": arena.get("runtime_enabled_routes", []),
            },
            "scale_summary": scale_summary,
            "demo_dataset": demo_dataset,
            "official_workflow": official_workflow,
            "official_path": official_path,
            "blockers": blockers,
            "latest_reports": latest_reports,
        }
    def _load_blocked_external(self) -> list[dict[str, Any]]:
        """Return blocked-external items from evidence cards and registry."""
        blocked: list[dict[str, Any]] = [
            {
                "name": "procedural_fallback_invalid_environment",
                "reason": "Procedural cube fallback has disabled collision and invalid bbox.",
                "next_step": "Escalate to Arena; use valid OOD cube for OOD evaluation.",
            },
            {
                "name": "large_yaw_torsional_slip",
                "reason": "Large-yaw torsional slip is outside current sensor/control capabilities.",
                "next_step": "Requires contact/force sensing or hardware change.",
            },
        ]
        for card in self._load_evidence_cards():
            status = card.get("promotion_decision", {}).get("status")
            if status == "blocked_external":
                blocked.append({
                    "name": card.get("name", "unknown"),
                    "reason": card.get("summary", ""),
                    "next_step": "See evidence card.",
                })
        return blocked

    def _load_promotions(self) -> dict[str, Any] | None:
        """Load latest promotion decision."""
        promo_dir = self.data_dir / "darwin" / "promotions"
        if not promo_dir.exists():
            promo_dir = Path("data/darwin/promotions")
        if not promo_dir.exists():
            return None
        files = sorted(promo_dir.glob("*_promotion_decision.json"))
        if not files:
            return None
        try:
            return json.loads(files[-1].read_text())
        except Exception:
            return None

    def _load_validity_summary(self) -> dict[str, Any] | None:
        """Aggregate task validity reports."""
        validity_dir = self.data_dir / "darwin" / "validity"
        if not validity_dir.exists():
            validity_dir = Path("data/darwin/validity")
        if not validity_dir.exists():
            return None
        per_task: dict[str, Any] = {}
        for f in validity_dir.glob("**/task_validity.json"):
            try:
                data = json.loads(f.read_text())
                per_task[data.get("task_id", f.stem)] = {
                    "scope": data.get("benchmark_scope"),
                    "status": data.get("validity_status"),
                    "official_asset": data.get("official_asset"),
                }
            except Exception:
                continue
        if not per_task:
            return None
        return {"per_task": per_task}

    def run(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        import uvicorn
        uvicorn.run(self.app, host=host, port=port)

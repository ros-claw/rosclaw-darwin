"""Backward-compatible v2 evaluation result schema.

``EvaluationResultV2`` extends the existing ``EvaluationResult`` with optional
fields for LeRobot-normalized benchmark runs while preserving the ability to
load older v1 JSON artifacts.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from rosclaw_darwin.evaluation.result import EvaluationResult


class EvaluationResultV2(EvaluationResult):
    """Extended evaluation result with benchmark-specific evidence fields."""

    schema_version: str = "rosclaw.darwin.evaluation_result.v2"

    benchmark: dict[str, Any] = Field(default_factory=dict)
    primary_metric: str | None = None
    raw_metrics: dict[str, Any] = Field(default_factory=dict)
    metric_definitions: dict[str, Any] = Field(default_factory=dict)

    num_tasks: int | None = None
    num_episodes: int | None = None

    confidence_intervals: dict[str, Any] = Field(default_factory=dict)
    validity_gate: dict[str, Any] = Field(default_factory=dict)
    performance_gate: dict[str, Any] = Field(default_factory=dict)

    task_results_path: str | None = None
    episode_results_path: str | None = None


# Keep a module-level alias so callers can treat this as the canonical result.
EvaluationResultModel: type[BaseModel] = EvaluationResultV2

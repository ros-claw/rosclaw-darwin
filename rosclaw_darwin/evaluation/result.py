"""Evaluation result schema."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EvaluationResult(BaseModel):
    run_id: str
    task_id: str
    policy_id: str
    adapter: str
    status: str

    metrics: dict[str, float] = Field(default_factory=dict)
    failure_types: dict[str, int] = Field(default_factory=dict)

    artifacts: dict[str, Any] = Field(default_factory=dict)
    command: list[str] | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

"""Evaluation result schema."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MetricScope(str, Enum):
    """Where the metrics came from and what they can claim."""

    mock_ci = "mock_ci"
    pipeline_sanity = "pipeline_sanity"
    arena_real = "arena_real"
    robotwin_replay = "robotwin_replay"
    semantic_only = "semantic_only"


class ClaimLevel(str, Enum):
    """Highest claim that can be made from a result."""

    infrastructure = "infrastructure"
    execution = "execution"
    capability = "capability"
    evolution = "evolution"
    none = "none"


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

    # Result-semantics metadata: separates pipeline sanity, real capability, and
    # evolution evidence. Defaults produce the conservative "real capability"
    # claim; adapters and runners are responsible for downgrading to
    # pipeline_sanity/oracle when appropriate.
    metric_scope: MetricScope = MetricScope.arena_real
    claim_level: ClaimLevel = ClaimLevel.capability
    can_claim_capability: bool = True
    can_claim_evolution: bool = False
    leaderboard_excluded: bool = False
    exclusion_reason: str | None = None

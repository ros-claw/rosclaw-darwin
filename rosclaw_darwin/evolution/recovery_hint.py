"""Recovery-policy schema for FailureToHint v3.2.

A recovery policy encodes a closed-loop intervention: a monitor, the condition
under which it is activated, concrete parameter overrides, the metric used to
decide success, and a fallback policy if the recovery fails.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MonitorConfig(BaseModel):
    """Configuration for the sensor/proxy that drives recovery activation."""

    type: str = "slip_monitor"  # slip_monitor | contact_proxy | none
    enabled: bool = True
    # Kinematic-slip-specific fields.
    event_score_threshold: float | None = None
    min_event_steps: int | None = None


class ActivationCondition(BaseModel):
    """Condition that must be satisfied before a recovery policy is triggered."""

    slip_score_gt: float | None = None
    phase_in: list[str] = Field(default_factory=list)
    consecutive_slip_steps: int | None = None
    any_slip: bool | None = None


class SuccessMetric(BaseModel):
    """Metric used to judge whether the recovery succeeded."""

    metric: str  # orientation_achieved_rate | slip_recovery_success_rate | lifted_rate
    threshold: float | None = None


class RecoveryPolicy(BaseModel):
    """A closed-loop recovery policy that can be attached to a hint/recipe."""

    type: str  # pause_stabilize | lower_regrip | place_push_correct | abort_safe | none
    max_attempts: int = 2
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)
    activation_condition: ActivationCondition = Field(default_factory=ActivationCondition)
    parameter_overrides: dict[str, Any] = Field(default_factory=dict)
    success_metric: list[SuccessMetric] = Field(default_factory=list)
    fallback_policy: "RecoveryPolicy | None" = None


class RecoveryHint(BaseModel):
    """A skill hint augmented with a recovery policy for v3.2."""

    name: str
    source: str
    confidence: float = 0.0
    rationale: str | None = None
    parameter_overrides: dict[str, Any] = Field(default_factory=dict)
    structural_overrides: dict[str, Any] = Field(default_factory=dict)
    strategy_switches: list[str] = Field(default_factory=list)
    recovery_policy: RecoveryPolicy | None = None

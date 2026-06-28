"""Candidate intervention schema for Darwin v1.0."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CandidateIntervention(BaseModel):
    """A policy patch, recovery, residual, or skill candidate under evaluation."""

    name: str
    intervention_type: str  # recovery | residual | skill | policy_patch
    trigger_signals: list[str] = Field(default_factory=list)
    action_type: str = "parameter_override"  # parameter_override | residual | closed_loop
    policy_config_path: str | None = None
    recovery_policy: dict[str, Any] | None = None
    residual_model_path: str | None = None
    trigger_model_path: str | None = None
    intended_scope: list[str] = Field(default_factory=list)
    safety_limits: dict[str, Any] = Field(default_factory=dict)
    status: str = "experimental_only"

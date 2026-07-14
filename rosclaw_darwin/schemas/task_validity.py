"""Task validity schema for Darwin v1.0."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from rosclaw_darwin.evaluation.object_validity import ObjectValidityReport


class TaskValidity(BaseModel):
    """Product-level validity verdict for a task / benchmark environment."""

    task_id: str
    benchmark_scope: Literal[
        "official_arena_asset",
        "rosclaw_ood_diagnostic",
        "libero_10_official_suite",
        "invalid_environment",
    ]
    validity_status: Literal["valid", "invalid", "warning"] = "valid"
    asset_fallback_used: bool = False
    official_asset: bool = False
    can_claim_official_benchmark: bool = False
    can_claim_ood_diagnostic: bool = False
    object_validity: ObjectValidityReport | None = None
    reason: list[str] = Field(default_factory=list)

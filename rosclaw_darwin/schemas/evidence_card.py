"""Evidence card schema for Darwin v1.0."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from rosclaw_darwin.evaluation.failure_signature import FailureSignature
from rosclaw_darwin.evaluation.paired_evaluation import PairedEvaluationSummary
from rosclaw_darwin.schemas.intervention import CandidateIntervention
from rosclaw_darwin.schemas.promotion_decision import PromotionDecision
from rosclaw_darwin.schemas.task_validity import TaskValidity


class EvidenceCard(BaseModel):
    """Human- and machine-readable evidence summary for a candidate."""

    name: str
    type: str = "recovery"  # baseline | recovery | diagnosis | blocked_external
    summary: str
    candidate: CandidateIntervention | None = None
    task_validity: TaskValidity | None = None
    failure_signature: FailureSignature | None = None
    paired_evidence: PairedEvaluationSummary | dict[str, Any] | None = None
    promotion_decision: PromotionDecision
    demo_scope: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    allowed_claims: list[str] = Field(default_factory=list)
    blocked_claims: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    created_at: str | None = None

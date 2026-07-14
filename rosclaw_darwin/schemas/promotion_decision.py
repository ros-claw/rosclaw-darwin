"""Promotion decision schema for Darwin v1.0."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from rosclaw_darwin.evolution.evidence_level import EvidenceLevel, EvidenceType
from rosclaw_darwin.evolution.evidence_status import EvidenceStatus


class PromotionDecision(BaseModel):
    """Productized promotion decision for a candidate intervention."""

    candidate_name: str
    status: str
    claim_level: str = "experimental"
    evidence_refs: list[str] = Field(default_factory=list)
    passed_gates: list[str] = Field(default_factory=list)
    failed_gates: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    allowed_claims: list[str] = Field(default_factory=list)
    disallowed_claims: list[str] = Field(default_factory=list)
    next_required_evidence: list[str] = Field(default_factory=list)
    fth_status: EvidenceStatus | None = None
    # v1.4 evidence taxonomy
    evidence_level: str = EvidenceLevel.L0_SYNTHETIC_PIPELINE_DEMO.value
    evidence_type: str = EvidenceType.SYNTHETIC.value
    runtime_eligible: bool = False
    promotion_scope: str | None = None
    # v1.6 supplement: pilot vs. confirmed scale metadata
    scale_validated: bool = False
    seed_count: int | None = None
    minimum_required_seed_count: int | None = None
    requires_scale_validation: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict."""
        return self.model_dump(mode="json")

"""Promotion decision schema for Darwin v1.0."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

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

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict."""
        return self.model_dump(mode="json")

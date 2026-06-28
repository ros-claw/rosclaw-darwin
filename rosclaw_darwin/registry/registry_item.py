"""Promotion registry item schema."""

from __future__ import annotations

from pydantic import BaseModel


class RegistryItem(BaseModel):
    """A single entry in the promotion registry."""

    id: str
    kind: str  # recovery | policy | diagnostic | blocked
    status: str
    card: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    owner: str = "darwin"
    enabled_for_runtime: bool = False
    requires_human_approval: bool = False

    def is_promotable(self) -> bool:
        """Return True if the item can be enabled for runtime promotion."""
        if self.status == "blocked_external":
            return False
        if self.status in {"candidate_recovery", "validated_recovery", "validated_transferable_skill"}:
            return True
        return False

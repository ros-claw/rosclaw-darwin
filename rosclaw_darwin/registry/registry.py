"""Promotion registry for Darwin v1.0."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rosclaw_darwin.registry.promotion_policy import (
    allowed_claims,
    can_promote,
    disallowed_claims,
    promotion_level_from_summary,
)
from rosclaw_darwin.registry.registry_item import RegistryItem


class PromotionRegistry:
    """Read/write registry of promoted candidates with runtime query interface."""

    def __init__(self, registry_dir: str | Path = "data/darwin/registry"):
        self.registry_dir = Path(registry_dir)
        self._items: dict[str, RegistryItem] = {}
        self._load()

    @property
    def _index_path(self) -> Path:
        return self.registry_dir / "registry.json"

    def _load(self) -> None:
        if not self._index_path.exists():
            return
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for item_data in data.get("items", []):
            item = RegistryItem.model_validate(item_data)
            self._items[item.id] = item

    def _save(self) -> None:
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "items": [item.model_dump(mode="json") for item in self._items.values()],
        }
        self._index_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def add(
        self,
        item_id: str,
        kind: str,
        status: str,
        card: str | None = None,
        owner: str = "darwin",
        evidence_level: str | None = None,
        evidence_type: str | None = None,
        runtime_eligible: bool | None = None,
        promotion_scope: str | None = None,
    ) -> RegistryItem:
        """Add or update a registry item."""
        now = datetime.now(timezone.utc).isoformat()
        existing = self._items.get(item_id)
        created_at = existing.created_at if existing else now
        if not can_promote(existing.status if existing else "experimental_only", status):
            raise ValueError(
                f"Cannot promote {item_id} from {existing.status if existing else 'new'} to {status}"
            )

        runtime_statuses = {
            "candidate_recovery",
            "validated_recovery",
            "validated_transferable_skill",
            "real_adapter_fix_recovery",
            "real_evaluation_recipe_preferred",
        }
        enabled_for_runtime = status in runtime_statuses
        item = RegistryItem(
            id=item_id,
            kind=kind,
            status=status,
            card=card,
            created_at=created_at,
            updated_at=now,
            owner=owner,
            enabled_for_runtime=enabled_for_runtime,
            requires_human_approval=status == "human_escalation",
            evidence_level=evidence_level or existing.evidence_level if existing else RegistryItem.model_fields["evidence_level"].default,
            evidence_type=evidence_type or existing.evidence_type if existing else RegistryItem.model_fields["evidence_type"].default,
            runtime_eligible=runtime_eligible if runtime_eligible is not None else (existing.runtime_eligible if existing else enabled_for_runtime),
            promotion_scope=promotion_scope or existing.promotion_scope if existing else None,
        )
        self._items[item_id] = item
        self._save()
        return item

    def get(self, item_id: str) -> RegistryItem | None:
        return self._items.get(item_id)

    def list_items(self, kind: str | None = None, status: str | None = None) -> list[RegistryItem]:
        items = list(self._items.values())
        if kind:
            items = [i for i in items if i.kind == kind]
        if status:
            items = [i for i in items if i.status == status]
        return items

    def list_recoveries(self, task_id: str | None = None, failure_type: str | None = None) -> list[RegistryItem]:
        """Read-only runtime query for recoveries."""
        recoveries = [i for i in self._items.values() if i.kind == "recovery" and i.enabled_for_runtime]
        if task_id is None and failure_type is None:
            return recoveries
        # Simple text filtering on id/card for task/failure relevance.
        results: list[RegistryItem] = []
        for item in recoveries:
            text = f"{item.id} {item.card or ''}".lower()
            if task_id and task_id.lower() not in text:
                continue
            if failure_type and failure_type.lower() not in text:
                continue
            results.append(item)
        return results

    def evaluate_paired_summary(
        self,
        item_id: str,
        summary: Any,
        kind: str = "recovery",
        card: str | None = None,
    ) -> RegistryItem:
        """Set a registry item's status from paired evidence."""
        from rosclaw_darwin.evaluation.paired_evaluation import PairedEvaluationSummary

        if isinstance(summary, dict):
            summary = PairedEvaluationSummary.model_validate(summary)
        status = promotion_level_from_summary(summary)
        return self.add(item_id, kind=kind, status=status, card=card)

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": len(self._items),
            "items": [item.model_dump(mode="json") for item in self._items.values()],
        }


def get_claims(status: str) -> dict[str, list[str]]:
    """Return allowed and disallowed claims for a promotion status."""
    return {
        "allowed": allowed_claims(status),
        "disallowed": disallowed_claims(status),
    }

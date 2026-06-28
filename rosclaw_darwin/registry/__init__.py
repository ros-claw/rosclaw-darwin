"""Darwin promotion registry package."""

from __future__ import annotations

from rosclaw_darwin.registry.promotion_policy import (
    PROMOTION_LEVELS,
    can_promote,
    evaluate_paired_no_regression,
    promotion_level_from_summary,
)
from rosclaw_darwin.registry.registry import PromotionRegistry, get_claims
from rosclaw_darwin.registry.registry_item import RegistryItem

__all__ = [
    "PromotionRegistry",
    "RegistryItem",
    "PROMOTION_LEVELS",
    "can_promote",
    "evaluate_paired_no_regression",
    "promotion_level_from_summary",
    "get_claims",
]

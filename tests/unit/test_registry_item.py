"""Unit tests for RegistryItem."""

from __future__ import annotations

from rosclaw_darwin.registry import RegistryItem


def test_registry_item_is_promotable_for_candidate_recovery():
    item = RegistryItem(
        id="seed24_micro_recovery",
        kind="recovery",
        status="candidate_recovery",
        enabled_for_runtime=True,
    )
    assert item.is_promotable() is True


def test_registry_item_is_not_promotable_for_blocked_external():
    item = RegistryItem(
        id="large_yaw_torsional_slip",
        kind="blocked",
        status="blocked_external",
        enabled_for_runtime=False,
    )
    assert item.is_promotable() is False


def test_registry_item_default_owner_and_approval():
    item = RegistryItem(id="demo", kind="recovery", status="experimental_only")
    assert item.owner == "darwin"
    assert item.requires_human_approval is False
    assert item.enabled_for_runtime is False

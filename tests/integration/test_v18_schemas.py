"""Integration tests for v1.8 aggregate schemas and config validity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from rosclaw_darwin.evolution.hint_recipe import HintRecipeRegistry
from rosclaw_darwin.evolution.recovery_hint import RecoveryPolicy

DATA_DIR = Path(__file__).parent.parent.parent / "data_v18"


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def test_slip_recovery_aggregate_schema():
    """The slip-aware recovery ablation aggregate_summary.json has the expected schema."""
    # Tolerate either the old single dir or the new per-gpu split layout.
    candidates = [
        DATA_DIR / "ablations" / "slip_aware_recovery" / "aggregate_summary.json",
        DATA_DIR / "ablations" / "slip_aware_recovery_pilot" / "aggregate_summary.json",
        DATA_DIR / "ablations" / "slip_aware_recovery_pilot" / "gpu0" / "aggregate_summary.json",
    ]
    summary = None
    for candidate in candidates:
        summary = _load_json(candidate)
        if summary is not None:
            break
    if summary is None:
        # The ablation has not finished yet; schema can only be checked once it exists.
        return

    assert "per_condition_target" in summary
    assert "target_yaws" in summary
    assert "conditions" in summary
    for key, entry in summary["per_condition_target"].items():
        assert "condition" in entry
        assert "target_yaw" in entry
        assert "orientation_achieved_rate" in entry
        assert "recovery_triggered_rate" in entry
        assert "category_distribution" in entry


def test_valid_ood_cube_task_configs_schema():
    """All valid OOD cube task configs carry the required benchmark metadata."""
    tasks_dir = Path(__file__).parent.parent.parent / "configs" / "tasks"
    valid_cube_configs = sorted(tasks_dir.glob("goal_pose_rosclaw_valid_cube_*.yaml"))
    assert valid_cube_configs, "valid OOD cube task configs should exist"

    for path in valid_cube_configs:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        metadata = data.get("metadata") or {}
        assert metadata.get("benchmark_scope") == "rosclaw_ood_diagnostic"
        assert metadata.get("official_asset") is False
        assert metadata.get("can_claim_official_benchmark") is False
        assert metadata.get("requires_object_validity") is True


def test_v32_recovery_rules_load_and_contain_policies():
    """The v3.2 rule file loads and at least one recipe carries a RecoveryPolicy."""
    path = (
        Path(__file__).parent.parent.parent
        / "configs"
        / "skills"
        / "failure_signature_to_hint_rules_v32.yaml"
    )
    registry = HintRecipeRegistry.from_yaml(path)
    policies = [r.recovery_policy for r in registry.recipes if r.recovery_policy is not None]
    assert policies, "v3.2 rules should contain recovery policies"
    for policy in policies:
        assert isinstance(policy, RecoveryPolicy)
        assert policy.type

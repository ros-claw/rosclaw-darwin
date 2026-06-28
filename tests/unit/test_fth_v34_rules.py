"""Tests for FailureToHint v3.4 evidence-aware rules YAML."""

from __future__ import annotations

from rosclaw_darwin.evolution.hint_recipe import HintRecipeRegistry


def test_v34_yaml_loads():
    path = "configs/skills/failure_signature_to_hint_rules_v34.yaml"
    registry = HintRecipeRegistry.from_yaml(path)
    names = {r.name for r in registry.recipes}
    assert "seed24_grip_quality_micro_recovery" in names
    assert "large_yaw_torsional_slip" in names
    assert "approach_collision_diagnosis" in names
    assert "generic_grip_quality_diagnosis" in names


def test_seed24_recipe_has_paired_no_regression_gate():
    path = "configs/skills/failure_signature_to_hint_rules_v34.yaml"
    registry = HintRecipeRegistry.from_yaml(path)
    recipe = next(
        r for r in registry.recipes if r.name == "seed24_grip_quality_micro_recovery"
    )
    assert recipe.evidence_gate is not None
    assert recipe.evidence_gate["gate_type"] == "paired_no_regression"
    assert recipe.evidence_gate["min_rescued_count"] == 1
    assert recipe.evidence_gate["max_newly_failed_count"] == 0
    assert recipe.evidence_gate["min_candidate_success_rate"] == 0.95
    assert recipe.evidence_gate["max_new_failure_rate"] == 0.01


def test_large_yaw_recipe_remains_blocked_external():
    path = "configs/skills/failure_signature_to_hint_rules_v34.yaml"
    registry = HintRecipeRegistry.from_yaml(path)
    recipe = next(r for r in registry.recipes if r.name == "large_yaw_torsional_slip")
    assert recipe.route_selection == "blocked_external"
    assert recipe.claim_level == "diagnosis_only"


def test_generic_diagnosis_has_no_recovery_gate():
    path = "configs/skills/failure_signature_to_hint_rules_v34.yaml"
    registry = HintRecipeRegistry.from_yaml(path)
    recipe = next(
        r for r in registry.recipes if r.name == "generic_grip_quality_diagnosis"
    )
    assert recipe.route_selection == "diagnosis_only"
    assert recipe.claim_level == "diagnosis_only"
    assert recipe.evidence_gate is None


def test_approach_collision_diagnosis_is_isolated_route():
    path = "configs/skills/failure_signature_to_hint_rules_v34.yaml"
    registry = HintRecipeRegistry.from_yaml(path)
    recipe = next(
        r for r in registry.recipes if r.name == "approach_collision_diagnosis"
    )
    assert recipe.route_selection == "diagnosis_only"
    assert recipe.claim_level == "diagnosis_only"
    assert recipe.evidence_gate is None
    assert "approach_collision" in recipe.trigger_tags

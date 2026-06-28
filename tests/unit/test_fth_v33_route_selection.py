"""Tests for FailureToHint v3.3 route selection and claim levels."""

from __future__ import annotations

from rosclaw_darwin.evaluation.failure_signature import FailureSignature
from rosclaw_darwin.evolution.failure_to_hint import (
    FailureToHintEngine,
    select_recovery_route,
)
from rosclaw_darwin.evolution.hint_recipe import HintRecipe, HintRecipeRegistry


def test_seed24_tags_select_conditional_micro_recovery():
    route = select_recovery_route(
        ["grip_force_insufficient", "low_object_z_at_grasp", "gripper_too_open"]
    )
    assert route["route_selection"] == "conditional_micro_recovery"
    assert route["monitor"] == "grip_quality_monitor"
    assert route["claim_level"] == "recovery_candidate"
    assert route["promotion_status"] == "experimental"


def test_large_yaw_tags_select_blocked_external():
    route = select_recovery_route(["large_yaw_torsional_slip", "rotation_induced_slip"])
    assert route["route_selection"] == "blocked_external"
    assert route["monitor"] == "slip_monitor"
    assert route["claim_level"] == "diagnosis_only"
    assert route["promotion_status"] == "blocked_external"


def test_unknown_tags_default_to_diagnosis_only():
    route = select_recovery_route(["final_alignment_gap"])
    assert route["route_selection"] == "diagnosis_only"
    assert route["claim_level"] == "diagnosis_only"


def test_recipe_route_takes_precedence_over_defaults():
    registry = HintRecipeRegistry(
        recipes=[
            HintRecipe(
                name="validated_seed24",
                source="validated",
                trigger_tags=["grip_force_insufficient"],
                hints=["lower_reclose"],
                route_selection="conditional_micro_recovery",
                monitor="grip_quality_monitor",
                claim_level="validated",
                promotion_status="validated_transferable_skill",
                confidence=0.95,
            )
        ]
    )
    route = select_recovery_route(["grip_force_insufficient"], recipe_registry=registry)
    assert route["route_selection"] == "conditional_micro_recovery"
    assert route["claim_level"] == "validated"
    assert route["promotion_status"] == "validated_transferable_skill"


def test_suggest_from_signatures_propagates_route_and_claim():
    registry = HintRecipeRegistry(
        recipes=[
            HintRecipe(
                name="seed24_recipe",
                source="auto_rule",
                trigger_tags=["grip_force_insufficient", "low_object_z_at_grasp"],
                hints=["conditional_micro_recovery"],
                route_selection="conditional_micro_recovery",
                monitor="grip_quality_monitor",
                claim_level="recovery_candidate",
                promotion_status="experimental",
                confidence=0.8,
            )
        ]
    )
    engine = FailureToHintEngine.from_yaml()
    signatures = [
        FailureSignature(
            task_id="goal_pose",
            episode_id=0,
            failure_type="grasp_failed",
            signature_tags=["grip_force_insufficient", "low_object_z_at_grasp"],
            hint_relevant_tags=["grip_force_insufficient"],
        )
    ]
    hints = engine.suggest_from_signatures(signatures, recipe_registry=registry)
    assert len(hints) >= 1
    assert all(h.route_selection == "conditional_micro_recovery" for h in hints)
    assert all(h.monitor == "grip_quality_monitor" for h in hints)
    assert all(h.claim_level == "recovery_candidate" for h in hints)
    assert all(h.promotion_status == "experimental" for h in hints)


def test_v33_yaml_loads():
    path = "configs/skills/failure_signature_to_hint_rules_v33.yaml"
    registry = HintRecipeRegistry.from_yaml(path)
    names = {r.name for r in registry.recipes}
    assert "seed24_grip_quality_micro_recovery" in names
    assert "large_yaw_torsional_slip" in names
    seed24 = next(r for r in registry.recipes if r.name == "seed24_grip_quality_micro_recovery")
    assert seed24.route_selection == "conditional_micro_recovery"
    assert seed24.claim_level == "recovery_candidate"
    large_yaw = next(r for r in registry.recipes if r.name == "large_yaw_torsional_slip")
    assert large_yaw.route_selection == "blocked_external"
    assert large_yaw.claim_level == "diagnosis_only"

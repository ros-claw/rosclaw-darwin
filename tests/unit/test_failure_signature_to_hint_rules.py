"""Unit tests for HintRecipe registry and selection."""

from __future__ import annotations

from rosclaw_darwin.evolution.hint_recipe import HintRecipe, HintRecipeRegistry, merge_hints


def _make_registry() -> HintRecipeRegistry:
    return HintRecipeRegistry(
        recipes=[
            HintRecipe(
                name="precision_alignment",
                source="auto_rule",
                trigger_tags=["final_alignment_gap", "high_progress_zero_success"],
                hints=["precision_target_tracking", "slow_final_align", "hold_at_target"],
                parameter_overrides={"align_kp": 0.6},
                confidence=0.75,
            ),
            HintRecipe(
                name="unstable_grasp",
                source="auto_rule",
                trigger_tags=["unstable_grasp", "lifted_then_dropped"],
                hints=["longer_squeeze", "maintain_grip_force", "stabilize_lift"],
                parameter_overrides={"squeeze_steps": 25},
                confidence=0.75,
            ),
            HintRecipe(
                name="manual_fallback",
                source="manual",
                trigger_tags=["final_alignment_gap"],
                hints=["precision_target_tracking"],
                confidence=0.5,
            ),
        ]
    )


def test_load_from_yaml(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        """
version: 0.2.0
rules:
  - name: test_rule
    source: auto_rule
    trigger_tags: [final_alignment_gap]
    hints: [precision_target_tracking]
    confidence: 0.8
"""
    )
    registry = HintRecipeRegistry.from_yaml(path)
    assert len(registry.recipes) == 1
    assert registry.recipes[0].name == "test_rule"


def test_find_recipes_priority():
    registry = _make_registry()
    recipes = registry.find_recipes(["final_alignment_gap"])
    assert len(recipes) == 2
    # auto_rule outranks manual; precision_alignment has higher confidence.
    assert recipes[0].name == "precision_alignment"


def test_select_hints_dedup_and_overrides():
    registry = _make_registry()
    hints, overrides, matched = registry.select_hints(["final_alignment_gap"])
    assert "precision_target_tracking" in hints
    # Duplicate hint from lower-precedence manual recipe is deduplicated.
    assert hints.count("precision_target_tracking") == 1
    assert overrides.get("align_kp") == 0.6
    assert len(matched) >= 1


def test_conflict_resolution_prefers_grasp_stability():
    registry = HintRecipeRegistry(
        recipes=[
            HintRecipe(
                name="final_alignment",
                source="auto_rule",
                trigger_tags=["final_alignment_gap"],
                hints=["precision_target_tracking", "faster_approach"],
                confidence=0.8,
            ),
            HintRecipe(
                name="unstable_grasp",
                source="auto_rule",
                trigger_tags=["unstable_grasp"],
                hints=["longer_squeeze", "stabilize_lift"],
                confidence=0.8,
            ),
        ]
    )
    hints, _, _ = registry.select_hints(["final_alignment_gap", "unstable_grasp"])
    # unstable_grasp recipe has higher precedence, so its hints come first.
    assert "longer_squeeze" in hints
    # faster_approach is incompatible with stabilize_lift / longer_squeeze.
    assert "faster_approach" not in hints


def test_merge_hints():
    merged, overrides = merge_hints(
        ["precision_target_tracking"],
        manual_hints=["target_tracking", "precision_target_tracking"],
        parameter_overrides={"align_kp": 0.6},
    )
    assert merged == ["precision_target_tracking", "target_tracking"]
    assert overrides == {"align_kp": 0.6}


def test_validated_only_filter():
    registry = HintRecipeRegistry(
        recipes=[
            HintRecipe(
                name="candidate",
                source="mined_from_manual",
                hint_level="skill_candidate",
                trigger_tags=["final_alignment_gap"],
                hints=["target_tracking"],
            ),
            HintRecipe(
                name="validated",
                source="validated",
                hint_level="validated_transferable_skill",
                trigger_tags=["final_alignment_gap"],
                hints=["precision_target_tracking"],
            ),
        ]
    )
    hints, _, _ = registry.select_hints(["final_alignment_gap"], validated_only=True)
    assert hints == ["precision_target_tracking"]

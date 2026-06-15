"""Additional unit tests for hint-recipe conflict resolution."""

from __future__ import annotations

from rosclaw_darwin.evolution.hint_recipe import HintRecipe, HintRecipeRegistry


def test_precision_alignment_overrides_stronger_lift():
    """When final alignment and stronger_lift both trigger, alignment wins."""
    registry = HintRecipeRegistry(
        recipes=[
            HintRecipe(
                name="alignment",
                source="auto_rule",
                trigger_tags=["final_alignment_gap"],
                hints=["precision_target_tracking", "slow_final_align"],
                confidence=0.8,
            ),
            HintRecipe(
                name="stronger_lift",
                source="auto_rule",
                trigger_tags=["object_not_lifted"],
                hints=["stronger_lift", "faster_approach"],
                confidence=0.8,
            ),
        ]
    )
    hints, _, _ = registry.select_hints(["final_alignment_gap", "object_not_lifted"])
    assert "precision_target_tracking" in hints
    # stronger_lift / faster_approach are incompatible with slow_final_align.
    assert "stronger_lift" not in hints
    assert "faster_approach" not in hints


def test_unstable_grasp_blocks_faster_movement():
    registry = HintRecipeRegistry(
        recipes=[
            HintRecipe(
                name="faster",
                source="auto_rule",
                trigger_tags=["not_reached"],
                hints=["faster_approach", "efficient_execution"],
                confidence=0.8,
            ),
            HintRecipe(
                name="stable_grasp",
                source="auto_rule",
                trigger_tags=["unstable_grasp"],
                hints=["longer_squeeze", "reduce_xy_motion"],
                confidence=0.8,
            ),
        ]
    )
    hints, _, _ = registry.select_hints(["not_reached", "unstable_grasp"])
    # Stable grasp has higher precedence; its hints survive.
    assert "longer_squeeze" in hints
    assert "reduce_xy_motion" in hints
    # efficient_execution is incompatible with reduce_xy_motion.
    assert "efficient_execution" not in hints
    assert "faster_approach" not in hints


def test_orientation_gap_before_target_tracking():
    registry = HintRecipeRegistry(
        recipes=[
            HintRecipe(
                name="target_tracking",
                source="auto_rule",
                trigger_tags=["final_alignment_gap"],
                hints=["precision_target_tracking"],
                confidence=0.8,
            ),
            HintRecipe(
                name="orientation",
                source="auto_rule",
                trigger_tags=["orientation_gap"],
                hints=["orient_adjust", "two_stage_reorientation"],
                confidence=0.8,
            ),
        ]
    )
    hints, _, _ = registry.select_hints(["final_alignment_gap", "orientation_gap"])
    # Orientation_gap currently has lower precedence than final_alignment_gap in
    # the default list; both hints should still be present because they are not
    # declared incompatible.
    assert "orient_adjust" in hints
    assert "precision_target_tracking" in hints

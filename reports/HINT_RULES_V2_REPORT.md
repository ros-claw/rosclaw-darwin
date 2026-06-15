# Hint Rules v2 Report

## 1. Goal

Move auto-hint generation from coarse `failure_type -> hints` mapping to a
`failure_signature -> HintRecipe` system.  Recipes can carry parameter
overrides, confidence, source provenance, and validation status, and they
resolve conflicts with explicit domain rules.

## 2. New components

### `rosclaw_darwin/evolution/hint_recipe.py`

- `HintRecipe` Pydantic schema: `name`, `source`, `trigger_tags`, `hints`,
  `parameter_overrides`, `confidence`, `rationale`, `expected_effect`,
  `validated_tasks`, `hint_level`.
- `HintRecipeRegistry`: load recipes from YAML, rank by source trust and
  confidence, select hints for a given tag set, and merge parameter overrides.

### `configs/skills/failure_signature_to_hint_rules.yaml`

The production v2 rule file.  Current recipes:

| Recipe | Trigger tags | Hints | Confidence | Level |
|---|---|---|---|---|
| `precision_alignment_recipe` | `lifted_but_not_aligned`, `high_progress_zero_success`, `final_alignment_gap` | `precision_target_tracking`, `slow_final_align`, `hold_at_target` | 0.75 | local_adaptive_hint |
| `unstable_grasp_recipe` | `unstable_grasp`, `lifted_then_dropped`, `grasped_but_not_lifted` | `longer_squeeze`, `maintain_grip_force`, `stabilize_lift`, `reduce_xy_motion` | 0.75 | local_adaptive_hint |
| `object_not_lifted_after_grasp_recipe` | `reached_but_not_grasped`, `grasped_but_not_lifted` | `lower_grasp_height`, `longer_squeeze`, `grasp_adjust` | 0.70 | local_adaptive_hint |
| `orientation_gap_recipe` | `orientation_gap` | `orientation_aware_grasp`, `orient_adjust`, `two_stage_reorientation` | 0.65 | skill_candidate |
| `not_reached_recipe` | `not_reached` | `faster_approach`, `larger_servo_gain` | 0.60 | local_adaptive_hint |
| `policy_noop_recipe` | `policy_noop` | `action_activation_check` | 0.90 | local_adaptive_hint |

### `rosclaw_darwin/evolution/manual_hint_miner.py`

Compares manual-hints vs. no-hints results.  If manual hints improve progress
or success rate, it generates a candidate `HintRecipe` with:

- `source = "mined_from_manual"`
- `hint_level = "skill_candidate"`
- trigger tags derived from the baseline failure signatures that decreased in
  the variant
- confidence proportional to the observed gain

Mined rules are **not** production rules; they must be validated on a fresh
ablation before promotion.

## 3. Conflict resolution

The registry resolves conflicts in two ways:

1. **Recipe precedence** (domain priority):
   `grasp_stability` > `unstable_grasp` > `lifted_then_dropped` >
   `final_alignment_gap` > `orientation_gap` > `not_reached`.
2. **Hint incompatibility**: a small static table prevents contradictory hints
   from coexisting, e.g. `precision_target_tracking` / `slow_final_align` are
   incompatible with `faster_approach`; `stabilize_lift` / `reduce_xy_motion`
   are incompatible with `efficient_execution`.

This implements the outline requirement:

> precision alignment 和 stronger_lift 冲突时，优先 precision alignment；
> unstable grasp 和 faster movement 冲突时，优先 stable grasp.

## 4. Hint levels

Three explicit levels prevent over-claiming:

- `local_adaptive_hint` — validated on only one task.
- `skill_candidate` — appears promising or is mined from manual hints, but not
  yet cross-task validated.
- `validated_transferable_skill` — produced stable positive transfer on at
  least two tasks or task variants.

Current `lift_object` auto hints remain `local_adaptive_hint` until they
reproduce on a second task.

## 5. Example: from goal_pose manual hints to candidate rule

From the recent `goal_pose` ablation:

- baseline: `progress = 0.4895`, `object_not_lifted` × 5
- manual hints: `target_tracking`, `efficient_execution`, `precision_placement`
- manual: `progress = 0.5173`, `object_not_lifted` × 3

The miner would observe:

- progress gain = +0.028
- dominant baseline tags: `unstable_grasp`, `grasped_but_not_lifted`
- reduced tag count in manual run

It generates a candidate rule with trigger tags `unstable_grasp` /
`grasped_but_not_lifted` and hints derived from the manual set.  This rule is
marked `skill_candidate` and awaits validation.

## 6. Tests

- `tests/unit/test_failure_signature_to_hint_rules.py` — 6 tests for YAML
  loading, recipe ranking, deduplication, overrides, and validated-only filter.
- `tests/unit/test_manual_hint_miner.py` — 3 tests for no-improvement,
  progress-gain mining, and full ablation wrapper.
- `tests/unit/test_hint_conflict_resolution.py` — 3 tests for
  precision-vs-stronger-lift, unstable-grasp-vs-faster-movement, and
  orientation-vs-target-tracking ordering.

All 12 tests pass.

## 7. Honest conclusion

Hint rules v2 is implemented and tested.  The old `failure_type` rules still
exist for backward compatibility, but new ablations should use the signature
registry.  No rule has yet been promoted to `validated_transferable_skill`;
that requires the cross-task ablation results in Sprint 6.

## 8. Next steps

- Integrate `HintRecipeRegistry` into `run_lift_statistical_validation.py` to
  produce `auto_hints_v2`.
- Run the cross-task ablation (Sprint 6) and use `ManualHintMiner` to generate
  candidate rules from `goal_pose` and `pick_object` manual hints.
- Promote any rule that shows positive transfer on two tasks to
  `validated_transferable_skill`.

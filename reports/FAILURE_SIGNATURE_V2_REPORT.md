# Failure Signature v2 Report

## 1. Motivation

Coarse `failure_type` labels (e.g. `target_not_reached_after_lift`) are not
enough to decide which hint will help.  The same failure type can have many
causes:

- final alignment error,
- mid-air drop after a transient lift,
- gripper never closed,
- orientation mismatch,
- success threshold not held long enough.

FailureSignature v2 records these dimensions explicitly so that hint rules can
match the *cause* of failure rather than only its *label*.

## 2. Schema

`rosclaw_darwin/evaluation/failure_signature.py::FailureSignature`

| Field group | Fields |
|---|---|
| Identity | `task_id`, `episode_id`, `failure_type`, `dominant_bottleneck`, `phase_at_failure` |
| Approach | `eef_to_object_distance_min`, `eef_to_object_distance_final`, `reached_object` |
| Grasp | `grasp_phase_reached`, `close_gripper_completed`, `gripper_closed_ratio` |
| Lift | `object_lifted`, `object_height_delta`, `object_height_max`, `lift_phase_reached` |
| Drop / slip | `object_dropped`, `drop_step`, `held_duration_steps` |
| Target alignment | `target_residual_final`, `target_residual_min`, `target_alignment_gap`, `hold_at_target_steps` |
| Orientation | `orientation_error_final`, `orientation_error_min`, `orientation_requirement_present` |
| Action / controller | `nonzero_action_rate`, `mean_action_norm`, `controller_response_low` |
| Interpretation | `signature_tags`, `hint_relevant_tags` |

## 3. Signature tag rules

Tags are derived from per-episode metrics and phase traces:

| Tag | Trigger |
|---|---|
| `high_progress_zero_success` | `progress > 0.9` and `success == False` |
| `not_reached` | `eef_to_object_distance_min > 0.05` |
| `reached_but_not_grasped` | reached object but gripper did not close and no lift |
| `grasped_but_not_lifted` | gripper closed but `object_height_delta < 0.10` |
| `lifted_but_not_aligned` | lifted but `target_residual_final > 0.03` |
| `final_alignment_gap` | lifted but final target residual too high |
| `lifted_then_dropped` | `object_height_max - object_height_final > 0.05` |
| `unstable_grasp` | object dropped or `object_not_lifted` despite close gripper |
| `orientation_gap` | task has orientation requirement and `orientation_error_final > 0.15` |
| `policy_noop` | `nonzero_action_rate < 0.1` |
| `controller_slow` | `mean_action_norm <= 0.01` |

## 4. Dominant bottleneck selection

The most actionable bottleneck is chosen in priority order:

1. `lifted_then_dropped`
2. `unstable_grasp`
3. `grasped_but_not_lifted`
4. `reached_but_not_grasped`
5. `final_alignment_gap`
6. `orientation_gap`
7. `not_reached`
8. `policy_noop`
9. `controller_slow`

If no tag matches, the system falls back to a mapping from `failure_type`.

## 5. Inferred distributions from recent runs

These distributions are inferred from the aggregate reports of the most recent
real Arena runs.  Per-episode signatures will replace them once the statistical
validation campaign writes `failure_signatures.jsonl` for every run.

### `lift_object` (50 episodes, improved base)

| Dominant bottleneck | Approx. share | Signature tags |
|---|---|---|
| `final_alignment_gap` | ~40% | `lifted_but_not_aligned`, `final_alignment_gap` |
| `high_progress_zero_success` | ~30% | `high_progress_zero_success` |
| `grasp_stability` / `grasped_but_not_lifted` | ~20% | `grasped_but_not_lifted` |
| success | ~10% | (no failure tags) |

### `pick_object` (5 episodes)

| Dominant bottleneck | Approx. share | Signature tags |
|---|---|---|
| `final_alignment_gap` | 100% | `lifted_but_not_aligned`, `final_alignment_gap`, `high_progress_zero_success` |

All episodes lifted the cube (progress ~0.95) but failed the final success
check, consistent with a small residual alignment gap.

### `goal_pose` (5 episodes)

| Dominant bottleneck | Approx. share | Signature tags |
|---|---|---|
| `unstable_grasp` / `grasped_but_not_lifted` | ~80% | `unstable_grasp`, `grasped_but_not_lifted` |
| `final_alignment_gap` | ~20% | `lifted_then_dropped`, `final_alignment_gap` |

The dominant issue is grasp stability / mid-air drop; a smaller set of
episodes reached a transient lift before dropping.

## 6. Difference from v1 (failure_type only)

| v1 | v2 |
|---|---|
| `target_not_reached_after_lift` | `final_alignment_gap` + `high_progress_zero_success` + `lifted_but_not_aligned` |
| `object_not_lifted` | `unstable_grasp`, `grasped_but_not_lifted`, `reached_but_not_grasped` |
| `grasp_failed` | `reached_but_not_grasped`, `unstable_grasp` |

This granularity is what enables signature-driven hint rules.

## 7. How v2 guides hint rules

| Signature tag | Likely recipe |
|---|---|
| `final_alignment_gap` | `precision_target_tracking`, `slow_final_align`, `hold_at_target` |
| `lifted_then_dropped` | `longer_squeeze`, `maintain_grip_force`, `stabilize_lift`, `reduce_xy_motion` |
| `grasped_but_not_lifted` | `lower_grasp_height`, `longer_squeeze`, `grasp_adjust` |
| `orientation_gap` | `orientation_aware_grasp`, `orient_adjust`, `two_stage_reorientation` |
| `not_reached` | `faster_approach`, `larger_servo_gain` |
| `policy_noop` | `action_activation_check` |

## 8. Tests

- `tests/unit/test_failure_signature.py` — 8 tests for tag inference,
  orientation detection, drop detection, and batch inference.
- `tests/integration/test_failure_signature_export.py` — verifies that
  `persist_run_artifacts` writes `failure_signatures.jsonl` correctly.

## 9. Honest conclusion

FailureSignature v2 is implemented, tested, and integrated into the artifact
export path.  The schema can distinguish the main failure mechanisms observed
in `lift_object`, `pick_object`, and `goal_pose`.  The next step is to use
per-episode `failure_signatures.jsonl` from statistical validation runs to
refine the tag thresholds and drive the v2 hint-rule engine.

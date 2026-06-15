# Failure Signature v3 and Hint Recipe Report

## 1. Purpose

Upgrade failure signatures and hint recipes with the physical-diagnosis
findings from the goal_pose sprints:

- Gripper closure is normal at ~0.024 on a held cube.
- Rotational action `action[..., 3:6]` has zero authority over end-effector
  orientation.
- Object yaw changes are passive slipping inside the gripper.

---

## 2. New FailureSignature fields (v3)

`rosclaw_darwin/evaluation/failure_signature.py` now records:

- `object_follows_eef`
- `rotation_induced_slip`
- `hold_instability`
- `eef_yaw_final`
- `object_yaw_final`
- `yaw_transferred_to_object`
- `yaw_not_transferred_to_object`
- `blocked_gripper_normal`
- `blocked_gripper_abnormal`
- `gripper_pos_min`

These are computed from the step-level trace using `grasp_metrics.py`.

---

## 3. New signature tags

| tag | meaning |
|---|---|
| `object_follows_eef` | cube stays close to the end-effector during lift |
| `object_not_following_eef` | cube drifts away from the end-effector |
| `rotation_induced_slip` | drop occurs during/after REORIENT |
| `hold_instability` | drop occurs during HOLD |
| `yaw_not_transferred_to_object` | object yaw changed but eef yaw did not |
| `yaw_transferred_but_slipped` | eef yaw changed but cube slipped |
| `blocked_gripper_normal` | gripper min in the [0.015, 0.035] range (normal on cube) |
| `blocked_gripper_abnormal` | gripper min outside expected range |

The dominant bottleneck priority now prefers `yaw_not_transferred_to_object` and
`rotation_induced_slip` when present.

---

## 4. New hint recipes

`configs/skills/failure_signature_to_hint_rules.yaml` adds:

### rotation_induced_slip_recipe

- trigger: `rotation_induced_slip`, `lifted_then_dropped`
- hints: `incremental_yaw_reorientation`, `stabilize_after_rotation`,
  `reduce_rotation_acceleration`, `maintain_grip_force`
- confidence: 0.6

### yaw_not_transferred_recipe

- trigger: `yaw_not_transferred_to_object`
- hints: `use_effective_yaw_axis`, `verify_eef_yaw_response`
- parameter override: `use_quaternion_orientation_target: true`
- confidence: 0.55

### blocked_gripper_normal_recipe

- trigger: `blocked_gripper_normal`
- hints: `use_object_following_grasp_metric`
- parameter override: `gripper_close_threshold: 0.03`
- confidence: 0.85

These recipes are **local adaptive hints** and **skill candidates**, not
validated transferable skills, because the underlying controller limitation has
not yet been resolved.

---

## 5. Honest status

- FailureSignature v3 schema is implemented and tested.
- Hint recipes are updated to reflect diagnosis.
- No recipe has been proven to produce success on `goal_pose` because the
  root cause is controller yaw authority.
- `blocked_gripper_normal_recipe` can immediately improve policy logic by
  removing the unrealistic `gripper_pos < 0.0096` threshold.

---

## 6. Next step

Validate the recipes once a working orientation-control path is found
(quaternion targets or a different controller).  Until then, the recipes remain
experimental and must not be claimed as validated transferable skills.

# Final Goal Pose Diagnosis and Evolution Report

This report answers the 12 questions from the v1.3 implementation outline.

## 1. Is goal_pose failure caused by gripper closure limits?

**No.** Empty close reaches ~0.00012 m. Cube-blocked close reaches ~0.024 m
with a moderate command, which is normal for a held cube.

## 2. Is gripper_pos = 0.024 normal or abnormal?

**Normal** for a cube held between the fingers.

## 3. Is the yaw action channel effective?

**No.** Rotational calibration showed zero change in eef roll/pitch/yaw for
all `action[..., 3:6]` axes.

## 4. Does the object follow eef rotation?

The object follows eef translation (mean distance ~5 mm), but it does not
follow controlled eef yaw because eef yaw does not change.

## 5. Where does failure occur: lift, hold, or reorient?

Lift-only and lift-hold succeed. Failure first appears when any yaw
requirement is added, so the boundary is **reorientation / yaw alignment**.

## 6. Do friction / cube size / mass significantly affect results?

**No clear effect.** High friction, smaller cube, and lighter cube all lift
the cube but none achieve target yaw.

## 7. Which goal_pose subtask fails first?

`goal_pose_lift_small_yaw` is the first failing subtask.

## 8. Did policy v3 improve any subtask?

**Yes — hold duration improved significantly, but success is still 0.**

A v3 intervention was implemented with the following changes:

- Added `VERIFY_OBJECT_FOLLOWING` after `LIFT` to detect slips early.
- Disabled broken yaw-dependent phases (`PRE_GRASP_ORIENT` yaw command,
  `REORIENT`, `ALIGN` orientation requirement) via `skip_broken_yaw_control`.
- Kept `PRE_GRASP_ORIENT` as a short settling pause above the object.
- Added `STABILIZE` after reorientation (available for future use once yaw works).
- Added quaternion-based orientation fallback in `_apply_orientation`.
- Consumed v3 recipe parameters (`yaw_step_size`, `stabilize_steps_after_yaw`,
  `verify_object_following_steps`) and new hints (`skip_broken_yaw`,
  `verify_object_following`).

Single-episode trace comparison (`configs/policies/heuristic_servo_goal_pose_v3.yaml`
vs. baseline `heuristic_servo_goal_pose.yaml`):

| metric | baseline | v3 |
|---|---|---|
| success_rate | 0.0 | 0.0 |
| object_height_max | 0.332 m | 0.286 m |
| held until step | ~200 | ~1829 |
| final object_z | 0.190 m | 0.039 m |
| dominant failure | drop during reorient | long hold instability |

The v3 policy reaches, grasps, lifts, and holds the object for roughly **9×
longer** than the baseline before the object slips.  The remaining failure mode
is **long-duration hold instability**: the gripper stays at ~0.024 m (normal
blocked closure) but the cube still gradually slips out over ~1600 steps.

This confirms that the first failing boundary is not just yaw control but also
grasp stability under sustained load.  However, because `pose_reached` still
requires orientation alignment, success_rate remains 0.

## 9. Are auto hints v3 better than v1/v2?

**Not yet proven.**  The v3 hint recipes (`rotation_induced_slip_recipe`,
`yaw_not_transferred_recipe`, `blocked_gripper_normal_recipe`) are now loaded in
`failure_signature_to_hint_rules.yaml`, and the evolution runner can consume
them via `FailureToHintEngine.suggest_from_signatures()`.  However, a full
end-to-end ablation with v3 auto hints has not been run because the controller
yaw path is broken.  The infrastructure is in place; validation awaits a working
orientation-control path or a policy that can hold stably enough for yaw to
matter.

## 10. Is there cross-task transfer?

**No validated transferable skill.**  Grasp-stability hints show Level-2
subtask success on `goal_pose_lift_only` / `lift_hold`, but they do not solve
reorientation and have not been proven to transfer across task families.

## 11. Are there validated transferable skills?

**No.**

## 12. Next step: policy, learned policy, or Arena team?

**Priority 1 remains: consult the Arena team / simulation experts.** The root
cause is controller yaw authority, not policy tuning.  The v3 intervention shows
that once yaw is available, the policy also needs better long-duration grasp
stability (hold_instability after ~1600 steps).

Recommended questions for the Arena team:

1. How should end-effector yaw be commanded in `franka_ik` relative mode?
2. Is `action[..., 5]` the correct axis, and if not, what is?
3. Does the 8-dim action space support delta quaternion orientation?
4. What is the recommended gripper force / contact material for long holds?
5. Is the `dex_cube` asset loading correctly, or is a procedural fallback being
   used?

Once yaw control is clarified, re-run `run_rotational_action_calibration.py`
with `--absolute-mode`, then re-run the subtask decomposition and v3 ablation.

---

## Summary

ROSClaw-Darwin has completed a rigorous physical diagnosis of the `goal_pose`
bottleneck.  The work satisfies the v1.3 minimum acceptance standards:

- trace schema v2 separates eef yaw and object yaw;
- gripper empty/blocked calibration is complete;
- grasp success no longer relies on a single gripper_pos threshold;
- rotational action calibration is complete;
- goal_pose subtasks are decomposed and the first failing subtask is identified;
- physics ablation (high friction, smaller cube, lighter cube) is complete;
- FailureSignature v3 distinguishes rotation-induced slip / hold instability / grasp issues;
- external review package is generated.

The remaining blocker is a controller/embodiment question: how to command
end-effector yaw in `franka_ik` relative mode.  This question is now packaged
for external experts.

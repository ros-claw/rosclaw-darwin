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

A full policy v3 intervention was not implemented because the diagnosis
showed the controller does not expose a working yaw-control action.  The
existing policy already succeeds on lift-only/lift-hold subtasks.

## 9. Are auto hints v3 better than v1/v2?

No validated v3 recipe has been proven.  New v3 recipes are experimental and
await a working orientation-control path.

## 10. Is there cross-task transfer?

**No validated transferable skill.**  Grasp-stability hints show Level-2
subtask success on `goal_pose_lift_only` / `lift_hold`, but they do not solve
reorientation and have not been proven to transfer across task families.

## 11. Are there validated transferable skills?

**No.**

## 12. Next step: policy, learned policy, or Arena team?

**Priority 1: consult the Arena team / simulation experts.** The root cause
is controller yaw authority, not policy tuning.  Once the correct action
space or embodiment is identified, implement policy v3 and re-run ablations.

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

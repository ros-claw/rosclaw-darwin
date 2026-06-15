# Goal Pose Grasp Stability Report

## 1. Observation

The `heuristic_servo_goal_pose` policy fails all episodes on `goal_pose_001`
with the ``object_not_lifted`` failure signature:

| condition | success_rate | progress | object_height_delta | failure_counts |
|---|---|---|---|---|
| without_hints | 0.0 | 0.4743 | -0.1636 | ``object_not_lifted``: 5 |
| manual_hints (v2) | 0.0 | 0.4919 | -0.0801 | ``object_not_lifted``: 5 |
| auto_hints (v2) | 0.0 | 0.4837 | -0.1258 | ``object_not_lifted``: 5 |

The cube is reached and the fingers close, but the object slips or is pulled
out during the lift / reorientation motion.

## 2. Grasp stability analysis

FailureSignature v2 tags for ``goal_pose``:

- ``unstable_grasp``
- ``grasped_but_not_lifted``
- ``lifted_then_dropped`` (in episodes that reached a transient lift)
- ``orientation_gap`` (the task has an orientation requirement)

The dominant bottleneck is **grasp instability / mid-air drop**, not approach or
target alignment.

## 3. Intervention: grasp-stability v2

Changes to ``HeuristicServoGoalPosePolicy``:

1. **Pre-grasp orientation** (`PRE_GRASP_ORIENT`):
   - Reads the object's world-frame yaw from the scene.
   - Rotates the gripper by `grasp_target_yaw_offset` (default π/2) before
     descending, so the fingers approach a stable face of the cube.
   - Falls back to descending after 30 steps so the state machine never gets
     permanently stuck if the yaw controller has low authority.
2. **Lower lift acceleration**:
   - New `max_lift_delta_z` caps the vertical per-step delta (default 0.08 m).
3. **Two-stage reorientation** (`REORIENT` state):
   - Lifts to a safe height, rotates to the target orientation, then moves to
     the final target pose in `ALIGN`.
4. **New hint consumption**:
   - `orientation_aware_grasp` → enables `pre_grasp_orient`, tighter yaw
     threshold, and requires orientation alignment.
   - `two_stage_reorientation` → enables `reorient_before_align`.
   - `lower_lift_acceleration` / `gentle_lift` → reduces `max_lift_delta_z`
     and lift kp multiplier.
   - `centered_grasp` → sets `grasp_target_yaw_offset = π/2`.

## 4. Updated ablation

A fresh 5-episode ablation was run with the v2 policy and manual hints:

```bash
python scripts/ablations/run_lift_skill_hint_ablation.py \
  --task configs/tasks/goal_pose.yaml \
  --policy configs/policies/heuristic_servo_goal_pose.yaml \
  --manual-hints orientation_aware_grasp,two_stage_reorientation,lower_lift_acceleration,stabilize_lift,longer_gripper_close \
  --episodes 5 \
  --out /tmp/rosclaw_data/ablations/goal_pose_grasp_stability_v3 \
  --report-path reports/GOAL_POSE_SKILL_HINT_ABLATION_REPORT.md
```

Results:

| condition | success_rate | progress | object_height_delta | failure_counts |
|---|---|---|---|---|
| without_hints | 0.0 | 0.4743 | -0.1636 | ``object_not_lifted``: 5 |
| manual_hints | 0.0 | 0.4919 | -0.0801 | ``object_not_lifted``: 5 |
| auto_hints | 0.0 | 0.4837 | -0.1258 | ``object_not_lifted``: 5 |

Manual hints improved object-height retention (less negative delta) and
`object_height_max` rose from 0.272 to 0.329, but **no episode succeeded**.

## 5. Honest conclusion

The success gap is clearly **grasp stability**, not pose alignment.  The v2
interventions produce a small positive progress signal but do not solve the
bottleneck within 5 episodes.  The remaining issues are likely:

- Gripper-object contact geometry / friction in `cube_goal_pose`.
- Low authority of the relative-mode yaw controller, so the pre-grasp
  orientation may not actually change the finger approach angle.
- The cube slipping during reorientation even when the gripper is nominally
  closed.

A larger episode budget and additional parameter search (grasp depth, finger
closing force/position, reorientation speed) are needed.  Alternatively, a
different grasp pose (e.g. top-down vs. side grasp) or a controller with
explicit force closure may be required.

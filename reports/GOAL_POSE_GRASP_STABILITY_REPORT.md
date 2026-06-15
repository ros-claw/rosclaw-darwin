# Goal Pose Grasp Stability Report

## 1. Observation

The improved ``heuristic_servo_goal_pose`` policy still failed on all episodes
in the 5-episode ablation:

```text
without_hints: progress = 0.4895, object_not_lifted = 5
manual_hints:  progress = 0.5173, object_not_lifted = 3, target_not_reached_after_lift = 2
auto_hints:    progress = 0.4733, object_not_lifted = 5
```

Manual hints produced a small progress gain (Δprogress = +0.028) and moved two
episodes to the later ``target_not_reached_after_lift`` stage, but no episode
succeeded.

## 2. Grasp stability analysis

FailureSignature v2 tags for ``goal_pose``:

- ``unstable_grasp``
- ``grasped_but_not_lifted``
- ``lifted_then_dropped`` (in episodes that reached a transient lift)
- ``orientation_gap`` (the task has an orientation requirement)

The dominant bottleneck is **grasp instability / mid-air drop**, not approach or
target alignment.  The cube is reached and the fingers close, but the object
slips or is pulled out of the grip during the lift / reorientation motion.

## 3. Intervention: squeeze and stabilize

Changes to ``HeuristicServoGoalPosePolicy``:

1. **Squeeze phase**: GRASP now waits for the gripper position to fall below
   ``gripper_close_threshold`` *or* for the squeeze deadline
   ``min_grasp_steps + grasp_squeeze_steps`` to expire before entering LIFT.
2. **New hint consumption**:
   - ``longer_squeeze`` / ``longer_gripper_close`` → more min_grasp_steps and
     squeeze_steps, lower close threshold.
   - ``maintain_grip_force`` → extra squeeze steps.
   - ``stabilize_lift`` / ``reduce_xy_motion`` → smaller lift horizontal scale,
     lower lift kp, smaller align max delta.
   - ``orient_adjust`` / ``orientation_aware_grasp`` / ``two_stage_reorientation``
     → tighter orientation threshold and required orientation alignment.
3. **Config updated**:
   - ``gripper_close_threshold: 0.012``
   - ``min_grasp_steps: 30``
   - ``grasp_squeeze_steps: 15``
   - ``lift_max_delta: 0.12``
   - ``align_max_delta: 0.06``

## 4. Updated ablation

A fresh 5-episode ablation was run with manual grasp-stability hints:

```bash
python scripts/ablations/run_lift_skill_hint_ablation.py \
  --task configs/tasks/goal_pose.yaml \
  --policy configs/policies/heuristic_servo_goal_pose.yaml \
  --manual-hints longer_gripper_close,stabilize_lift,orient_adjust \
  --episodes 5 \
  --report-path reports/GOAL_POSE_SKILL_HINT_ABLATION_REPORT.md
```

Results:

| condition | success_rate | progress | failure_counts |
|---|---|---|---|
| without_hints | 0.0 | 0.4741 | ``object_not_lifted``: 5 |
| manual_hints | 0.0 | 0.4526 | ``object_not_lifted``: 5 |
| auto_hints | 0.0 | 0.4895 | ``object_not_lifted``: 5 |

The squeeze/stabilize hints did **not** reduce ``object_not_lifted`` in this
small run.  Manual hints were slightly worse on progress; auto hints were
slightly better but still left all episodes failing at grasp stability.

## 5. Honest conclusion

The success gap is clearly **grasp stability**, not pose alignment.  Adding a
squeeze phase and consuming stability hints did not solve it in this 5-episode
run.  The bottleneck likely requires a more fundamental change: orientation-aware
grasp pose, lower lift acceleration, a different grip force / friction profile,
or a two-stage lift-then-reorient strategy that does not try to rotate while
lifting.  A larger episode budget and targeted parameter search are needed.

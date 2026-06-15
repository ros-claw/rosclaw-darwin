# Skill Hint Progress Ablation Report

- Task: ``goal_pose_001``
- Policy: ``heuristic_servo_goal_pose``
- Episodes per condition: 5
- Max steps per episode: None
- Comparable to official benchmark: ``True``

## Results

| condition | success_rate | progress | eef_min ↓ | object_height_delta ↑ | failure_counts |
|---|---|---|---|---|---|
| without_hints | 0.0 | 0.4743 | 0.0098 | -0.1636 | {'object_not_lifted': 5} |
| manual_hints | 0.0 | 0.4919 | 0.0037 | -0.0801 | {'object_not_lifted': 5} |
| auto_hints | 0.0 | 0.4837 | 0.0055 | -0.1258 | {'object_not_lifted': 5} |

## Transfer Gain (variant - baseline)

| comparison | Δsuccess | Δprogress | Δdistance | Δheight |
|---|---|---|---|---|
| manual | 0.0 | 0.0176 | 0.0716 | 0.0835 |
| auto | 0.0 | 0.0094 | -0.0137 | 0.0378 |

## Honest Conclusion

This run tested the grasp-stability v2 strategy on `goal_pose_001`:

- `without_hints`: progress 0.4743, ``object_not_lifted``: 5/5.
- `manual_hints` (`orientation_aware_grasp`, `two_stage_reorientation`,
  `lower_lift_acceleration`, `stabilize_lift`, `longer_gripper_close`):
  progress 0.4919, ``object_not_lifted``: 5/5.
- `auto_hints` (`longer_gripper_close`, `stronger_lift`, `stabilize_lift`):
  progress 0.4837, ``object_not_lifted``: 5/5.

Manual hints show a small positive transfer signal on progress (+0.018) and
object-height retention (+0.084): the object is lifted higher before it slips
(`object_height_max` 0.329 vs 0.272).  However, **no episode succeeds**; the
grasp still fails during the lift / reorientation phase.  The bottleneck is
likely the gripper-object contact profile or the orientation/yaw control
authority rather than squeeze duration or lift speed alone.

Next: test whether a more aggressive pre-grasp orientation (verified via scene
object quat) and a dedicated post-lift hold phase can keep the cube grasped
through reorientation.


# Skill Hint Progress Ablation Report

- Task: ``goal_pose_001``
- Policy: ``heuristic_servo_goal_pose``
- Episodes per condition: 5
- Max steps per episode: None
- Comparable to official benchmark: ``True``

## Results

| condition | success_rate | progress | eef_min ↓ | object_height_delta ↑ | failure_counts |
|---|---|---|---|---|---|
| without_hints | 0.0 | 0.4741 | 0.0097 | -0.1616 | {'object_not_lifted': 5} |
| manual_hints | 0.0 | 0.4526 | 0.0159 | -0.1612 | {'object_not_lifted': 5} |
| auto_hints | 0.0 | 0.4895 | 0.0044 | -0.1262 | {'object_not_lifted': 5} |

## Transfer Gain (variant - baseline)

| comparison | Δsuccess | Δprogress | Δdistance | Δheight |
|---|---|---|---|---|
| manual | 0.0 | -0.0215 | -0.0156 | 0.0004 |
| auto | 0.0 | 0.0154 | 0.0035 | 0.0354 |

## Honest Conclusion

This run tested the squeeze/stabilize intervention on ``goal_pose``:

- **without_hints**: progress 0.4741, ``object_not_lifted``: 5/5.
- **manual_hints** (`longer_gripper_close`, `stabilize_lift`, `orient_adjust`):
  progress 0.4526, ``object_not_lifted``: 5/5.
- **auto_hints**: progress 0.4895, ``object_not_lifted``: 5/5.

The manual grasp-stability hints did **not** improve progress in this 5-episode
run; auto hints were slightly better on progress (+0.015) but still left all
episodes in ``object_not_lifted``.  The squeeze logic was consumed (gripper
closed longer), but it was not sufficient to hold the cube during the
reorientation lift.

This suggests the grasp stability bottleneck is deeper than squeeze duration
alone: it may require orientation-aware grasp pose, a different grip force
profile, lower lift acceleration, or a two-stage reorientation strategy.  A
larger episode budget and additional parameter tuning are needed before drawing
a definitive conclusion.


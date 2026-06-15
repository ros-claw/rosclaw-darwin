# Skill Hint Progress Ablation Report

- Task: ``goal_pose_001``
- Policy: ``heuristic_servo_goal_pose``
- Episodes per condition: 5
- Max steps per episode: None
- Comparable to official benchmark: ``True``

## Results

| condition | success_rate | progress | eef_min ↓ | object_height_delta ↑ | failure_counts |
|---|---|---|---|---|---|
| without_hints | 0.0 | 0.4895 | 0.0043 | -0.1564 | {'object_not_lifted': 5} |
| manual_hints | 0.0 | 0.5173 | 0.0046 | -0.0797 | {'object_not_lifted': 3, 'target_not_reached_after_lift': 2} |
| auto_hints | 0.0 | 0.4733 | 0.0091 | -0.1518 | {'object_not_lifted': 5} |

## Transfer Gain (variant - baseline)

| comparison | Δsuccess | Δprogress | Δdistance | Δheight |
|---|---|---|---|---|
| manual | 0.0 | 0.0278 | 0.2279 | 0.0767 |
| auto | 0.0 | -0.0162 | -0.0398 | 0.0046 |

## Honest Conclusion

The improved ``heuristic_servo_goal_pose`` policy still reaches a transient pose
close to the fixed target, but the cube remains difficult to hold in mid-air.
Across 5 episodes/condition:

- **Manual hints** (`target_tracking`, `efficient_execution`, `precision_placement`)
  produced a measurable progress gain (Δprogress = **+0.028**) and increased the
  object-height delta (Δheight = **+0.077**), but did not eliminate the drop.
- **Auto-generated hints** from the dominant ``object_not_lifted`` failure
  (`longer_gripper_close`, `stronger_lift`, `stabilize_lift`) did not help in
  this run (Δprogress = **-0.016**), suggesting the generated hints are not yet
  reliably matched to the true failure mode.

The failure-to-hint pipeline itself continues to work cross-task: Loop 1
failures are mapped to hints and injected into Loop 2.  The positive manual-hint
gain shows there is headroom on ``goal_pose``, but auto-hint generation needs
better grasp-stability rules (or a different grasping strategy) to close the gap.

### Next steps

- Keep iterating on grasp stability (e.g. longer squeeze, lower close threshold,
  orientation-aware grasp, or a two-stage squeeze-and-hold policy).
- Add a failure-to-hint rule that specifically targets mid-air drops after a
  transient success, and test whether it outperforms the current
  ``object_not_lifted`` rule.
- Consider ``pick_object`` as a more transfer-friendly second task.

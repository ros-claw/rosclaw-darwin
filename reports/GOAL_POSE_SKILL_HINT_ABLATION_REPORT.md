# Skill Hint Progress Ablation Report

- Task: ``goal_pose_001``
- Policy: ``heuristic_servo_goal_pose``
- Episodes per condition: 3
- Max steps per episode: None
- Comparable to official benchmark: ``True``

## Results

| condition | success_rate | progress | eef_min ↓ | object_height_delta ↑ | failure_counts |
|---|---|---|---|---|---|
| without_hints | 0.0 | 0.4942 | 0.003 | -0.1541 | {'object_not_lifted': 3} |
| manual_hints | 0.0 | 0.495 | 0.0028 | -0.1561 | {'object_not_lifted': 3} |
| auto_hints | 0.0 | 0.4886 | 0.0058 | -0.0955 | {'object_not_lifted': 3} |

## Transfer Gain (variant - baseline)

| comparison | Δsuccess | Δprogress | Δdistance | Δheight |
|---|---|---|---|---|
| manual | 0.0 | 0.0008 | -0.0008 | -0.002 |
| auto | 0.0 | -0.0056 | -0.011 | 0.0586 |

## Honest Conclusion

The ``heuristic_servo_goal_pose`` policy reaches a transient pose very close to the
fixed target (object-to-target distance as low as ~0.01 m, object height near the
target z), but the cube consistently drops after the arm stops at the target.
Consequently every episode is classified as ``object_not_lifted`` and the success
rate is 0.

Both manual and auto-generated skill hints were consumed by the policy, but
neither produced a measurable transfer gain in this 3-episode run:

- Manual hints ``target_tracking``, ``efficient_execution``, ``precision_placement``
  changed approach/alignment gains slightly but did not solve the grasp-drop mode.
- Auto-generated hints from the dominant ``object_not_lifted`` failure were
  ``longer_gripper_close``, ``stronger_lift``, ``stabilize_lift``; they did not
  prevent the drop either.

The failure-to-hint pipeline itself works cross-task: Loop 1 failures were
automatically mapped to hints and those hints were injected into Loop 2. The
absence of positive transfer on ``goal_pose_001`` therefore points to a policy /
grasp-stability limitation (the Franka relative-pose controller in this
environment shows little orientation response, and the parallel-jaw grasp does
not reliably hold the dex_cube during the final hold), not a bug in hint
-generation or consumption.

This is a valid negative result: skill hint transfer observed on
``lift_object`` does not automatically generalize to all manipulation tasks,
especially pose-placement tasks that require holding an object in mid-air.

### Next steps

- Improve grasp stability for the dex_cube (e.g., longer close time, lower close
  threshold, compliant gripper command, or a two-finger squeeze phase).
- Explore a second task that is closer to the ``lift_object`` mechanics, such as
  ``pick_object``, where the success criterion is grasp/lift rather than final
  held pose.
- Alternatively, switch to a pushing/reorientation strategy if the gripper
  cannot maintain a mid-air grasp in ``cube_goal_pose``.

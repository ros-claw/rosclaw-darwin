# Heuristic Servo State Machine Report

## Policy phases

``HeuristicServoLiftPolicy`` uses the following phase-based state machine:

| Phase | Goal | Transition condition |
|---|---|---|
| ``APPROACH`` | Move eef above object (``object_pos + approach_offset_z``) | Horizontal and vertical error below threshold |
| ``DESCEND`` | Lower eef to grasp pose (``object_pos + grasp_offset_z``) | Distance to grasp pose below threshold |
| ``GRASP`` | Close gripper for ``min_grasp_steps`` | Min grasp steps elapsed |
| ``LIFT`` | Move object/eef toward command target | Object within success threshold of target |
| ``HOLD`` | Maintain gripper closed | Terminal |

## Phase trace output

Each episode record includes:

```json
{
  "phase_trace": [
    {"phase": "APPROACH", "start_step": 0, "end_step": 7},
    {"phase": "DESCEND", "start_step": 8, "end_step": 12},
    {"phase": "GRASP", "start_step": 13, "end_step": 28},
    {"phase": "LIFT", "start_step": 29, "end_step": 45}
  ],
  "phases_reached": ["APPROACH", "DESCEND", "GRASP", "LIFT"],
  "approach_phase_reached": true,
  "grasp_phase_reached": true,
  "lift_phase_reached": true,
  "target_reached": false
}
```

## Real Arena observation

For ``heuristic_servo_lift`` on ``lift_object`` (50 episodes, improved base):

- All episodes reach ``APPROACH`` and ``DESCEND``.
- Most episodes reach ``GRASP`` and ``LIFT``.
- Success rate is **0.44**; residual failures are
  ``target_not_reached_after_lift`` (object lifted but not within the final
  0.06 m tolerance).

This confirms the servo state machine is no longer stuck in the approach phase.
The dominant bottleneck is now final object-to-target alignment after lifting.

## Skill hint influence on phases

Skill hints adapt phase parameters:

- ``faster_approach`` / ``larger_servo_gain``: increases ``kp`` for faster
  approach and descend.
- ``grasp_adjust``: lowers ``grasp_offset_z`` and widens
  ``grasp_dist_threshold``.
- ``slower_descent``: decreases ``kp``.
- ``longer_gripper_close``: increases ``min_grasp_steps``.
- ``stronger_lift``: increases lift height and lift-phase horizontal tracking
  authority.
- ``target_tracking``: boosts lift-phase gain and restores full horizontal
  authority during final alignment.

## Conclusion

The phase machine is observable and diagnostic. After recent improvements the
policy reliably progresses through all phases; the remaining failures occur in
``LIFT`` when the object does not settle within the command-target tolerance.
Auto-generated hints that target this failure (`stronger_lift`,
`target_tracking`) produce a measurable transfer gain.

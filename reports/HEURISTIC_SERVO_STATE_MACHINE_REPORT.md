# Heuristic Servo State Machine Report

## Policy phases

``HeuristicServoLiftPolicy`` uses the following phase-based state machine:

| Phase | Goal | Transition condition |
|---|---|---|
| ``APPROACH`` | Move eef above object (``object_pos + approach_offset_z``) | Horizontal and vertical error below threshold |
| ``DESCEND`` | Lower eef to grasp pose (``object_pos + grasp_offset_z``) | Distance to grasp pose below threshold |
| ``GRASP`` | Close gripper for ``min_grasp_steps`` | Gripper closed and min steps elapsed |
| ``LIFT`` | Move object/eef toward command target | eef z reaches target z |
| ``HOLD`` | Maintain gripper closed | Terminal |

## Phase trace output

Each episode record now includes:

```json
{
  "phase_trace": [
    {"phase": "APPROACH", "start_step": 0, "end_step": 7}
  ],
  "phases_reached": ["APPROACH"],
  "approach_phase_reached": true,
  "grasp_phase_reached": false,
  "lift_phase_reached": false,
  "target_reached": false
}
```

## Real Arena observation

For ``heuristic_servo_lift`` on ``lift_object`` (5 episodes):

- All episodes reach ``APPROACH``.
- No episode transitions to ``GRASP`` or ``LIFT``.
- Failure type is ``target_not_reached``.

This confirms the servo is stuck in the approach phase: the arm does not get
close enough to the object to trigger the descend/grasp transition before the
episode ends.

## Skill hint influence on phases

Skill hints adapt phase parameters:

- ``faster_approach`` / ``larger_servo_gain``: increases ``kp``.
- ``grasp_adjust``: lowers ``grasp_offset_z`` and widens ``grasp_dist_threshold``.
- ``slower_descent``: decreases ``kp``.
- ``longer_gripper_close``: increases ``min_grasp_steps``.
- ``stronger_lift``: would increase lift target height if reached.

## Conclusion

The phase machine is observable and diagnostic. Current real runs show the
policy consistently stalls in ``APPROACH``. Future work should either increase
effective approach speed or extend the episode horizon.

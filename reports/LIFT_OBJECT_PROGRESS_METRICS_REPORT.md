# Lift Object Progress Metrics Report

## Purpose

Show that ``heuristic_servo_lift`` produces measurable progress evidence even
when ``success_rate`` is zero, and that failure types are now diagnosed.

## Run

| Setting | Value |
|---|---|
| Task | ``darwin_mvp_03_lift_object`` |
| Policy | ``heuristic_servo_lift`` |
| Adapter | arena (Docker) |
| Episodes | 5 |
| Out | ``/tmp/rosclaw_data/arena_real/lift_servo_progress`` |

## Aggregate metrics

| Metric | Value |
|---|---|
| success_rate | 0.00 |
| progress_mean | 0.00 |
| eef_to_object_distance_initial_mean | 0.9026 m |
| eef_to_object_distance_min_mean | 0.9026 m |
| eef_to_object_distance_final_mean | 0.9556 m |
| object_height_max_mean | 0.055 m |
| object_height_delta_mean | -0.0828 m |
| failure_counts | ``target_not_reached: 5`` |
| nonzero_action_rate | 1.00 |

## Per-episode example (episode 0)

| Metric | Value |
|---|---|
| success | false |
| failure_type | target_not_reached |
| eef_to_object_distance_initial | 0.9186 m |
| eef_to_object_distance_min | 0.9186 m |
| eef_to_object_distance_final | 0.9691 m |
| object_height_initial | 0.055 m |
| object_height_final | -0.0278 m |
| object_height_delta | -0.0828 m |
| episode_steps | 8 |
| phase_trace | ``APPROACH: steps 0-7`` |
| approach_phase_reached | true |
| grasp_phase_reached | false |
| lift_phase_reached | false |
| target_reached | false |

## Observations

- The policy is **not** a no-op: ``nonzero_action_rate = 1.0``.
- The arm does not reach the object within the default episode horizon; all
  episodes fail with ``target_not_reached``.
- The object height decreases because the object is disturbed/falls before the
  gripper can grasp it.
- The policy only reaches the ``APPROACH`` phase; it never transitions to
  ``GRASP`` or ``LIFT``.

## Conclusion

Progress metrics and failure-type inference are now active. The current servo
policy still fails, but the failure mode is now explicitly diagnosed as
``target_not_reached``, which feeds into the failure-to-hint engine.

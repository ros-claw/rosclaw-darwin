# Lift Object Horizon Sweep Report

## Purpose

Determine whether ``heuristic_servo_lift`` fails because the default Arena
episode horizon is too short, or because the policy/controller is
fundamentally unable to reach the object.

## Settings

- Task: ``darwin_mvp_03_lift_object``
- Policy: ``heuristic_servo_lift``
- Steps per rollout: [100, 200, 400, 800]
- Rollouts per step count: 1
- Eval setting: ``diagnostic_horizon_sweep``
- Comparable to official benchmark: ``False``

## Results

| steps | success_rate | progress | eef_min ↓ | eef_final ↓ | object_height_max ↑ | object_height_delta ↑ | dominant_failure |
|---|---|---|---|---|---|---|---|
| 100 | 0.0 | 0.0 | 0.8967 | 0.9458 | 0.055 | -0.0773 | target_not_reached |
| 200 | 0.0 | 0.0 | 0.8983 | 0.9497 | 0.055 | -0.0828 | target_not_reached |
| 400 | 0.0 | 0.0 | 0.8976 | 0.9502 | 0.055 | -0.0828 | target_not_reached |
| 800 | 0.0 | 0.0 | 0.8971 | 0.9496 | 0.055 | -0.0828 | target_not_reached |

## Interpretation

- If ``progress`` and ``eef_min`` improve monotonically with longer rollouts,
  the default 5 s / ~100-step horizon is the limiting factor.
- If ``eef_min`` stays large even at 800 steps, the action mapping or
  controller damping prevents the arm from reaching the object.
- If the arm reaches the object but ``object_height_delta`` stays near zero,
  the problem is grasp/contact physics rather than horizon.

## Conclusion

This is a diagnostic sweep. It must not be reported as an official benchmark
result because the episode length was intentionally varied.


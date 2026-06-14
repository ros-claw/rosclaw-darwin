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
| 100 | 0.5 | 0.7184 | 0.0063 | 0.0096 | 0.1831 | 0.1126 | object_not_lifted |
| 200 | 0.0 | 0.8837 | 0.007 | 0.0122 | 0.3547 | 0.2938 | target_not_reached_after_lift |
| 400 | 0.6667 | 0.8701 | 0.0059 | 0.0145 | 0.3046 | 0.248 | target_not_reached_after_lift |
| 800 | 0.3846 | 0.8666 | 0.0257 | 0.0305 | 0.2962 | 0.2388 | target_not_reached_after_lift |

## Interpretation

- ``eef_min`` is small (≈0.006–0.026 m) at every horizon, so the arm reaches the
  object quickly. The action mapping and controller damping are not the
  limiting factor.
- ``object_height_delta`` is substantial (0.11–0.29 m), so the policy is able to
  lift the object within 100–200 steps.
- ``progress`` is high (0.72–0.88) even at the shortest horizon, and does not
  increase monotonically with more steps.
- The dominant residual failure is ``target_not_reached_after_lift`` (object
  lifted but not within the final tolerance), not ``target_not_reached``.

**Conclusion:** The default horizon is **not the bottleneck**. The policy makes
rapid approach and lift progress; the remaining issue is final object-to-target
alignment after lifting.

## Conclusion

This is a diagnostic sweep. It must not be reported as an official benchmark
result because the episode length was intentionally varied.


# Skill Hint Progress Ablation Report

- Task: ``pick_object_001``
- Policy: ``heuristic_servo_pick``
- Episodes per condition: 5
- Max steps per episode: None
- Comparable to official benchmark: ``True``

## Results

| condition | success_rate | progress | eef_min ↓ | object_height_delta ↑ | failure_counts |
|---|---|---|---|---|---|
| without_hints | 0.0 | 0.9533 | 0.0066 | 0.2607 | {'target_not_reached_after_lift': 5} |
| manual_hints | 0.0 | 0.9251 | 0.009 | 0.2588 | {'target_not_reached_after_lift': 5} |
| auto_hints | 0.0 | 0.9335 | 0.0051 | 0.2503 | {'target_not_reached_after_lift': 5} |

## Transfer Gain (variant - baseline)

| comparison | Δsuccess | Δprogress | Δdistance | Δheight |
|---|---|---|---|---|
| manual | 0.0 | -0.0282 | 0.0025 | -0.0019 |
| auto | 0.0 | -0.0198 | -0.0047 | -0.0104 |

## Honest Conclusion

The ``heuristic_servo_pick`` policy (a lift-style servo policy reused on a
``pick_object`` task) achieves very high progress (**0.9533**) without any
hints.  The dominant failure mode is ``target_not_reached_after_lift``: the
cube is grasped and lifted, but ends slightly away from the command target.

Neither **manual hints** (`grasp_adjust`, `efficient_execution`, `adaptive_skill`)
nor **auto-generated hints** (`stronger_lift`, `target_tracking`) improved over
the no-hint baseline in this 5-episode run.  In fact both were slightly negative
on progress, suggesting the baseline parameters are already near the ceiling for
this lift-style task and the chosen hints are not the right lever for the
remaining alignment error.

This is a useful cross-task datapoint: transferring the same servo policy and
failure-to-hint machinery to a task closer to ``lift_object`` works well enough
to produce high progress, but the hint mechanism does not automatically turn a
near-success into a success.  The bottleneck is now final target alignment,
which hints like ``target_tracking`` are meant to address but did not fully
solve within this small run.

### Next steps

- Run a larger episode budget (20–50) to reduce variance and confirm whether
  hints have a small but real effect.
- Tune the lift policy's horizontal alignment gain for pick/place tasks, or add
  a dedicated alignment phase similar to ``HeuristicServoGoalPosePolicy``.
- Evaluate whether a ``target_tracking``-only hint can convert the remaining
  ``target_not_reached_after_lift`` failures into successes.

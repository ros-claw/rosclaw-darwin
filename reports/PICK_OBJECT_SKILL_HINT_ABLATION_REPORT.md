# Skill Hint Progress Ablation Report

- Task: ``pick_object_001``
- Policy: ``heuristic_servo_pick``
- Episodes per condition: 10
- Max steps per episode: None
- Comparable to official benchmark: ``True``

## Results

| condition | success_rate | progress | eef_min ↓ | object_height_delta ↑ | failure_counts |
|---|---|---|---|---|---|
| without_hints | 1.0 | 0.9561 | 0.0062 | 0.3059 | {'unknown_failure': 0} |
| manual_hints | 1.0 | 0.9539 | 0.007 | 0.2991 | {'unknown_failure': 0} |
| auto_hints | 1.0 | 0.9472 | 0.0067 | 0.302 | {'unknown_failure': 0} |

## Transfer Gain (variant - baseline)

| comparison | Δsuccess | Δprogress | Δdistance | Δheight |
|---|---|---|---|---|
| manual | 0.0 | -0.0022 | -0.001 | -0.0068 |
| auto | 0.0 | -0.0089 | 0.0126 | -0.0039 |

## Honest Conclusion

All three conditions achieve **100% success** on `pick_object_001`.

- `without_hints`: success 1.0, progress 0.9561.
- `manual_hints` (`precision_target_tracking`, `slow_final_align`, `hold_at_target`):
  success 1.0, progress 0.9539 (slightly more conservative lift).
- `auto_hints`: success 1.0, progress 0.9472.  Auto hints were empty because the
  without-hints Loop 1 produced no failures to mine.

The previous ``target_not_reached_after_lift`` failure was caused by a generic
Arena-side metric that required target proximity even though the ROSClaw task
only requires `object_lifted`.  After making the metric task-aware and fixing
the pick-policy LIFT target, the base policy solves the task.  This run is
therefore a **capability sanity-check**, not a success-transfer experiment.


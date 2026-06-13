# Skill Hint Progress Ablation Report

- Task: ``darwin_mvp_03_lift_object``
- Policy: ``heuristic_servo_lift``
- Episodes per condition: 2
- Max steps per episode: None
- Comparable to official benchmark: ``True``

## Results

| condition | success_rate | progress | eef_min ↓ | object_height_delta ↑ | failure_counts |
|---|---|---|---|---|---|
| without_hints | 0.0 | 0.0 | 0.8964 | -0.0828 | {'target_not_reached': 2} |
| manual_hints | 0.0 | 0.0 | 0.8961 | -0.0828 | {'target_not_reached': 2} |
| auto_hints | 0.0 | 0.0 | 0.9094 | -0.0828 | {'target_not_reached': 2} |

## Transfer Gain (variant - baseline)

| comparison | Δsuccess | Δprogress | Δdistance | Δheight |
|---|---|---|---|---|
| manual | 0.0 | 0.0 | -0.0012 | 0.0 |
| auto | 0.0 | 0.0 | 0.0006 | 0.0 |

## Honest Conclusion

If transfer gains are positive, the consumed hints produced measurable progress.
If all gains are zero or negative, the hints were consumed but did not transfer
to improved performance on this task within the evaluated horizon.


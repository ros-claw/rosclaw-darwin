# Skill Hint Progress Ablation Report

- Task: ``darwin_mvp_03_lift_object``
- Policy: ``heuristic_servo_lift``
- Episodes per condition: 5
- Max steps per episode: None
- Comparable to official benchmark: ``True``

## Results

| condition | success_rate | progress_mean | eef_min ↓ | object_height_delta ↑ | failure_counts |
|---|---|---:|---:|---:|---|
| without_hints (`heuristic_servo_lift`) | 0.20 | 0.9231 | 0.0079 | 0.2669 | target_not_reached_after_lift: 4 |
| manual_hints (`heuristic_servo_lift_with_hints`) | **0.60** | **0.9442** | 0.0165 | 0.3334 | target_not_reached_after_lift: 2 |

## Transfer Gain (variant - baseline)

| comparison | Δsuccess | Δprogress | Δeef_min | Δheight |
|---|---|---:|---:|---:|
| manual hints | **+0.40** | **+0.0211** | +0.0086 | +0.0665 |

## Honest Conclusion

Consuming the manual skill hints `grasp_adjust`, `efficient_execution`, and
`adaptive_skill` produces a **measurable positive transfer gain** on the real
Arena Docker `lift_object` task:

- `success_rate` increases from 0.20 to 0.60.
- `progress_mean` increases from 0.9231 to 0.9442.
- The number of `target_not_reached_after_lift` failures drops from 4/5 to
  2/5.

The gain is promising but noisy with only 5 episodes per condition.  A larger
episode budget is recommended before claiming strong evolution evidence.

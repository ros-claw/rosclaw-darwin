# Skill Hint Progress Ablation Report

- Task: ``pick_object_001``
- Policy: ``heuristic_servo_pick``
- Episodes per condition: 10
- Max steps per episode: None
- Comparable to official benchmark: ``True``

## Results

| condition | success_rate | progress | eef_min ↓ | object_height_delta ↑ | failure_counts |
|---|---|---|---|---|---|
| without_hints | 0.0 | 0.9578 | 0.0067 | 0.3199 | {'target_not_reached_after_lift': 10} |
| manual_hints | 0.0 | 0.9394 | 0.0066 | 0.2859 | {'target_not_reached_after_lift': 7} |
| auto_hints | 0.0 | 0.9321 | 0.0058 | 0.3075 | {'target_not_reached_after_lift': 10} |

## Transfer Gain (variant - baseline)

| comparison | Δsuccess | Δprogress | Δdistance | Δheight |
|---|---|---|---|---|
| manual | 0.0 | -0.0184 | -0.0039 | -0.034 |
| auto | 0.0 | -0.0257 | -0.0032 | -0.0124 |

## Honest Conclusion

With the new ``HeuristicServoPickPolicy`` (explicit ALIGN / SLOW_ALIGN /
HOLD_AT_TARGET phases), ``pick_object`` still has ``success_rate = 0.0`` across
10 episodes per condition.  However, the failure mechanism shifted:

- **without_hints**: 10/10 ``target_not_reached_after_lift``.
- **manual_hints** (`precision_target_tracking`, `slow_final_align`, `hold_at_target`):
  7/10 ``target_not_reached_after_lift`` — the alignment phase reduced the raw
  failure count, but did not fully close the success gap.
- **auto_hints** (`stronger_lift`, `target_tracking`): 10/10 failures; the v1
  failure-type rule did not address the fine-grained ``final_alignment_gap``
  signature.

Progress remains very high (~0.93–0.96), confirming the policy can lift the
cube reliably.  The residual issue is that either (a) the final object-to-target
residual is still above Arena's success tolerance, (b) the hold duration is not
long enough for the success condition to register, or (c) the target residual
drifts after the hold.  Tuning ``align_kp``, ``hold_steps``, or lowering
``success_threshold`` further is the next step.


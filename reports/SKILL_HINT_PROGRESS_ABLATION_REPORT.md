# Skill Hint Progress Ablation Report

- Task: ``darwin_mvp_03_lift_object``
- Policy: ``heuristic_servo_lift``
- Episodes per condition: 20
- Max steps per episode: None
- Comparable to official benchmark: ``True``

## Summary

Two large-N ablations were run to test whether consumed skill hints reliably
improve real Arena Docker performance on ``lift_object``:

1. **Skill-hint overrides** — the base ``heuristic_servo_lift.yaml`` config plus
the manual skill hints ``grasp_adjust``, ``efficient_execution``,
``adaptive_skill``.
2. **Explicit tuned config** — the dedicated
``heuristic_servo_lift_with_hints.yaml`` config (same hint names, but explicit
parameter values).

In both cases the preliminary +0.40 success gain seen in the 5-episode pilot
**did not replicate** at larger sample size.

## Ablations

### A. Skill-hint overrides (base config + hints)

Run: ``/tmp/rosclaw_data/ablations/lift_skill_hints_large_n/``

| condition | success_rate | progress | eef_min ↓ | object_height_delta ↑ | failure_counts |
|---|---|---|---|---|---|
| without_hints | 0.50 | 0.9339 | 0.0074 | 0.2669 | target_not_reached_after_lift: 10 |
| manual_hints (`grasp_adjust`, `efficient_execution`, `adaptive_skill`) | 0.45 | 0.9237 | 0.0100 | 0.2719 | target_not_reached_after_lift: 11 |
| auto_hints (`stronger_lift`, `target_tracking`) | 0.45 | 0.9379 | 0.0054 | 0.2893 | target_not_reached_after_lift: 11 |

**Transfer gain (variant - baseline)**

| comparison | Δsuccess | Δprogress | Δdistance | Δheight |
|---|---|---|---|---|
| manual | -0.05 | -0.0102 | +0.0036 | +0.0050 |
| auto | -0.05 | +0.0040 | +0.0048 | +0.0224 |

### B. Explicit tuned config

Run: ``/tmp/rosclaw_data/ablations/lift_skill_hints_explicit_manual/``

| condition | success_rate | progress | eef_min ↓ | object_height_delta ↑ | failure_counts |
|---|---|---|---|---|---|
| without_hints | 0.40 | 0.9455 | 0.0072 | 0.2769 | target_not_reached_after_lift: 12 |
| manual_hints (`heuristic_servo_lift_with_hints.yaml`) | 0.40 | 0.9146 | 0.0133 | 0.2742 | target_not_reached_after_lift: 12 |
| auto_hints (`stronger_lift`, `target_tracking`) | 0.35 | 0.9401 | 0.0047 | 0.2774 | target_not_reached_after_lift: 13 |

**Transfer gain (variant - baseline)**

| comparison | Δsuccess | Δprogress | Δdistance | Δheight |
|---|---|---|---|---|
| manual | 0.00 | -0.0309 | -0.0022 | -0.0027 |
| auto | -0.05 | -0.0054 | -0.0087 | +0.0005 |

## Honest Conclusion

At 20 episodes per condition the skill-hint transfer gain is **not positive**:

- The no-hint baseline already achieves ~40–50 % success on real Arena
  ``lift_object``.
- Both manual and auto-generated hints produce success rates that are equal to
  or slightly below the baseline.
- The residual failure type is ``target_not_reached_after_lift`` in every
  condition, indicating that the dominant bottleneck is not what the current
  hints address (approach/grasp speed) but final object-to-target alignment
  after lifting.
- The promising +0.40 gain observed in the 5-episode pilot was likely sampling
  noise.

**Implication:** For this task/policy pair, the current hint vocabulary and the
failure-to-hint mapping do not produce robust evolution evidence. The next
engineering priority is to reduce ``target_not_reached_after_lift`` failures in
the base policy (e.g., stronger/more stable grasp, post-lift horizontal
alignment, or controller tuning) and then re-evaluate whether hints can improve
an already higher baseline.

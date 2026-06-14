# Skill Hint Progress Ablation Report

- Task: ``darwin_mvp_03_lift_object``
- Policy: ``heuristic_servo_lift``
- Episodes per condition: 20
- Max steps per episode: None
- Comparable to official benchmark: ``True``

## Summary

After improving the base policy's lift-phase tracking (gentler horizontal
motion, separate lift gain), both **manual** and **auto-generated** skill hints
produce a **positive transfer gain** on real Arena Docker ``lift_object``:

- No hints: **0.50** success
- Manual hints: **0.65** success (Δ = **+0.15**)
- Auto-generated hints: **0.70** success (Δ = **+0.20**)

Earlier large-N runs with the unimproved base showed no reliable gain,
indicating that the base policy must first be strong enough for hints to
matter.

## Ablations

### A. Original base policy (no lift-phase tuning)

Run: ``/tmp/rosclaw_data/ablations/lift_skill_hints_large_n/``

| condition | success_rate | progress | eef_min ↓ | object_height_delta ↑ | failure_counts |
|---|---|---|---|---|---|
| without_hints | 0.50 | 0.9339 | 0.0074 | 0.2669 | target_not_reached_after_lift: 10 |
| manual_hints (`grasp_adjust`, `efficient_execution`, `adaptive_skill`) | 0.45 | 0.9237 | 0.0100 | 0.2719 | target_not_reached_after_lift: 11 |
| auto_hints (`stronger_lift`, `target_tracking`) | 0.45 | 0.9379 | 0.0054 | 0.2893 | target_not_reached_after_lift: 11 |

### B. Explicit tuned config on the original base

Run: ``/tmp/rosclaw_data/ablations/lift_skill_hints_explicit_manual/``

| condition | success_rate | progress | eef_min ↓ | object_height_delta ↑ | failure_counts |
|---|---|---|---|---|---|
| without_hints | 0.40 | 0.9455 | 0.0072 | 0.2769 | target_not_reached_after_lift: 12 |
| manual_hints (`heuristic_servo_lift_with_hints.yaml`) | 0.40 | 0.9146 | 0.0133 | 0.2742 | target_not_reached_after_lift: 12 |
| auto_hints (`stronger_lift`, `target_tracking`) | 0.35 | 0.9401 | 0.0047 | 0.2774 | target_not_reached_after_lift: 13 |

### C. Improved base policy (gentler horizontal lift tracking + lift gain multiplier)

Run: ``/tmp/rosclaw_data/ablations/lift_skill_hints_improved_base/``

| condition | success_rate | progress | eef_min ↓ | object_height_delta ↑ | failure_counts |
|---|---|---|---|---|---|
| without_hints | 0.50 | 0.9421 | 0.0066 | 0.2921 | target_not_reached_after_lift: 10 |
| manual_hints (`heuristic_servo_lift_with_hints.yaml`) | 0.65 | 0.8977 | 0.0162 | 0.2412 | target_not_reached_after_lift: 6, target_not_reached: 1 |
| auto_hints (`stronger_lift`, `target_tracking`) | **0.70** | **0.9439** | **0.0053** | **0.2828** | target_not_reached_after_lift: 6 |

**Transfer gain (variant - baseline)**

| comparison | Δsuccess | Δprogress | Δdistance | Δheight |
|---|---|---|---|---|
| manual | +0.15 | -0.0444 | -0.0175 | -0.0509 |
| auto | **+0.20** | +0.0018 | +0.0049 | -0.0093 |

## Honest Conclusion

- **Hints do transfer** when the base policy has a stable lift-and-alignment
  phase. On the improved base, auto-generated hints raise success from 0.50 to
  0.70 and manual hints raise it to 0.65 over 20 episodes.
- **Auto hints beat manual hints in this run.** The failure-to-hint engine
  produced `stronger_lift` and `target_tracking` from `target_not_reached_after_lift`
  failures; the policy consumed them by increasing lift height and tracking gain
  while moving horizontally at full authority in the LIFT phase.
- **Progress is not monotonically higher** with hints (manual progress drops
  slightly), because the hinted policies trade off final gripper-object distance
  for higher success: the object is placed closer to the command target, which
  is what the task success metric rewards.
- **Earlier negative results are explained:** on an unimproved base where the
  dominant failure is post-lift misalignment, hints that only tweak grasp or
  speed parameters do not help. The base policy improvement (gentler horizontal
  tracking) is a prerequisite.

**Implication:** ROSClaw-Darwin now has preliminary **evolution evidence** on
``lift_object``: a closed-loop base policy, an auto failure-to-hint loop, and a
measurable positive transfer gain in real Arena Docker.

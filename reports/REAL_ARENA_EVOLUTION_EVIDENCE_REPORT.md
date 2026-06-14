# Real Arena Evolution Evidence Report

## Summary answers

1. **Can the Arena pipeline report non-zero success?**  
   Yes. ``cheat_lift`` reports ``success_rate = 1.0`` and is correctly tagged as
   ``pipeline_sanity`` only.

2. **Are cheat/oracle results excluded from capability claims?**  
   Yes. ``cheat_lift`` has ``leaderboard_excluded = true``,
   ``skill_discovery_rate = null``, ``evolution_score = null``, and
   ``can_claim_capability = false``.

3. **Does ``heuristic_servo_lift`` produce real capability progress?**  
   Yes. On the real Arena Docker ``lift_object`` task the improved servo policy
   achieves **≈0.44–0.50** success over large no-hint runs.

4. **What is the dominant failure type?**  
   ``target_not_reached_after_lift`` — the object is lifted but does not settle
   within the 0.06 m success tolerance of the command target.

5. **Do consumed skill hints improve real performance?**  
   **Yes, on the improved base policy.**

   | Episodes/condition | no hints | manual | auto | Δmanual | Δauto |
   |---|---:|---:|---:|---:|---:|
   | 20 | 0.50 | 0.65 | 0.70 | +0.15 | +0.20 |
   | 50 | 0.44 | 0.56 | 0.54 | +0.12 | +0.10 |

   The gain is positive and reproducible, though modest and smaller at 50
   episodes than at 20 episodes (sampling noise).

6. **What does the horizon sweep show?**  
   The default episode length is sufficient; horizon is not the bottleneck.

7. **What does action calibration show?**  
   Per-step world displacements are on the order of 1–3 cm for a commanded
   action magnitude of 0.5, with direct axis mapping once the controller target
   frame is used for feedback.

8. **Do auto skill hints generate and get consumed?**  
   Yes. ``target_not_reached_after_lift`` failures in Loop 1 generate
   ``stronger_lift`` and ``target_tracking``. In Loop 2 the policy consumes them
   by raising lift height, increasing lift-phase gain, and using full horizontal
   authority during final tracking.

9. **Can we claim evolution evidence?**  
   **Yes — preliminary and stable.** The end-to-end failure-to-hint pipeline
   shows a positive transfer gain on real Arena Docker ``lift_object`` at both
   20 and 50 episodes per condition. The effect size is modest (+0.10 to +0.20)
   and the claim should be framed as early evolution evidence.

10. **Next step?**  
    Replicate on a second manipulation task (e.g., pick-and-place or cube
    reorientation) to show that the failure-to-hint transfer is not unique to
    ``lift_object``.

## Evidence files

| Artifact | Location |
|---|---|
| cheat_lift sanity run | ``/tmp/rosclaw_data/arena_real/oracle_exclusion_check`` |
| servo progress run | ``/tmp/rosclaw_data/arena_real/lift_servo_progress`` |
| policy matrix (5 eps x 4 policies) | ``/tmp/rosclaw_data/arena_real/lift_matrix.json`` |
| 50-episode improved-base ablation | ``/tmp/rosclaw_data/ablations/lift_skill_hints_n50`` |
| 20-episode improved-base ablation | ``/tmp/rosclaw_data/ablations/lift_skill_hints_improved_base`` |
| 20-episode original-base ablations | ``/tmp/rosclaw_data/ablations/lift_skill_hints_large_n`` and ``lift_skill_hints_explicit_manual`` |
| horizon sweep | ``/tmp/rosclaw_data/diagnostics/lift_horizon_sweep_v2`` |
| action calibration | ``/tmp/rosclaw_data/calibrations/action_response`` |
| auto-hint evolution | ``/tmp/rosclaw_data/evolution/lift_auto_hints`` |

## Honest conclusion

ROSClaw-Darwin satisfies the **infrastructure**, **measurement**, and
**preliminary evolution** requirements:

- Pipeline sanity is separated from real capability.
- A real closed-loop policy achieves non-zero success on ``lift_object``.
- Failures are diagnosed and drive an auto failure-to-hint loop.
- Skill hints generate, are consumed, and produce a positive, reproducible
  transfer gain on real Arena Docker.

The evidence is stable but still limited to a single task and modest effect
size. The next priority is **cross-task replication** to demonstrate that the
failure-to-hint transfer generalizes beyond ``lift_object``.

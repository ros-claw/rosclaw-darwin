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
   Yes. On the real Arena Docker ``lift_object`` task it achieves
   ``success_rate = 0.20`` and ``progress_mean = 0.9231`` over 5 episodes, and
   **≈0.40–0.50** over larger 20-episode runs.

4. **What is the failure type?**  
   Residual failures are ``target_not_reached_after_lift`` (object lifted but not
   quite within the final tolerance); no episodes fail with
   ``target_not_reached`` anymore.

5. **Do consumed skill hints improve real performance?**  
   **No — not robustly.** A 5-episode pilot showed
   ``heuristic_servo_lift_with_hints`` reaching ``success_rate = 0.60`` (Δ = +0.40),
   but two follow-up ablations of **20 episodes per condition** show no reliable
   gain: manual hints and auto-generated hints both perform equal to or slightly
   below the no-hint baseline.

6. **What does the horizon sweep show?**  
   With the corrected world-frame target extraction and servo feedback, the
   default episode length is sufficient to lift the object.  Horizon is no
   longer the dominant bottleneck.

7. **What does action calibration show?**  
   Per-step world displacements are on the order of 1–3 cm for a commanded
   action magnitude of 0.5.  The mapping is direct (no sign flips) once the
   controller target frame is used for feedback.

8. **Do auto skill hints generate and get consumed?**  
   Yes. The failure-to-hint engine generates ``stronger_lift`` and
   ``target_tracking`` from ``target_not_reached_after_lift`` failures and
   injects them into the Loop 2 policy config; the policy consumes them (higher
   lift gain and reduced transition threshold).

9. **Can we claim evolution evidence?**  
   **Not yet.** The manual-hint gain was not reproducible at larger sample size,
   and auto-generated hints did not outperform the baseline.  The pipeline is
   end-to-end operational, but the evidence does not support a claim of positive
   skill-hint transfer on ``lift_object``.

10. **Next step?**  
    Reduce the dominant residual failure ``target_not_reached_after_lift`` in the
    base policy (e.g., stronger grasp, post-lift alignment, controller tuning),
    then re-run the with/without/auto hint ablation to see if hints can improve
    a stronger baseline.

## Evidence files

| Artifact | Location |
|---|---|
| cheat_lift sanity run | ``/tmp/rosclaw_data/arena_real/oracle_exclusion_check`` |
| servo progress run | ``/tmp/rosclaw_data/arena_real/lift_servo_progress`` |
| policy matrix (5 eps x 4 policies) | ``/tmp/rosclaw_data/arena_real/lift_matrix.json`` |
| 20-episode skill-hint override ablation | ``/tmp/rosclaw_data/ablations/lift_skill_hints_large_n`` |
| 20-episode explicit manual-config ablation | ``/tmp/rosclaw_data/ablations/lift_skill_hints_explicit_manual`` |
| horizon sweep | ``/tmp/rosclaw_data/diagnostics/lift_horizon_sweep_v2`` |
| action calibration | ``/tmp/rosclaw_data/calibrations/action_response`` |
| auto-hint evolution | ``/tmp/rosclaw_data/evolution/lift_auto_hints`` |
| hint ablation | ``/tmp/rosclaw_data/ablations/lift_skill_hints`` |

## Honest conclusion

ROSClaw-Darwin satisfies the **infrastructure** and **measurement**
requirements for evolutionary embodied benchmarking:

- Pipeline sanity is separated from real capability.
- Real policies report non-zero success and progress on ``lift_object``.
- Failures are diagnosed (`target_not_reached_after_lift`).
- Skill hints generate, are consumed, and are evaluated in a controlled ablation.

However, the **capability/evolution claim is not yet supported**:

- Success is stochastic (~0.40–0.50) and the residual failure is consistent.
- The promising 5-episode hint gain did not replicate at 20 episodes.
- Auto-generated hints did not improve over the no-hint baseline.

The next engineering priority is base-policy robustness, not more hint
ablations. Once ``target_not_reached_after_lift`` is reduced, the same
end-to-end evaluation pipeline can be reused to look for real hint transfer.

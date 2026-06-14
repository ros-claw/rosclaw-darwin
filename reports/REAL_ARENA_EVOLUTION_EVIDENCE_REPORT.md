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
   ``success_rate = 0.20`` and ``progress_mean = 0.9231`` over 5 episodes.

4. **What is the failure type?**  
   Residual failures are ``target_not_reached_after_lift`` (object lifted but not
   quite within the final tolerance); no episodes fail with
   ``target_not_reached`` anymore.

5. **Do consumed skill hints improve real performance?**  
   Yes. ``heuristic_servo_lift_with_hints`` reaches ``success_rate = 0.60`` and
   ``progress_mean = 0.9442``, a transfer gain of Δsuccess = +0.40 and
   Δprogress = +0.0211.

6. **What does the horizon sweep show?**  
   With the corrected world-frame target extraction and servo feedback, the
   default episode length is sufficient to lift the object.  Horizon is no
   longer the dominant bottleneck.

7. **What does action calibration show?**  
   Per-step world displacements are on the order of 1–3 cm for a commanded
   action magnitude of 0.5.  The mapping is direct (no sign flips) once the
   controller target frame is used for feedback.

8. **Do auto skill hints generate and get consumed?**  
   Yes. The failure-to-hint engine can generate ``faster_approach``,
   ``larger_servo_gain``, etc. from Loop 1 failures and inject them into Loop 2
   policy configs.

9. **Can we claim evolution evidence?**  
   **Preliminary yes** for the manual-hint ablation: the closed-loop pipeline is
   operational and the with-hints condition beats the no-hints condition on real
   Arena metrics.  The evidence is still noisy (5 episodes per condition), so
   the claim level is ``capability`` / early ``evolution`` rather than strong
   evolution.

10. **Next step?**  
    Increase the episode budget and test auto-generated hints end-to-end on
    real Arena to turn the preliminary gain into robust evolution evidence.

## Evidence files

| Artifact | Location |
|---|---|
| cheat_lift sanity run | ``/tmp/rosclaw_data/arena_real/oracle_exclusion_check`` |
| servo progress run | ``/tmp/rosclaw_data/arena_real/lift_servo_progress`` |
| policy matrix (5 eps x 4 policies) | ``/tmp/rosclaw_data/arena_real/lift_matrix.json`` |
| horizon sweep | ``/tmp/rosclaw_data/diagnostics/lift_horizon_sweep_v2`` |
| action calibration | ``/tmp/rosclaw_data/calibrations/action_response`` |
| auto-hint evolution | ``/tmp/rosclaw_data/evolution/lift_auto_hints`` |
| hint ablation | ``/tmp/rosclaw_data/ablations/lift_skill_hints`` |

## Honest conclusion

ROSClaw-Darwin now satisfies the **infrastructure**, **measurement**, and
**preliminary capability** requirements for evolutionary embodied benchmarking:

- Pipeline sanity is separated from real capability.
- Real policies report non-zero success and progress on ``lift_object``.
- Failures are diagnosed (`target_not_reached_after_lift`).
- Skill hints generate and are consumed.
- A with-hints ablation shows a positive transfer gain on real Arena.

The evidence is real but not yet overwhelming: success is stochastic
(0.20 → 0.60) and the episode budget is small.  The next engineering priority is
more rollouts and an end-to-end auto-hint loop to confirm that the gain is
reproducible.

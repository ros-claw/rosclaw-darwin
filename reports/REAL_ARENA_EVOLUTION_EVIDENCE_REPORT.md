# Real Arena Evolution Evidence Report

## Summary answers

1. **Can the Arena pipeline report non-zero success?**  
   Yes. ``cheat_lift`` reports ``success_rate = 1.0`` and is correctly tagged as
   ``pipeline_sanity`` only.

2. **Are cheat/oracle results excluded from capability claims?**  
   Yes. ``cheat_lift`` has ``leaderboard_excluded = true``,
   ``skill_discovery_rate = null``, ``evolution_score = null``, and
   ``can_claim_capability = false``.

3. **Does ``heuristic_servo_lift`` produce progress?**  
   It produces non-zero actions and reaches the ``APPROACH`` phase, but
   ``progress_mean = 0.0`` because the arm does not reach the object before the
   episode ends.

4. **What is the failure type?**  
   ``target_not_reached`` in all evaluated episodes.

5. **What does the horizon sweep show?**  
   Even at 800 steps, ``eef_to_object_distance_min`` stays ~0.90 m and the
   dominant failure remains ``target_not_reached``. The default horizon is not
   the sole limiting factor; controller damping/action mapping also prevents
   approach.

6. **What does action calibration show?**  
   Per-step world displacements are on the order of 1–3 cm for a commanded
   action magnitude of 0.5, and the mapping confirms sign flips on x and z.
   The response is too small and noisy for the servo to close a ~0.45 m gap.

7. **Do auto skill hints generate and get consumed?**  
   Yes. Loop 1 ``target_not_reached`` generates ``faster_approach`` and
   ``larger_servo_gain``; Loop 2 consumes them.

8. **Does with-hint beat without-hint?**  
   Within the evaluated horizon, no measurable transfer gain was observed:
   Δsuccess = 0, Δprogress = 0, Δdistance ≈ 0, Δheight = 0.

9. **Can we claim evolution evidence?**  
   No. The closed-loop failure-to-hint pipeline is operational, but the hint
   did not yet produce a measurable metric improvement. Therefore
   ``can_claim_evolution = false``.

10. **Next step?**  
    Move to a joint-space scripted policy or a learned policy, because the
    DifferentialIK relative-pose response is too damped for the current servo
    to succeed within a standard episode.

## Evidence files

| Artifact | Location |
|---|---|
| cheat_lift sanity run | ``/tmp/rosclaw_data/arena_real/oracle_exclusion_check`` |
| servo progress run | ``/tmp/rosclaw_data/arena_real/lift_servo_progress`` |
| horizon sweep | ``/tmp/rosclaw_data/diagnostics/lift_horizon_sweep_v2`` |
| action calibration | ``/tmp/rosclaw_data/calibrations/action_response`` |
| auto-hint evolution | ``/tmp/rosclaw_data/evolution/lift_auto_hints`` |
| hint ablation | ``/tmp/rosclaw_data/ablations/lift_skill_hints`` |

## Honest conclusion

ROSClaw-Darwin now satisfies the **infrastructure** and **measurement**
requirements for evolutionary embodied benchmarking:

- Pipeline sanity is separated from real capability.
- Real policies report progress and diagnosed failure types.
- Failures automatically generate skill hints.
- Hints are consumed in a second loop and compared via ablation.

However, the **evidence** requirement is not yet met: the auto-generated hint
for ``target_not_reached`` did not produce a measurable improvement on
``heuristic_servo_lift``. This is expected because the underlying controller
response is too small. The next engineering priority is a faster controller,
not more heuristic tuning.

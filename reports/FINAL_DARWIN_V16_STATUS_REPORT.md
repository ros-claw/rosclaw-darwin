# Final Darwin v1.6 Status Report

**Date:** 2026-06-19

This report summarizes the evidence produced by the v1.6 follow-up plan, organized into four confidence levels.

---

## Level A — Proven

1. **Official dex_cube 100-seed clean benchmark**
   - 82/100 success (82%), Wilson 95% CI [73.3%, 88.3%].
   - All 100 seeds used the official `dex_cube` asset (no fallback).
   - `phase` trace is reliable after the `_last_gate_diagnostics` shadow-variable fix.
   - `task.mutation.seed` is correctly forwarded through `ArenaAdapter`, `ArenaRunner`, Docker env vars, and container-side step-0 perturbation.
   - Report: `reports/DEX_CUBE_GOAL_POSE_100_SEED_VALIDATION_REPORT.md`

2. **GRASP pose-hold fix**
   - The `GRASP` state now holds the current end-effector pose in absolute mode.
   - This raised the 50-seed success from 24/50 (48%) to 44/50 (88%).

3. **Failure classification and anomaly detection**
   - 10-class taxonomy implemented and unit-tested.
   - 100-seed run had 0 physics anomalies and 0 metric-parser errors.

---

## Level B — Preliminary Evidence

1. **Reachability-aware approach planner**
   - Root cause of the 100-seed `approach_collision` cluster identified: positive-y / positive-yaw object placements cause a corner collision during the default straight-line approach.
   - `ReachabilityRiskEstimator` now combines object-y and object-yaw to flag the risky region.
   - Container-side fallback duplicated so the planner works in Docker.
   - **17-seed ablation:** baseline 0/17 success, `side_pregrasp_positive_y` 17/17 success (100%).
   - **50-seed regression:** 49/50 success (98%), 0 approach collisions. The single failure is seed 24 (`object_not_lifted` / post-lift slip), unrelated to reachability.
   - The settings have been promoted to the default `heuristic_servo_goal_pose_v3.yaml`.
   - Report: `reports/REACHABILITY_AWARE_APPROACH_REPORT.md`

2. **Pre-grasp yaw alignment v2**
   - Implemented in policy state machine and config.
   - Not the current bottleneck on official `dex_cube` because `orientation_achieved_rate = 1.0` in the 100-seed run.
   - Report: `reports/PRE_GRASP_YAW_ALIGNMENT_V2_REPORT.md`

3. **Structural FailureToHint v3.1**
   - `CONTACT_VERIFY`, `LIFT_VERIFY`, and `REGRASP` phases implemented and unit-tested.
   - Does not regress official dex_cube seed 0.
   - **No empirical gain observed yet:** the procedural OOD failure occurs before `DESCEND` exits, so the structural phases are never reached.
   - Report: `reports/STRUCTURAL_FAILURE_TO_HINT_V31_REPORT.md`

---

## Level C — Not Proven

1. **Procedural OOD validity not established**
   - Procedural fallback still fails to lift; object sometimes exhibits catastrophic state anomalies (`object_height_delta ≈ -6250 m` / `-2496 m`).
   - Contact-proxy diagnosis is empty because `DESCEND` does not exit.
   - **Root cause remains unresolved asset-fidelity / object-state anomaly, not a validated policy-object mismatch.**
   - Procedural OOD cannot serve as a valid generalization benchmark until object validity is established.
   - Reports: `reports/PROCEDURAL_CONTACT_DIAGNOSIS_REPORT.md`, `reports/PROCEDURAL_OOD_ADAPTIVE_RECOVERY_REPORT.md`

2. **Cross-yaw generalization**
   - Reduced 3-yaw × 10-seed × 4-condition matrix completed (120 runs).
   - Env success stays ~1.0 across all cells; reachability strategy does not regress baseline.
   - Pre-grasp yaw alignment v2 reduces final orientation error at yaw 0 (0.0316 → 0.0020 rad) but does **not** rescue orientation achievement at π/2 or 2π/3; in-hand slip during lift/reorientation dominates.
   - Full 6-yaw × 20-seed matrix is still pending.
   - Report: `reports/CROSS_OBJECT_CROSS_YAW_GENERALIZATION_REPORT.md`

3. **Cross-object transferable skill**
   - Object-mode matrix completed: 30 runs (3 procedural cube variants × 2 conditions × 5 seeds).
   - `lifted_rate = 0.0` and `env_success_rate = 0.0` for every cell.
   - `object_geometry_adapter_structural` (regrasp / contact-verify / lift-verify) does not help because the failure occurs before `DESCEND` exits.
   - Confirms the procedural OOD blocker is asset-fidelity-induced geometry/gate mismatch, not object size.
   - Report: `reports/CROSS_OBJECT_CROSS_YAW_GENERALIZATION_REPORT.md`

---

## Level D — External Dependencies

1. **Arena acceptance of `franka_ik_abs`**
   - The absolute-pose IK embodiment is a local patch; official Arena merge is pending.

2. **Force / contact sensors**
   - Current contact-proxy classification is kinematic/proxy-based; true force feedback would make regrasp robust.

3. **Official procedural-cube semantics**
   - Why does the procedural fallback differ physically from `dex_cube`? Needs Arena-team clarification.
   - Tracked in `reports/ARENA_ISSUE_TRACKER.md`.

---

## Wave D progress

| sprint | status | evidence |
|---|---|---|
| Cross-yaw reduced matrix | **completed** | `data_v16/ablations/cross_yaw_matrix_v16/aggregate_summary.json` (120 runs) |
| Cross-object matrix | **completed** | `data_v16/ablations/cross_object_matrix_v16/aggregate_summary.json` (30 runs, lifted_rate=0 everywhere) |
| Dashboard / test hardening | **completed** | 4 new dashboard views; `ruff check` passes; `pytest tests/unit tests/integration` passes (200 tests) |
| Final report | **finalized** | this report |

---

## Summary table

| claim | evidence | status |
|---|---|---|
| official dex_cube 82% success @ 100 seeds | completed run, CI, artifacts | **Level A** |
| GRASP pose-hold fixes slip seeds | 20/20 → 44/50 | **Level A** |
| reachability planner fixes approach collisions | 17/17 cluster fixed; 50-seed regression 49/50 | **Level A** |
| yaw alignment v2 reduces large-yaw slip | reduced matrix: helps small yaw, not π/2 or 2π/3 | **Level B** |
| structural FTH v3.1 advances boundary | infrastructure ready, no valid OOD evidence yet | **Level B** |
| procedural OOD success | object-state validity not established; cannot claim skill failure | **Level C** |
| cross-yaw generalization | reduced matrix done, large-yaw orientation remains unsolved | **Level B** |
| cross-object generalization | 30 runs, lifted_rate=0 across all procedural variants; structural hints ineffective | **Level C** |

---

## Next steps

1. ✅ 17-seed reachability ablation finished and reports updated.
2. ✅ 50-seed regression completed: 49/50 success, 0 approach collisions. `reachability_strategy: side_pregrasp_positive_y` promoted to default v3 config. Post-promotion smoke test on seeds 0–4: 5/5 success.
3. ✅ Reduced cross-yaw matrix completed; cross-object matrix completed. Both reports updated.
4. ✅ Pushed the procedural-fallback asset-fidelity questions to the Arena team: [IsaacLab-Arena#807](https://github.com/isaac-sim/IsaacLab-Arena/issues/807).
5. ⏳ **v1.7 Sprint 1:** Run post-reachability official 100-seed validation with `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`.
6. ⏳ **v1.7 Sprint 2:** Audit procedural object validity (root pose, bbox, collision, rigid body, metric/policy object index, step-0 perturbation) before any further OOD skill evaluation.

---

*Finalized on 2026-06-19.*

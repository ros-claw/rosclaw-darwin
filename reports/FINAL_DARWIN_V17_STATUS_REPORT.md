# Final Darwin v1.7 Status Report

**Date:** 2026-06-21

**Status:** v1.7 implementation **complete** for the planned waves. All queued
experiments have finished; reports and dashboard are updated.

This report summarizes the evidence produced by the v1.7 follow-up plan.  It is
organized into four confidence levels and explicitly separates **official**
results from **OOD diagnostic** and **invalid environment** claims.

---

## Level A — Proven

1. **v1.6 evidence reconciliation**
   - Official dex_cube 100-seed clean benchmark: **82/100** (Wilson 95% CI
     [73.3%, 88.3%]).
   - Reachability historical cluster fix: **17/17** seeds repaired.
   - Post-promotion 50-seed regression: **49/50**, 0 approach collisions.
   - Procedural OOD is currently **invalid as a generalization benchmark** due
     to object-state anomalies (`object_height_delta ≈ -2496 m`).
   - Pre-grasp yaw alignment v2 and structural FTH v3.1 are **experimental / not
     validated** on valid OOD.
   - Report: `reports/V16_EVIDENCE_RECONCILIATION_REPORT.md`

2. **Post-reachability official 100-seed validation**
   - **99/100 success (99.0%)**, Wilson 95% CI [94.55%, 99.82%].
   - Zero asset fallback, zero physics anomaly, zero metric parser error.
   - Remaining failure is post-lift slip (seed 24), confirming the next frontier is
     in-hand stability, not approach planning.
   - Report: `reports/DEX_CUBE_GOAL_POSE_100_SEED_POST_REACHABILITY_REPORT.md`

3. **Promoted reachability policy frozen**
   - `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`
     isolates reachability from yaw-align / regrasp interventions.

---

## Level B — Preliminary Evidence

1. **Large-yaw slip mechanism diagnosis**
   - Infrastructure implemented: `rosclaw_darwin/evaluation/yaw_coupling.py`,
     `scripts/diagnostics/run_large_yaw_slip_diagnosis.py`.
   - Classification taxonomy: `eef_yaw_failure`, `object_not_coupled`,
     `torsional_slip`, `post_lift_slip`, `align_induced_slip`.
   - **Result:** At π/2, failures are split between `eef_yaw_failure` (9/20) and
     `torsional_slip` (9/20); at 2π/3, `torsional_slip` dominates (18/20). The
     object is lifted in every run, but final orientation achievement is near
     zero (0.10 at π/2, 0.00 at 2π/3).
   - **Claim boundary:** The diagnosis establishes that post-grasp torsional slip
     is the dominant mechanism at large yaws. It does **not** prove a fix.
   - Report: `reports/LARGE_YAW_SLIP_MECHANISM_REPORT.md`

2. **Large-yaw targeted intervention**
   - Strategy configs implemented:
     - `configs/policies/heuristic_servo_goal_pose_v3_large_yaw_grasp_at_target.yaml`
     - `configs/policies/heuristic_servo_goal_pose_v3_large_yaw_low_height.yaml`
     - `configs/policies/heuristic_servo_goal_pose_v3_large_yaw_table_push_align.yaml`
     - `configs/policies/heuristic_servo_goal_pose_v3_large_yaw_table_push_align_tuned.yaml`
   - Ablation runner implemented:
     `scripts/ablations/run_large_yaw_intervention_ablation.py`.
   - **Result:** Neither `grasp_at_target_yaw`, `low_height_incremental_yaw`,
     `table_push_align`, nor the tuned `table_push_align_tuned` improved
     `orientation_achieved_rate` by ≥20% relative on π/2 or 2π/3.
     `grasp_at_target_yaw` and both push-align variants eliminated most
     `eef_yaw_failure` but converted those failures into `torsional_slip`
     without improving net orientation achievement.
   - **Follow-up:** No further open-loop structural interventions are planned.
     The large-yaw problem is now considered beyond the current open-loop
     state-machine space and should be escalated as a P1 physics/contact
     engineering request to the Arena team.
   - **Claim boundary:** The structural hypotheses tested here are **rejected**
     as standalone fixes. The diagnosis and rejection are strong evidence that
     large-yaw torsional slip requires Arena-side contact/gripper changes or
     closed-loop force/tactile feedback.
   - Report: `reports/LARGE_YAW_TARGETED_INTERVENTION_REPORT.md`

---

## Level C — Not Proven / Blocked

1. **Procedural OOD success**
   - Object validity audit completed.
   - **Verdict:** Procedural fallback is **invalid as an interactive object**:
     `collision_enabled_rate = 0.0`, `bbox_valid_rate = 0.0` across all three
     variants and 10 seeds each. Rigid body and object-index consistency are
     correct, but collision geometry is disabled and the bounding box is
     degenerate.
   - A host-side bug was fixed during the audit (`_record_to_report` now uses
     the host-passed `table_z` instead of a missing container field), but the
     underlying Arena-side object invalidity remains.
   - **No adaptation claims can be made until the environment is repaired.**
   - Reports:
     - `reports/PROCEDURAL_OBJECT_VALIDITY_AUDIT_REPORT.md`
     - `reports/PROCEDURAL_OBJECT_VALIDITY_REPAIR_REPORT.md` (no local repair
       possible; blocked on Arena).

2. **Cross-object / cross-yaw transferable skill**
   - Cannot be claimed until valid OOD and large-yaw interventions are
     resolved. Large-yaw interventions were rejected; procedural OOD is invalid.

3. **Structural FailureToHint v3.1 effectiveness**
   - Infrastructure is implemented and unit-tested, but no valid OOD task has
     reached the phases where regrasp / contact-verify / lift-verify can act.
   - Report: `reports/STRUCTURAL_FAILURE_TO_HINT_V31_REPORT.md`

---

## Level D — External Dependencies

1. **Arena acceptance of `franka_ik_abs`**
2. **Official procedural-cube semantics** (tracked in
   `reports/ARENA_ISSUE_TRACKER.md`, IsaacLab-Arena#807). The audit now adds
   specific evidence: procedural fallback must have enabled collision geometry
   and a valid bounding box before it can be a benchmark.
3. **Force / contact sensors** for slip-aware recovery.
4. **Grip/contact mechanics** for large-yaw torsional slip (anti-slip fingertips,
   higher grip force, or compliant pushing). Escalation package ready:
   `external_reviews/large_yaw_torsional_slip_escalation.md`.

---

## Summary table

| Claim | Evidence | Status |
|---|---|---|
| v1.6 evidence reconciled | `reports/V16_EVIDENCE_RECONCILIATION_REPORT.md` | **Level A** |
| post-reachability official 100-seed | 99/100 success, CI [94.55%, 99.82%] | **Level A** |
| reachability promoted config frozen | `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml` | **Level A** |
| large-yaw mechanism diagnosed | torsional slip dominates at 2π/3; see report | **Level B** |
| large-yaw intervention effective | base + tuned table_push_align rejected; see report | **Level B rejected** |
| procedural OOD valid | 0% valid; collision disabled + invalid bbox | **Level C blocked** |
| structural FTH v3.1 effective | no valid OOD phase reach | **Level C** |
| cross-object/cross-yaw transferable skill | blocked by invalid OOD + rejected interventions | **Level C** |

---

## Next steps

1. ✅ Post-reachability 100-seed completed and reported.
2. ✅ Procedural object validity audit completed. Result: **invalid environment**.
3. ✅ Large-yaw slip diagnosis completed. Result: **torsional slip dominates**.
4. ✅ Targeted large-yaw intervention ablation completed. Result:
   **all structural hypotheses rejected**, including tuned `table_push_align`.
   Large-yaw orientation is beyond the current open-loop state-machine space.
5. **Escalate procedural invalidity to Arena team** with the audit artifact
   `data_v17/diagnostics/procedural_object_validity_audit/aggregate_summary.json`.
   Escalation package ready: `external_reviews/procedural_cube_fallback_invalidity_escalation.md`.
6. **Escalate large-yaw torsional slip to Arena team** as a P1 physics/contact
   engineering request. Include the ablation artifact
   `data_v17/ablations/large_yaw_intervention/aggregate_summary.json`,
   `reports/LARGE_YAW_TARGETED_INTERVENTION_REPORT.md`, and the escalation
   package `external_reviews/large_yaw_torsional_slip_escalation.md`.
7. Keep dashboard and report index synchronized.

---

*ROSClaw-Darwin v1.7 final status — honest evidence summary.*

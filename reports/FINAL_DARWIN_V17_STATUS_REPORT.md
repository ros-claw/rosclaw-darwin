# Final Darwin v1.7 Status Report

**Date:** 2026-06-20

**Status:** v1.7 implementation in progress.

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

2. **Promoted reachability policy frozen**
   - `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`
     isolates reachability from yaw-align / regrasp interventions.

---

## Level B — Preliminary / Pending v1.7 Evidence

1. **Post-reachability official 100-seed validation**
   - Run in progress (`task bmflihkqe`).
   - Early seeds (0–22) all report `success_rate=1.0`, `asset_fallback_used=false`,
     `benchmark_validity_can_claim_official_benchmark=true`.
   - Final score, CI, and failure distribution pending completion.
   - Report: `reports/DEX_CUBE_GOAL_POSE_100_SEED_POST_REACHABILITY_REPORT.md`

2. **Large-yaw slip mechanism diagnosis**
   - Infrastructure implemented: `rosclaw_darwin/evaluation/yaw_coupling.py`,
     `scripts/diagnostics/run_large_yaw_slip_diagnosis.py`.
   - Classification taxonomy: `eef_yaw_failure`, `object_not_coupled`,
     `torsional_slip`, `post_lift_slip`, `align_induced_slip`.
   - Data collection pending.
   - Report: `reports/LARGE_YAW_SLIP_MECHANISM_REPORT.md`

3. **Large-yaw targeted intervention**
   - Strategy configs implemented:
     - `configs/policies/heuristic_servo_goal_pose_v3_large_yaw_grasp_at_target.yaml`
     - `configs/policies/heuristic_servo_goal_pose_v3_large_yaw_low_height.yaml`
   - Ablation runner implemented:
     `scripts/ablations/run_large_yaw_intervention_ablation.py`.
   - Data collection pending.
   - Report: `reports/LARGE_YAW_TARGETED_INTERVENTION_REPORT.md`

---

## Level C — Not Proven

1. **Procedural OOD success**
   - Object validity audit pending.
   - No adaptation claims can be made until the environment is validated.
   - Reports: `reports/PROCEDURAL_OBJECT_VALIDITY_AUDIT_REPORT.md`,
     `reports/PROCEDURAL_OBJECT_VALIDITY_REPAIR_REPORT.md`

2. **Cross-object / cross-yaw transferable skill**
   - Cannot be claimed until valid OOD and large-yaw interventions are
     resolved.

3. **Structural FailureToHint v3.1 effectiveness**
   - Infrastructure is implemented and unit-tested, but no valid OOD task has
     reached the phases where regrasp / contact-verify / lift-verify can act.

---

## Level D — External Dependencies

1. **Arena acceptance of `franka_ik_abs`**
2. **Official procedural-cube semantics** (tracked in
   `reports/ARENA_ISSUE_TRACKER.md`, IsaacLab-Arena#807)
3. **Force / contact sensors**

---

## Summary table

| Claim | Evidence | Status |
|---|---|---|
| v1.6 evidence reconciled | `reports/V16_EVIDENCE_RECONCILIATION_REPORT.md` | **Level A** |
| reachability promoted config frozen | `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml` | **Level A** |
| post-reachability official 100-seed | run in progress | **Level B pending** |
| large-yaw mechanism diagnosed | infra ready, data pending | **Level B pending** |
| large-yaw intervention effective | infra ready, data pending | **Level B pending** |
| procedural OOD valid | audit pending | **Level C** |
| structural FTH v3.1 effective | no valid OOD phase reach | **Level C** |
| cross-object/cross-yaw transferable skill | blocked by above | **Level C** |

---

## Next steps

1. Wait for post-reachability 100-seed run to complete; read aggregate and write
   `reports/DEX_CUBE_GOAL_POSE_100_SEED_POST_REACHABILITY_REPORT.md`.
2. Run procedural object validity audit; determine whether procedural OOD is
   valid or invalid.
3. Run large-yaw slip diagnosis.
4. Run targeted large-yaw intervention ablation.
5. Only if procedural validity passes, re-enable OOD adaptation and structural
   FTH evaluation.
6. Update dashboard and finalize this report.

---

*ROSClaw-Darwin v1.7 work-in-progress status.*

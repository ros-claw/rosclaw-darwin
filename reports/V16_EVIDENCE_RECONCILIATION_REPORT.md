# ROSClaw-Darwin v1.6 Evidence Reconciliation Report

**Date:** 2026-06-20

**Purpose:** Re-classify every v1.6 result into four confidence/use buckets before v1.7 work begins. This prevents the v1.7 reports from mixing *official benchmark evidence*, *promoted-reachability evidence*, *invalid-OOD evidence*, and *experimental/inconclusive evidence*.

---

## A. Official clean benchmark evidence

### A.1 Official dex_cube 100-seed (pre-reachability promotion)

- **Run:** `configs/tasks/goal_pose_dex_cube_official.yaml` + `configs/policies/heuristic_servo_goal_pose_v3.yaml` (before reachability strategy was promoted)
- **Seeds:** 0–99
- **Success:** 82/100 (82%)
- **Wilson 95% CI:** [73.3%, 88.3%]
- **Asset fallback used:** 0 runs
- **Physics anomaly rate:** 0
- **Metric parser error rate:** 0
- **Failure distribution:** dominated by `approach_collision` / `workspace_unreachable` (positive-y workspace edge) and a smaller cluster of post-lift / orientation failures.
- **Claim status:** ✅ Valid official clean benchmark claim.
- **Report:** `reports/DEX_CUBE_GOAL_POSE_100_SEED_VALIDATION_REPORT.md`

### A.2 GRASP pose-hold fix

- **Effect:** In absolute-pose mode the `GRASP` phase now holds the current end-effector pose instead of commanding zero action.
- **Validation:** A 20-seed slip cluster improved from 20/20 failure to a later 50-seed run at 44/50 success.
- **Claim status:** ✅ Valid fix; part of the v3 baseline.

### A.3 Seed randomization and phase trace reliability

- `task.mutation.seed` is forwarded through `ArenaAdapter`, `ArenaRunner`, Docker env vars, and container-side step-0 perturbation.
- Phase trace is reliable after the `_last_gate_diagnostics` shadow-variable fix.
- **Claim status:** ✅ Valid infrastructure evidence.

---

## B. Promoted reachability evidence

### B.1 Reachability-aware approach planner — historical cluster fix

- **Run:** `scripts/diagnostics/run_reachability_approach_ablation.py`
- **Seeds:** 17 historical approach-collision seeds
- **Result:** baseline 0/17 success, `side_pregrasp_positive_y` 17/17 success (100%).
- **Claim status:** ✅ Valid for the specific historical cluster.

### B.2 Post-promotion 50-seed regression

- **Run:** `configs/policies/heuristic_servo_goal_pose_v3_reachability.yaml` on seeds 0–49
- **Result:** 49/50 success (98%), 0 approach collisions
- **Single failure:** seed 24 — `object_not_lifted` / post-lift slip, not a reachability failure.
- **Claim status:** ✅ Valid regression evidence. Does **not** yet replace the 100-seed official benchmark.

### B.3 Reachability promoted to default v3

- `configs/policies/heuristic_servo_goal_pose_v3.yaml` now sets:
  - `reachability_strategy: side_pregrasp_positive_y`
  - `reachability_positive_y_threshold: 0.01`
  - `reachability_positive_yaw_threshold: 0.0`
- A frozen promoted config has been created for v1.7:
  - `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`
- **Claim status:** ✅ Promotion is procedurally complete; its impact on the full 100-seed official score is pending Sprint 1 of v1.7.

---

## C. OOD invalid / unresolved evidence

### C.1 Procedural cube fallback

- **Run:** cross-object matrix (3 variants × 2 conditions × 5 seeds = 30 runs)
- **Artifacts:** `data_v16/ablations/cross_object_matrix_v16/aggregate_summary.json`
- **Result:**
  - `lifted_rate = 0.0` for every cell
  - `env_success_rate = 0.0` for every cell
  - `object_height_delta ≈ -2496.85 m` (catastrophic object-state anomaly)
  - `descend_exit_rate = 0.0` (failure occurs before `GRASP`)
- **Claim status:** ⚠️ **Not a valid generalization failure.** The environment/object-state is invalid; policy adaptation cannot be evaluated on an invalid task.

### C.2 Contact-proxy and structural hints on procedural fallback

- Contact-proxy diagnosis is empty because `DESCEND` does not exit.
- `object_geometry_adapter_structural` (regrasp / contact-verify / lift-verify) cannot help because those phases are downstream of the failure.
- **Claim status:** ❌ No evidence of ineffectiveness; the intervention never had a chance to run.

---

## D. Experimental / inconclusive evidence

### D.1 Pre-grasp yaw alignment v2

- **Run:** reduced cross-yaw matrix (3 yaws × 10 seeds × 4 conditions = 120 runs)
- **Artifacts:** `data_v16/ablations/cross_yaw_matrix_v16/aggregate_summary.json`
- **Result:**
  - Yaw 0: final orientation error reduced (0.0316 → 0.0020 rad)
  - Yaw π/2 and 2π/3: `orientation_achieved_rate` remains near 0; in-hand slip during lift/reorientation dominates.
- **Claim status:** ⚠️ Partial / inconclusive. Helps small-yaw precision, does **not** rescue large-yaw orientation achievement.
- **Report:** `reports/CROSS_OBJECT_CROSS_YAW_GENERALIZATION_REPORT.md`

### D.2 Structural FailureToHint v3.1

- **Implementation:** `CONTACT_VERIFY`, `LIFT_VERIFY`, `REGRASP` phases are implemented and unit-tested.
- **Empirical validation:** None on a valid OOD task.
- **Claim status:** ⚠️ Infrastructure implemented; no empirical gain observed yet because the procedural failure occurs before structural phases are reachable.
- **Report:** `reports/STRUCTURAL_FAILURE_TO_HINT_V31_REPORT.md`

---

## Corrected summary table

| Claim | Previous wording (if any) | Corrected wording |
|---|---|---|
| structural FTH v3.1 | "advances boundary" | **Infrastructure is implemented, but no empirical gain is observed yet because the procedural failure occurs before structural phases are reachable.** |
| procedural OOD cross-object | "cross-object generalization failed" | **Procedural OOD cannot yet serve as a valid generalization benchmark because object-state validity is not established.** |
| reachability planner | fixed historical cluster | **Historical cluster fixed; 50-seed regression clean; full 100-seed official score pending v1.7 Sprint 1.** |
| pre-grasp yaw alignment v2 | (implied large-yaw fix) | **Improves small-yaw precision; does not solve π/2 or 2π/3 large-yaw in-hand slip.** |

---

## What v1.7 must still answer

1. What is the **post-reachability official 100-seed** success rate with the promoted config?
2. Is the **procedural object** a valid rigid body / collision object / metric object, or is the environment invalid?
3. What is the **large-yaw slip mechanism** (eef yaw control vs. object yaw coupling vs. torsional slip)?
4. Only after (2) is resolved can OOD adaptation / structural FTH be re-evaluated.

---

*ROSClaw-Darwin v1.7 start-of-phase reconciliation.*

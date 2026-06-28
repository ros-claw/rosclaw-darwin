# ROSClaw-Darwin v1.8 Kinematic Limit Milestone Report

**Date:** 2026-06-23  
**Status:** v1.8 evidence frozen as the v1.9 baseline. The official dex_cube line remains **99/100**.

---

## Executive Summary

v1.8 systematically probed the next frontier after the v1.7 99/100 breakthrough. The conclusion is unambiguous: **the current kinematic-heuristic approach is near its ceiling**. The following facts are frozen and must not be contradicted by v1.9 experiments unless a new sensor, actuator, or Arena-side capability is introduced.

| Claim | Evidence | Status |
|---|---|---|
| Official dex_cube line | `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml` on seeds 0:99 | **99/100** |
| Holdout run | Not triggered because no candidate cleared the no-regression gate | **N/A** |
| seed24 root cause | `grip_force_insufficient` due to low object z at grasp | Deterministic |
| seed24 global fix | Three successive fixes all regress 0:99 | Rejected |
| Valid OOD benchmark | 7 `rosclaw_valid_cube` variants pass full validity audit | Constructed |
| Valid OOD adaptation gain | ObjectGeometryAdapter / mass / friction / structural show no gain over baseline | No measurable gain |
| SlipMonitor | Recall 0.974, precision 1.000, FPR 0.0 on 40 large-yaw traces | Effective |
| Slip-aware kinematic recovery | No strategy improves large-yaw orientation success | Ineffective |
| FailureToHint v3.2 | Schema implemented and tested | Runtime gain not proven |

---

## 1. Official Baseline Frozen at 99/100

The official benchmark is:

- **Policy:** `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`
- **Task:** `configs/tasks/goal_pose_dex_cube_official.yaml`
- **Embodiment:** `franka_ik_abs`
- **Result:** 99/100 success on seeds 0:99
- **Wilson 95% CI:** [94.55%, 99.82%]
- **Asset fallback:** 0
- **Physics anomaly:** 0
- **Metric parser error:** 0
- **Approach collision:** 0

This is the hardest evidence in the project and the starting point for v1.9. Any v1.9 candidate must pass the `official_promotion_gate` in `configs/evaluation/darwin_v19_gates.yaml` before it can be considered for promotion.

Report: `reports/DEX_CUBE_GOAL_POSE_100_SEED_POST_REACHABILITY_REPORT.md`

---

## 2. Seed24 is Deterministic and Root-Caused

Seed 24 is the single known deterministic residual failure in the official 0:99 distribution.

- **Failure signature:** `grip_force_insufficient`
- **Object z at GRASP:** ~0.021 m (successful seeds are ~0.025–0.028 m)
- **Gripper width after lift:** ~0.0388 m (blocked width is ~0.024 m)
- **Mechanism:** The gripper does not close tightly enough on the low-z grasp, so the object slips after lift.
- **Repeatability:** 10/10 repeats failed with the same signature.

Report: `reports/SEED24_POST_LIFT_SLIP_FORENSICS_REPORT.md`

### Why global fixes were rejected

Three minimal pre-grasp-orientation fixes were ablated:

| Fix | Seed 24 focused ablation | 0:99 regression |
|---|---|---|
| v1 | 10/10 success | 84/100 |
| v2 | 10/10 success | 95/100 |
| v3 | 10/10 success | 38/41 (0.927) before early stop |

All fixes repaired seed 24 but introduced new failures elsewhere. Therefore, **seed 24 cannot be fixed by a global policy change without regression**.

Report: `reports/SEED24_FIX_AND_OFFICIAL_REGRESSION_REPORT.md`

### v1.9 implication

The only acceptable path is **conditional micro-recovery**: detect a seed24-like signature and trigger a local intervention, leaving normal seeds untouched.

---

## 3. Valid OOD Cube Benchmark Constructed

Because the Arena `procedural_cube` fallback is invalid (`collision_enabled=False`, `bbox_valid=False`), v1.8 built a local valid OOD cube benchmark.

- **Variants:** 0.04, 0.05, 0.06, 0.08, 0.10 m cubes; low-friction; heavy.
- **Validity audit:** 7 variants × 20 seeds × 5 episodes = 700 episodes.
- **Results:**
  - `valid_rate = 1.0`
  - `collision_enabled_rate = 1.0`
  - `bbox_valid_rate = 1.0`
  - `rigid_body_enabled_rate = 1.0`

Report: `reports/VALID_OOD_CUBE_BENCHMARK_CONSTRUCTION_REPORT.md`

### Adaptation evaluation

Four conditions were compared on seeds 0:19:

- `baseline_no_adapter`
- `object_geometry_adapter`
- `adapter_mass_friction`
- `adapter_structural`

Aggregate success rate was approximately **0.686** for all four conditions. Per-variant pattern:

- 0.04–0.06 m cubes: 10/10 success
- 0.08–0.10 m cubes: 0/10 success (reachability / grasp geometry boundary)
- low-friction: ~8/10 success
- heavy: 10/10 success

**Conclusion:** The bottleneck on valid OOD is size/reachability and large-yaw slip, not simple threshold scaling.

Report: `reports/VALID_OOD_OBJECT_GEOMETRY_ADAPTER_REPORT.md`

---

## 4. SlipMonitor is Effective, Kinematic Recovery is Not

### SlipMonitor performance

- **Dataset:** 40 v1.7 large-yaw traces (20 per yaw: π/2 and 2π/3).
- **Recall on failures:** 0.974
- **Precision:** 1.000
- **FPR on successes:** 0.0
- **Median early detection:** ~20 steps before episode end.

Report: `reports/SLIP_MONITOR_VALIDATION_REPORT.md`

### Slip-aware recovery pilot

A 36-run serial pilot compared six strategies against the no-monitor baseline:

| Condition | π/2 orientation | 2π/3 orientation | Lifted rate |
|---|---|---|---|
| baseline | 33.3% | 0% | 100% |
| pause_stabilize | 0% | 0% | 100% |
| lower_regrip | 33.3% | 0% | 100% |
| abort_residual_yaw | 0% | 0% | 0% (destructive) |
| place_push_correct | 33.3% | 0% | 100% |
| best_combined | 33.3% | 0% | 100% |

**Conclusion:** Recovery triggers reliably and preserves lift, but **no kinematic strategy improves large-yaw orientation success**. `abort_residual_yaw` is destructive and rejected.

Report: `reports/SLIP_AWARE_RECOVERY_ABLATION_REPORT.md`

### v1.9 implication

Large-yaw torsional slip is a **contact-mechanics problem**, not a waypoint problem. v1.9 must move toward contact-aware residuals and must not add more open-loop waypoints.

---

## 5. FailureToHint v3.2 Schema Implemented, Runtime Gain Not Proven

v3.2 introduced a complete recovery-policy schema:

- `MonitorConfig`
- `ActivationCondition`
- `SuccessMetric`
- `RecoveryPolicy` with recursive `fallback_policy`
- `HintRecipe.recovery_policy`
- `SkillHint.recovery_policy`

The schema is backward-compatible with v3.1 and covered by unit/integration tests.

However, **no v3.2 policy has been shown to improve live Arena outcomes**. The default rule set therefore does **not** claim a validated closed-loop recovery for `torsional_slip`.

Report: `reports/FAILURE_TO_HINT_V32_RECOVERY_POLICY_REPORT.md`

---

## 6. External Blockers Remain

The following are outside the project's direct control and are documented in escalation packages:

1. **Arena acceptance of `franka_ik_abs`** as an official embodiment.
2. **Arena-side fix for procedural cube fallback** so it is collision-enabled and has a valid bounding box without a local patch.
3. **Force / contact / tactile sensors** for slip-aware recovery.
4. **Gripper/contact mechanics changes** to address large-yaw torsional slip.

Escalation packages:

- `external_reviews/procedural_cube_fallback_invalidity_escalation.md`
- `external_reviews/large_yaw_torsional_slip_escalation.md`

These packages are ready to submit but have **not** been submitted without user authorization.

---

## 7. Honest Conclusion: Kinematic Heuristic is Near Ceiling

v1.8 advanced the **infrastructure** for closed-loop recovery and produced a valid local OOD benchmark. It did **not** move the official success line past 99/100 and did **not** solve large-yaw torsional slip.

The path to 100/100 and validated transferable skills now depends on:

- **Contact-aware residual evolution** (v1.9's core goal).
- **Conditional micro-recovery** for seed24-like signatures.
- **Arena-side contact/gripper changes and force sensing**, not on further open-loop or kinematic-only tuning.

This report is the v1.9 baseline. All v1.9 claims must be compared against the evidence here and must pass the gates in `configs/evaluation/darwin_v19_gates.yaml`.

---

## Files Frozen by This Milestone

- `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`
- `reports/FINAL_DARWIN_V18_STATUS_REPORT.md`
- `reports/SEED24_POST_LIFT_SLIP_FORENSICS_REPORT.md`
- `reports/SEED24_FIX_AND_OFFICIAL_REGRESSION_REPORT.md`
- `reports/VALID_OOD_CUBE_BENCHMARK_CONSTRUCTION_REPORT.md`
- `reports/VALID_OOD_OBJECT_GEOMETRY_ADAPTER_REPORT.md`
- `reports/SLIP_MONITOR_VALIDATION_REPORT.md`
- `reports/SLIP_AWARE_RECOVERY_ABLATION_REPORT.md`
- `reports/FAILURE_TO_HINT_V32_RECOVERY_POLICY_REPORT.md`
- `configs/evaluation/darwin_v19_gates.yaml`
- `reports/V19_EXPERIMENT_GATE_SPEC.md`
- `reports/MILESTONE_DARWIN_V18_KINEMATIC_LIMIT_REPORT.md` (this report)

---

*ROSClaw-Darwin v1.8 milestone freeze — honest evidence summary for v1.9 baseline.*

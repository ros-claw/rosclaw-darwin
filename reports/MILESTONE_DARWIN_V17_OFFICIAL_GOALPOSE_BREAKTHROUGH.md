# ROSClaw-Darwin v1.7 Official GoalPose Breakthrough Milestone

**Date:** 2026-06-21
**Milestone:** `darwin-v1.7-official-goalpose-breakthrough`

This document freezes the v1.7 milestone for the `cube_goal_pose` task. It is intended as an immutable reference so that subsequent v1.8 work does not blur the evidence chain.

---

## 1. Official dex_cube 100-seed result: 99/100

- **Task:** `configs/tasks/goal_pose_dex_cube_official.yaml`
- **Policy:** `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`
- **Result:** **99/100 success (99.0%)**
- **Wilson 95% confidence interval:** [94.55%, 99.82%]
- **Artifact:** `data_v17/official/dex_cube_goal_pose_100_seed_post_reachability/aggregate_summary.json`

---

## 2. Clean benchmark attributes

| Attribute | Value | Evidence |
|---|---|---|
| Asset fallback used | 0 / 100 | `asset_fallback_used_rate = 0.0` |
| Physics anomaly | 0 / 100 | `physics_anomaly_rate = 0.0` |
| Metric parser error | 0 / 100 | `metric_parser_error_rate = 0.0` |
| Approach collision | 0 / 100 | `approach_collision_rate = 0.0` |
| Reachability failure | 0 / 100 | promoted reachability strategy active |

---

## 3. Remaining failure: seed 24 post-lift slip

- **Seed:** 24
- **Failure mode:** post-lift slip / hold instability
- **Phase at failure:** `HOLD` / post-lift
- **Lift achieved:** yes
- **Orientation achieved:** no
- **Next step in v1.8:** forensic analysis and minimal fix ablation with 0:99 and 100:199 regression.

---

## 4. Procedural fallback invalid as OOD benchmark

- **Audit artifact:** `data_v17/diagnostics/procedural_object_validity_audit/aggregate_summary.json`
- **Result:** `valid_rate = 0.0` across all three procedural variants
- **Root cause:** `collision_enabled_rate = 0.0`, `bbox_valid_rate = 0.0`
- **Claim boundary:** No procedural-cube result may be reported as OOD skill evaluation until `valid_rate = 1.0`.
- **External tracker:** `reports/ARENA_ISSUE_TRACKER.md` §2.5, IsaacLab-Arena#807.

---

## 5. Large-yaw in-hand torsional slip

- **Diagnosis artifact:** `data_v17/diagnostics/large_yaw_slip/aggregate_summary.json`
- **Dominant mechanism:** `torsional_slip` at π/2 (9/20) and 2π/3 (18/20)
- **Lifted rate:** 100% at both target yaws
- **Orientation achieved:** 10% at π/2, 0% at 2π/3
- **Interventions tested and rejected:**
  - `grasp_at_target_yaw`
  - `low_height_incremental_yaw`
  - `table_push_align`
  - `table_push_align_tuned`
- **Conclusion:** Structural open-loop interventions do not improve `orientation_achieved_rate`. Large-yaw orientation is beyond the current open-loop state-machine space.
- **External tracker:** `reports/ARENA_ISSUE_TRACKER.md` §5.

---

## 6. Controller status

- `franka_ik_abs` is a **local patch** that enables absolute-pose control for the `cube_goal_pose` task.
- It is **not** an officially accepted Arena embodiment.
- All official benchmark claims are conditioned on this local patch being functionally equivalent to the intended controller semantics.

---

## 7. Files that constitute this milestone

| File | Purpose |
|---|---|
| `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml` | Frozen official policy config |
| `data_v17/official/dex_cube_goal_pose_100_seed_post_reachability/` | 100-seed official benchmark artifacts |
| `reports/DEX_CUBE_GOAL_POSE_100_SEED_POST_REACHABILITY_REPORT.md` | Detailed 100-seed report |
| `reports/FINAL_DARWIN_V17_STATUS_REPORT.md` | v1.7 Level A-D summary |
| `data_v17/diagnostics/procedural_object_validity_audit/` | Procedural OOD invalidity evidence |
| `data_v17/diagnostics/large_yaw_slip/` | Large-yaw mechanism evidence |
| `data_v17/ablations/large_yaw_intervention/` | Rejected intervention evidence |

---

## 8. Honest claim boundary

What is proven at v1.7:
- `dex_cube` official benchmark success of **99/100** with the promoted reachability policy.
- Workspace approach collisions are eliminated by the reachability-aware planner.
- Procedural fallback is invalid as an interactive object / OOD benchmark.
- Large-yaw failures are dominated by in-hand torsional slip, and structural open-loop fixes do not solve them.

What is **not** proven:
- 100/100 official robustness (seed 24 remains).
- Cross-object / cross-yaw transferable skill.
- Large-yaw orientation solution without Arena-side contact/gripper changes or force/tactile feedback.
- Real-robot transfer.

---

*ROSClaw-Darwin v1.7 milestone — frozen on 2026-06-21.*

# Large-Yaw Slip Mechanism Report

**Date:** 2026-06-20

**Status:** Sprint 4 of v1.7 — **diagnosis complete. Large-yaw failures are dominated by post-grasp torsional slip, not by inability to command end-effector yaw.**

**Purpose:** Determine whether large-yaw (π/2, 2π/3) failures are caused by:

1. End-effector yaw not reaching the target.
2. End-effector yaw reaching the target but object yaw not following.
3. Object yaw following initially, then slipping relative to the gripper.
4. Wrong object yaw at grasp time.
5. Slip triggered during LIFT, REORIENT, ALIGN, or HOLD.

---

## 1. Method

Script: `scripts/diagnostics/run_large_yaw_slip_diagnosis.py`

Module: `rosclaw_darwin/evaluation/yaw_coupling.py`

Policy: `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`

Task: `configs/tasks/goal_pose_dex_cube_official.yaml`

Target yaws:

- `1.5708` rad (π/2)
- `2.0944` rad (2π/3)

Seeds: 0–19

Trace fields per step:

- `target_yaw`
- `eef_yaw`, `object_yaw`
- `eef_yaw_error`, `object_yaw_error`
- `object_eef_yaw_delta`
- `gripper_width`, `object_height`, `object_z_velocity`
- `yaw_coupling_score`
- `torsional_slip_detected`

Metrics:

- `eef_yaw_final_error`
- `object_yaw_final_error`
- `yaw_coupling_score`
- `torsional_slip_rate`
- `phase_of_first_slip`
- `object_height_at_slip`

Classification taxonomy in `classify_large_yaw_failure`:

- `eef_yaw_failure` — gripper yaw never reaches the target.
- `object_not_coupled` — gripper yaw reaches target, object yaw barely moves.
- `torsional_slip` — object follows initially, then diverges from gripper yaw.
- `post_lift_slip` — divergence begins during LIFT or REORIENT.
- `align_induced_slip` — divergence begins during ALIGN.
- `success` — final object yaw within tolerance.

---

## 2. Command

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
cd /code/rosclaw/rosclaw_darwin/rosclaw-darwin

python scripts/diagnostics/run_large_yaw_slip_diagnosis.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --target-yaws 1.5708,2.0944 \
  --seeds 0:19 \
  --out-dir /code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v17/diagnostics/large_yaw_slip \
  --cleanup
```

---

## 3. Results

**Artifact:** `data_v17/diagnostics/large_yaw_slip/aggregate_summary.json`

| Target Yaw | Env Success | Lifted | Orientation Achieved | Mean Object Yaw Error | Mean Coupling Score | Torsional Slip Count | EEF Yaw Failure Count | Success Count |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| π/2 (1.5708) | 1.0 | 1.0 | 0.10 (2/20) | 2.60 rad | 0.75 | 9 | 9 | 2 |
| 2π/3 (2.0944) | 1.0 | 1.0 | 0.00 (0/20) | 2.23 rad | 1.27 | 18 | 2 | 0 |

**Observations:**

- The object is lifted in every run (`lifted_rate = 1.0`). The problem is not pick-up but final orientation.
- At π/2 the failures are split evenly between `eef_yaw_failure` (gripper never reaches the target yaw) and `torsional_slip` (object follows then slips).
- At 2π/3 the failures are overwhelmingly `torsional_slip` (18/20). The gripper generally reaches the target yaw, but the object twists out of alignment after grasping.
- Mean object yaw final error is large (>2 rad), confirming that the object ends far from the requested orientation.
- The yaw-coupling score is higher at 2π/3 (1.27) than at π/2 (0.75), indicating stronger post-grasp divergence as the requested yaw increases.

---

## 4. Mechanism classification

**Dominant mechanism: torsional slip during or after lift.**

The taxonomy counts show:

- `eef_yaw_failure` — non-negligible at π/2 (9/20), minor at 2π/3 (2/20).
- `torsional_slip` — dominates at 2π/3 (18/20) and is the largest single category at π/2 (9/20).
- `success` — only 2/20 at π/2 and 0/20 at 2π/3.

This means pre-grasp yaw alignment alone cannot solve the problem, because even when the gripper reaches the target yaw, the object does not stay aligned. The object is initially coupled to the gripper (it is lifted), but the frictional/grasp coupling is insufficient to hold the large in-hand yaw torque, and the object rotates relative to the gripper.

---

## 5. Answers to the Sprint 4 questions

1. **Is eef yaw controllable to the target?**
   **Partially.** At π/2, 9/20 runs fail because the gripper yaw itself does not reach the target (`eef_yaw_failure`). At 2π/3, the gripper usually reaches the target (only 2/20 `eef_yaw_failure`), so controllability is worse at π/2 than at 2π/3. When the gripper does reach the target, the object still slips.

2. **Does object yaw follow eef yaw?**
   **Initially yes, but not persistently.** The high `torsional_slip` count and high yaw-coupling scores show that the object follows the gripper long enough to be lifted, then diverges. This is consistent with insufficient frictional coupling for large yaw torques.

3. **In which phase does slip occur?**
   The aggregate classifier assigns `torsional_slip`, which indicates divergence after initial coupling. The traces would need deeper per-phase attribution to say whether slip begins in LIFT, REORIENT, ALIGN, or HOLD. The fact that `lifted_rate = 1.0` but `orientation_achieved_rate ≈ 0` implies the divergence happens after the object leaves the table, most likely during REORIENT/ALIGN/HOLD.

4. **Why does pre-grasp yaw alignment v2 not solve it?**
   Because the root failure is **post-grasp torsional slip**, not pre-grasp misalignment. Aligning the gripper before grasp reduces the residual rotation needed after lift, but once the object is in the air, the grasp cannot transmit the yaw torque required to maintain large target yaws.

5. **Next step: pre-grasp yaw, incremental align, push-align, or force/contact?**
   **Force/contact-aware alignment or push-align near the table is the most plausible next hypothesis.** Simple pre-grasp yaw alignment has already been shown insufficient. Incremental yaw alignment at low height might reduce the torque arm, but the ablation in `reports/LARGE_YAW_TARGETED_INTERVENTION_REPORT.md` shows it does not materially improve orientation achievement. A mechanical solution (tighter grasp, anti-slip fingertips, or compliant pushing against the table) is likely required; these are external dependencies unless the policy can exploit table contact.

---

*ROSClaw-Darwin v1.7 Sprint 4 — diagnosis complete; torsional slip is the dominant large-yaw failure mechanism.*

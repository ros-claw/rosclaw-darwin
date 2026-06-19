# Large-Yaw Slip Mechanism Report

**Date:** 2026-06-20

**Status:** Sprint 4 of v1.7 — diagnosis data collection in progress.

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
  --out-dir data_v17/diagnostics/large_yaw_slip \
  --cleanup
```

---

## 3. Results

**Artifact:** `data_v17/diagnostics/large_yaw_slip/aggregate_summary.json`

| Target Yaw | Env Success | Lifted | Orientation Achieved | Mean Object Yaw Error | Mean Coupling Score | Torsional Slip Rate | Dominant Category |
|---|---:|---:|---:|---:|---:|---:|---:|
| π/2 | *pending* | *pending* | *pending* | *pending* | *pending* | *pending* | *pending* |
| 2π/3 | *pending* | *pending* | *pending* | *pending* | *pending* | *pending* | *pending* |

---

## 4. Mechanism classification

Categories used:

- `eef_yaw_failure` — gripper yaw never reaches the target.
- `object_not_coupled` — gripper yaw reaches target, object yaw barely moves.
- `torsional_slip` — object follows initially, then diverges from gripper yaw.
- `post_lift_slip` — divergence begins during LIFT or REORIENT.
- `align_induced_slip` — divergence begins during ALIGN.

**Preliminary hypothesis:** The reduced cross-yaw matrix showed that the object
is lifted successfully at π/2 and 2π/3 but ends with the wrong yaw, suggesting
`object_not_coupled` or `torsional_slip` rather than `eef_yaw_failure`. The
diagnosis will quantify which mechanism dominates.

---

## 5. Answers to the Sprint 4 questions

1. **Is eef yaw controllable to the target?** *pending diagnosis*
2. **Does object yaw follow eef yaw?** *pending diagnosis*
3. **In which phase does slip occur?** *pending diagnosis*
4. **Why does pre-grasp yaw alignment v2 not solve it?** *pending diagnosis*
5. **Next step: pre-grasp yaw, incremental align, push-align, or force/contact?** *pending diagnosis*

---

*ROSClaw-Darwin v1.7 Sprint 4 — to be filled after the diagnosis completes.*

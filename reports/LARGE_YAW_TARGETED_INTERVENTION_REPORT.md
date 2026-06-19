# Large-Yaw Targeted Intervention Report

**Date:** 2026-06-20

**Status:** Sprint 5 of v1.7 — intervention code implemented; ablation pending.

**Purpose:** Test whether the large-yaw failure can be reduced by two targeted
structural strategies that do not require new sensors:

1. **Grasp-at-target-yaw** — align the gripper to the full target yaw before
   descending, then disable in-hand reorientation.
2. **Low-height incremental yaw** — lift only slightly, perform incremental
   yaw alignment close to the table, then continue to full height.

---

## 1. Method

Script: `scripts/ablations/run_large_yaw_intervention_ablation.py`

Policy configs:

- Baseline: `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`
- Grasp-at-target-yaw: `configs/policies/heuristic_servo_goal_pose_v3_large_yaw_grasp_at_target.yaml`
- Low-height incremental yaw: `configs/policies/heuristic_servo_goal_pose_v3_large_yaw_low_height.yaml`

Policy changes implemented in `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`:

- Added `large_yaw_strategy`, `disable_inhand_reorient`, and
  `lift_height_before_yaw` to `HeuristicServoGoalPosePolicyArgs`.
- `grasp_at_target_yaw` sets `pre_grasp_yaw_align_v2=True`,
  `pre_grasp_yaw_fraction=1.0`, `post_grasp_yaw_residual_fraction=0.0`, and
  disables in-hand reorientation.
- `low_height_incremental_yaw` lowers both `lift_height` and
  `reorient_height_offset` to `lift_height_before_yaw` while keeping residual
  in-hand rotation small.

Task: `configs/tasks/goal_pose_dex_cube_official.yaml`

Target yaws: π/2, 2π/3

Seeds: 0–19 per condition × yaw.

---

## 2. Command

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
cd /code/rosclaw/rosclaw_darwin/rosclaw-darwin

python scripts/ablations/run_large_yaw_intervention_ablation.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --target-yaws 1.5708,2.0944 \
  --seeds 0:19 \
  --conditions baseline,grasp_at_target_yaw,low_height_incremental_yaw \
  --out-dir data_v17/ablations/large_yaw_intervention \
  --cleanup
```

---

## 3. Metrics

- `env_success_rate` — native Arena success (expected near 0 because target yaw
  is overridden).
- `lifted_rate` — object reached `object_z > 0.1`.
- `orientation_achieved_rate` — final object yaw within 0.5 rad of override.
- `torsional_slip_rate` — fraction with detected slip.
- `mean_yaw_coupling_score` — how tightly object yaw tracks eef yaw.
- `category_distribution` — counts of `eef_yaw_failure`, `object_not_coupled`,
  `torsional_slip`, `post_lift_slip`, `align_induced_slip`, `success`.

---

## 4. Results

**Artifact:** `data_v17/ablations/large_yaw_intervention/aggregate_summary.json`

| Condition | Target Yaw | Lifted | Orient Achieved | Mean Coupling | Slip Rate | Dominant Category |
|---|---:|---:|---:|---:|---:|---:|
| baseline | π/2 | *pending* | *pending* | *pending* | *pending* | *pending* |
| baseline | 2π/3 | *pending* | *pending* | *pending* | *pending* | *pending* |
| grasp_at_target_yaw | π/2 | *pending* | *pending* | *pending* | *pending* | *pending* |
| grasp_at_target_yaw | 2π/3 | *pending* | *pending* | *pending* | *pending* | *pending* |
| low_height_incremental_yaw | π/2 | *pending* | *pending* | *pending* | *pending* | *pending* |
| low_height_incremental_yaw | 2π/3 | *pending* | *pending* | *pending* | *pending* | *pending* |

---

## 5. Pass criteria

- **Minimum:** at least one intervention improves `orientation_achieved_rate` by
  ≥20% relative on π/2 or 2π/3.
- **High quality:** improvement without regression on native success at yaw 0
  (to be verified separately).
- **Claim boundary:** a positive result is evidence for a specific slip
  mechanism; it does not yet prove cross-yaw generalization until tested across
  the full yaw matrix with many seeds.

---

*ROSClaw-Darwin v1.7 Sprint 5 — to be filled after the ablation completes.*

# Large-Yaw Targeted Intervention Report

**Date:** 2026-06-21

**Status:** Sprint 5–6 of v1.7 — **ablation complete. None of the targeted structural interventions, including two table push-align variants, improved large-yaw orientation achievement by ≥20% relative. The large-yaw slip problem is beyond the current open-loop state-machine space.**

**Purpose:** Test whether the large-yaw failure can be reduced by targeted
structural strategies that do not require new sensors:

1. **Grasp-at-target-yaw** — align the gripper to the full target yaw before
   descending, then disable in-hand reorientation.
2. **Low-height incremental yaw** — lift only slightly, perform incremental
   yaw alignment close to the table, then continue to full height.
3. **Table push-align** — keep the object pressed against the tabletop while
   applying yaw torque, exploiting table reaction friction instead of pure
   in-hand friction.

---

## 1. Method

Script: `scripts/ablations/run_large_yaw_intervention_ablation.py`

Policy configs:

- Baseline: `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`
- Grasp-at-target-yaw: `configs/policies/heuristic_servo_goal_pose_v3_large_yaw_grasp_at_target.yaml`
- Low-height incremental yaw: `configs/policies/heuristic_servo_goal_pose_v3_large_yaw_low_height.yaml`
- Table push-align (base): `configs/policies/heuristic_servo_goal_pose_v3_large_yaw_table_push_align.yaml`
- Table push-align (tuned): `configs/policies/heuristic_servo_goal_pose_v3_large_yaw_table_push_align_tuned.yaml`

Policy changes implemented in `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`:

- Added `large_yaw_strategy`, `disable_inhand_reorient`, and
  `lift_height_before_yaw` to `HeuristicServoGoalPosePolicyArgs`.
- `grasp_at_target_yaw` sets `pre_grasp_yaw_align_v2=True`,
  `pre_grasp_yaw_fraction=1.0`, `post_grasp_yaw_residual_fraction=0.0`, and
  disables in-hand reorientation.
- `low_height_incremental_yaw` lowers both `lift_height` and
  `reorient_height_offset` to `lift_height_before_yaw` while keeping residual
  in-hand rotation small.
- `table_push_align` adds a `TABLE_PUSH_ALIGN` state after `GRASP` that keeps
  the gripper pressed on top of the object while rotating toward the target
  yaw, with optional tangential oscillation to break static friction.

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
  --target-yaws 1.5708 2.0944 \
  --seeds 0:19 \
  --conditions baseline,grasp_at_target_yaw,low_height_incremental_yaw \
  --out-dir /code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v17/ablations/large_yaw_intervention \
  --cleanup
```

Table push-align was added later and run as a supplementary condition, then
merged into the same aggregate:

```bash
python scripts/ablations/run_large_yaw_intervention_ablation.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --target-yaws 1.5708 2.0944 \
  --seeds 0:19 \
  --conditions table_push_align \
  --out-dir /code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v17/ablations/large_yaw_intervention_table_push_align \
  --cleanup

python scripts/ablations/merge_large_yaw_intervention_aggregates.py \
  --source data_v17/ablations/large_yaw_intervention_table_push_align/aggregate_summary.json \
  --target data_v17/ablations/large_yaw_intervention/aggregate_summary.json \
  --out-dir data_v17/ablations/large_yaw_intervention
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

| Condition | Target Yaw | Env Success | Lifted | Orient Achieved | Mean Coupling | Slip Count | EEF Yaw Failure Count | Success Count |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | π/2 | 1.00 | 1.00 | 0.10 (2/20) | 0.75 | 9 | 9 | 2 |
| baseline | 2π/3 | 1.00 | 1.00 | 0.00 (0/20) | 1.27 | 18 | 2 | 0 |
| grasp_at_target_yaw | π/2 | 1.00 | 1.00 | 0.10 (2/20) | 1.31 | 18 | 0 | 2 |
| grasp_at_target_yaw | 2π/3 | 0.95 | 1.00 | 0.05 (1/20) | 1.38 | 18 | 1 | 1 |
| low_height_incremental_yaw | π/2 | 0.95 | 1.00 | 0.05 (1/20) | 0.57 | 17 | 2 | 1 |
| low_height_incremental_yaw | 2π/3 | 1.00 | 1.00 | 0.00 (0/20) | 1.08 | 4 | 16 | 0 |
| table_push_align | π/2 | 0.90 | 1.00 | 0.10 (2/20) | 1.24 | 17 | 1 | 2 |
| table_push_align | 2π/3 | 0.75 | 1.00 | 0.00 (0/20) | 1.12 | 20 | 0 | 0 |
| table_push_align_tuned | π/2 | 0.90 | 1.00 | 0.10 (2/20) | 1.14 | 18 | 0 | 2 |
| table_push_align_tuned | 2π/3 | 1.00 | 1.00 | 0.00 (0/20) | 1.23 | 19 | 1 | 0 |

### Interpretation

- **Baseline already lifts every object; the failure is orientation, not pick-up.**
- **Grasp-at-target-yaw** at π/2 eliminated `eef_yaw_failure` (0 vs 9) but converted those failures into `torsional_slip` (18 vs 9). The net `orientation_achieved_rate` did not improve (0.10 vs 0.10). This confirms that pre-grasp alignment is not the binding constraint.
- **Grasp-at-target-yaw** at 2π/3 produced a marginal improvement from 0/20 to 1/20 orientation achieved, still essentially zero.
- **Low-height incremental yaw** at π/2 slightly reduced mean coupling (0.57 vs 0.75) but orientation achievement dropped from 2/20 to 1/20.
- **Low-height incremental yaw** at 2π/3 dramatically changed the failure mode: `eef_yaw_failure` rose from 2 to 16 while `torsional_slip` dropped from 18 to 4. Operating close to the table at this yaw prevents the gripper from reaching the target yaw, so this intervention is harmful for 2π/3.
- **Table push-align** at π/2 also eliminated most `eef_yaw_failure` (1 vs 9) but converted them into `torsional_slip` (17 vs 9). Mean coupling rose (1.24 vs 0.75), showing the object tracks the gripper more tightly, yet net `orientation_achieved_rate` stayed at 0.10 (2/20). The mean object yaw final error improved from 2.60 rad to 1.40 rad, so the object ends closer to the target yaw, but still outside the 0.5 rad threshold.
- **Table push-align** at 2π/3 produced 0/20 orientation achieved, with all failures classified as `torsional_slip`. Gripper yaw control while pressed against the table is still insufficient at this extreme yaw.
- **Table push-align tuned** did not improve over the base variant. At π/2, orientation achievement stayed at 2/20, mean coupling was similar (1.14 vs 1.24), and mean object yaw final error was slightly worse (1.51 rad vs 1.40 rad). At 2π/3, it produced 0/20 orientation achieved with 19/20 `torsional_slip` and 1/20 `eef_yaw_failure`. The parameter changes (more time, higher z-offset, faster yaw step, stronger oscillation, less downward pressure) did not materially change the outcome.

---

## 5. Pass criteria

- **Minimum:** at least one intervention improves `orientation_achieved_rate` by
  ≥20% relative on π/2 or 2π/3.
- **High quality:** improvement without regression on native success at yaw 0
  (to be verified separately).
- **Claim boundary:** a positive result is evidence for a specific slip
  mechanism; it does not yet prove cross-yaw generalization until tested across
  the full yaw matrix with many seeds.

### Verdict

**Minimum criterion not met.** None of the interventions, including both
`table_push_align` variants, improved `orientation_achieved_rate` by ≥20%
relative on either target yaw:

- π/2: baseline 0.10 → grasp_at_target_yaw 0.10 (0%); low_height 0.05 (−50%); table_push_align 0.10 (0%); table_push_align_tuned 0.10 (0%).
- 2π/3: baseline 0.00 → grasp_at_target_yaw 0.05 (0 to 1/20, not meaningful); low_height 0.00; table_push_align 0.00; table_push_align_tuned 0.00.

The structural hypotheses tested here, including table-reaction-friction
push-align, are therefore **rejected** as standalone fixes for large-yaw slip.

---

## 6. Conclusions

1. **Torsional slip is the binding failure mode.** Even when the gripper is forced to the target yaw before grasp (`grasp_at_target_yaw`) or kept pressed against the table while rotating (`table_push_align` and `table_push_align_tuned`), the object still twists out of alignment. The failure is not missing yaw authority before or during grasp; it is the inability to maintain the object-gripper yaw coupling under torque.
2. **Low-height operation, table contact, and parameter tuning help neither controllability nor net slip.** At 2π/3, low-height operation prevents the gripper from reaching the target yaw (`eef_yaw_failure` 16/20). Table push-align improves coupling and eliminates most pre-grasp yaw failures, but the object still slips before the threshold is reached. Tuning push-align time, z-offset, yaw step, lateral oscillation, and downward pressure did not change the outcome.
3. **The remaining frontier is outside the current open-loop state-machine space.** Large-yaw orientation likely requires one or more of:
   - Higher grip force or anti-slip contact (Arena-side gripper/object properties).
   - Explicit torque/force feedback for slip detection and recovery.
   - A different controller or embodiment that can command or exploit yaw torque more effectively.
   These are external dependencies relative to the current heuristic position-control policy.

---

*ROSClaw-Darwin v1.7 Sprint 5–6 — ablation complete; all targeted structural interventions rejected.*

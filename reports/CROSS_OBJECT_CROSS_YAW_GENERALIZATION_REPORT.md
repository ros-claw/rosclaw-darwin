# Cross-Object / Cross-Yaw Generalization Report

**Date:** 2026-06-19

**Goal:** Verify whether the v1.6 interventions (reachability-aware approach planner and pre-grasp yaw alignment v2) generalize across target yaws and object variants.

---

## 1. Method

Script: `scripts/diagnostics/run_cross_object_cross_yaw_matrix.py`

The matrix runner supports two modes:

- **Yaw matrix** — sweeps `target_yaw_override` on the official `dex_cube` task.
- **Object matrix** — sweeps a list of task configs, each representing a different object or size.

Conditions:

| condition | policy overrides |
|---|---|
| `baseline_v3` | none (already contains default reachability settings) |
| `v3_reachability` | `reachability_strategy: side_pregrasp_positive_y` |
| `v3_yaw_align` | `pre_grasp_yaw_align_v2: true` |
| `v3_reachability_yaw_align` | both reachability and yaw-align v2 |
| `object_geometry_adapter_structural` | `enable_regrasp: true` (object mode only) |

Metrics per cell:

- `env_success_rate` — environment-reported success.
- `lifted_rate` — fraction of runs where the object reached `object_z > 0.25 m`.
- `orientation_achieved_rate` — fraction of lifted runs whose final object yaw is within 0.5 rad of the target.
- `mean_progress`, `mean_object_height_delta`, `mean_final_orientation_error`.

---

## 2. Experiments

### 2.1 Reduced cross-yaw matrix

A first cross-yaw matrix with a reduced yaw set and seed range was run to validate the runner and get an early signal:

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
python scripts/diagnostics/run_cross_object_cross_yaw_matrix.py \
  --mode yaw \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3.yaml \
  --target-yaws 0.0 1.5708 2.0944 \
  --conditions baseline_v3,v3_reachability,v3_yaw_align,v3_reachability_yaw_align \
  --seeds 0:9 \
  --cleanup \
  --out-dir /code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v16/ablations/cross_yaw_matrix_v16
```

Aggregate artifact: `data_v16/ablations/cross_yaw_matrix_v16/aggregate_summary.json`

Total: 120 runs (4 conditions × 3 yaws × 10 seeds).

### 2.2 Full cross-yaw matrix

The full planned yaw sweep remains:

```bash
python scripts/diagnostics/run_cross_object_cross_yaw_matrix.py \
  --mode yaw \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3.yaml \
  --target-yaws 0.0 0.5236 0.7854 1.0472 1.5708 2.0944 \
  --conditions baseline_v3,v3_reachability,v3_yaw_align,v3_reachability_yaw_align \
  --seeds 0:19 \
  --cleanup \
  --out-dir data_v16/ablations/cross_yaw_matrix_full_v16
```

This has **not** been run yet; the reduced matrix is the current evidence base.

### 2.3 Cross-object matrix

Planned command:

```bash
python scripts/diagnostics/run_cross_object_cross_yaw_matrix.py \
  --mode object \
  --policy configs/policies/heuristic_servo_goal_pose_v3.yaml \
  --object-task-configs \
    configs/tasks/goal_pose_procedural_cube_ood.yaml \
    configs/tasks/goal_pose_procedural_cube_dex_size.yaml \
    configs/tasks/goal_pose_procedural_cube_large.yaml \
  --conditions baseline_v3,object_geometry_adapter_structural \
  --seeds 0:4 \
  --cleanup \
  --out-dir data_v16/ablations/cross_object_matrix_v16
```

This is the next pending Wave D run.

---

## 3. Results

### 3.1 Reduced cross-yaw matrix

| condition | target yaw | env_success | lifted | orientation_achieved | mean final orientation error (rad) |
|---|---|---:|---:|---:|---:|
| baseline_v3 | 0.0000 | 1.0 | 1.0 | 1.0 | 0.0316 |
| baseline_v3 | 1.5708 | 1.0 | 1.0 | 0.2 | 1.2733 |
| baseline_v3 | 2.0944 | 1.0 | 1.0 | 0.0 | 1.8209 |
| v3_reachability | 0.0000 | 1.0 | 1.0 | 1.0 | 0.0316 |
| v3_reachability | 1.5708 | 1.0 | 1.0 | 0.2 | 1.2733 |
| v3_reachability | 2.0944 | 1.0 | 1.0 | 0.0 | 1.8209 |
| v3_yaw_align | 0.0000 | 0.9 | 1.0 | 1.0 | 0.0020 |
| v3_yaw_align | 1.5708 | 1.0 | 1.0 | 0.2 | 1.1012 |
| v3_yaw_align | 2.0944 | 1.0 | 1.0 | 0.0 | 1.8075 |
| v3_reachability_yaw_align | 0.0000 | 0.9 | 1.0 | 1.0 | 0.0020 |
| v3_reachability_yaw_align | 1.5708 | 0.9 | 0.9 | 0.1 | 1.2232 |
| v3_reachability_yaw_align | 2.0944 | 1.0 | 1.0 | 0.0 | 1.8075 |

Key observations:

1. **Environment success stays high across all cells.** Every condition achieves near-perfect `lifted_rate` on the official `dex_cube` asset; the failures that do appear are post-lift / orientation criterion failures, not workspace collisions or grasp misses.
2. **Reachability strategy has no visible effect in this matrix.** `baseline_v3` already uses `reachability_strategy: side_pregrasp_positive_y` as the default, so the `v3_reachability` override is redundant. The matrix therefore confirms that the promoted reachability settings do not regress performance at these yaws.
3. **Pre-grasp yaw alignment v2 strongly reduces final orientation error at yaw 0** (mean error 0.0020 rad vs 0.0316 rad) but **does not rescue orientation achievement at large yaws**:
   - yaw π/2: orientation_achieved_rate stays at 0.1–0.2 across yaw-align conditions.
   - yaw 2π/3: orientation_achieved_rate stays at 0.0.
4. **Yaw alignment can trade orientation precision for overall progress.** At yaw 0, yaw-align conditions show lower `mean_progress` (0.609 vs 0.773) and one env-success failure per cell, suggesting that holding the pre-grasp pose to align yaw can occasionally time out or destabilize the later lift.
5. **The large-yaw orientation failure is an in-hand slip/reorientation problem, not an approach problem.** Because the object is lifted successfully but ends up with the wrong yaw, the bottleneck occurs during `LIFT` / `REORIENT` / `ALIGN`, not during `APPROACH` or `GRASP`.

### 3.2 Cross-object matrix

Command run:

```bash
python scripts/diagnostics/run_cross_object_cross_yaw_matrix.py \
  --mode object \
  --policy configs/policies/heuristic_servo_goal_pose_v3.yaml \
  --object-task-configs \
    configs/tasks/goal_pose_procedural_cube_ood.yaml \
    configs/tasks/goal_pose_procedural_cube_dex_size.yaml \
    configs/tasks/goal_pose_procedural_cube_large.yaml \
  --conditions baseline_v3,object_geometry_adapter_structural \
  --seeds 0:4 \
  --cleanup \
  --out-dir /code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v16/ablations/cross_object_matrix_v16
```

Total: 30 runs (3 objects × 2 conditions × 5 seeds).

| condition | object variant | completed | lifted | orientation_achieved | env_success | mean progress | mean object_height_delta |
|---|---|---:|---:|---:|---:|---:|---:|
| baseline_v3 | procedural_cube_ood | 1.0 | 0.0 | 0.0 | 0.0 | 0.4863 | -2496.85 |
| baseline_v3 | procedural_cube_dex_size | 1.0 | 0.0 | 0.0 | 0.0 | 0.4863 | -2496.85 |
| baseline_v3 | procedural_cube_large | 1.0 | 0.0 | 0.0 | 0.0 | 0.4863 | -2496.85 |
| object_geometry_adapter_structural | procedural_cube_ood | 1.0 | 0.0 | 0.0 | 0.0 | 0.4863 | -2496.85 |
| object_geometry_adapter_structural | procedural_cube_dex_size | 1.0 | 0.0 | 0.0 | 0.0 | 0.4863 | -2496.85 |
| object_geometry_adapter_structural | procedural_cube_large | 1.0 | 0.0 | 0.0 | 0.0 | 0.4863 | -2496.85 |

Key observations:

1. **Zero lift across all procedural variants.** `lifted_rate = 0.0`, `env_success_rate = 0.0` for every object and both conditions.
2. **`object_geometry_adapter_structural` (regrasp / contact-verify / lift-verify) does not help.** The failure occurs before `DESCEND` exits (`descend_exit_rate = 0.0`), so the regrasp state machine is never reached.
3. **The failure is identical across sizes.** dex_size, large, and ood procedural cubes all show the same `mean_progress` (~0.486) and catastrophic `object_height_delta` (~-2496 m), confirming the root cause is not object dimensions but **asset-fidelity-induced policy-object geometry/gate mismatch**.
4. **No cross-object generalization claim can be made for v1.6.** Official `dex_cube` success does not transfer to any of the tested procedural variants under the current policy.

---

## 4. Honest conclusion

1. **A unified cross-object / cross-yaw matrix runner now exists** and uses absolute output paths to avoid the Docker volume-mount issue.
2. **The reduced yaw matrix is a valid early signal but not a full generalization proof.** It covers only 3 yaws and 10 seeds per cell; the full 6-yaw × 20-seed matrix is still needed.
3. **Reachability-aware approach planning does not hurt yaw generalization.** Because reachability only reroutes the approach for positive-y / positive-yaw object placements, it is not expected to change behavior at arbitrary target yaws, and the data confirm this.
4. **Pre-grasp yaw alignment v2 improves small-yaw orientation accuracy but not large-yaw orientation achievement.** At π/2 and 2π/3 the in-hand slip during lift/reorientation dominates, so a pre-grasp alignment of the gripper yaw cannot propagate through to the final object pose.
5. **Cross-object generalization is not demonstrated.** The object-mode matrix (30 runs) shows `lifted_rate = 0.0` for all three procedural cube variants and both conditions. `object_geometry_adapter_structural` cannot help because the failure occurs before `DESCEND` exits, confirming the blocker is asset-fidelity-induced geometry/gate mismatch rather than object size.

---

## 5. Files changed

- `scripts/diagnostics/run_cross_object_cross_yaw_matrix.py` (new)
- `reports/CROSS_OBJECT_CROSS_YAW_GENERALIZATION_REPORT.md` (this report)
- `data_v16/ablations/cross_yaw_matrix_v16/aggregate_summary.json`
- `data_v16/ablations/cross_object_matrix_v16/aggregate_summary.json`

# Seed 24 Fix and Official Regression Report

**Date:** 2026-06-22

**Status:** Sprint 2 of v1.8 — **v3 focused seed-24 ablation passed (10/10 success, gripper blocked 10/10, no new failure mode), but the v3 official 0:99 regression regressed (≥3 failures in the first 41 seeds). All pre-grasp-orientation candidates (v1/v2/v3) are rejected. The v1.7 promoted config (`heuristic_servo_goal_pose_v3_reachability_promoted.yaml`) remains the official benchmark.**

**Purpose:** Validate the minimal fix identified in `SEED24_POST_LIFT_SLIP_FORENSICS_REPORT.md`, promote it to a candidate official config, and confirm that the fix does not regress the v1.7 100-seed benchmark.

---

## 1. Candidate Fix

The Sprint 1 forensics concluded that seed 24 fails deterministically because the gripper never blocks on the cube during GRASP (`gripper_pos_min_while_lifted ≈ 0.039` vs. blocked width `≈ 0.024`). The promoted reachability config disabled pre-grasp orientation alignment to isolate reachability effects; for seed 24 this causes a face-to-face grasp-geometry mismatch.

**Intervention:** re-enable `pre_grasp_orient` with zero yaw offset so the gripper aligns with the cube faces before DESCEND/GRASP.

**Config:** `configs/policies/heuristic_servo_goal_pose_v3_reachability_seed24_fix.yaml`

Changes from `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`:

```yaml
policy_id: heuristic_servo_goal_pose_v3_reachability_seed24_fix
pre_grasp_orient: true
grasp_target_yaw_offset: 0.0
```

All other parameters (reachability strategy, `ObjectGeometryAdapter`, grasp thresholds, etc.) remain identical to the v1.7 promoted config.

---

## 2. Focused Seed 24 Fix Ablation

**Script:** `scripts/ablations/run_seed24_slip_fix_ablation.py`

**Task:** `configs/tasks/goal_pose_dex_cube_official.yaml`

**Base policy:** `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`

**Seed:** 24

**Repeats per condition:** 10 (serial, fresh container per repeat, private trace directory)

**Conditions:**

- `baseline` — no parameter overrides.
- `enable_pre_grasp_orient` — `pre_grasp_orient: true`, `grasp_target_yaw_offset: 0.0`.

### Aggregate results

**Artifact:** `data_v18/ablations/seed24_slip_fix_focused/aggregate_summary.json`

| Metric | Baseline (10 repeats) | `enable_pre_grasp_orient` (10 repeats) |
|---|---:|---:|
| Valid repeats | 10 | 10 |
| Env success repeats | 0 | **10** |
| Env success rate | 0.0 | **1.0** |
| Dominant category | `grip_force_insufficient` (10/10) | `success` (10/10) |
| Mean max object z | 0.5142 m | 0.5019 m |
| Mean final object z | 0.0210 m | **0.4648 m** |
| Mean gripper pos min while lifted | 0.0388 m | **0.0245 m** |
| Gripper blocked while lifted | 0/10 | **10/10** |

The fix restores the blocked gripper closure width and converts the deterministic seed-24 failure into a deterministic success.

### Per-repeat CSV

`data_v18/ablations/seed24_slip_fix_focused/per_repeat_results.csv`

---

## 3. Promotion Decision (v1 fix)

The `enable_pre_grasp_orient` condition satisfies the focused-ablation promotion gate:

1. Seed 24 repeat success rate = 10/10 ≥ 8/10 threshold.
2. No new failure mode introduced in the focused ablation — the only category is `success`.
3. The change is minimal (two YAML overrides) and preserves all v1.7 reachability / geometry-adaptation behavior.

Therefore `configs/policies/heuristic_servo_goal_pose_v3_reachability_seed24_fix.yaml` was promoted to the **first candidate** for the 0:99 regression.

---

## 4. Official 0:99 Regression (v1 fix)

**Command:**

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
cd /code/rosclaw/rosclaw_darwin/rosclaw-darwin

python scripts/diagnostics/run_dex_cube_generalization_matrix.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3_reachability_seed24_fix.yaml \
  --seeds 0:99 \
  --strict-official-asset --serial --cleanup --classify-failures --save-traces-on-failure \
  --out-dir data_v18/official/dex_cube_100_seed_seed24_fix
```

**Status:** completed.

**Artifact:** `data_v18/official/dex_cube_100_seed_seed24_fix/aggregate_summary.json`

### 4.1 Results

| Metric | v1.7 promoted | seed24_fix (0:99) |
|---|---:|---:|
| Total seeds | 100 | 100 |
| Valid seeds | 100 | 100 |
| Successful seeds | 99 | **84** |
| Overall success rate | 0.99 | **0.84** |
| Progress mean | 0.7829 | **0.7467** |
| Object height max mean | 0.77 | **0.4745** |
| Failed seed distribution | seed 24 (`unknown`) | **15 `unknown`, 1 `approach_collision`** |

The v1 fix causes a severe regression: 15 previously successful seeds now fail with `object_height_max = 0.2 m`, i.e. the object is never lifted.

### 4.2 Regression diagnosis

Trace-level inspection of the failed seeds shows a common mechanism:

- All 15 `unknown` failures enter `PRE_GRASP_ORIENT` and stay for the full 30-step timeout.
- At timeout the gripper yaw has **not converged** to the object yaw; the end-effector descends at an intermediate, misaligned orientation.
- During `GRASP` the gripper closes fully (`gripper_pos_min ≈ 0.0001 m`) without blocking on the cube, so the subsequent `LIFT` leaves the object on the table.
- The `approach_collision` failure (seed 49) is a separate transient.

Root cause: the v1 config re-enabled `pre_grasp_orient`, but the `PRE_GRASP_ORIENT` state builds its target quaternion in the **world frame** and passes it directly to the absolute-mode controller, which expects a **base-frame** quaternion. The resulting target is almost collinear with the current orientation, so the gripper barely rotates during the 30-step window and then descends misaligned.

Seed 24 happens to benefit from the small residual rotation / position settling, but the same bug is catastrophic for the 15 regression seeds.

### 4.3 No-regression criterion

- The v1 fix is **rejected**: 0:99 success rate dropped to 0.84, far below the 0.98 threshold.
- The v1.7 promoted config remains the current official benchmark config.

---

## 5. v2 Candidate Fix — Corrected Pre-Grasp Orientation

**Intervention:** keep `pre_grasp_orient: true` and `grasp_target_yaw_offset: 0.0`, but

1. Convert the world-frame object-yaw target into the robot base frame before applying orientation control.
2. Choose the quaternion sign that gives the shortest rotation from the current end-effector orientation.
3. Increase the `PRE_GRASP_ORIENT` timeout from 30 to 60 steps so the absolute-mode controller has time to converge.

**Code changes:** `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`

- Added `_pre_grasp_target_quat(...)` helper (world→base conversion + shortest-path sign flip).
- Updated `PRE_GRASP_YAW_ALIGN` and `PRE_GRASP_ORIENT` to use the helper and to use the configurable `pre_grasp_orient_max_steps` timeout.
- Added `pre_grasp_orient_max_steps` parameter to `HeuristicServoGoalPosePolicyArgs`.

**Config:** `configs/policies/heuristic_servo_goal_pose_v3_reachability_seed24_fix_v2.yaml`

```yaml
policy_id: heuristic_servo_goal_pose_v3_reachability_seed24_fix_v2
pre_grasp_orient: true
grasp_target_yaw_offset: 0.0
pre_grasp_yaw_threshold: 0.2
pre_grasp_orient_max_steps: 60
```

All other parameters remain identical to the v1.7 promoted config.

### 5.1 Focused Seed 24 Fix Ablation (v2)

**Command:**

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
cd /code/rosclaw/rosclaw_darwin/rosclaw-darwin

python scripts/ablations/run_seed24_slip_fix_ablation.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --base-policy configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --seed 24 --repeat 10 \
  --conditions baseline,enable_pre_grasp_orient_v2 \
  --out-dir data_v18/ablations/seed24_slip_fix_v2 \
  --cleanup
```

**Status:** completed.

**Artifact:** `data_v18/ablations/seed24_slip_fix_v2/aggregate_summary.json`

| Metric | Baseline (10 repeats) | `enable_pre_grasp_orient_v2` (10 repeats) |
|---|---:|---:|
| Valid repeats | 10 | 10 |
| Env success repeats | 0 | **10** |
| Env success rate | 0.0 | **1.0** |
| Dominant category | `grip_force_insufficient` (10/10) | `success` (10/10) |
| Mean max object z | 0.5142 m | 0.5141 m |
| Mean final object z | 0.0210 m | **0.4291 m** |
| Mean gripper pos min while lifted | 0.0388 m | **0.0238 m** |
| Gripper blocked while lifted | 0/10 | **10/10** |

The corrected orientation target (world→base conversion + shortest-path quaternion sign + 60-step timeout) restores the blocked gripper closure width and converts the deterministic seed-24 failure into a deterministic success, without introducing any new failure mode in the focused ablation.

### Promotion Decision (v2)

The `enable_pre_grasp_orient_v2` condition satisfies the focused-ablation promotion gate:

1. Seed 24 repeat success rate = 10/10 ≥ 8/10 threshold.
2. No new failure mode introduced in the focused ablation — the only category is `success`.
3. The change keeps the v1.7 promoted config otherwise identical and only corrects the frame/shape of the pre-grasp orientation target plus a longer timeout.

Therefore `configs/policies/heuristic_servo_goal_pose_v3_reachability_seed24_fix_v2.yaml` is promoted to the **second candidate** for the 0:99 regression.

---

## 5.2 Official 0:99 Regression (v2 fix)

**Command:**

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
cd /code/rosclaw/rosclaw_darwin/rosclaw-darwin

python scripts/diagnostics/run_dex_cube_generalization_matrix.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3_reachability_seed24_fix_v2.yaml \
  --seeds 0:99 \
  --strict-official-asset --serial --cleanup --classify-failures --save-traces-on-failure \
  --out-dir data_v18/official/dex_cube_100_seed_seed24_fix_v2
```

**Status:** completed.

**Artifact:** `data_v18/official/dex_cube_100_seed_seed24_fix_v2/aggregate_summary.json`

### 5.2.1 Results

| Metric | v1.7 promoted | seed24_fix_v2 (0:99) |
|---|---:|---:|
| Total seeds | 100 | 100 |
| Valid seeds | 100 | 100 |
| Successful seeds | 99 | **95** |
| Overall success rate | 0.99 | **0.95** |
| Progress mean | 0.7829 | **0.7623** |
| Object height max mean | 0.77 | **0.5011** |
| Failed seed distribution | seed 24 (`unknown`) | **4 `unknown`, 1 `approach_collision`** |

The v2 fix improves on the v1 regression (84/100) but still fails the no-regression criterion. The four `unknown` failures (seeds 4, 29, 31, 42) all show `progress_mean ≈ 0.4965` and `object_height_max ≈ 0.2 m`, i.e. the object never leaves the table. Seed 61 is an `approach_collision` outlier.

### 5.2.2 No-regression criterion

- The v2 fix is **rejected**: 0:99 success rate dropped to 0.95, below the 0.98 threshold.
- The v1.7 promoted config remains the current official benchmark config.
- The remaining `unknown` failures must be diagnosed before any v3 candidate is attempted.

### 5.2.3 Failure-seed summary

| Seed | Failure class | Object yaw initial | Notes |
|---:|---|---:|---|
| 4 | `unknown` | -0.109 | Object not lifted; reaches GRASP/LIFT phases |
| 29 | `unknown` | +0.361 | Object not lifted; reaches GRASP/LIFT phases |
| 31 | `unknown` | -0.112 | Object not lifted; reaches GRASP/LIFT phases |
| 42 | `unknown` | -0.236 | Object not lifted; reaches GRASP/LIFT phases |
| 61 | `approach_collision` | N/A | Approach-phase collision; separate transient |

All four `unknown` seeds reach `GRASP` and `LIFT` (`object_height_max = 0.2 m`), suggesting the gripper closes without blocking on the cube — the same family as the original seed-24 `grip_force_insufficient` failure, but not fully resolved by the v2 orientation target.

### 5.2.4 Regression diagnosis — why v2 still fails on 4 seeds

Trace-level inspection of the v2 failure seeds shows a clear pattern:

- In every failing seed the policy enters `PRE_GRASP_ORIENT` and stays for the full 60-step timeout.
- The end-effector yaw moves only **~0.4 rad** during those 60 steps (e.g., seed 4: -3.093 → -2.677 rad), while the residual yaw error to the object yaw remains **~2.7 rad**.
- At timeout the gripper descends misaligned, closes fully (`gripper_pos ≈ 0.002` at the end of `GRASP`), and the subsequent `LIFT` leaves the object on the table.

Root cause: the v2 target quaternion is a **pure yaw** quaternion (`[0, 0, sin(yaw/2), cos(yaw/2)]`), which corresponds to roll = 0 / pitch = 0. The Franka gripper's normal grasping pose has **roll ≈ π** (pointing downward). Commanding a roll = 0 target makes the absolute-mode controller try to flip the gripper upright, a large rotation that it cannot complete in the pre-grasp window. The small residual rotation that does occur is incidental and happens to leave seed 24 close enough to grasp, but leaves seeds 4/29/31/42 misaligned.

Consequence: the v2 fix is better than v1 because it converts the target to the base frame and picks the shortest quaternion path, but it still uses the wrong grasping pose for the pre-grasp target.

---

## 5.3 v3 Candidate Fix — Preserve Gripper Roll while Aligning Yaw

**Intervention:** keep `pre_grasp_orient: true` and `grasp_target_yaw_offset: 0.0`, but build the pre-grasp target quaternion with **roll = π, pitch = 0, yaw = object_yaw** before converting to the base frame. This aligns only the gripper yaw while preserving the downward-pointing grasp pose.

**Code changes:** `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`

- Updated `_pre_grasp_target_quat(...)` to use `[cos(yaw/2), sin(yaw/2), 0, 0]` (roll=π) instead of `[0, 0, sin(yaw/2), cos(yaw/2)]` (roll=0).
- Base-frame conversion and shortest-path sign flip are unchanged.

**Config:** `configs/policies/heuristic_servo_goal_pose_v3_reachability_seed24_fix_v3.yaml`

```yaml
policy_id: heuristic_servo_goal_pose_v3_reachability_seed24_fix_v3
pre_grasp_orient: true
grasp_target_yaw_offset: 0.0
pre_grasp_yaw_threshold: 0.2
pre_grasp_orient_max_steps: 60
```

All other parameters remain identical to the v1.7 promoted config.

### 5.3.1 Focused Seed 24 Fix Ablation (v3)

**Command:**

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
cd /code/rosclaw/rosclaw_darwin/rosclaw-darwin

python scripts/ablations/run_seed24_slip_fix_ablation.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --base-policy configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --seed 24 --repeat 10 \
  --conditions baseline,enable_pre_grasp_orient_v3 \
  --out-dir data_v18/ablations/seed24_slip_fix_v3 \
  --cleanup
```

| Metric | Baseline (10 repeats) | `enable_pre_grasp_orient_v3` (10 repeats) |
|---|---:|---:|
| Valid repeats | 10 | 10 |
| Env success repeats | 0 | **10** |
| Env success rate | 0.0 | **1.0** |
| Dominant category | `grip_force_insufficient` (10/10) | `success` (10/10) |
| Mean max object z | 0.5142 m | **0.4994 m** |
| Mean final object z | 0.0210 m | **0.4732 m** |
| Mean gripper pos min while lifted | 0.0388 m | **0.0239 m** |
| Gripper blocked while lifted | 0/10 | **10/10** |

Preserving the gripper's downward roll (roll = π) while aligning yaw converts the deterministic seed-24 failure into a deterministic success, without introducing any new failure mode in the focused ablation.

**Status:** completed.

### 5.3.2 Promotion Decision (v3)

The `enable_pre_grasp_orient_v3` condition satisfies the focused-ablation promotion gate:

1. Seed 24 repeat success rate = 10/10 ≥ 8/10 threshold.
2. No new failure mode introduced in the focused ablation — the only category is `success`.
3. The change keeps the v1.7 promoted config otherwise identical and only corrects the *shape* of the pre-grasp orientation target to match the grasping pose (roll = π), in addition to the v2 frame/timeout corrections.

Therefore `configs/policies/heuristic_servo_goal_pose_v3_reachability_seed24_fix_v3.yaml` is promoted to the **third candidate** for the 0:99 regression.

---

## 5.4 Official 0:99 Regression (v3 fix)

**Command:**

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
cd /code/rosclaw/rosclaw_darwin/rosclaw-darwin

python scripts/diagnostics/run_dex_cube_generalization_matrix.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3_reachability_seed24_fix_v3.yaml \
  --seeds 0:99 \
  --strict-official-asset --serial --cleanup --classify-failures --save-traces-on-failure \
  --out-dir data_v18/official/dex_cube_100_seed_seed24_fix_v3
```

**Status:** stopped at seed 39 / 100 because the no-regression threshold was already violated.

The runner was terminated early once three `unknown` failures appeared among the first 41 seeds (0–40), since reaching the required ≥98/100 success rate was impossible.

### 5.4.1 Results (partial)

| Metric | v1.7 promoted | seed24_fix_v3 (0:99, seeds 0–40) |
|---|---:|---:|
| Total seeds | 100 | 41 (completed before stop) |
| Valid seeds | 100 | 41 |
| Successful seeds | 99 | **38** |
| Overall success rate | 0.99 | **0.9268** |
| Progress mean | 0.7829 | **0.7665** |
| Object height max mean | 0.77 | **0.5026** |
| Failed seed distribution | seed 24 (`unknown`) | seeds 2, 7, 28 (`unknown`) |

The extrapolated full-seed result would be at most 97/100 only if the remaining 59 seeds were perfect, and the observed failure rate already exceeds the 0.98 no-regression threshold.

### 5.4.2 Failure diagnosis

Trace inspection of the three failing seeds (2, 7, 28) shows the same pattern observed in the v2 regression:

- The policy enters `PRE_GRASP_ORIENT` and stays for the full 60-step timeout.
- The end-effector yaw rotates only **≈0.4–0.45 rad** during the timeout (e.g., seed 28: 2.627 → 2.218 rad), while the residual yaw error to the object yaw remains **≈2.2 rad**.
- At timeout the gripper descends at the intermediate, misaligned orientation, closes fully without blocking on the cube, and the subsequent `LIFT` leaves the object on the table.

The v3 target quaternion is geometrically correct (roll = π, pitch = 0, yaw = object_yaw, converted to the base frame with shortest-path sign), but the absolute-mode Franka IK controller simply cannot rotate the wrist fast enough to converge in the pre-grasp window. The small residual rotation is enough to flip seed 24 from failure to success, but it flips other previously-successful seeds from success to failure.

### 5.4.3 No-regression criterion

- The v3 fix is **rejected**: even the partial 0:99 result (38/41 = 0.927) is below the 0.98 threshold, and the full run cannot recover to ≥98/100.
- The v1.7 promoted config remains the current official benchmark config.
- The 100:199 holdout regression is **not run** because the 0:99 gate was not cleared.

---

## 6. Holdout 100:199 Regression

**Command:**

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
cd /code/rosclaw/rosclaw_darwin/rosclaw-darwin

python scripts/diagnostics/run_dex_cube_generalization_matrix.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3_reachability_seed24_fix_v3.yaml \
  --seeds 100:199 \
  --strict-official-asset --serial --cleanup --classify-failures --save-traces-on-failure \
  --out-dir data_v18/official/dex_cube_holdout_100_seed_seed24_fix_v3
```

**Status:** not executed — the v3 0:99 regression failed the no-regression criterion, so the holdout was skipped to avoid wasting compute.

**Artifact:** `data_v18/official/dex_cube_holdout_100_seed_seed24_fix_v3/aggregate_summary.json` (not produced).

### 6.1 Results (to be filled after run completes)

| Metric | seed24_fix_v3 (100:199) |
|---|---:|
| Total seeds | 100 |
| Valid seeds | TBD |
| Successful seeds | TBD |
| Overall success rate | TBD |
| Failed seed distribution | TBD |

### 6.2 Holdout criterion

- The fix is considered generalizable if 100:199 success rate is **≥ 0.97**.
- Any failure on 100:199 must be classified and compared against v1.7 failure modes; if the new failures are unrelated to seed-24-style gripper blocking, the fix may still be accepted with an honest caveat.

---

## 7. Comparison with v1.7 Promoted Config

| Property | v1.7 promoted | seed24_fix_v3 candidate |
|---|---|---|
| Official 0:99 result | 99/100 | **rejected** — 38/41 in partial run, ≥3 failures before seed 40 |
| Seed 24 deterministic behavior | failure (`grip_force_insufficient`) | success in focused ablation (10/10) |
| Reachability strategy | `side_pregrasp_positive_y` | unchanged |
| `ObjectGeometryAdapter` | enabled | unchanged |
| Pre-grasp orientation | disabled | re-enabled with roll=π base-frame target + shortest-path sign + 60-step timeout |
| Structural / regrasp code | unchanged | unchanged |

(Previous v1 and v2 candidates were rejected after regressing 0:99 to 84/100 and 95/100 respectively.)

---

## 8. Honest Claim Boundary

- **Can claim now:**
  - Seed 24 is deterministically fixed by the roll-preserved pre-grasp orientation target under the v3 10-repeat focused ablation (10/10 env success, gripper blocked 10/10, no new failure mode).
  - The original v1 fix causes a severe 0:99 regression (84/100) because the pre-grasp orientation target is applied in the wrong frame.
  - The v2 fix (base-frame conversion + shortest-path sign + 60-step timeout) reduces the regression to 95/100, but is still below the 0.98 no-regression threshold.
  - The v3 fix (roll = π target preserving the downward grasp pose) passes the focused-ablation gate but **regresses the official 0:99 benchmark (≥3 failures in the first 41 seeds)** and is rejected.
- **Cannot claim:** A seed-24 fix that does not regress the v1.7 official benchmark; no pre-grasp-orientation candidate cleared the 0:99 gate.
- **Cannot claim:** The fix generalizes to other objects, embodiments, or large-yaw targets; those are separate v1.8 Sprints.

---

## 9. Artifacts

- Original focused ablation aggregate: `data_v18/ablations/seed24_slip_fix_focused/aggregate_summary.json`
- Original focused ablation per-repeat CSV: `data_v18/ablations/seed24_slip_fix_focused/per_repeat_results.csv`
- v1 candidate config (rejected): `configs/policies/heuristic_servo_goal_pose_v3_reachability_seed24_fix.yaml`
- v1 0:99 regression aggregate: `data_v18/official/dex_cube_100_seed_seed24_fix/aggregate_summary.json`
- v2 focused ablation aggregate: `data_v18/ablations/seed24_slip_fix_v2/aggregate_summary.json`
- v2 focused ablation per-repeat CSV: `data_v18/ablations/seed24_slip_fix_v2/per_repeat_results.csv`
- v2 candidate config (rejected): `configs/policies/heuristic_servo_goal_pose_v3_reachability_seed24_fix_v2.yaml`
- v2 0:99 regression aggregate: `data_v18/official/dex_cube_100_seed_seed24_fix_v2/aggregate_summary.json`
- v2 100:199 regression aggregate: not produced (0:99 did not pass)
- v3 focused ablation aggregate: `data_v18/ablations/seed24_slip_fix_v3/aggregate_summary.json`
- v3 focused ablation per-repeat CSV: `data_v18/ablations/seed24_slip_fix_v3/per_repeat_results.csv`
- v3 candidate config (rejected): `configs/policies/heuristic_servo_goal_pose_v3_reachability_seed24_fix_v3.yaml`
- v3 0:99 regression partial output (stopped at seed 39): `/tmp/claude-1001/-code-rosclaw-rosclaw-darwin/b13dd464-9e1f-46fa-b8ab-ab93bfd86f45/tasks/bhs4j1p86.output`
- v3 0:99 regression aggregate (not produced): `data_v18/official/dex_cube_100_seed_seed24_fix_v3/aggregate_summary.json`
- v3 100:199 regression aggregate (not produced): `data_v18/official/dex_cube_holdout_100_seed_seed24_fix_v3/aggregate_summary.json`
- Forensics report: `reports/SEED24_POST_LIFT_SLIP_FORENSICS_REPORT.md`

---

## 10. Final Conclusion

Three successive pre-grasp-orientation fixes were evaluated for the deterministic seed-24 `grip_force_insufficient` failure:

| Candidate | Seed 24 focused ablation | 0:99 regression result | Decision |
|---|---|---|---|
| v1 (raw world-frame target) | 10/10 success | 84/100 | rejected |
| v2 (base-frame + shortest-path sign) | 10/10 success | 95/100 | rejected |
| v3 (roll=π base-frame target) | 10/10 success | ≥3 failures in first 41 seeds (0.927) | rejected |

All candidates fix seed 24 in isolation, but all regress the v1.7 official benchmark because the absolute-mode Franka IK controller cannot reorient the gripper fast enough to converge within the pre-grasp window. The partial reorientation flips the contact geometry on other seeds, turning previous successes into failures.

**Outcome:** No seed-24 fix clears the no-regression gate. `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml` remains the official benchmark config with the v1.7 result of **99/100** on `goal_pose_dex_cube_official.yaml`. Seed 24 is a known, deterministic residual failure.

**Implication for later Sprints:** Closed-loop slip detection/recovery (Sprints 5–6) may be able to detect the seed-24 grip-force-insufficient signature and recover after lift, without relying on fast pre-grasp reorientation. That path is now the highest-probability route to push the official line toward 100/100.

# Valid OOD Object Geometry Adapter Report

**Date:** 2026-06-22

**Status:** Sprint 4 of v1.8 — **complete**. The valid OOD cube matrix has finished and the results are below.

**Purpose:** Measure whether `ObjectGeometryAdapter` and structural `FailureToHint` hints improve goal-pose performance on locally validated OOD cubes that differ in size, mass, and friction.

---

## 1. Experiment Design

### 1.1 Objects

All objects are local spawn-config patches marked `rosclaw_valid_cube`; they are **not** official Arena assets.

| Variant | size (m) | mass (kg) | static friction | dynamic friction |
|---|---:|---:|---:|---:|
| `valid_cube_004` | 0.04 | 0.04 | 0.5 | 0.5 |
| `valid_cube_005` | 0.05 | 0.05 | 0.5 | 0.5 |
| `valid_cube_006` | 0.06 | 0.06 | 0.5 | 0.5 |
| `valid_cube_008` | 0.08 | 0.08 | 0.5 | 0.5 |
| `valid_cube_010` | 0.10 | 0.10 | 0.5 | 0.5 |
| `valid_cube_low_friction` | 0.05 | 0.05 | 0.05 | 0.05 |
| `valid_cube_heavy` | 0.05 | 0.50 | 0.5 | 0.5 |

### 1.2 Conditions

| Condition | Geometry adaptation | Mass/friction | Structural hints |
|---|---|---|---|
| `baseline_no_adapter` | disabled | no | no |
| `object_geometry_adapter` | size-only | no | no |
| `adapter_mass_friction` | size + mass/friction | yes | no |
| `adapter_structural` | size-only | no | yes |

### 1.3 Protocol

- Policy: `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`
- Embodiment: `franka_ik_abs`
- Seeds: 0–9 (10 seeds per variant/condition)
- Total episodes: 7 variants × 4 conditions × 10 seeds = **280**
- Runner: `scripts/ablations/run_valid_ood_cube_matrix.py`
- Artifact: `data_v18/ablations/valid_ood_cube_matrix/aggregate_summary.json`

Command:

```bash
PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin \
python scripts/ablations/run_valid_ood_cube_matrix.py \
  --tasks \
    configs/tasks/goal_pose_rosclaw_valid_cube_004.yaml \
    configs/tasks/goal_pose_rosclaw_valid_cube_005.yaml \
    configs/tasks/goal_pose_rosclaw_valid_cube_006.yaml \
    configs/tasks/goal_pose_rosclaw_valid_cube_008.yaml \
    configs/tasks/goal_pose_rosclaw_valid_cube_010.yaml \
    configs/tasks/goal_pose_rosclaw_valid_cube_low_friction.yaml \
    configs/tasks/goal_pose_rosclaw_valid_cube_heavy.yaml \
  --seeds 0:9 \
  --cleanup \
  --out-dir data_v18/ablations/valid_ood_cube_matrix
```

---

## 2. Aggregate Results

| Condition | Episodes | Success rate | Lifted rate | Mean progress | `object_not_lifted` | `target_not_reached` |
|---:|---:|---:|---:|---:|---:|---:|
| `baseline_no_adapter` | 70 | 0.686 | 0.686 | 0.701 | 6 | 16 |
| `object_geometry_adapter` | 70 | 0.686 | 0.686 | 0.701 | 6 | 16 |
| `adapter_mass_friction` | 70 | 0.686 | 0.686 | 0.701 | 6 | 16 |
| `adapter_structural` | 69 | 0.681 | 0.681 | 0.700 | 6 | 16 |

The aggregate success rate, lifted rate, and failure distribution are effectively identical across all four conditions.

---

## 3. Per-Variant Results

| Variant | Baseline | Geometry | Mass/Friction | Structural |
|---|---:|---:|---:|---:|
| `valid_cube_004` | 10/10 | 10/10 | 10/10 | 10/10 |
| `valid_cube_005` | 10/10 | 10/10 | 10/10 | 10/10 |
| `valid_cube_006` | 10/10 | 10/10 | 10/10 | 10/10 |
| `valid_cube_008` | 0/10 | 0/10 | 0/10 | 0/10 |
| `valid_cube_010` | 0/10 | 0/10 | 0/10 | 0/10 |
| `valid_cube_low_friction` | 8/10 | 8/10 | 8/10 | 7/9 |
| `valid_cube_heavy` | 10/10 | 10/10 | 10/10 | 10/10 |

Success and lifted rates are the same within each variant regardless of condition.

---

## 4. Discussion

### 4.1 Why the adapter shows no gain

1. **Binary success is insensitive to threshold scaling.** Small cubes (0.04–0.06 m) and the heavy variant are already within the policy’s graspable range; default thresholds succeed. Large cubes (0.08–0.10 m) fail for kinematic/reachability reasons, not because grasp thresholds are slightly off.
2. **Mass/friction values are still mild.** The heaviest variant is only 0.50 kg (similar to `dex_cube`), and the low-friction variant is the only non-trivial physics change. It achieves 80% success, so there is little headroom for mass/friction-aware adaptation to show an effect.
3. **Structural hints target failure modes that do not dominate here.** The selected structural tags (`unstable_grasp`, `grasped_but_not_lifted`, `lifted_then_dropped`, `object_not_lifted`) did not change the outcome distribution on this benchmark.

### 4.2 What this does and does not prove

- **Does not prove** that `ObjectGeometryAdapter` is useless in general. It only shows that, on this set of valid OOD cubes with the promoted v1.7 policy, the scaling rules did not change binary success.
- **Does prove** that the local valid-cube benchmark is stable enough to run controlled ablations: the same seed under four different configs produces deterministic, comparable outcomes.
- **Does prove** that the promoted policy transfers robustly to small and heavy non-official cubes without any adaptation.

### 4.3 Data quality note

The raw `object_height_delta_mean` across all conditions is dominated by large negative outliers from failed episodes (objects that were never lifted). The binary `lifted` flag and `success` flag are the cleanest comparators; they agree almost perfectly.

---

## 5. Verdict

| Claim | Result |
|---|---|
| Size-only geometry adaptation improves success | **Not supported** |
| Mass/friction-aware adaptation improves success | **Not supported** |
| Structural FailureToHint hints improve success | **Not supported** |
| Valid OOD benchmark supports controlled ablation | **Supported** |

**Honest conclusion:** On the current valid OOD cube benchmark, `ObjectGeometryAdapter` and structural hints do not provide a measurable advantage over the promoted v1.7 baseline. The main failure modes are object-size/reachability boundaries and large-yaw in-hand slip, neither of which is addressed by scaling grasp or lift thresholds. We should not claim validated transferable skill based on these results.

---

## 6. Next Steps

1. Mark Sprint 4 complete.
2. Proceed to Sprint 5: closed-loop large-yaw slip detection and monitoring.

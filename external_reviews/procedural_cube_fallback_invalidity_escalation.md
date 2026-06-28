# Procedural Cube Fallback Invalidity — Arena Escalation Package

**Prepared:** 2026-06-20  
**Status:** Ready to submit / attach to IsaacLab-Arena issue  
**Related tracker:** `reports/ARENA_ISSUE_TRACKER.md` §2.5  
**Blocking claim:** Cross-object / OOD skill evaluation on `procedural_cube` variants.

---

## 1. Executive Summary

The `procedural_cube` fallback that loads when `dex_cube` is not available is not a valid interactive rigid body. Across three procedural task variants and 10 seeds (110 observations each), the object reports:

- `collision_enabled = False` in 100% of observations.
- `bbox_valid = False` in 100% of observations (zero or degenerate bounding box).

Rigid body simulation is enabled and the scene index is consistent, but the object cannot participate in contact dynamics. **Any policy result on the procedural fallback is currently an invalid-environment result, not a policy result.** We are holding all OOD / cross-object benchmark claims until this is fixed.

---

## 2. Evidence

### 2.1 Aggregate validity audit

Script: `scripts/diagnostics/run_procedural_object_validity_audit.py`

Artifact: `data_v17/diagnostics/procedural_object_validity_audit/aggregate_summary.json`

| Task | Valid Rate | Collision Enabled | BBox Valid | Rigid Body Enabled | Index Consistent |
|---|---:|---:|---:|---:|---:|
| `goal_pose_procedural_cube_ood` | 0.0% | 0.0% | 0.0% | 100.0% | 100.0% |
| `goal_pose_procedural_cube_dex_size` | 0.0% | 0.0% | 0.0% | 100.0% | 100.0% |
| `goal_pose_procedural_cube_large` | 0.0% | 0.0% | 0.0% | 100.0% | 100.0% |

Error distribution per task: `invalid_bbox`: 110, `collision_disabled`: 110 (10 seeds × 11 steps).

### 2.2 What the audit checks

`ObjectValidityReport` is computed from `env.scene["object"]` each step:

- `collision_enabled`: `bool(rb.body.data.enable_collision)` for the rigid body handle.
- `bbox_valid`: `bbox[3] > 0` where `bbox` is the axis-aligned bounding box from `rigid_body_properties_view`.
- `rigid_body_enabled`: the object prim exists and has a rigid body API.
- `index_consistency`: the object body index matches the expected `object_index` from the task.

A report is valid only when all four checks are true.

### 2.3 Why this invalidates OOD evaluation

The policy depends on contact between gripper fingers and the object to grasp and lift. With `collision_enabled = False`, the gripper passes through the object or pushes it with unstable/non-physical contact proxies. Lift failures on this asset therefore do not generalize to physical objects. Reporting them as OOD skill failures would be misleading.

---

## 3. Reproduction

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
cd /code/rosclaw/rosclaw_darwin/rosclaw-darwin

python scripts/diagnostics/run_procedural_object_validity_audit.py \
  --tasks configs/tasks/goal_pose_procedural_cube_ood.yaml,configs/tasks/goal_pose_procedural_cube_dex_size.yaml,configs/tasks/goal_pose_procedural_cube_large.yaml \
  --seeds 0:9 \
  --out-dir data_v17/diagnostics/procedural_object_validity_audit \
  --cleanup
```

Expected output: `valid_rate = 0.0` for every task, with errors `invalid_bbox` and `collision_disabled`.

---

## 4. Request to the Arena Team

1. **Confirm** whether the `procedural_cube` fallback is intended to be collision-enabled and geometry-valid.
2. **Provide** the intended collision geometry, bounding box, mass, inertia, and friction parameters for the procedural fallback.
3. **Fix** the asset / spawn path so that `collision_enabled = True` and the bounding box matches the configured `size`.
4. **Clarify** whether `dex_cube` should be expected to resolve in the Docker runtime; if not, what is the supported path for cross-object OOD evaluation?
5. **Until fixed, acknowledge** that `procedural_cube` fallback results should not be reported as OOD skill evaluation.

---

## 5. Local Claim Boundary

Until the procedural fallback passes `valid_rate ≥ 1.0`:

- **Do not report** `procedural_cube` results as OOD skill evaluation.
- **Do not claim** cross-object generalization on procedural variants.
- **Can report** the validity audit itself, the blocked claim boundary, and any policy behavior on the **official `dex_cube`** asset.

---

## 6. Draft GitHub Comment / Issue Text

Below is a ready-to-post comment for the existing Arena issue (e.g., `IsaacLab-Arena#807`) or a new issue if none exists.

```markdown
## Follow-up: procedural cube fallback is invalid for OOD evaluation

We ran an object-validity audit on the `procedural_cube` fallback used when `dex_cube` is not available in the Docker runtime.

**Result:** the fallback object is never valid for contact dynamics.

| Task | Valid Rate | Collision Enabled | BBox Valid |
|---|---:|---:|---:|
| `goal_pose_procedural_cube_ood` | 0.0% | 0.0% | 0.0% |
| `goal_pose_procedural_cube_dex_size` | 0.0% | 0.0% | 0.0% |
| `goal_pose_procedural_cube_large` | 0.0% | 0.0% | 0.0% |

Every observation (10 seeds × 11 steps × 3 tasks = 330 total) reports:
- `collision_enabled = False`
- `bbox_valid = False` (zero or degenerate bounding box)

Rigid body simulation is present (`rigid_body_enabled = 100%`) and the scene index is consistent, but the object cannot participate in physical contact. This means lift/grasp failures on the procedural fallback are **invalid-environment failures**, not policy failures.

**Reproduction:**
```bash
python scripts/diagnostics/run_procedural_object_validity_audit.py \
  --tasks configs/tasks/goal_pose_procedural_cube_ood.yaml,configs/tasks/goal_pose_procedural_cube_dex_size.yaml,configs/tasks/goal_pose_procedural_cube_large.yaml \
  --seeds 0:9 \
  --out-dir data_v17/diagnostics/procedural_object_validity_audit \
  --cleanup
```

**Ask:**
1. Is the `procedural_cube` fallback intended to be collision-enabled?
2. What is the intended collision geometry / bounding box / mass / friction?
3. Can the fallback be fixed to match the official `dex_cube` contact properties?
4. Until fixed, can you confirm that procedural fallback results should not be reported as OOD skill evaluation?

We are blocking all `procedural_cube` OOD claims until `valid_rate = 1.0`.
```

---

## 7. Files Referenced

- `scripts/diagnostics/run_procedural_object_validity_audit.py`
- `data_v17/diagnostics/procedural_object_validity_audit/aggregate_summary.json`
- `data_v17/diagnostics/procedural_object_validity_audit/per_step_validity.csv`
- `reports/ARENA_ISSUE_TRACKER.md`
- `reports/FINAL_DARWIN_V17_STATUS_REPORT.md`

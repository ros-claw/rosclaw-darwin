# Procedural Object Validity Audit Report

**Date:** 2026-06-20

**Status:** Sprint 2 of v1.7 — audit data collection in progress.

**Purpose:** Before any OOD skill adaptation is attempted, determine whether the
procedural cube fallback is a valid interactive rigid body with a reasonable
root pose, bounding box, enabled collision, and consistent metric/policy index.

---

## 1. Method

Script: `scripts/diagnostics/run_procedural_object_validity_audit.py`

Module: `rosclaw_darwin/evaluation/object_validity.py`

Tasks audited:

- `configs/tasks/goal_pose_procedural_cube_ood.yaml`
- `configs/tasks/goal_pose_procedural_cube_dex_size.yaml`
- `configs/tasks/goal_pose_procedural_cube_large.yaml`
- `configs/tasks/goal_pose_procedural_cube_adaptive.yaml`

Audit steps per task/seed:

1. Reset the environment with the requested procedural task config.
2. Run a passive `ObjectValidityAuditPolicy` for 11 steps.
3. Record object root pose, quaternion, linear/angular velocity, bounding box,
   rigid-body/collision flags, mass, friction, table contact, and object index
   consistency at steps 0, 1, 2, 5, 10.
4. Apply `check_object_validity()` rules:
   - `object_z_out_of_bounds`
   - `object_root_pose_unreasonable`
   - `invalid_bbox`
   - `rigid_body_disabled`
   - `collision_disabled`
   - `object_index_mismatch`
   - `table_penetration`

---

## 2. Command

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
cd /code/rosclaw/rosclaw_darwin/rosclaw-darwin

python scripts/diagnostics/run_procedural_object_validity_audit.py \
  --tasks \
    configs/tasks/goal_pose_procedural_cube_ood.yaml \
    configs/tasks/goal_pose_procedural_cube_dex_size.yaml \
    configs/tasks/goal_pose_procedural_cube_large.yaml \
  --seeds 0:9 \
  --out-dir data_v17/diagnostics/procedural_object_validity_audit \
  --cleanup
```

---

## 3. Results

**Artifact:** `data_v17/diagnostics/procedural_object_validity_audit/aggregate_summary.json`

| Task | Valid Rate | Rigid Body % | Collision % | Index Consistency % | Object Z Range | Error Distribution |
|---|---:|---:|---:|---:|---:|---:|
| `goal_pose_procedural_cube_ood` | *pending* | *pending* | *pending* | *pending* | *pending* | *pending* |
| `goal_pose_procedural_cube_dex_size` | *pending* | *pending* | *pending* | *pending* | *pending* | *pending* |
| `goal_pose_procedural_cube_large` | *pending* | *pending* | *pending* | *pending* | *pending* | *pending* |

---

## 4. Answers to the Sprint 2 questions

1. **Procedural object root pose — reasonable?** *pending audit*
2. **`object_z` huge negative value source?** *pending audit*
3. **BBox valid?** *pending audit*
4. **Collision / rigid body enabled?** *pending audit*
5. **Table contact normal?** *pending audit*
6. **Step-0 perturbation writing wrong object?** *pending audit*
7. **Policy/metric/trace reading same object?** *pending audit*
8. **Can procedural OOD continue as valid benchmark?** *pending audit*

---

## 5. Pass criteria

For procedural OOD to re-enter adaptation evaluation:

- `object_z` in reasonable range.
- BBox valid.
- Collision and rigid body enabled.
- No table penetration.
- Metric/policy/trace object index consistent.
- 10 seeds show no catastrophic `object_height_delta`.
- `validity_status = valid`.

If any criterion fails, procedural skill evaluation remains blocked and the
failure is reported as an **invalid environment**, not a policy failure.

---

*ROSClaw-Darwin v1.7 Sprint 2 — to be filled after the audit completes.*

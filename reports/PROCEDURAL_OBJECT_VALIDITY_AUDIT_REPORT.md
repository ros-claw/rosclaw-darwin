# Procedural Object Validity Audit Report

**Date:** 2026-06-20

**Status:** Sprint 2 of v1.7 — **audit complete. Procedural fallback is an invalid interactive object; OOD skill evaluation remains blocked.**

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

Important fix applied during the audit: `_record_to_report` was corrected to
use the host-passed `--table-z` value rather than reading a non-existent
`table_z` field from the container trace record. Without this fix, all records
were spuriously flagged for `table_penetration`.

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
  --audit-steps 11 \
  --table-z 0.02 \
  --out-dir /code/rosclaw/rosclaw_darwin/rosclaw-darwin/data_v17/diagnostics/procedural_object_validity_audit \
  --cleanup
```

---

## 3. Results

**Artifact:** `data_v17/diagnostics/procedural_object_validity_audit/aggregate_summary.json`

| Task | Valid Rate | Rigid Body % | Collision % | Index Consistency % | BBox Valid % | Object Z Range | Error Distribution |
|---|---:|---:|---:|---:|---:|---:|---:|
| `goal_pose_procedural_cube_ood` | **0.0%** | 100.0% | **0.0%** | 100.0% | **0.0%** | [0.047, 0.200] | `invalid_bbox`: 110, `collision_disabled`: 110 |
| `goal_pose_procedural_cube_dex_size` | **0.0%** | 100.0% | **0.0%** | 100.0% | **0.0%** | [0.047, 0.200] | `invalid_bbox`: 110, `collision_disabled`: 110 |
| `goal_pose_procedural_cube_large` | **0.0%** | 100.0% | **0.0%** | 100.0% | **0.0%** | [0.047, 0.200] | `invalid_bbox`: 110, `collision_disabled`: 110 |

Sample size: 10 seeds × 11 steps = 110 reports per task variant.

---

## 4. Answers to the Sprint 2 questions

1. **Procedural object root pose — reasonable?**
   **Yes.** Object `z` is in [0.047 m, 0.200 m], well above the table (`table_z = 0.02 m`) and within reasonable bounds. No `object_z_out_of_bounds` or `object_root_pose_unreasonable` flags.

2. **`object_z` huge negative value source?**
   **Not reproduced in the passive audit.** The catastrophic `object_height_delta ≈ -2496 m` observed during active skill runs is likely a downstream artifact of interacting with an object whose collision geometry is disabled and whose bounding box is invalid, rather than an initial spawn error.

3. **BBox valid?**
   **No.** `bbox_valid_rate = 0.0` across all variants. All 330 reports carry `invalid_bbox`. The procedural fallback reports a zero or degenerate bounding box extent.

4. **Collision / rigid body enabled?**
   **Rigid body is enabled (100%), but collision is disabled (0%).** All 330 reports carry `collision_disabled`. The object cannot be grasped, pushed, or lifted in a physically meaningful way.

5. **Table contact normal?**
   **Object is stably above the table.** With the corrected `table_z = 0.02 m` propagation, no `table_penetration` flags remain. The object rests near `z ≈ 0.05 m`.

6. **Step-0 perturbation writing wrong object?**
   **No.** `object_index_consistency_rate = 1.0` across all variants. Metric, policy, and trace agree on the object index.

7. **Policy/metric/trace reading same object?**
   **Yes.** The object index is consistent across all observation sources.

8. **Can procedural OOD continue as valid benchmark?**
   **No.** The procedural fallback fails two mandatory validity criteria:
   - Invalid bounding box.
   - Disabled collision geometry.
   Until these Arena-side issues are resolved, procedural OOD cannot be used as a valid skill-evaluation benchmark. Any skill failure on this fallback must be classified as an **invalid environment**, not a policy failure.

---

## 5. Pass criteria

For procedural OOD to re-enter adaptation evaluation:

- `object_z` in reasonable range. ✅
- BBox valid. ❌ (currently 0%)
- Collision and rigid body enabled. ❌ (collision 0%)
- No table penetration. ✅
- Metric/policy/trace object index consistent. ✅
- 10 seeds show no catastrophic `object_height_delta`.
  (Cannot be meaningfully evaluated while collision is disabled.)
- `validity_status = valid`. ❌

**Verdict:** Procedural OOD skill evaluation remains **blocked**. The failure is an **invalid environment / asset fallback**, not a policy failure.

---

## 6. External dependency

The invalid bounding box and disabled collision are Arena-side properties of the
procedural fallback. They cannot be repaired from the policy side. The issue is
tracked in `reports/ARENA_ISSUE_TRACKER.md` (IsaacLab-Arena#807) and should be
escalated to the Arena team as a prerequisite for any procedural OOD skill
claims.

---

*ROSClaw-Darwin v1.7 Sprint 2 — audit complete; procedural fallback invalid.*

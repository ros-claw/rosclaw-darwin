# Procedural OOD Recovery After Validity Report

**Date:** 2026-06-20

**Status:** Sprint 6 of v1.7 — blocked until procedural object validity passes.

**Purpose:** If and only if the procedural object validity audit passes, re-run
contact diagnosis, parameter hints, structural FailureToHint v3.1, and
adaptive recovery ablations on a valid OOD task.

---

## 1. Trigger condition

This sprint is only executed if:

- `reports/PROCEDURAL_OBJECT_VALIDITY_AUDIT_REPORT.md` reports
  `validity_status = valid`.
- `reports/PROCEDURAL_OBJECT_VALIDITY_REPAIR_REPORT.md` confirms the recheck
  also passes.

If validity fails, this report will state that **OOD adaptation is postponed**
and procedural OOD remains an invalid environment for skill evaluation.

---

## 2. Planned runs

### 2.1 Contact diagnosis after validity

```bash
python scripts/diagnostics/run_procedural_contact_diagnosis.py \
  --task configs/tasks/goal_pose_procedural_cube_ood.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --seeds 0:9 \
  --with-hints \
  --out-dir data_v17/diagnostics/procedural_contact_after_validity \
  --cleanup
```

### 2.2 Adaptive recovery ablation after validity

```bash
python scripts/ablations/run_procedural_ood_adaptive_recovery.py \
  --task configs/tasks/goal_pose_procedural_cube_ood.yaml \
  --seeds 0:19 \
  --conditions baseline,param_hints,structural_regrasp,best_combined \
  --out-dir data_v17/ablations/procedural_ood_recovery_after_validity \
  --cleanup
```

---

## 3. Metrics

- `success_rate`
- `object_lifted_rate`
- `descend_exit_rate`
- `grasp_reached_rate`
- `lift_phase_reached_rate`
- `contact_proxy_distribution`
- `object_height_max`
- `failure_boundary_advancement`
- `physics_anomaly_rate`

---

## 4. Results

| Condition | Success | Lifted | Descend Exit | Grasp Reached | Lift Reached | FBA |
|---|---:|---:|---:|---:|---:|---:|
| baseline | *pending* | *pending* | *pending* | *pending* | *pending* | *pending* |
| param_hints | *pending* | *pending* | *pending* | *pending* | *pending* | *pending* |
| structural_regrasp | *pending* | *pending* | *pending* | *pending* | *pending* | *pending* |
| best_combined | *pending* | *pending* | *pending* | *pending* | *pending* | *pending* |

---

## 5. Conclusion

- **Did any condition lift the object?** *pending*
- **Did structural FTH v3.1 advance the failure boundary?** *pending*
- **Claim boundary:** Only positive results on a **valid** OOD task can be used
  to argue for adaptive recovery; until then, no OOD adaptation claim is made.

---

*ROSClaw-Darwin v1.7 Sprint 6 — placeholder until procedural validity passes.*

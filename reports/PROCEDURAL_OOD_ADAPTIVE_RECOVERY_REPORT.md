# Procedural OOD Adaptive Recovery Report

**Date:** 2026-06-19

**Goal:** Quantify whether structural FailureToHint v3.1 (regrasp / contact verify / lift verify) advances the failure boundary on the procedural-cube OOD fallback, using the Failure Boundary Advancement (FBA) metric.

---

## 1. Method

Script: `scripts/ablations/run_procedural_ood_adaptive_recovery.py`

Conditions:

- `baseline` — `heuristic_servo_goal_pose_v3.yaml`.
- `param_hints` — geometry-adaptive parameter overrides.
- `regrasp` — enable structural regrasp state machine.
- `side_grasp` — yaw-aligned side grasp.
- `push_to_center` — larger horizontal approach tolerance / higher kp.
- `best_combined` — param hints + regrasp.

FBA is computed as:

```text
mean(max_phase_score_condition) - mean(max_phase_score_baseline)
```

with phase scores:

```python
{"APPROACH": 1, "DESCEND": 2, "GRASP": 3, "LIFT": 4,
 "ALIGN": 5, "HOLD": 6, "SUCCESS": 7}
```

---

## 2. Current observations

Single-seed (seed 0) baseline vs regrasp:

| condition | status | success | descend_exit_rate | object_lifted_rate | FBA |
|---|---|---:|---:|---:|---:|
| baseline | completed | 0.0 | 0.0 | 0.0 | — |
| regrasp | completed | 0.0 | 0.0 | 0.0 | 0.0 |

Both conditions fail before `GRASP`, so regrasp is never triggered. The FBA is 0.

This matches the contact-diagnosis conclusion: the procedural fallback fails upstream of any contact-level recovery.

---

## 3. Honest conclusion

1. Structural regrasp does **not** advance the failure boundary on the current procedural OOD fallback because the policy never reaches `GRASP`.
2. The dominant blocker is **asset-fidelity / geometry mismatch**, not grasp contact quality.
3. Before adaptive recovery can show positive FBA, the policy must at least reach `DESCEND`/`GRASP` on some procedural seeds.
4. The most honest path forward is to treat the procedural fallback as a **diagnostic signal** and continue pushing the asset-fidelity question to the Arena team (`reports/ARENA_ISSUE_TRACKER.md`).

---

## 4. Files changed

- `rosclaw_darwin/evaluation/progress_metrics.py`
- `scripts/ablations/run_procedural_ood_adaptive_recovery.py`
- `reports/PROCEDURAL_OOD_ADAPTIVE_RECOVERY_REPORT.md` (this report)

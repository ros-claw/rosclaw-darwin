# Milestone: ROSClaw-Darwin v1.9 Contact-Aware Residual Infrastructure Frozen

**Date:** 2026-06-25  
**Scope:** Freeze the v1.9 implementation artifacts that v1.10 will build upon.  
**Plan:** [ROSClaw-Darwin v1.10 Implementation Plan](../plans/polished-weaving-pizza.md)

---

## Frozen Artifacts

| Artifact | Purpose | Location |
|---|---|---|
| Official dex_cube baseline policy | No-regression reference for all v1.10 candidates | `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml` |
| Seed-24 conditional micro-recovery policy | First paired no-regression candidate in v1.10 | `configs/policies/heuristic_servo_goal_pose_v3_seed24_micro_recovery.yaml` |
| ContactSignal schema + provider | Unified contact abstraction across phases | `rosclaw_darwin/evaluation/contact_signal.py` |
| Grip quality monitor | Container-fallback-aware grip-quality signal | `rosclaw_darwin/evaluation/grip_quality.py` |
| Residual dataset builder | Convert traces into stratified residual-learning datasets | `rosclaw_darwin/learning/residual_dataset.py` |
| Residual policy wrapper | Bounded residual action with safety clamps | `rosclaw_darwin/learning/residual_policy.py` |
| FailureToHint v3.3 route selection | Explicit recovery routes and claim levels | `rosclaw_darwin/evolution/hint_recipe.py`, `failure_signature_to_hint_rules_v33.yaml` |

---

## What v1.9 Proved

1. **Official baseline is stable** — 99/100 on dex_cube 0:99; the single deterministic residual failure is seed 24.
2. **Seed-24 micro-recovery works in isolation** — 0:99 audit 100/100; triggered seeds (24, 154, 198) succeed.
3. **ContactSignal parity is live** — 12/12 agreement with legacy proxy on classified `CONTACT_VERIFY` steps.
4. **Residual wrapper is safe offline** — `seed24_guard` success-frame trigger rate ≤ 0.22% on combined v17/v19 dataset.
5. **Valid OOD benchmark is valid** — `rosclaw_valid_cube_*` variants pass object-validity audit.
6. **FTH v3.3 blocks false claims** — large-yaw torsional slip is explicitly `blocked_external`.

---

## What v1.10 Must Prove

1. **No-regression is per-seed, not per-rate** — v1.10 replaces aggregate success-rate comparisons with paired `rescued` / `newly_failed` / `unchanged` classification.
2. **Learned models must be small and bounded** — trigger classifier + bounded residual micro-policy only; no full-policy replacement.
3. **OOD gains require medium-difficulty tasks** — baseline success 20%–80%, validity passed, failure boundary clear.
4. **Promotion is evidence-aware** — FTH v3.4 assigns `candidate_recovery` / `experimental_only` / `blocked_external` based on paired evaluation.

---

## Sign-off

v1.9 infrastructure is frozen and ready to serve as the foundation for v1.10 evidence-driven residual evolution.

- [v1.9 Final Status Report](FINAL_DARWIN_V19_STATUS_REPORT.md)
- [v1.10 Paired Evaluation Protocol](PAIRED_EVALUATION_PROTOCOL_REPORT.md)

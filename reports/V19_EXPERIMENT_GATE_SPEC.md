# ROSClaw-Darwin v1.9 Experiment Gate Specification

**Date:** 2026-06-23  
**Status:** v1.9 Sprint 0 — gate config finalized, baseline frozen.

---

## Purpose

This document defines the acceptance criteria that every v1.9 experiment must meet before a result can be promoted, reported as validated, or used to claim a transferable skill. The gates are stored in machine-readable form in `configs/evaluation/darwin_v19_gates.yaml`.

---

## Gate 1 — Official Promotion Gate

### What it protects
The `dex_cube` official benchmark line of **99/100** on seeds 0:99 and **≥98/100** on holdout seeds 100:199.

### Thresholds

| Field | Value | Rationale |
|---|---|---|
| `seeds_main` | `0:99` | The published official line. |
| `min_success_rate_main` | `0.99` | No regression from v1.8. |
| `seeds_holdout` | `100:199` | Unseen seeds to detect overfitting. |
| `min_success_rate_holdout` | `0.98` | Tolerable minor variance on a harder split. |
| `max_physics_anomaly_rate` | `0.0` | Physics anomalies invalidate the result. |
| `max_asset_fallback_count` | `0` | Official benchmark must use the official asset. |
| `max_metric_parser_error_rate` | `0.0` | Metrics must be trustworthy. |
| `max_approach_collision_rate` | `0.0` | New approach collisions are a regression. |
| `min_official_asset_rate` | `1.0` | Every run must resolve the official `dex_cube`. |

### Validation command

```bash
python scripts/diagnostics/run_dex_cube_generalization_matrix.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --seeds 0:99 \
  --strict-official-asset --serial --cleanup --classify-failures \
  --save-traces-on-failure \
  --out-dir data_v19/official/dex_cube_100_seed_baseline
```

### How to fail / what to do
- If `success_rate_main < 0.99`, the candidate is rejected. Keep the v1.7/v1.8 promoted config.
- If `success_rate_holdout < 0.98`, investigate overfitting or instability before any promotion.

---

## Gate 2 — Seed24 Micro-Recovery Gate

### What it protects
Conditional micro-recovery must repair the single deterministic failure (seed 24) without disturbing the rest of the distribution.

### Thresholds

| Field | Value | Rationale |
|---|---|---|
| `seed` | `24` | The only known deterministic residual failure in 0:99. |
| `repeat` | `20` | Enough repeats to estimate success rate. |
| `min_seed24_success_rate` | `0.9` | Must fix at least 18/20 repeats. |
| `max_trigger_rate_on_normal_seeds` | `0.05` | Normal seeds must not be side-effected. |
| `min_official_success_main` | `0.99` | 0:99 must still pass. |
| `min_official_success_holdout` | `0.98` | 100:199 must still pass. |

### Validation commands

Focused seed24 ablation:
```bash
python scripts/ablations/run_seed24_micro_recovery_ablation.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --base-policy configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --seed 24 --repeat 20 \
  --conditions baseline,lower_reclose,z_adjust,grip_verify,best_combined \
  --out-dir data_v19/ablations/seed24_micro_recovery \
  --cleanup
```

Trigger audit on normal seeds:
```bash
python scripts/diagnostics/run_micro_recovery_trigger_audit.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3_seed24_micro_recovery.yaml \
  --seeds 0:99 \
  --out-dir data_v19/diagnostics/micro_recovery_trigger_audit \
  --cleanup
```

### How to fail / what to do
- If `seed24_success_rate < 0.9`, the micro-recovery is not strong enough.
- If `trigger_rate_on_normal_seeds > 0.05`, disable the trigger by default and keep it as a diagnostic-only mode.
- If official success drops, reject the candidate regardless of seed24 improvement.

---

## Gate 3 — Large-Yaw Gate

### What it protects
Any large-yaw residual/recovery candidate must improve orientation success without breaking lift.

### Thresholds

| Field | Value | Rationale |
|---|---|---|
| `target_yaws` | `[1.5708, 2.0944]` | π/2 and 2π/3, the known failure region. |
| `seeds` | `0:19` | Enough seeds for a pilot; serial execution. |
| `min_relative_orientation_gain` | `0.20` | At least 20% relative improvement over baseline at π/2. |
| `max_lift_regression` | `0.05` | Lift must be preserved. |
| `min_lift_rate` | `0.95` | Hard floor for lifted rate. |

### Validation command

```bash
python scripts/ablations/run_residual_policy_pilot.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --base-policy configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --residual-policy residual_rule_slip_guard \
  --target-yaws 1.5708 2.0944 \
  --seeds 0:19 \
  --out-dir data_v19/arena_pilot/residual_slip_guard_large_yaw \
  --cleanup
```

### How to fail / what to do
- If orientation improvement is below 20% relative or lift drops by more than 5%, do not promote the residual policy.
- Report the result as a trend / experimental only.

---

## Gate 4 — Valid OOD Gate

### What it protects
OOD experiments use only the local `rosclaw_valid_cube` variants; procedural fallback remains excluded.

### Thresholds

| Field | Value | Rationale |
|---|---|---|
| `task_family` | `goal_pose_rosclaw_valid_cube` | Only validated local cube configs. |
| `require_validity_rate` | `1.0` | Every variant must pass object validity. |
| `require_collision_enabled_rate` | `1.0` | Collision geometry must be enabled. |
| `require_bbox_valid_rate` | `1.0` | Bounding box must be valid. |
| `require_rigid_body_enabled_rate` | `1.0` | Rigid body must be enabled. |
| `min_positive_delta_object_lifted_rate` | `0.10` | Candidate must improve object-lifted rate by ≥10 points to claim boundary advancement. |
| `min_positive_delta_fba` | `0.5` | Fine-grained behavior advantage threshold. |
| `can_claim_official_benchmark` | `false` | OOD cubes are explicitly not the official benchmark. |

### Validation command

```bash
python scripts/ablations/run_valid_ood_residual_adaptation.py \
  --object-variants valid_cube_008,valid_cube_010,low_friction \
  --subtasks lift_only,lift_hold,yaw_90,full \
  --conditions baseline_v3,ObjectGeometryAdapter,conditional_micro_recovery,residual_seed24_guard,residual_slip_guard,best_combined \
  --seeds 0:19 \
  --out-dir data_v19/ablations/valid_ood_residual_adaptation \
  --cleanup
```

### How to fail / what to do
- If any variant fails the validity audit, stop the experiment and report the blocker.
- If adaptation does not exceed baseline, report `no gain` or `boundary advancement only` — do not claim a validated transferable skill.

---

## Gate 5 — Residual Policy Safety Gate

### What it protects
Residual policies are bounded and cannot destabilize the heuristic base policy.

### Thresholds

| Field | Value | Rationale |
|---|---|---|
| `wrapper_formula` | `final_action = heuristic_action + clip(residual, residual_limits)` | Residual is additive and clamped. |
| `residual_limits.dx/dy/dz` | `0.005 m` | Small Cartesian corrections. |
| `residual_limits.drot_*` | `0.03 rad` | Small rotational corrections. |
| `residual_limits.gripper` | `0.05` | Small gripper corrections. |
| `max_success_frame_trigger_rate` | `0.05` | Must not interfere with successful trajectories. |
| `max_action_norm_increase_factor` | `2.0` | Residual cannot double action magnitude. |
| `require_safety_clamp_trace` | `true` | Every run must record clamp events. |
| `require_residual_enabled_baseline` | `true` | Must compare against `residual_enabled=false`. |

### Validation command

```bash
python scripts/learning/offline_replay_residual_policy.py \
  --dataset data_v19/datasets/residual_learning \
  --residual-policy residual_rule_seed24_guard \
  --out-dir data_v19/offline_replay/residual_rule_seed24_guard
```

### How to fail / what to do
- If a residual violates the clamp, fix the wrapper.
- If success-frame trigger rate > 5%, reduce residual sensitivity or disable it by default.

---

## Gate 6 — FailureToHint v3.3 Claim Gate

### What it protects
No recovery route is promoted to `validated_transferable_skill` without live Arena gain.

### Rules

- `no_claim_without_live_arena_gain: true`
- Allowed experimental claim levels:
  - `diagnosis_only`
  - `boundary_recovery_candidate`
- `validated_transferable_skill` requires:
  - At least 2 OOD variants with measurable gain.
  - A holdout seed split that preserves gain.
  - No official `dex_cube` regression.
  - Evidence that the gain is not a metric or validity artifact.

### How to fail / what to do
- If a rule has no winning Arena strategy, it must be tagged `blocked_external` or `diagnosis_only`.
- Do not emit a `validated_transferable_skill` hint from a rule that has not passed Gate 2, Gate 3, or Gate 4.

---

## Execution Policy

All Docker-backed experiments in v1.9 follow:

- `default_serial: true`
- `default_cleanup: true`
- `one_container_per_run: true`
- Required saved artifacts per run:
  - `command.json`
  - `task.yaml`
  - `policy.yaml`
  - `summary.json`
  - `episode_metrics.jsonl`
  - `phase_trace.jsonl`
  - `contact_signal.jsonl`
  - `slip_signal.jsonl`
  - `grip_quality_signal.jsonl`
  - `failure_signature.json`
  - `asset_info.json`
  - `benchmark_validity.json`
  - `object_validity.json`
  - `stdout.log`
  - `stderr.log`
  - `environment_info.json`

---

## Summary

| Gate | Primary metric | Hard threshold |
|---|---|---|
| Official promotion | 0:99 success rate | ≥ 99/100 |
| Official promotion | 100:199 success rate | ≥ 98/100 |
| Seed24 micro-recovery | seed24 20-repeat success | ≥ 18/20 |
| Seed24 micro-recovery | normal-seed trigger rate | ≤ 5% |
| Large-yaw | π/2 orientation gain | ≥ 20% relative |
| Large-yaw | lift regression | ≤ 5% |
| Valid OOD | validity rate | 1.0 |
| Valid OOD | object-lifted delta | ≥ +10 points |
| Residual safety | success-frame trigger | ≤ 5% |
| FTH v3.3 | validated skill claim | live Arena gain required |

Any result that does not pass the relevant gate is reported at a lower claim level or as not proven.

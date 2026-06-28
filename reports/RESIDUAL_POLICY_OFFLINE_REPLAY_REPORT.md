# Residual Policy Offline Replay Validation Report

## Goal

Establish a bounded residual policy wrapper and validate it offline on the residual dataset built in Sprint 3.  The wrapper enforces `final_action = heuristic_action + clip(residual, limits)` so that a residual policy can never override the heuristic by more than a small, predefined amount.

## Wrapper Design

- `ResidualAction` (Pydantic v2): declares `delta_pos`, `delta_rot`, `delta_gripper`, `active_axes`, `confidence`, and `reason`.
- `ResidualPolicy` (ABC): single method `predict(obs, contact_signal, slip_signal, grip_quality_signal, phase) -> ResidualAction`.
- `ResidualPolicyWrapper`: holds a heuristic action vector and a `ResidualPolicy`.  `compute_final_action` builds the 7-DOF residual vector, pads `active_axes` to length 7, clips each active axis to its limit, and adds it to the heuristic action.

## Residual Limits

| Axis | Limit |
|---|---|
| dx, dy, dz | +/- 0.005 m |
| droll, dpitch, dyaw | +/- 0.03 rad |
| dgripper | +/- 0.05 |

These limits are stored in `DEFAULT_RESIDUAL_LIMITS` and can be overridden per-wrapper instance.

## Baseline Policies

1. `ResidualNonePolicy` — always returns zero residual.  Serves as the safety baseline.
2. `ResidualSeed24GuardPolicy` — activates in `GRASP` / `CONTACT_VERIFY` / `PRE_LIFT` when `grip_quality_signal` reports `low_object_z=True` and `gripper_too_open=True`.  Produces `delta_z = -0.003` and `delta_gripper = -0.03` (tighter close).
3. `ResidualSlipGuardPolicy` — activates when `slip_signal` reports `slip_risk="high"` or `slip_score > 2.0`.  Reduces rotational motion (`droll = -0.02`, `dyaw = -0.02`) and keeps gripper closed (`dgripper = +0.02`).

All policies return `active_axes` so the wrapper knows exactly which indices are modified.

## Offline Replay Command

```bash
python scripts/learning/offline_replay_residual_policy.py \
  --dataset-dir data_v19/datasets/residual_learning \
  --policy none \
  --output-dir data_v19/reports/residual_replay
```

Supported policies: `none`, `seed24_guard`, `slip_guard`.

The script loads `frames.parquet` (or `frames.jsonl` fallback), replays each frame through the selected policy, and writes `replay_summary.json`.

## Safety Thresholds

| Metric | Threshold | Rationale |
|---|---|---|
| `success_frame_trigger_rate` | <= 5% | Residual must not disturb successful trajectories. |
| `safety_clamp_rate` | 0% | No raw residual should exceed the clip limit (indicates policy bug). |
| `residual_action_norm_mean` | < 0.01 | Residual corrections should remain small. |
| `would_modify_success_frames_rate` | <= 5% | Even a non-zero residual that is later clipped to zero counts as a modification attempt. |

## Synthetic Validation Results

A synthetic dataset with 4 frames (2 success, 1 seed24-like failure, 1 slip-like failure) was replayed:

- `none` policy: trigger rate 0%, norm 0, clamp rate 0.  Baseline clean.
- `seed24_guard` policy: success trigger rate 0%, failure trigger rate > 0%, clamp rate 0.  Only the seed24-like frame is modified.
- `slip_guard` policy: success trigger rate 0%, failure trigger rate > 0%, clamp rate 0.  Only the slip-like frame is modified.

All policies satisfy the safety thresholds on the synthetic set.

## Real Dataset Replay (combined seed24 + large-yaw)

A combined residual dataset was built from:

- `data_v19/diagnostics/micro_recovery_trigger_audit_gated_v2_full_rerun` (97 successful dex_cube episodes, seed-level labels).
- `data_v17/diagnostics/large_yaw_slip` (40 large-yaw episodes, trace-level labels keyed by `yaw_* / seed_*`).

The v17 episodes were labelled by `orientation_achieved` rather than environment-level completion, yielding 2 successes and 38 failures. This gives the dataset a meaningful failure class for offline safety checks.

Build command:

```bash
python scripts/learning/build_residual_dataset.py \
  --input-dir data_v17/diagnostics/large_yaw_slip \
  --input-dir data_v19/diagnostics/micro_recovery_trigger_audit_gated_v2_full_rerun \
  --output-dir data_v19/datasets/residual_learning/combined_seed24_large_yaw \
  --per-trace-csv data_v19/datasets/residual_learning/v17_large_yaw_slip_per_trace.csv \
  --per-seed-csv data_v19/diagnostics/micro_recovery_trigger_audit_gated_v2_full_rerun/per_seed_results.csv \
  --train-ratio 0.70 --val-ratio 0.15 --test-ratio 0.15 --jsonl
```

Dataset statistics:

| Metric | Value |
|---|---|
| `num_episodes` | 137 |
| `num_frames` | 342,500 |
| `success_frames` | 247,500 |
| `failure_frames` | 95,000 |
| `seed24_like_frames` | 11,817 |

Offline replay commands:

```bash
python scripts/learning/offline_replay_residual_policy.py \
  --dataset-dir data_v19/datasets/residual_learning/combined_seed24_large_yaw \
  --policy seed24_guard \
  --output-dir data_v19/reports/residual_replay/combined_seed24_large_yaw/seed24_guard

python scripts/learning/offline_replay_residual_policy.py \
  --dataset-dir data_v19/datasets/residual_learning/combined_seed24_large_yaw \
  --policy slip_guard \
  --output-dir data_v19/reports/residual_replay/combined_seed24_large_yaw/slip_guard

python scripts/learning/offline_replay_residual_policy.py \
  --dataset-dir data_v19/datasets/residual_learning/combined_seed24_large_yaw \
  --policy none \
  --output-dir data_v19/reports/residual_replay/combined_seed24_large_yaw/none
```

Results:

| Policy | Trigger rate | Success-frame trigger | Failure-frame trigger | Mean residual norm | Clamp rate | Modifies success frames |
|---|---|---|---|---|---|---|
| `none` | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| `seed24_guard` | 0.001909 | 0.002198 | 0.001158 | 0.000058 | 0.000000 | 0.002198 |
| `slip_guard` | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |

Verdict:

- `seed24_guard` is well below the 5% success-frame trigger threshold and has zero safety clamps. It touches only a tiny fraction of frames, consistent with the conditional micro-recovery design.
- `slip_guard` does not trigger because the v17/v19 traces do not yet contain a structured `slip_signal` field (`slip_score` / `slip_risk`). Once Sprint-2 contact/slip signals are logged, this policy can be re-evaluated.
- `none` baseline is unchanged.

## Files Added

- `rosclaw_darwin/learning/residual_policy.py` — schemas, wrapper, and baseline policies.
- `scripts/learning/offline_replay_residual_policy.py` — CLI replay tool.
- `tests/unit/test_residual_policy_wrapper.py` — unit tests for clipping, activation, and norms.
- `tests/integration/test_residual_offline_replay.py` — integration tests for the CLI on synthetic data.
- `reports/RESIDUAL_POLICY_OFFLINE_REPLAY_REPORT.md` — this report.

## Next Steps (Sprint 5)

1. Arena pilot: run `seed24_guard` on seed 24 repeats (20x) and verify 0:99 regression >= 99/100.
2. Arena pilot: run `slip_guard` on large-yaw seeds (`target_yaw = pi/2`, `2pi/3`) and measure orientation-achieved / lift-hold rates.
3. If both pilots pass safety thresholds, enable residual wrapper in `heuristic_policy.py` behind `enable_residual_policy=True`.
4. Update dashboard with residual-policy views in Sprint 9.

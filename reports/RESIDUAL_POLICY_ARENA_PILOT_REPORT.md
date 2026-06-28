# Arena Residual Policy Pilot Report (Sprint 5 v1.9)

**Status:** Code and configuration complete. Arena runs pending background Docker 0:99 rerun.

## Goal

Wire the bounded residual policy into the heuristic policy so that `seed24_guard`
and `slip_guard` policies can be evaluated in Arena once the current Docker run
finishes. This sprint does **not** claim validated results; it only delivers the
infrastructure and configs ready for evaluation.

## Deliverables

### 1. Configs

- `configs/policies/heuristic_servo_goal_pose_v3_residual_seed24_guard.yaml`
  - `enable_residual_policy: true`
  - `residual_policy: seed24_guard`
  - `residual_enabled_phases: [GRASP, CONTACT_VERIFY, PRE_LIFT]`

- `configs/policies/heuristic_servo_goal_pose_v3_residual_slip_guard.yaml`
  - `enable_residual_policy: true`
  - `residual_policy: slip_guard`
  - `residual_enabled_phases: [LIFT, REORIENT, ALIGN, HOLD]`

Both configs inherit the promoted reachability baseline and conditional
micro-recovery settings from Sprint 1.

### 2. Policy Integration (`heuristic_policy.py`)

**Args added to `HeuristicServoGoalPosePolicyArgs`:**
- `enable_residual_policy: bool = False`
- `residual_policy: str = "none"`
- `residual_enabled_phases: list[str] = field(default_factory=list)`

**`__init__` changes:**
- If `enable_residual_policy` is True, import `ResidualPolicyWrapper`,
  `ResidualSeed24GuardPolicy`, `ResidualSlipGuardPolicy` from
  `rosclaw_darwin.learning.residual_policy` inside a `try/except`.
- Instantiate the appropriate policy and wrapper; store in
  `self._residual_policy` and `self._residual_wrapper`.
- If import fails, disable residual and log to stderr (container fallback).

**`get_action()` changes:**
- After computing the heuristic action (and after any micro-recovery) and before
  `_append_trace()`, if residual is enabled and current phase is in
  `residual_enabled_phases`:
  - Build `obs` dict from current state.
  - Extract `contact_signal`, `slip_signal`, `grip_quality_signal` from existing
    trace/observation data.
  - Call `self._residual_wrapper.compute_final_action(...)`.
  - Convert back to tensor, clamp to action shape.
  - Record residual metadata (`residual_delta_pos`, `residual_delta_rot`, etc.).
- If residual is disabled or phase not allowed, `final_action = heuristic_action`.

**`_append_trace()` changes:**
- Added fields: `residual_enabled`, `residual_policy`, `residual_delta_pos`,
  `residual_delta_rot`, `residual_delta_gripper`, `residual_active_axes`,
  `residual_confidence`, `residual_reason`, `final_action`.
- Existing trace fields remain unchanged.

**Container fallback:**
- If `rosclaw_darwin.learning.residual_policy` cannot be imported, define minimal
  `_ResidualPolicyWrapper` and `_ResidualNonePolicy` no-op classes.
- Alias `ResidualPolicyWrapper = _ResidualPolicyWrapper` so the policy does not
  crash when config accidentally enables residual in a container without the host
  module.

### 3. Pilot Runner (`scripts/ablations/run_residual_policy_pilot.py`)

CLI: `--policy {seed24_guard|slip_guard}`, `--seeds`, `--out-dir`, `--dry-run`.

- **seed24_guard:**
  - Default seeds: 24 (20 repeats) and 0:99 regression.
  - Uses `heuristic_servo_goal_pose_v3_residual_seed24_guard.yaml`.
  - Outputs: aggregate summary, `per_seed_results.csv`, `summary.json`.
  - Tracks: `residual_trigger_count`, `residual_trigger_steps`, `success_rate`,
    `normal_trigger_rate` (excluding seed 24).

- **slip_guard:**
  - Default: `target_yaws [1.5708, 2.0944]` with seeds 0:19.
  - Uses `heuristic_servo_goal_pose_v3_residual_slip_guard.yaml`.
  - Injects `target_yaw_override` into policy config per run.
  - Outputs: per-yaw summary, `per_seed_results.csv`, `summary.json`.
  - Tracks: `trigger_rate`, `orientation_achieved_rate`, `lifted_rate`.

### 4. Smoke Tests

- `tests/arena/test_seed24_micro_recovery_smoke.py`
  - Instantiates policy with seed24_guard config.
  - Verifies `reset()` and `get_action()` with dummy env do not crash.
  - Verifies residual disabled by default.

- `tests/arena/test_residual_policy_pilot_smoke.py`
  - Instantiates policies with both seed24_guard and slip_guard configs.
  - Verifies trace fields are present when residual is enabled.
  - Does not run Docker; uses dummy observations.

### 5. Validation Plan (Pending Arena Runs)

**seed24_guard:**
- seed24 repeat success >= 18/20.
- 0:99 regression >= 99/100.
- normal seeds trigger rate <= 5%.

**slip_guard:**
- large-yaw pi/2 `orientation_achieved_rate` relative gain >= 20%.
- `lifted_rate` regression <= 5%.

If no gain is observed, residual infrastructure will be retained but
`enable_residual_policy` will remain default `False`, and the report will be
marked as `experimental / not proven`.

## Constraints Observed

- `enable_residual_policy` default is `False` so the existing 0:99 audit is
  unaffected.
- No existing `ContactSignal`, `GripQualityMonitor`, or micro-recovery logic was
  removed or altered.
- `rosclaw_darwin/learning/residual_policy.py` and `residual_dataset.py` were
  not modified.
- No Docker/Arena jobs were started.

## Files Changed / New

| File | Status |
|------|--------|
| `configs/policies/heuristic_servo_goal_pose_v3_residual_seed24_guard.yaml` | New |
| `configs/policies/heuristic_servo_goal_pose_v3_residual_slip_guard.yaml` | New |
| `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py` | Modified |
| `scripts/ablations/run_residual_policy_pilot.py` | New |
| `tests/arena/test_seed24_micro_recovery_smoke.py` | New |
| `tests/arena/test_residual_policy_pilot_smoke.py` | New |
| `reports/RESIDUAL_POLICY_ARENA_PILOT_REPORT.md` | New |

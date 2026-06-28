# Valid OOD Learned Adaptation Benchmark Report

## Scope

This report documents Sprint 7 of ROSClaw-Darwin v1.10: a **valid OOD learned adaptation benchmark** that re-runs the Sprint 6 selected medium-difficulty tasks under a v1.10 condition matrix and compares each candidate against the promoted v3 baseline in a per-seed paired fashion.

The Sprint 7 matrix isolates three adaptation mechanisms:

- Hand-written rule micro-recovery (`lower_reclose`).
- Learned trigger model gating the same rule action.
- Learned trigger model gating a small bounded residual regressor.
- FailureToHint v3.3 route/parameter selection.

## Condition matrix

| Condition | What is enabled |
|---|---|
| `baseline_v3` | Promoted heuristic servo goal-pose v3; no micro-recovery, no residual, no geometry adaptation beyond the frozen baseline. |
| `rule_micro_recovery` | `enable_grip_quality_monitor=True` + `micro_recovery_strategy=lower_reclose`. |
| `learned_trigger_only` | Grip-quality monitor stays enabled, but the physical recovery action is gated by a learned trigger model (`triggered_rule`). This isolates the trigger's value from the residual regressor's value. |
| `learned_trigger_plus_bounded_residual` | `triggered_bounded_learned`: the trigger model gates a bounded residual micro-policy whose action space is restricted to `dz`, `dgripper`, and `lift_speed_scale`. |
| `FTH_v33_selected_route` | `ObjectGeometryAdapter` + skill hints selected from the v3.3 hint recipe registry for the unstable-grasp / not-lifted failure family. |

All non-baseline conditions are compared **per seed** against `baseline_v3` to compute `paired_rescued`, `paired_newly_failed`, `paired_unchanged_success`, and `paired_unchanged_failure`.

## Component

### `scripts/ablations/run_valid_ood_learned_adaptation_benchmark.py`

CLI that reads `data_v20/diagnostics/valid_ood_medium_task_mining/selected_tasks.yaml` (Sprint 6 output) and runs the condition matrix.

Inputs:

- `--selected-tasks`: Sprint 6 `selected_tasks.yaml`.
- `--tasks`: fallback task configs if the selected-tasks file is absent.
- `--policy`: base policy config (`heuristic_servo_goal_pose_v3_reachability_promoted.yaml`).
- `--conditions`: subset of the five v1.10 conditions.
- `--seeds`: seed range, default `0:49`.
- `--trigger-model-path`: learned trigger model JSON.
- `--bounded-residual-model-path`: bounded residual model JSON.
- `--trigger-threshold`: trigger probability threshold (default `0.5`).
- `--hint-rules`: v3.3 hint recipe YAML (required when `FTH_v33_selected_route` is used).

Outputs:

```
data_v20/ablations/valid_ood_learned_adaptation/
  per_seed_results.csv
  aggregate_summary.json
```

`aggregate_summary.json` extends the Sprint 6 summary with:

- `residual_trigger_rate` for `learned_trigger_only` and `learned_trigger_plus_bounded_residual`.
- Paired metrics `paired_rescued`, `paired_newly_failed`, `paired_unchanged_success`, `paired_unchanged_failure`, `paired_valid_seeds` for every `(task, subtask, condition)` tuple.

### Container-side support

`rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py` was extended to load the new `triggered_rule` residual policy in addition to the existing `bounded_learned` and `triggered_bounded_learned` paths. If the trigger model file is missing inside the Docker container, the policy falls back to disabling the residual branch and keeps the hand-written grip-quality monitor active.

### `TriggeredRuleResidualPolicy`

A small wrapper in `rosclaw_darwin/learning/bounded_residual_policy.py` that loads a learned trigger model and returns a fixed `lower_reclose` residual action when the trigger fires. This lets Sprint 7 measure the trigger model's contribution independently of the bounded residual regressor.

## Validation performed

### Unit tests (`tests/unit/test_bounded_residual_policy.py`)

- `test_triggered_rule_policy_fires_and_returns_rule_action` — trigger fires on a low-object-z / gripper-too-open GRASP frame and returns the expected `dz=0.015`, `dgripper=-0.05` action; it returns a no-op on a clearly successful frame.
- `test_load_triggered_rule_policy_roundtrip` — `load_triggered_rule_policy()` loads a saved trigger model and preserves the configured thresholds/action parameters.

### Integration test (`tests/integration/test_valid_ood_learned_adaptation_benchmark.py`)

- `test_learned_adaptation_benchmark_dry_run` — runs the full CLI with `--dry-run` and asserts that the matrix size, selected task list, and all requested conditions are printed without invoking Docker.
- `test_learned_adaptation_benchmark_rejects_unknown_condition` — asserts that an unsupported condition causes a clean error exit.

### Lint

```bash
ruff check rosclaw_darwin/learning/bounded_residual_policy.py \
  rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py \
  scripts/ablations/run_valid_ood_learned_adaptation_benchmark.py \
  tests/unit/test_bounded_residual_policy.py \
  tests/integration/test_valid_ood_learned_adaptation_benchmark.py
```

All checks passed.

## Test results

```
tests/unit/test_bounded_residual_policy.py::test_bounded_mlp_trains_and_residuals_are_clamped PASSED
tests/unit/test_bounded_residual_policy.py::test_save_load_roundtrip PASSED
tests/unit/test_bounded_residual_policy.py::test_factory_creates_mlp PASSED
tests/unit/test_bounded_residual_policy.py::test_factory_rejects_unknown_type PASSED
tests/unit/test_bounded_residual_policy.py::test_bounded_residual_policy_predict_shape PASSED
tests/unit/test_bounded_residual_policy.py::test_wrapper_applies_lift_speed_scale PASSED
tests/unit/test_bounded_residual_policy.py::test_evaluate_offline_metrics PASSED
tests/unit/test_bounded_residual_policy.py::test_triggered_residual_policy_gates_by_trigger PASSED
tests/unit/test_bounded_residual_policy.py::test_load_triggered_residual_policy_roundtrip PASSED
tests/unit/test_bounded_residual_policy.py::test_triggered_rule_policy_fires_and_returns_rule_action PASSED
tests/unit/test_bounded_residual_policy.py::test_load_triggered_rule_policy_roundtrip PASSED

11 passed

tests/integration/test_valid_ood_learned_adaptation_benchmark.py::test_learned_adaptation_benchmark_dry_run PASSED
tests/integration/test_valid_ood_learned_adaptation_benchmark.py::test_learned_adaptation_benchmark_rejects_unknown_condition PASSED

2 passed
```

## Honest status

- **Benchmark harness**: complete, tested, and lint-clean.
- **Container-side loading**: `triggered_rule`, `bounded_learned`, and `triggered_bounded_learned` are all wired with fallback to disabled residual if model files are missing.
- **Live Arena evidence**: **not yet collected**. The report will be updated after running the full matrix on the Sprint 6 selected tasks with seeds `0:49`.

Until live data is available, the Sprint 7 benchmark runner is ready and validated on synthetic / dry-run inputs.

## Required questions to answer after live benchmark

1. For each selected task, what is the baseline success rate and the success rate under each condition?
2. Which conditions produce `paired_rescued >= 1` with `paired_newly_failed == 0`?
3. What is the residual trigger rate on baseline-success seeds (false-positive rate) for the learned-trigger conditions?
4. Does `FTH_v33_selected_route` shift the first-failing-subtask boundary or improve object-lifted rate without creating newly-failed seeds?
5. Are there any container-side model-loading failures or physics anomalies?

## Files

- `scripts/ablations/run_valid_ood_learned_adaptation_benchmark.py`
- `rosclaw_darwin/learning/bounded_residual_policy.py`
- `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`
- `tests/unit/test_bounded_residual_policy.py`
- `tests/integration/test_valid_ood_learned_adaptation_benchmark.py`
- `reports/VALID_OOD_LEARNED_ADAPTATION_BENCHMARK_REPORT.md`

## Relation to other v1.10 sprints

- **Sprint 6**: `mine_valid_ood_medium_tasks.py` produces the `selected_tasks.yaml` consumed by this runner.
- **Sprint 9**: FTH v3.4 will use the Sprint 7 paired evaluation to assign evidence-aware promotion statuses.
- **Sprint 10**: dashboard views will display the paired delta tables and residual trigger rates produced here.

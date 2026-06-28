# Valid OOD Medium-Task Selection Report

## Scope

This report documents Sprint 6 of ROSClaw-Darwin v1.10: mining **valid OOD medium-difficulty tasks** for learned adaptation. A medium task is defined as one where the promoted v3 baseline succeeds on the `full` goal_pose subtask in **20%–80%** of seeds. Tasks outside this band are either too easy (no adaptation signal) or too hard (likely invalid geometry or impossible physics). The selected tasks feed Sprint 7's learned adaptation benchmark.

## Why medium difficulty matters

- **Too easy** (success >= 80%): any measured gain is noise; adaptation cannot be distinguished from sampling variance.
- **Too hard** (success <= 20%): baseline is either failing at a fundamental physics/collision boundary or the task itself is invalid; learned residuals risk hallucinating recovery success.
- **Medium** (20%–80%): there is a clear failure boundary and enough successes to define a positive residual target, while enough failures remain to measure improvement.

## Component

### `scripts/diagnostics/mine_valid_ood_medium_tasks.py`

CLI that reads the aggregate summary produced by `run_valid_ood_subtask_decomposition.py` and emits:

```
data_v20/diagnostics/valid_ood_medium_task_mining/
  selected_tasks.yaml
  rejected_tasks.yaml
  difficulty_table.csv
  mining_result.json
```

Selection logic:

1. Only considers entries with `subtask == "full"` and `condition == "baseline_v3"`.
2. Optional `--validity-file` JSON restricts selection to task IDs that passed the object-validity gate.
3. Classifies each task as one of:
   - `selected` — success rate in `[success_min, success_max]`
   - `too_easy` — success rate `>= success_max`
   - `too_hard` — success rate `<= success_min`
   - `invalid_geometry` — `reachability_failure_rate` or `gripper_aperture_limit_rate` above threshold
   - `insufficient_data` — fewer than `--min-seeds` completed runs
   - `invalid_validity` — failed the validity gate
4. For selected tasks, computes:
   - `first_failing_subtask` (inherited from the subtask decomposition summary)
   - `dominant_failure` — heuristic failure mode
   - `recommended_adaptation_axis` — maps failure mode to a Sprint 7 adaptation axis

### Failure-to-axis mapping

| Dominant failure | Recommended adaptation axis |
|---|---|
| `in_hand_slip` | `slip_monitor / lower_speed_scale` |
| `reachability_failure` | `reachability_aware_approach` |
| `grasp_failure` / `object_not_lifted` | `grip_quality / lower_reclose` |
| `orientation_misalignment` | `orientation_alignment / residual_yaw` |
| fallback | `object_geometry_adapter` |

## Validation performed

### Unit tests (`tests/unit/test_medium_task_mining.py`)

- `test_mines_medium_tasks` — easy/medium/hard classification.
- `test_respects_custom_thresholds` — custom `[success_min, success_max]`.
- `test_invalid_geometry_rejected` — reachability-dominant tasks rejected.
- `test_insufficient_data_rejected` — low seed count rejected.
- `test_validity_set_filters_tasks` — optional validity gate filters tasks.
- `test_ignores_non_full_or_non_baseline_entries` — only mines the correct slice.
- `test_dominant_failure_and_axis` — slip tasks map to slip axis.
- `test_recommended_axis_for_grasp_failure` — grasp failures map to grip-quality axis.
- `test_difficulty_table_sorted` — output table sorted by baseline success rate.

### Integration test (`tests/integration/test_mine_valid_ood_medium_tasks.py`)

- Builds a synthetic `aggregate_summary.json` with one medium task and one saturated task.
- Runs the CLI as a subprocess.
- Asserts all four output files are written and the correct task is selected/rejected.

### Lint

```bash
ruff check scripts/diagnostics/mine_valid_ood_medium_tasks.py \
  tests/unit/test_medium_task_mining.py \
  tests/integration/test_mine_valid_ood_medium_tasks.py
```

All checks passed.

## Test results

```
tests/unit/test_medium_task_mining.py::test_mines_medium_tasks PASSED
tests/unit/test_medium_task_mining.py::test_respects_custom_thresholds PASSED
tests/unit/test_medium_task_mining.py::test_invalid_geometry_rejected PASSED
tests/unit/test_medium_task_mining.py::test_insufficient_data_rejected PASSED
tests/unit/test_medium_task_mining.py::test_validity_set_filters_tasks PASSED
tests/unit/test_medium_task_mining.py::test_ignores_non_full_or_non_baseline_entries PASSED
tests/unit/test_medium_task_mining.py::test_dominant_failure_and_axis PASSED
tests/unit/test_medium_task_mining.py::test_recommended_axis_for_grasp_failure PASSED
tests/unit/test_medium_task_mining.py::test_difficulty_table_sorted PASSED

9 passed in 0.06s

tests/integration/test_mine_valid_ood_medium_tasks.py::test_mine_valid_ood_medium_tasks_cli PASSED

1 passed in 0.16s
```

## Honest status

- **Mining logic**: complete, tested, and lint-clean.
- **Input dependency**: requires `run_valid_ood_subtask_decomposition.py` aggregate summary with baseline_v3 / full subtask data.
- **Real selection**: **not yet executed** on a live v1.10 subtask decomposition matrix. Once executed, the report will be updated with:
  - The actual selected task list.
  - The rejected-task reasons.
  - Answers to the four required questions (see below).

Until live data is available, the medium-task mining harness is ready and the selection pipeline is validated on synthetic inputs.

## Required questions to answer after live mining

1. How many valid OOD tasks were evaluated and how many fell into the 20%–80% band?
2. What is the first failing subtask for each selected task?
3. Are the selected tasks physically valid (collision geometry, mass, friction) and reproducible?
4. Which adaptation axis does each selected task suggest, and why?

## Files

- `scripts/diagnostics/mine_valid_ood_medium_tasks.py`
- `tests/unit/test_medium_task_mining.py`
- `tests/integration/test_mine_valid_ood_medium_tasks.py`
- `reports/VALID_OOD_MEDIUM_TASK_SELECTION_REPORT.md`

## Relation to other v1.10 sprints

- **Sprint 3/4/5**: the residual dataset, trigger model, and bounded residual model provide the adaptation mechanisms tested on Sprint 6's selected tasks.
- **Sprint 7**: `run_valid_ood_learned_adaptation_benchmark.py` will read `selected_tasks.yaml` and compare baseline_v3 / rule_micro_recovery / learned_trigger_only / learned_trigger_plus_bounded_residual / FTH_v33_selected_route.
- **Sprint 9**: FTH v3.4 will use the Sprint 7 paired evaluation to decide whether any OOD adaptation can be promoted beyond `experimental_only`.

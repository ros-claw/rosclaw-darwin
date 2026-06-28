# Learned Bounded Residual Micro-Policy Report

## Scope

This report documents Sprint 5 of ROSClaw-Darwin v1.10: a **small learned residual regressor** restricted to three bounded axes — `dz`, `dgripper`, and `lift_speed_scale` — for grip-quality failures. The micro-policy is designed to be:

- **Small**: single hidden-layer MLP (default hidden dim 16, tunable).
- **Bounded**: hard output clamps on every axis, learned inside the feasible region.
- **Residual only**: does not replace the heuristic policy; it is applied through `ResidualPolicyWrapper`.
- **Evidence-gated**: offline safety replay must pass before any live Arena pilot.

## Components

### `rosclaw_darwin/learning/bounded_residual_policy.py`

Implements the model, policy wrapper, factory, and offline evaluator.

- `BoundedResidualModel` — abstract base with JSON-serializable weights.
- `BoundedMLPResidualModel` — small MLP with:
  - input = `ResidualDataset.to_residual_target_matrix()` feature vector
  - hidden layer + ReLU + 0.1 dropout
  - output = `[dz, dgripper, lift_speed_scale]`
  - hard clamping **at inference only**; clamping is intentionally removed during training so gradients can reach in-bound targets that start outside the feasible region
- `BoundedResidualPolicy` — implements `ResidualPolicy.predict()`:
  - active only in `GRASP`, `CONTACT_VERIFY`, `PRE_LIFT`, `LIFT`, `LIFT_VERIFY`, `HOLD`
  - output activates axis 2 (`dz`) and axis 6 (`gripper`)
  - includes `lift_speed_scale` for phases where `ResidualPolicyWrapper` scales heuristic z
- `create_bounded_residual_model(...)` — factory (currently `mlp` only)
- `evaluate_bounded_residual_offline(...)` — offline replay safety metrics

### `scripts/learning/train_bounded_residual_policy.py`

CLI that loads a saved `ResidualDataset` v2, trains the bounded residual model, and writes:

```
<output-dir>/
  model.json
  metrics.json
```

Training options include `--hidden-dim`, `--epochs`, `--lr`, `--batch-size`, `--patience`, `--dz-limit`, `--dgripper-limit`, `--speed-min`, `--speed-max`, and `--random-seed`.

## Feature contract with `ResidualDataset`

`ResidualDataset.to_residual_target_matrix()` returns:

- `X` — phase one-hot + numeric observation keys + grip-quality/slip/contact booleans
- `Y` — residual target mapped to `[dz, dgripper, lift_speed_scale]`
- `feature_names` — ordered list used by `BoundedResidualPolicy._observation_to_features()`
- `phases` — phase vocabulary (one-hot prefix)
- `axes` — one-hot residual-axis mask

The same saved dataset feeds both the trigger classifier (Sprint 4) and the bounded residual regressor (Sprint 5).

## Bounded action space

```yaml
residual_axes:
  dz: true
  gripper: true
  lift_speed_scale: true
  dx: false
  dy: false
  drot_x: false
  drot_y: false
  drot_z: false

residual_limits:
  dz: 0.004
  gripper: 0.05
  lift_speed_scale: [0.5, 1.0]
```

These limits are enforced in the model at training time and at inference time, so the residual can never exceed the configured envelope even if the network extrapolates.

## Offline replay safety metrics

`evaluate_bounded_residual_offline` computes:

| Metric | Meaning | Gate |
|---|---|---|
| `mse` / `mae` | Regression quality on residual target | — |
| `clamp_rate` | Fraction of predictions that hit a limit | `<= 10%` preferred |
| `success_frame_modification_rate` | Fraction of successful frames that receive non-zero residual | `<= 5%` hard gate |
| `mean_residual_norm` / `max_residual_norm` | Magnitude of residual on position axes | low preferred |
| `dz_min/max`, `dgripper_min/max`, `lift_speed_scale_min/max` | Observed range per axis | must stay inside limits |

## Validation performed

### Unit tests (`tests/unit/test_bounded_residual_policy.py`)

1. `test_bounded_mlp_trains_and_residuals_are_clamped`
   - Synthetic 100-sample regression task.
   - Asserts all predictions are inside configured `dz`, `dgripper`, and `lift_speed_scale` limits.
2. `test_save_load_roundtrip`
   - JSON-serializable weights survive save/load; predictions are bit-exact.
3. `test_factory_creates_mlp` / `test_factory_rejects_unknown_type`
4. `test_bounded_residual_policy_predict_shape`
   - `ResidualAction` produced by the policy activates only axes 2 and 6 and sets `lift_speed_scale`.
5. `test_wrapper_applies_lift_speed_scale`
   - Verifies `ResidualPolicyWrapper.compute_final_action` scales heuristic z during `LIFT` when `lift_speed_scale != 1.0`.
6. `test_evaluate_offline_metrics`
   - Offline replay metrics are computed without error on a tiny synthetic dataset.

### Integration test (`tests/integration/test_train_bounded_residual_policy.py`)

- Builds a temporary `ResidualDataset` v2 with:
  - 10 success frames (residual target = 0)
  - 10 seed24-like failure frames (negative `dz`, negative `dgripper`)
- Invokes `scripts/learning/train_bounded_residual_policy.py` as a subprocess.
- Asserts `model.json` and `metrics.json` are written and `metrics.test.clamp_rate` is in `[0, 1]`.

### Lint

All new and modified files pass `ruff check`:

```bash
ruff check rosclaw_darwin/learning/bounded_residual_policy.py \
  scripts/learning/train_bounded_residual_policy.py \
  tests/unit/test_bounded_residual_policy.py \
  tests/integration/test_train_bounded_residual_policy.py
```

## Test results

```
tests/unit/test_bounded_residual_policy.py::test_bounded_mlp_trains_and_residuals_are_clamped PASSED
tests/unit/test_bounded_residual_policy.py::test_save_load_roundtrip PASSED
tests/unit/test_bounded_residual_policy.py::test_factory_creates_mlp PASSED
tests/unit/test_bounded_residual_policy.py::test_factory_rejects_unknown_type PASSED
tests/unit/test_bounded_residual_policy.py::test_bounded_residual_policy_predict_shape PASSED
tests/unit/test_bounded_residual_policy.py::test_wrapper_applies_lift_speed_scale PASSED
tests/unit/test_bounded_residual_policy.py::test_evaluate_offline_metrics PASSED
tests/integration/test_train_bounded_residual_policy.py::test_train_bounded_residual_policy_cli PASSED

8 passed in 8.53s
```

## Training run on `data_v20/datasets/residual_learning_v2`

A bounded residual MLP was trained on the existing v2 residual dataset (342,500
frames, 23 input features).  The dataset lacks explicit speed annotations, so
`lift_speed_scale` target defaults to 1.0 (no change).  For seed-24-like frames
(low object z + gripper too open) in active phases, the residual target is
overridden with the hand-authored `lower_reclose` action (`dz = 0.015`,
`dgripper = -0.05`) so the model has a concrete correction to learn.

Offline replay metrics on the test split:

| Metric | Value | Gate |
|---|---|---|
| `mse` | ~3e-7 | — |
| `success_frame_modification_rate` | **0.27%** | `<= 5%` ✅ |
| `clamp_rate` | **0.0%** | `<= 10%` ✅ |
| `mean_residual_norm` | ~2.5e-4 | low preferred |
| `max_residual_norm` | ~8.3e-3 | inside limits |
| `dz` range | [-2.7e-5, 2.4e-3] | inside [-0.004, 0.004] |
| `dgripper` range | [-7.9e-3, 2.2e-4] | inside [-0.05, 0.05] |
| `lift_speed_scale` range | [0.999, 1.0] | inside [0.5, 1.0] |

The offline safety gate passes, but the correction magnitude on seed-24-like
frames is small; the model learns the correlation direction but is conservative.
A learned trigger model is required to gate when the residual is applied so that
success frames are not modified.

## Live Arena pilot (triggered bounded residual on `dex_cube` `0:199`)

The bounded residual model was combined with the learned trigger model and
evaluated in a paired Arena pilot on official `dex_cube` seeds `0:199` against
the frozen v1.9 baseline.

Paired summary (`data_v20/paired/triggered_learned_0_199/paired_summary.json`):

| Metric | Value |
|---|---|
| `total_pairs` | 200 |
| `valid_pairs` | 200 |
| `baseline_success_rate` | 0.970 |
| `candidate_success_rate` | 0.970 |
| `rescued_count` | **0** |
| `newly_failed_count` | **0** |
| `unchanged_success_count` | 194 |
| `unchanged_failure_count` | 6 |
| `invalid_pair_count` | 0 |
| `mcnemar_p_value` | 1.0 |

Safety: **passes**.  The residual never modified a baseline-success seed into a
failure.  All 200 pairs are valid; there were no infrastructure failures, asset
fallbacks, or physics anomalies.

Efficacy: **does not pass the promotion gate**.  No baseline-failing seeds were
rescued.  The bounded residual is either too conservative on the six remaining
failure cases or the trigger did not fire at the right moments.

## Honest status

- **Offline infrastructure**: complete and gated (success-frame modification rate, clamp rate, residual norm).
- **Model serialization**: complete — weights are stored as nested lists in JSON, so the model loads without `sklearn` in the Arena container.
- **Offline safety replay on v2 dataset**: **passes** (`success_frame_modification_rate ≈ 0.27%`, `clamp_rate = 0%`).
- **Live Arena pilot**: **completed**.  The combination is **safe** (`newly_failed_count = 0`) but **not yet effective** (`rescued_count = 0`).  It remains an **experimental recovery component** until `rescued_count >= 1` is demonstrated.

Next tuning options:

1. Use the learned trigger to gate the stronger hand-authored `lower_reclose`
   action (`triggered_rule` policy) to verify the trigger fires on the right
   frames.
2. Strengthen the residual target on seed-24-like frames and re-train the
   bounded residual model.
3. Lower `trigger_threshold` to increase recall while monitoring the
   success-frame trigger rate stays below 5%.

## Files

- `rosclaw_darwin/learning/bounded_residual_policy.py`
- `scripts/learning/train_bounded_residual_policy.py`
- `tests/unit/test_bounded_residual_policy.py`
- `tests/integration/test_train_bounded_residual_policy.py`
- `reports/LEARNED_BOUNDED_RESIDUAL_MICRO_POLICY_REPORT.md`

## Relation to other v1.10 sprints

- **Sprint 4**: the bounded residual model consumes the same `ResidualDataset` features and is triggered by the learned trigger model or a rule trigger.
- **Sprint 7**: if the learned trigger + bounded residual passes the live pilot on official seeds, it can be evaluated on Sprint 6's selected medium OOD tasks.
- **Sprint 9**: FTH v3.4 will not promote this recovery beyond `experimental_only` until paired no-regression evidence is available.

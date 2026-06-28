# Learned Trigger Model Report (Sprint 4)

**Date:** 2026-06-26  
**Plan:** [ROSClaw-Darwin v1.10 Implementation Plan](../plans/polished-weaving-pizza.md)  
**Module:** `rosclaw_darwin/learning/trigger_model.py`  
**Trainer:** `scripts/learning/train_trigger_model.py`

---

## Goal

Train a small learned trigger classifier that predicts when the residual
micro-recovery policy should be activated, and compare it against the
hand-written seed-24-like heuristic.  The trigger model must:

- Use only the feature matrix exported by `ResidualDataset.to_feature_matrix()`.
- Remain small (logistic, tiny MLP, or gradient-boosted with PyTorch fallback).
- Achieve high recall on seed-24-like failures while keeping the success-frame
  false-positive rate low.
- Serialize to a container-loadable JSON artifact.

---

## Methods

### Feature extraction

`ResidualDataset.to_feature_matrix()` was extended to emit a fixed numeric
matrix from every frame:

- Phase one-hot (e.g. `APPROACH`, `GRASP`, `LIFT`, `HOLD`).
- Observation scalars: `object_z`, `gripper_pos`, `eef_z`,
  `orientation_error`, `object_eef_distance`, `object_eef_yaw_delta`.
- Inferred booleans: `gripper_too_open`, `low_object_z`.
- Slip signal: `any_slip`, `slip_score`.
- Contact signal: `contact_confidence`, `has_contact`.

Four label modes are supported:

| Label mode | Positive class |
|---|---|
| `seed24_like` | Frames matching the seed-24-like heuristic. |
| `grip_failure` | Failed episodes with grip / not-lifted / slip failure types. |
| `pair_rescued` | Frames whose seed was `rescued` in paired evaluation. |
| `pair_failure` | Frames whose seed was `rescued` or `unchanged_failure`. |

### Model family

Three model classes are implemented in `trigger_model.py`:

1. `LogisticTriggerModel` — PyTorch logistic regression (no hidden layers).
2. `SmallMLPTriggerModel` — one hidden layer (default 16 units), ReLU,
   10% dropout, sigmoid output.
3. `GBTriggerModel` — `sklearn.ensemble.GradientBoostingClassifier` when
   available; falls back to `SmallMLPTriggerModel` in containers without
   sklearn.

All models support `fit`, `predict_proba`, `predict`, `save`, and `load`.
Weights are serialized as JSON-compatible nested lists in `model.json`.

### Training

`train_trigger_model.py` loads a saved v2 dataset, builds train/val/test
feature matrices with a consistent phase vocabulary, trains the selected model
with early stopping on the validation set, and writes:

- `model.json` — model config and weights.
- `metrics.json` — per-split metrics including accuracy, precision, recall,
  F1, FPR, AUROC, AUPRC, calibration error, success-frame FPR, seed24-like
  recall, and trigger rate by phase.

---

## Validation

### Unit tests

`tests/unit/test_trigger_model.py` covers:

- Training and prediction shape/validity for logistic and MLP models.
- Save/load round-trip equality of probabilities.
- Linear separability sanity check for the logistic model.
- Evaluation metric computation.
- `GBTriggerModel` fallback path when sklearn is unavailable.

### Integration tests

`tests/integration/test_train_trigger_model.py` builds a synthetic v2 dataset
(10 success frames, 10 seed24-like failure frames), runs the CLI, and asserts
that `model.json` and `metrics.json` are produced with non-trivial test
accuracy.

### Lint

`ruff check` passes on all new and modified modules.

---

## Results

A `SmallMLPTriggerModel` was trained on the existing `data_v20/datasets/residual_learning_v2`
dataset with label mode `seed24_like` (positive = frame matching the seed-24-like
heuristic: low object z and gripper too open).  The dataset contains 342,500
frames; the positive class is heavily imbalanced (~2.4% positive).  Training ran
with early stopping and stopped at epoch 54 (best validation loss 0.00671).

Per-split metrics:

| Split | n | Positives | Accuracy | Precision | Recall | F1 | FPR | AUROC | Success-frame FPR |
|---|---|---|---|---|---|---|---|---|---|
| train | 239,750 | 8,235 | 0.9977 | 0.9371 | 1.000 | 0.9675 | 0.0024 | 0.9997 | 0.0032 |
| val | 51,375 | 1,860 | 0.9980 | 0.9470 | 1.000 | 0.9728 | 0.0021 | 0.9997 | 0.0028 |
| test | 51,375 | 1,722 | 0.9975 | 0.9313 | 1.000 | 0.9644 | 0.0026 | 0.9996 | 0.0034 |

Key observations:

- **Recall on seed-24-like frames is 1.0** on all splits; the model does not miss
  any labeled seed-24-like frame.
- **Success-frame false-positive rate is ~0.3%**, well below the 5% gate and far
  better than a naive always-trigger baseline.
- **AUROC / AUPRC are near-perfect**, indicating that the state features
  (`object_z`, `gripper_pos`, etc.) are highly predictive of the seed-24-like
  heuristic label.
- **Calibration error is low** (< 0.001), so the output probability can be used
  directly for threshold tuning if needed.

Trigger rate by phase (test split):

| Phase | Trigger rate |
|---|---|
| APPROACH | 27.8% |
| DESCEND | 25.4% |
| SIDE_PREGRASP | 24.0% |
| GRASP | 0.7% |
| LIFT / HOLD / VERIFY_OBJECT_FOLLOWING / GRIP_QUALITY_RECOVERY | 0.0% |

The high trigger rate in `APPROACH`, `DESCEND`, and `SIDE_PREGRASP` is expected
because the seed-24-like heuristic (`low_object_z` + `gripper_too_open`) is
satisfied early in an episode, before the gripper has closed on the object.  This
is not a failure of the classifier; it simply reflects the definition of the
heuristic label.  The downstream `BoundedResidualPolicy` is phase-gated and only
acts in `GRASP`, `LIFT`, `HOLD`, and related recovery phases, so an
`APPROACH`-phase trigger does not cause an unsafe residual action.  For a future
live pilot, the trigger should be combined with the same phase gate (or the
label should be restricted to post-grasp frames) to ensure the residual fires
only when it can physically help.

### Offline gate assessment

| Gate | Required | Test result | Pass |
|---|---|---|---|
| seed24-like recall >= 0.9 | yes | 1.000 | ✅ |
| success-frame FPR <= 5% | yes | 0.34% | ✅ |
| AUROC > 0.8 | preferred | 0.9996 | ✅ |

The offline trigger-model gate passes.  However, the true safety test is a live
Arena pilot: the trigger must not fire on baseline-success seeds in a way that
converts them to failures, and it must actually permit the bounded residual to
rescue seed-24-like failures.

## Live Arena pilot (triggered bounded residual on `dex_cube` `0:199`)

A paired Arena pilot was run on official `dex_cube` seeds `0:199` comparing the
frozen v1.9 baseline against the candidate policy that combines the learned
trigger model (`trigger_threshold = 0.5`) with the bounded residual micro-policy.

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

Safety verdict: **no regression** — the learned trigger + bounded residual
does not break any baseline-success seeds (`newly_failed_count = 0`,
`invalid_pair_count = 0`, no asset fallback or physics anomaly).

Efficacy verdict: **no rescue** — none of the six baseline-failing seeds were
rescued (`rescued_count = 0`).  Candidate and baseline success rates are
identical (0.970).  This means the trigger either did not fire on the failing
frames or the bounded residual correction was insufficient to change the
outcome on these particular seeds.

Because the hard safety gate (`newly_failed_count = 0`) passes but the efficacy
gate (`rescued_count >= 1`) does not, the learned trigger + bounded residual
combination is classified as a **safe experimental component**, not a promoted
recovery.  For promotion, either the trigger threshold must be lowered, a
hand-authored `lower_reclose` action must be used when the trigger fires
(`triggered_rule` policy), or the residual target must be strengthened on the
six remaining failure modes.
---

## Limitations

1. **Label definition fires early in the episode:** `seed24_like` is satisfied in
   `APPROACH` / `DESCEND` / `SIDE_PREGRASP` because the heuristic only checks
   `low_object_z` and `gripper_too_open`.  The classifier therefore triggers
   heavily before the residual can legally act.  For a live pilot, the trigger
   must be combined with the residual policy's phase gate (or the label must be
   restricted to post-grasp frames).
2. **Live Arena pilot completed but did not rescue failures:** The trigger +
   bounded residual ran on all 200 official `0:199` pairs without causing any
   `newly_failed` seeds, but it also rescued zero seeds.  Efficacy must be
   improved before promotion.
3. **Feature set is intentionally narrow:** It excludes raw images, full action
   history, and tactile arrays; these are out of scope for v1.10's small-model
   mandate.
4. **Label leakage risk:** `seed24_like` labels are derived from the same
   observations the model sees; `pair_rescued` labels (preferred) require a
   paired-evaluation summary, but only two rescued seeds exist in the current
   dataset, which is too few for a learned classifier.

---

## Artifacts

- Module: `rosclaw_darwin/learning/trigger_model.py`
- Trainer: `scripts/learning/train_trigger_model.py`
- Dataset helpers: `rosclaw_darwin/learning/residual_dataset.py`
- Unit tests: `tests/unit/test_trigger_model.py`
- Integration tests: `tests/integration/test_train_trigger_model.py`

---

## Conclusion

The learned trigger-model infrastructure is implemented, tested, and now trained
on the full `data_v20/datasets/residual_learning_v2` dataset.  The `seed24_like`
`SmallMLPTriggerModel` achieves near-perfect recall (1.000) and a success-frame
false-positive rate below 0.35% on all splits, comfortably passing the offline
trigger gate.  Model weights are serialized to JSON and load without `sklearn` in
the Arena container.

The live paired Arena pilot on official `dex_cube` seeds `0:199` shows that the
learned trigger + bounded residual is **safe but not yet effective**: no
baseline-success seeds were converted to failures (`newly_failed_count = 0`),
but no failing seeds were rescued (`rescued_count = 0`).  The combination
therefore remains an **experimental component** and does not meet the promotion
gate.  The offline metrics are strong enough that a different residual action
(e.g. the hand-authored `lower_reclose` used by the seed-24 micro-recovery) or a
lower trigger threshold may unlock a rescue without sacrificing safety.

---

## Next steps

1. Run a `triggered_rule` paired Arena pilot that uses the learned trigger to
   gate the hand-authored `lower_reclose` micro-recovery; this isolates whether
   the trigger is firing on the right frames.
2. If the trigger is correct but the bounded residual is too weak, increase the
   residual target magnitude on seed-24-like frames and re-train.
3. Try lowering `trigger_threshold` to increase recall at the cost of a higher
   success-frame trigger rate, staying below the 5% gate.
4. Once `rescued_count >= 1` and `newly_failed_count = 0` are both satisfied,
   evaluate the promoted combination on Sprint 6's selected medium OOD tasks.

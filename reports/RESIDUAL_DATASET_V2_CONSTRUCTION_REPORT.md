# Residual Dataset v2 Construction Report (Sprint 3)

**Date:** 2026-06-25  
**Plan:** [ROSClaw-Darwin v1.10 Implementation Plan](../plans/polished-weaving-pizza.md)  
**Module:** `rosclaw_darwin/learning/residual_dataset.py`  
**Builder:** `scripts/learning/build_residual_dataset_v2.py`

---

## Goal

Evolve the v1.9 residual dataset into a v2 dataset that carries explicit
labels for downstream v1.10 tasks:

- `pair_label` — per-seed paired-evaluation delta class (`rescued`,
  `newly_failed`, `unchanged_success`, `unchanged_failure`, `invalid_pair`).
- `route_label` — per-frame route decision for large-yaw recovery
  (`continue`, `pause`, `lower_regrip`, `abort_safe`, `blocked_external`).
- `medium_ood_label` — per-frame label for valid OOD medium-task boundaries
  (`first_failing_subtask`, `success_noop`, etc.).

The v2 dataset must remain backward-compatible with the v1.9 residual policy
wrapper and must expose train/val/test splits plus the new label manifests.

---

## Methods

### Schema additions

`ResidualFrame` gained six new optional fields:

| Field | Type | Purpose |
|---|---|---|
| `pair_label` | `str \| None` | Paired-evaluation delta class for the seed. |
| `route_label` | `str \| None` | Per-frame route decision. |
| `medium_ood_label` | `str \| None` | Per-frame medium-OOD boundary label. |
| `trigger_model_score` | `float \| None` | Score from learned trigger model. |
| `bounded_residual` | `list[float]` | Output of bounded residual micro-policy. |

### Builder additions

`ResidualDataset.save()` now emits v2 artifacts:

```
data_v20/datasets/residual_learning_v2/
  frames.parquet
  frames.jsonl
  episodes.jsonl
  metadata.yaml              # version: v2
  split_train.json
  split_val.json
  split_test.json
  pair_labels.jsonl          # NEW
  route_labels.jsonl         # NEW
  medium_ood_labels.jsonl    # NEW
```

`scripts/learning/build_residual_dataset_v2.py` orchestrates the build:

1. Loads traces from one or more `--input-dir` directories.
2. Optionally loads a `--paired-summary` (`paired_summary.json`) and assigns
   `pair_label` to every frame whose seed appears in the summary.
3. Optionally loads `--route-labels` and `--medium-ood-labels` JSONL files and
   assigns per-frame `route_label` / `medium_ood_label`.
4. Re-splits the merged frames into train/val/test episodes.
5. Calls `ResidualDataset.save()` to write the v2 artifact tree.

### Label semantics

- `pair_label = rescued` — candidate fixed this seed; residual target should
  encode the successful recovery.
- `pair_label = newly_failed` — regression; residual target should be zero
  (do not learn from regressions).
- `pair_label = unchanged_success` — baseline already succeeded; residual
  target should be near zero.
- `pair_label = unchanged_failure` — both policies failed; label may be used
  for diagnosis-only route labels.
- `route_label = blocked_external` — large-yaw slip with no honest recovery;
  residual target must be zero.
- `medium_ood_label = first_failing_subtask` — frames at the boundary where the
  baseline first fails on a medium-difficulty OOD task.

---

## Validation

### Unit tests

- `test_residual_frame_v2_fields` — verifies the new Pydantic fields.
- `test_save_outputs_v2_label_files` — verifies that `save()` emits
  `pair_labels.jsonl`, `route_labels.jsonl`, and `medium_ood_labels.jsonl`.

### Integration tests

- `test_build_v2_with_pair_labels` — runs the v2 builder with a synthetic trace
  and paired summary, asserts `pair_label == rescued` on all frames and
  `metadata.version == v2`.
- `test_build_v2_without_labels_runs` — confirms the builder runs even when no
  optional label files are provided.

### Lint

`ruff check` passes for:

- `rosclaw_darwin/learning/residual_dataset.py`
- `scripts/learning/build_residual_dataset_v2.py`
- `tests/unit/test_residual_dataset_schema.py`
- `tests/integration/test_residual_dataset_build.py`
- `tests/integration/test_residual_dataset_v2_build.py`

---

## Results

The v2 schema and builder are implemented and tested.  Because the full live
`0:199` paired evaluation (Sprint 1) is still running in the background, a
complete v2 dataset with real `pair_label` coverage has not been built yet.

A synthetic validation build confirmed:

- 2 frames from one seed are correctly labeled `rescued` from the paired summary.
- Output metadata version is `v2`.
- All required output files are produced.

---

## Limitations

1. **Real dataset pending:** The builder cannot be run on the full official
   benchmark until the Sprint 1 paired evaluation completes.
2. **Route and medium-OOD labels are stubbed:** No real route classifier or
   medium-task mining has been run yet, so `--route-labels` and
   `--medium-ood-labels` are optional and currently unused in live data.
3. **No holdout split:** The current split remains train/val/test.  A dedicated
   holdout split for final model selection will be added in Sprint 4 if needed.

---

## Artifacts

- Module: `rosclaw_darwin/learning/residual_dataset.py`
- Builder: `scripts/learning/build_residual_dataset_v2.py`
- Unit tests: `tests/unit/test_residual_dataset_schema.py`
- Integration tests:
  - `tests/integration/test_residual_dataset_build.py`
  - `tests/integration/test_residual_dataset_v2_build.py`

---

## Conclusion

Residual Dataset v2 is schema-ready and builder-ready.  The new fields and
label manifests provide the data contract needed by:

- Sprint 4 (learned trigger model)
- Sprint 5 (bounded residual micro-policy)
- Sprint 7 (valid OOD learned adaptation)
- Sprint 8 (large-yaw route classifier)

The full v2 dataset build will be executed as soon as the Sprint 1 paired
evaluation artifacts are available.

---

## Next steps

1. Wait for Sprint 1 full `0:199` paired evaluation to complete.
2. Run `build_residual_dataset_v2.py` on the paired-evaluation output to create
   the first real v2 dataset.
3. Add route labels after Sprint 8 and medium-OOD labels after Sprint 6.
4. Proceed to Sprint 4: train a small learned trigger model on the v2 dataset.

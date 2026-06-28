# Slip-aware Residual Dataset Construction Report (v1.9 Sprint 3)

**Date:** 2026-06-24
**Status:** implementation complete, synthetic validation passed, real dataset build pending trace availability
**Module:** `rosclaw_darwin/learning/residual_dataset.py`
**CLI:** `scripts/learning/build_residual_dataset.py`

---

## 1. Goal

Convert v1.7/v1.8 success and failure traces into a structured residual-learning dataset without training a full policy. The dataset must support:

- Per-frame residual targets (`executed_action - heuristic_action`).
- Sample-weighted learning (failure frames weighted higher).
- Stratified train/val/test splits by episode.
- Graceful handling of missing traces, missing heuristic actions, and missing signal fields.

---

## 2. Schema

### 2.1 `ResidualFrame` (Pydantic v2)

| Field | Type | Description |
|---|---|---|
| `episode` | `int` | Episode identifier |
| `step` | `int` | Step index within episode |
| `task` | `str` | Task identifier |
| `object_name` | `str \| None` | Object name if known |
| `seed` | `int \| None` | Random seed if known |
| `phase` | `str` | Policy phase (APPROACH, GRASP, LIFT, ...) |
| `observation` | `dict[str, Any]` | Subset of trace observation fields |
| `heuristic_action` | `list[float]` | Base heuristic action vector |
| `executed_action` | `list[float]` | Actually executed action vector |
| `success_label` | `bool` | Episode-level success |
| `failure_type` | `str \| None` | Inferred failure type (from `failure_signature.py` if available) |
| `contact_signal` | `dict \| None` | Contact signal snapshot if present in trace |
| `slip_signal` | `dict \| None` | Slip signal snapshot if present in trace |
| `grip_quality_signal` | `dict \| None` | Grip quality signal snapshot if present in trace |
| `residual_target` | `list[float]` | `executed_action - heuristic_action` |
| `residual_mask` | `list[bool]` | Which action axes may be modified (default all True) |
| `sample_weight` | `float` | Class weight: 2.0 for failure, 1.0 for success |

### 2.2 `ResidualDataset`

- **Construction:** `from_traces(trace_dir, summary_path=None, seed_success_map=None)` loads all `trace.jsonl` files recursively, pairs them with per-episode metadata from an optional aggregate summary JSON, and computes residual targets. An optional `seed_success_map` (e.g. from a per-seed audit CSV) overrides summary metadata for matching seeds.
- **Splitting:** `train/val/test` are 70/15/15 by episode, stratified by `success_label`, with a configurable random seed.
- **Persistence:** `save(output_dir)` writes:
  - `frames.parquet` (or `frames.jsonl` fallback)
  - `episodes.jsonl`
  - `metadata.yaml`
  - `split_train.json`, `split_val.json`, `split_test.json`

---

## 3. Sample Classes

The dataset is designed to capture three canonical classes:

### Class A: Success no-op
- **Source:** Successful dex_cube official traces.
- **Residual target:** ~0 (heuristic action already optimal).
- **Weight:** 1.0.
- **Purpose:** Teach the residual policy to stay near zero on already-successful trajectories.

### Class B: Seed-24-like grip failure
- **Source:** Seed 24 and similar low-object-z / wide-gripper traces.
- **Residual target:** Small negative z adjustment, tighter gripper re-close.
- **Weight:** 2.0.
- **Purpose:** Provide supervised signal for the `residual_rule_seed24_guard` baseline.

### Class C: Large-yaw slip
- **Source:** `data_v17/diagnostics/large_yaw_slip`, `data_v18/diagnostics/slip_monitor_validation`.
- **Residual target:** Reduced yaw motion, maintained grip, pose-hold.
- **Weight:** 2.0.
- **Purpose:** Provide supervised signal for the `residual_rule_slip_guard` baseline.

---

## 4. Build Commands

### Default multi-source build

```bash
python scripts/learning/build_residual_dataset.py \
  --input-dir data_v17/diagnostics/large_yaw_slip \
  --input-dir data_v18/diagnostics/slip_monitor_validation \
  --input-dir data_v18/ablations/slip_aware_recovery \
  --input-dir data_v18/ablations/valid_ood_cube_matrix \
  --input-dir data_v19/diagnostics/micro_recovery_trigger_audit_gated_v2 \
  --output-dir data_v19/datasets/residual_learning \
  --train-ratio 0.70 \
  --val-ratio 0.15 \
  --test-ratio 0.15
```

### Seed-level success labels from audit CSV

When summary JSONs do not contain per-episode success metadata, use a per-seed audit CSV (e.g. `per_seed_results.csv`) to label episodes:

```bash
python scripts/learning/build_residual_dataset.py \
  --input-dir data_v19/diagnostics/micro_recovery_trigger_audit_gated_v2_full_rerun \
  --output-dir data_v19/datasets/residual_learning/seed24_micro_recovery \
  --per-seed-csv data_v19/diagnostics/micro_recovery_trigger_audit_gated_v2_full_rerun/per_seed_results.csv \
  --train-ratio 0.70 \
  --val-ratio 0.15 \
  --test-ratio 0.15
```

The CLI gracefully skips missing directories and aggregates all valid traces into a unified dataset with a single stratified split.

---

### Trace-level success labels from audit CSV

When the same seed is reused across conditions (e.g. different target yaws or OOD variants), a global seed map is ambiguous. Use `--per-trace-csv` with `trace_path` and `success` columns to label exact traces. The key is the path of the `trace.jsonl` file relative to its input directory:

```bash
python scripts/learning/build_residual_dataset.py \
  --input-dir data_v17/diagnostics/large_yaw_slip \
  --output-dir data_v19/datasets/residual_learning/v17_large_yaw_slip \
  --per-trace-csv data_v19/datasets/residual_learning/v17_large_yaw_slip_per_trace.csv \
  --train-ratio 0.70 --val-ratio 0.15 --test-ratio 0.15
```

The CLI accepts multiple `--per-trace-csv` options and combines them with `--per-seed-csv`. Trace-level labels take precedence over seed-level labels and summary metadata.

### Force JSONL output

Nested signal dicts (contact, slip, grip quality) do not round-trip cleanly through `pandas.json_normalize` + parquet. Use `--jsonl` to emit `frames.jsonl` instead:

```bash
python scripts/learning/build_residual_dataset.py ... --jsonl
```

`frames.jsonl` is the canonical format for downstream offline replay and residual learning.

---

## 5. Statistics

### 5.1 Synthetic validation dataset

A temporary synthetic dataset (3 frames, 1 episode, success) was used for unit and integration testing. All statistics logic validated:

- `num_episodes`: 1
- `num_frames`: 3
- `success_frames`: 3
- `failure_frames`: 0
- `phase_distribution`: `{"APPROACH": 1, "GRASP": 1, "LIFT": 1}`
- Splits: train/val/test episode counts sum to 1.

### 5.2 Real dataset

A real dataset was built from the gated 0:99 micro-recovery audit traces using the per-seed success override:

```bash
python scripts/learning/build_residual_dataset.py \
  --input-dir data_v19/diagnostics/micro_recovery_trigger_audit_gated_v2_full_rerun \
  --output-dir data_v19/datasets/residual_learning/seed24_micro_recovery \
  --per-seed-csv data_v19/diagnostics/micro_recovery_trigger_audit_gated_v2_full_rerun/per_seed_results.csv \
  --train-ratio 0.70 --val-ratio 0.15 --test-ratio 0.15
```

Resulting statistics:

| Metric | Value |
|---|---|
| `num_episodes` | 97 |
| `num_frames` | 242,500 |
| `success_frames` | 242,500 |
| `failure_frames` | 0 |
| `slip_frames` | 0 |
| `seed24_like_frames` | 0 *(all frames are from successful episodes)* |
| `phase_distribution` | APPPROACH 29,779; DESCEND 1,823; GRASP 6,249; LIFT 5,969; VERIFY_OBJECT_FOLLOWING 485; REORIENT 136,063; STABILIZE 540; ALIGN 31,532; HOLD 29,962; SIDE_PREGRASP 89; GRIP_QUALITY_RECOVERY 9 |
| splits | train 67 episodes, val 14 episodes, test 16 episodes |

Notes:
- Only 97 episodes are present because three seeds failed with null metrics and did not produce traces.
- The per-seed CSV supplied 97 `completed` labels, all with `env_success_rate = 1.0`, so every frame is a success-frame no-op residual target.
- The `GRIP_QUALITY_RECOVERY` phase appears in 9 frames (seed 24 only), providing a concrete recovery trajectory for future residual learning.
- v1.7/v1.8 large-yaw and valid-OOD traces were not available at the expected paths; the CLI correctly skips missing directories.

---

### 5.3 Combined v17 large-yaw + v19 seed24 micro-recovery dataset

To create a success/failure mix for offline replay, the v17 large-yaw traces were labelled by `orientation_achieved` (the relevant task-level success signal for goal_pose) and merged with the v19 seed24 micro-recovery traces. Episode IDs are renumbered globally when multiple input directories are supplied, so no episodes collide.

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

Resulting statistics:

| Metric | Value |
|---|---|
| `num_episodes` | 137 |
| `num_frames` | 342,500 |
| `success_frames` | 247,500 |
| `failure_frames` | 95,000 |
| `slip_frames` | 0 *(traces lack structured slip_signal fields)* |
| `seed24_like_frames` | 11,817 |
| `phase_distribution` | APPROACH 42,095; DESCEND 2,613; GRASP 8,849; LIFT 8,435; VERIFY_OBJECT_FOLLOWING 685; REORIENT 175,473; STABILIZE 850; ALIGN 45,707; HOLD 57,671; SIDE_PREGRASP 113; GRIP_QUALITY_RECOVERY 9 |
| splits | train 95 episodes, val 19 episodes, test 23 episodes |

Notes:
- The v17 large-yaw traces are labelled by `orientation_achieved` because the environment-level `env_success_rate` is 1.0 for all large-yaw runs even when the cube does not reach the target yaw.
- The combined dataset is emitted as `frames.jsonl` to preserve nested signal dicts for offline replay.
- This dataset is used for the real-data offline replay in [Residual Policy Offline Replay Report](RESIDUAL_POLICY_OFFLINE_REPLAY_REPORT.md).

---

## 6. Tests

### Unit tests (`tests/unit/test_residual_dataset_schema.py`)

- `ResidualFrame` schema validation with defaults and full construction.
- Serialization round-trip (`model_dump()`).
- `ResidualDataset.from_traces()` with synthetic traces:
  - Basic construction, success/failure weight assignment.
  - Missing `heuristic_action` defaults to `executed_action` (zero residual).
  - Default `residual_mask` all True.
  - Stratified 70/15/15 split with 10 episodes (5 success, 5 failure).
- Helper extraction functions: `_extract_action`, `_extract_heuristic_action`, `_extract_observation`, `_extract_signal`, `_is_seed24_like`.

### Integration tests (`tests/integration/test_residual_dataset_build.py`)

- CLI run on synthetic trace directory verifies output files (`frames.parquet`, `episodes.jsonl`, `metadata.yaml`, split JSONs).
- Graceful skip of missing input directories.
- Error exit when all input directories are missing.
- Parquet save/load round-trip (when pandas/pyarrow available).
- `--per-seed-csv` correctly overrides summary success labels for matching seeds.

### Lint

```bash
ruff check rosclaw_darwin/learning/residual_dataset.py \
           scripts/learning/build_residual_dataset.py \
           tests/unit/test_residual_dataset_schema.py \
           tests/integration/test_residual_dataset_build.py
pytest tests/unit/test_residual_dataset_schema.py \
       tests/integration/test_residual_dataset_build.py -q
```

All checks pass. 29 tests passed.

---

## 7. Artifacts

- `rosclaw_darwin/learning/residual_dataset.py`
- `scripts/learning/build_residual_dataset.py`
- `tests/unit/test_residual_dataset_schema.py`
- `tests/integration/test_residual_dataset_build.py`
- `data_v19/datasets/residual_learning/seed24_micro_recovery/`
- `data_v19/datasets/residual_learning/v17_large_yaw_slip/`
- `data_v19/datasets/residual_learning/v17_large_yaw_slip_per_trace.csv`
- `data_v19/datasets/residual_learning/combined_seed24_large_yaw/`
  - `frames.jsonl`
  - `episodes.jsonl`
  - `metadata.yaml`
  - `split_train.json`, `split_val.json`, `split_test.json`

---

## 8. Next Steps

1. **Wait for the 100:199 holdout Docker audit to complete** so Sprint 1 can be promoted or its failures rechecked.
2. **Add structured `slip_signal` fields to future traces** so the `slip_guard` residual policy can be evaluated on real large-yaw data.
3. **Re-run the offline replay** against the combined JSONL dataset once contact/slip signals are present.
4. **Use the combined dataset** as the training/validation source for a small learned residual network in v1.10 if offline safety thresholds hold.
5. **Extend `--per-trace-csv` generation** to v18 `valid_ood_cube_matrix` and any other multi-condition directories where seed-level labels are ambiguous.

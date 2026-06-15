# Dashboard Evolution Evidence Report

## 1. Goal

Upgrade the ROSClaw-Darwin Dashboard from table views to evolution-evidence
visualizations: per-episode curves, ablation charts, failure-signature
distributions, transfer matrices, and hint-rule evidence tables.

## 2. New / enhanced views

### `/lift-progress`

- Per-episode curves:
  - `eef_to_object_distance` over steps
  - `object_height` over steps
  - `object_to_target_distance` over steps
- Phase timeline (colored bars per step).
- Failure signature tag chips.

### `/ablations`

- Bar charts:
  - success_rate per condition
  - progress per condition
  - target residual per condition
- Stacked bar: failure signature distribution per condition.
- Error bars: Wilson 95% CI for success rate, bootstrap CI for progress.

### `/failure-signatures`

- Filterable table: task × condition × failure_type × dominant_bottleneck × tags.
- Aggregate counts per tag.
- Representative episode link.

### `/transfer`

- Task × condition matrix.
- Transfer gain (success / progress / residual).
- Transfer level badge (Level 0–3).
- Validation status (local hint / candidate / validated skill).

### `/hint-rules`

- Rule name, trigger tags, hints, confidence, source, validated tasks.
- Positive / negative evidence counts.
- "Requires validation" badge for mined rules.

## 3. Anti-misleading principles

- Oracle / cheat policies are hidden by default.
- ``mock`` and ``arena_real`` metric scopes are shown in separate tabs.
- ``local_adaptive_hint`` and ``validated_transferable_skill`` are visually
distinguished.
- Single-task evidence and cross-task evidence are in separate sections.
- Semantic-only tasks are excluded from the real-leaderboard view.

## 4. Implementation status

- Backend models (`FailureSignature`, `HintRecipe`, statistics helpers) are in place.
- Report artifacts (`failure_signatures.jsonl`, `summary.json`) are written by the ablation scripts.
- Static SVG chart generation is implemented in `rosclaw_darwin/dashboard/charts.py` using only the
  Python standard library, so no matplotlib dependency is required.
- New dashboard endpoints serve the charts:
  - `/lift-progress/{run_id}/chart.svg` — per-episode progress / height / distance summary
  - `/ablations/chart.svg` — grouped success-rate / progress bars across conditions
  - `/failures/chart.svg` — failure-type distribution
  - `/transfer/chart.svg` — cross-task transfer-gain heatmap
- New `/transfer` page shows the task × condition matrix with transfer gain badges.
- The lift-progress, ablations, and failures templates embed the SVG charts directly.

## 5. Honest conclusion

The Dashboard now renders evidence visualizations from existing run artifacts without adding
heavy frontend dependencies.  The charts are static SVGs, so they work offline and load quickly.
Interactive drill-down (e.g. selecting a single episode from the curve) remains future work.

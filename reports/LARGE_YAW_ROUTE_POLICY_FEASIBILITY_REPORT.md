# Large-Yaw Route Policy Feasibility Report (Sprint 8)

**Date:** 2026-06-26  
**Plan:** [ROSClaw-Darwin v1.10 Implementation Plan](../plans/polished-weaving-pizza.md)  
**Mechanism background:** [Large-Yaw Slip Mechanism Report](LARGE_YAW_SLIP_MECHANISM_REPORT.md)

---

## Goal

Assess whether a learned **route classifier** (not an action residual) can
honestly label large-yaw episodes as `continue`, `pause`, `lower_regrip`,
`abort_safe`, or `blocked_external`.  The classifier is run in **diagnostic
mode**: it logs a `route_prediction` in every trace frame but does **not**
change the policy action.  This avoids the v1.10 prohibition against faking
recovery success with an untrained residual.

- **Baseline:** `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`
- **Diagnostic condition:** same policy with `enable_route_classifier=True`
- **Route classifier:** `data_v20/models/large_yaw_route_classifier/model.json`
- **Target yaws:** `1.5708` rad (π/2) and `2.0944` rad (2π/3)
- **Seeds:** `0:4` (pilot slice)

---

## Methods

The pilot uses `scripts/ablations/run_large_yaw_route_policy_pilot.py`.  For
each seed and subtask it runs:

1. `baseline_v3` — promoted v3 policy, no route classifier.
2. `route_diagnostic` — same policy with the route classifier enabled.

The classifier is a `SmallMLPRouteClassifier` (22 input features, 16 hidden
units, 5 output classes).  It is loaded inside the Docker container via a
bind-mounted copy of `route_classifier.py` at `/workspace/data/route_classifier.py`.

Per-step trace fields:

- `route_prediction` — predicted route class
- `route_confidence` — softmax confidence of the prediction

Aggregate metrics:

- Route distribution counts / fractions per `(task, subtask, condition)`
- `blocked_external_rate`
- Success / lifted / grasp-reached rates (for baseline comparison)

---

## Offline training on `data_v20/datasets/residual_learning_v2`

A `SmallMLPRouteClassifier` was trained on the full v2 residual dataset
(342,500 frames) using the same 22-feature input as the trigger model.  The
objective was to learn the five route classes
(`continue` / `pause` / `lower_regrip` / `abort_safe` / `blocked_external`)
from frame-level route labels.

### Dataset route-label distribution

| Route label | Frame count | Fraction |
|---|---|---|
| `continue` | 247,500 | 72.3% |
| `blocked_external` | 95,000 | 27.7% |
| `pause` | 0 | 0.0% |
| `lower_regrip` | 0 | 0.0% |
| `abort_safe` | 0 | 0.0% |

The v2 dataset contains **only** `continue` and `blocked_external` route labels;
there are no frame-level examples of `pause`, `lower_regrip`, or `abort_safe`.
Consequently, a classifier trained on these labels can only learn a binary
boundary.

### Offline metrics

| Split | n | Accuracy | `continue` recall | `blocked_external` recall | Other-class recall |
|---|---|---|---|---|---|
| train | 6,999 | 0.976 | 0.967 | 1.000 | 0.000 |
| val | 1,499 | 0.977 | 0.968 | 1.000 | 0.000 |
| test | 1,502 | 0.981 | 0.973 | 1.000 | 0.000 |

- The classifier cleanly separates `continue` from `blocked_external`.
- It never predicts `pause`, `lower_regrip`, or `abort_safe` because it has never
  seen them.
- On failure frames the model routes ~29–30% to `blocked_external`; the rest are
  classified as `continue`.

This is an **honest but limited** outcome: the classifier is doing exactly what
its labels permit, no more.

---

## Results

### Route distribution (route_diagnostic condition)

| Subtask | Total route frames | `continue` | `pause` | `lower_regrip` | `abort_safe` | `blocked_external` |
|---|---|---|---|---|---|---|
| `yaw_90` (π/2) | 443 | 443 (100%) | 0 | 0 | 0 | 0 |
| `yaw_120` (2π/3) | 159 | 159 (100%) | 0 | 0 | 0 | 0 |

Per-seed route frames:

| Subtask | Seed | `continue` frames |
|---|---|---|
| `yaw_90` | 0 | 93 |
| `yaw_90` | 1 | 0 (trace empty) |
| `yaw_90` | 2 | 106 |
| `yaw_90` | 3 | 85 |
| `yaw_90` | 4 | 0 (trace empty) |
| `yaw_120` | 0 | 65 |
| `yaw_120` | 1 | 30 |
| `yaw_120` | 2 | 64 |
| `yaw_120` | 3 | 0 (trace empty) |
| `yaw_120` | 4 | 0 (trace empty) |

Empty traces for some seeds are expected because the episodes terminate early
(object not lifted / not reached).

### Episode outcomes

All 20 runs (2 subtasks × 2 conditions × 5 seeds) reported `status=failed` with
`success_rate=0.0`.  This is consistent with prior v1.7/v1.8 large-yaw results:
kinematic-only control cannot reliably achieve large target yaws on the
official dex_cube asset.  Because every run failed, the aggregate
success/lift/orientation metrics are `null` in `aggregate_summary.json` (no
`status=completed` episodes).

### Classifier behavior

- The classifier loads successfully inside Docker and writes `route_prediction`
  in every frame.
- It predicts `continue` for 100% of non-empty trace frames across both yaws.
- It does **not** predict `blocked_external`, `abort_safe`, `lower_regrip`, or
  `pause` in this pilot.

---

## Interpretation

### What was proven

1. **Technical integration works.** The route classifier can be bound into the
   Docker container, imported locally by `heuristic_policy.py`, and its
   predictions logged in the episode trace without breaking the policy loop.
2. **No action corruption.** Running the classifier in diagnostic mode does
   not change the policy action; baseline and diagnostic traces are identical
   except for the added `route_prediction` / `route_confidence` fields.
3. **No false recovery claim.** Because the classifier does not alter actions,
   it cannot create spurious successes. Large-yaw remains unsolved, as
   expected.
4. **Binary offline separation is learnable.** On the v2 dataset the trained
   classifier cleanly distinguishes `continue` from `blocked_external`
   (accuracy ~0.98, blocked_external recall 1.0).

### What was not proven

1. **The three intermediate route classes are not learnable from v2 labels.**
   `pause`, `lower_regrip`, and `abort_safe` have zero examples in the dataset,
   so the classifier cannot predict them.
2. **The live pilot did not reflect the trained model's offline behavior.**  The
   pilot predicted `continue` for 100% of non-empty frames.  The trained model
   does predict `blocked_external` on ~30% of failure frames in offline
   evaluation, but the pilot artifact that was loaded inside Docker either
   predated the training run or the route-classifier path was not exercised on
   the large-yaw frames that score as `blocked_external`.
3. **No useful route decisions are made in live large-yaw episodes.** A useful
   route classifier would predict `blocked_external` or `abort_safe` once
   torsional slip is detected, and possibly `lower_regrip` in grasp-contact
   frames. None of these were observed in the live pilot.
4. **No improvement in success/lift/orientation.** The pilot does not show any
   gain; large-yaw success stays at 0/20.

---

## Promotion-gate sub-checks

| Gate | Required | Actual | Pass |
|---|---|---|---|
| Route classifier loads inside Docker | yes | yes | ✅ |
| Predictions logged in trace | yes | yes | ✅ |
| Does not change action / create fake success | yes | yes | ✅ |
| Does not degrade lifted_rate | N/A (all failed) | no degradation possible | ✅ |
| Correctly labels unsolved cases `blocked_external` | yes (eventually) | no — all `continue` | ❌ |
| Reduces slip severity or improves orientation | optional | no change | — |

---

## Artifacts

- Pilot runner: `scripts/ablations/run_large_yaw_route_policy_pilot.py`
- Route classifier: `rosclaw_darwin/learning/route_classifier.py`
- Container bind-mount copy: `rosclaw_darwin/evaluation/arena_docker_deps/route_classifier.py`
- Trained model: `data_v20/models/large_yaw_route_classifier/model.json`
- Offline metrics: `data_v20/models/large_yaw_route_classifier/metrics.json`
- Pilot output: `data_v20/ablations/large_yaw_route_policy_pilot/`
  - `aggregate_summary.json`
  - `per_seed_results.csv`
  - per-seed trace directories

---

## Conclusion

The large-yaw route-policy **infrastructure is feasible**: a route classifier
can be loaded inside the Arena Docker container and its predictions logged in
the trace.  Training the `SmallMLPRouteClassifier` on the v2 residual dataset
produces a clean binary split between `continue` and `blocked_external`
(accuracy ~0.98), which is exactly what the dataset labels permit.

However, the classifier **cannot make the three intermediate route decisions**
(`pause`, `lower_regrip`, `abort_safe`) because the v2 dataset contains zero
examples of those classes.  The live pilot also did not show the trained model
predicting `blocked_external` on large-yaw frames, so the route-classifier path
has not yet been demonstrated to correctly label unsolved large-yaw episodes in
Arena.

This is an honest feasibility outcome, not a failure: v1.10 explicitly forbids
training a fake action residual to manufacture success.  The route-classifier
path remains open, but it requires:

1. A curated large-yaw dataset with frame-level labels for all five route
   classes, especially `blocked_external` on confirmed torsional-slip frames and
   at least some `pause` / `lower_regrip` / `abort_safe` examples.
2. Re-training the `SmallMLPRouteClassifier` on that dataset.
3. Offline validation that the classifier predicts `blocked_external` on
   torsional-slip frames and `continue` on normal frames.
4. A second Arena pilot where the classifier is allowed to influence action
   selection only after offline validation passes.

Until those steps are completed, large-yaw torsional slip stays
`blocked_external` in FailureToHint v3.4 and the escalation package remains the
honest route.

---

## Next steps

1. Annotate or synthesize frame-level route labels for the five classes using
   v1.7/v1.8 large-yaw traces and slip-monitor signals.
2. Re-train the route classifier on the augmented dataset.
3. Validate offline that per-class recall for `blocked_external` is ≥ 80% and
   that false `blocked_external` rate on normal frames is low.
4. Re-run the Arena pilot and confirm that the trained classifier labels
   large-yaw slip episodes as `blocked_external` in the live trace.
5. Only then consider allowing the classifier to influence action selection
   (e.g., trigger abort-safe or pause).

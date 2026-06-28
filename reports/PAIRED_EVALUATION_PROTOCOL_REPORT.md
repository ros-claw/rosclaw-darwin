# Paired No-Regression Evaluation Protocol (v1.10)

**Date:** 2026-06-25  
**Status:** Active protocol for all v1.10 candidate evaluations  
**Schema:** `rosclaw_darwin/evaluation/paired_evaluation.py`

---

## Purpose

Raw success-rate comparisons hide per-seed regressions. A candidate that improves ten hard seeds while breaking two easy seeds can show a net positive rate but still be unsafe to promote. The paired protocol compares baseline and candidate on the **exact same seeds** under the **same perturbation protocol**, classifies every seed into one of five categories, and reports McNemar significance plus a bootstrap CI on the paired net gain.

---

## Definitions

For each seed `s`:

| Baseline | Candidate | Delta class | Interpretation |
|---|---|---|---|
| Success | Success | `unchanged_success` | No effect |
| Failure | Failure | `unchanged_failure` | Both fail; candidate did not help this seed |
| Failure | Success | `rescued` | Candidate fixed this seed |
| Success | Failure | `newly_failed` | **Regression** — candidate broke this seed |
| Any | Any | `invalid_pair` | Asset fallback, physics anomaly, or protocol violation |

---

## Statistical Summary

For a set of paired seed outcomes, the aggregate summary reports:

- `total_pairs`, `valid_pairs`, `invalid_pair_count`
- `rescued_count`, `newly_failed_count`, `unchanged_success_count`, `unchanged_failure_count`
- `net_delta = rescued_count - newly_failed_count`
- `rescue_rate_on_baseline_failures`
- `new_failure_rate_on_baseline_successes`
- `baseline_success_rate`, `candidate_success_rate`
- `mcnemar_p_value` (exact binomial by default)
- `paired_bootstrap_ci` (percentile bootstrap on per-seed success delta)

### McNemar table

                       candidate
                   success   failure
        baseline
        success      a          b   (newly_failed)
        failure      c          d   (rescued)

`b` and `c` are the discordant cells. The exact binomial test conditions on `b + c` and tests `p = 0.5`.

### Bootstrap CI

Per-seed delta is `candidate_success - baseline_success` ∈ {-1, 0, 1}. The reported CI is the percentile bootstrap 95% interval for the mean of these deltas over valid pairs.

---

## Promotion Gate

A candidate may be labeled `paired_no_regression_candidate` only if **all** of the following hold:

1. `newly_failed_count == 0`
2. `invalid_pair_count == 0`
3. `asset_fallback_used_count == 0` (across candidate runs)
4. `physics_anomaly_count == 0` (across candidate runs)
5. `candidate_success_rate >= baseline_success_rate`
6. Micro-recovery trigger rate on baseline-success seeds ≤ 5%

A candidate that meets the gate is **not** automatically promoted to the official default. It becomes eligible for further ablation, learned-model integration, or FTH v3.4 evidence-aware promotion.

---

## Required Seed Splits

Every official-dex-cube paired evaluation must report three slices:

- `0:99` — primary official benchmark
- `100:199` — holdout benchmark
- `0:199` — combined benchmark

The `0:99` slice protects the frozen 99/100 result. The `100:199` slice guards against overfitting to the published benchmark.

---

## Artifact Isolation

Each seed must produce an isolated artifact directory:

```
data_v20/paired/<task_id>/
  paired_summary.json
  paired_summary.csv
  rescued_seeds.json
  newly_failed_seeds.json
  unchanged_failure_seeds.json
  invalid_pairs.json
  per_seed/seed_000/{baseline,candidate,pair_result.json}
```

Isolation guarantees that a seed can be rechecked independently if its pair is disputed.

---

## Usage

```python
from rosclaw_darwin.evaluation.paired_evaluation import (
    PairedSeedOutcome,
    compute_paired_summary,
)

outcomes = []
for seed, baseline_ok, candidate_ok in results:
    outcomes.append(PairedSeedOutcome(
        seed=seed,
        baseline_success=baseline_ok,
        candidate_success=candidate_ok,
        baseline_artifact_dir=f".../seed_{seed:03d}/baseline",
        candidate_artifact_dir=f".../seed_{seed:03d}/candidate",
    ))

summary = compute_paired_summary(
    outcomes,
    task_id="official_seed24_micro_recovery",
    baseline_policy="heuristic_servo_goal_pose_v3_reachability_promoted",
    candidate_policy="heuristic_servo_goal_pose_v3_seed24_micro_recovery",
    seed_range="0:199",
)
```

---

## Related Reports

- [Milestone: v1.9 Infrastructure Frozen](MILESTONE_DARWIN_V19_CONTACT_RESIDUAL_INFRASTRUCTURE.md)
- [Seed24 Micro-Recovery Paired No-Regression Report](SEED24_MICRO_RECOVERY_PAIRED_NO_REGRESSION_REPORT.md) *(Sprint 1)*

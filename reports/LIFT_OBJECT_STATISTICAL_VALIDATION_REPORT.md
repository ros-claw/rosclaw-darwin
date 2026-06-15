# Lift Object Statistical Validation Report

- Task: ``darwin_mvp_03_lift_object``
- Policy: ``heuristic_servo_lift``
- Episodes per seed per condition: 50
- Seeds: [0, 1, 2]

## Per-condition summary (aggregated across seeds)

| condition | n_expected | n_observed | success_rate | 95% CI | progress (mean ± std) | progress 95% CI |
|---|---:|---:|---:|---:|---:|---:|
| without_hints | 150 | 150 | 0.5133 | [0.434, 0.592] | 0.937856 ± 0.035862 | [0.93189, 0.943289] |
| manual_hints | 150 | 150 | 0.4467 | [0.3694, 0.5266] | 0.939072 ± 0.032632 | [0.933668, 0.944117] |
| auto_hints | 150 | 150 | 0.5067 | [0.4275, 0.5855] | 0.938023 ± 0.034442 | [0.932344, 0.943176] |

## Pairwise comparisons vs. without_hints

| comparison | Δsuccess | Δprogress | Fisher exact p | odds_ratio | progress Δ CI |
|---|---|---|---|---|---|---|
| manual_hints_vs_without_hints | -0.0666 | 0.0012 | 0.247834 | 0.7667 | [-0.0064, 0.0089] |
| auto_hints_vs_without_hints | -0.0066 | 0.0002 | 0.908054 | 0.9738 | [-0.0076, 0.0081] |

## Failure counts (aggregated across seeds)

- **without_hints**: {'target_not_reached_after_lift': 73, 'unknown_failure': 0}
- **manual_hints**: {'unknown_failure': 0, 'target_not_reached_after_lift': 83}
- **auto_hints**: {'unknown_failure': 0, 'target_not_reached_after_lift': 74}

## Honest conclusion

This report aggregates multiple seeds with confidence intervals and Fisher
exact tests.  Missing per-episode metrics are conservatively treated as
failures with zero progress, so the reported success rate is a lower bound.
A positive Δsuccess whose CI is mostly above zero and whose p-value is small
provides stronger evidence than a single-seed point estimate.


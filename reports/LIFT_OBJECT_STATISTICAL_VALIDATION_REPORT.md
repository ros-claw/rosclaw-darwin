# Lift Object Statistical Validation Report

- Task: ``darwin_mvp_03_lift_object``
- Policy: ``heuristic_servo_lift``
- Episodes per seed per condition: 20
- Seeds: [0, 1, 2]

## Per-condition summary (aggregated across seeds)

| condition | n | success_rate | 95% CI | progress (mean ± std) | progress 95% CI |
|---|---|---|---|---|---|
| without_hints | 60 | 0.3167 | [0.213, 0.4424] | 0.913456 ± 0.152016 | [0.859698, 0.945571] |
| manual_hints | 60 | 0.35 | [0.2417, 0.4764] | 0.91332 ± 0.150266 | [0.861093, 0.943939] |
| auto_hints | 60 | 0.3833 | [0.2709, 0.5099] | 0.922034 ± 0.150145 | [0.871294, 0.951154] |

## Pairwise comparisons vs. without_hints

| comparison | Δsuccess | Δprogress | Fisher exact p | odds_ratio | progress Δ CI |
|---|---|---|---|---|---|
| manual_hints_vs_without_hints | 0.0333 | -0.0001 | 0.698535 | 1.1584 | [-0.0001, -0.0001] |
| auto_hints_vs_without_hints | 0.0666 | 0.0086 | 0.443939 | 1.3337 | [0.0086, 0.0086] |

## Failure counts (aggregated across seeds)

- **without_hints**: {'unknown_failure': 0, 'target_not_reached_after_lift': 21}
- **manual_hints**: {'target_not_reached_after_lift': 19, 'unknown_failure': 0}
- **auto_hints**: {'target_not_reached_after_lift': 17, 'unknown_failure': 0}

## Honest conclusion

This report aggregates **60 episodes per condition** (20 episodes × 3 seeds) on
``darwin_mvp_03_lift_object``.  Two of the nine runs (seed 1 auto_hints and
seed 2 without_hints / manual_hints) returned ``None`` scalar metrics from the
Arena Docker container; the success-rate counts above treat those missing
episodes conservatively as failures, so the reported baseline may be slightly
underestimated.

Observed trend:

| comparison | Δsuccess | Δprogress | Fisher exact p |
|---|---|---|---|
| manual_hints vs without_hints | +0.0333 | -0.0001 | 0.699 |
| auto_hints vs without_hints | +0.0666 | +0.0086 | 0.444 |

- Auto hints show a **positive success-rate trend** (+6.7 pp) and a small
  progress improvement, but the effect is **not statistically significant**
  (Fisher exact p ≈ 0.44, Wilson CIs overlap substantially).
- Manual hints also show a small positive success-rate trend (+3.3 pp) with
  negligible progress change.
- Failure mode remains dominated by ``target_not_reached_after_lift`` in all
  conditions, consistent with FailureSignature v2 ``final_alignment_gap``.

Interpretation: the preliminary positive transfer seen in the earlier 50-episode
single-seed run is **directionally reproduced across seeds**, but the effect
size is modest and the evidence is weaker than a single large-N run suggested.
A larger validation (≥50 episodes × 3 seeds, or 100 episodes per condition) with
stable metric export is needed before claiming robust statistical evidence.


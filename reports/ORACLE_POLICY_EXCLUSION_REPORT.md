# Oracle / Cheat Policy Exclusion Report

## Purpose

Verify that ``cheat_lift`` remains usable as a **pipeline sanity check** while
being completely excluded from skill discovery, evolution score, and leaderboard.

## Policy metadata

```yaml
policy_id: cheat_lift
type: cheat_lift
is_oracle: true
is_cheat: true
excluded_from_leaderboard: true
can_claim_capability: false
can_discover_skill: false
can_compute_evolution_score: false
```

## Run

| Setting | Value |
|---|---|
| Task | ``darwin_mvp_03_lift_object`` |
| Adapter | arena (Docker) |
| Episodes | 5 |
| Out | ``/tmp/rosclaw_data/arena_real/oracle_exclusion_check`` |

## Result

| Metric | Value |
|---|---|
| status | completed |
| success_rate | 1.00 |
| skill_discovery_rate | null |
| evolution_score | null |
| skill_candidate_count | 0 |
| leaderboard_excluded | true |
| can_claim_capability | false |
| metric_scope | pipeline_sanity |
| claim_level | infrastructure |

## Conclusion

- The Arena Docker pipeline correctly reports ``success_rate = 1.0`` for the cheat policy.
- The result is tagged as ``pipeline_sanity`` and is **not** treated as a real capability.
- No skill-discovery or evolution metrics are produced.
- This satisfies the oracle-exclusion requirement.

# Approach-Collision Failure Diagnosis Report

**Date:** 2026-06-26  
**Route:** `approach_collision_diagnosis` (FailureToHint v3.4)
**Status:** `diagnosis_only` / `experimental_only`

---

## Goal

Separate approach-collision failures from the seed-24 grip-quality
micro-recovery evidence pool.  Approach collisions are a distinct
failure boundary (workspace / placement geometry) and must not be
counted as grip-quality micro-recovery candidates.

## Method

Read the paired-evaluation summary and per-seed
`failure_signature.json` artifacts.  A seed is classified as
approach-collision dominated if either the baseline or the candidate
failure class is `approach_collision`.

## Source evidence

- Paired summary: `official_seed24_micro_recovery_0_199`
- Seeds covered: `0:199`
- Total pairs: 200
- Valid pairs: 200

## Results

- **Approach-collision dominated seeds:** 4
- **Both sides:** 4 — [104, 105, 114, 119]
- **Baseline only:** 0 — []
- **Candidate only:** 0 — []

## Seed detail

| Seed | Delta class | Baseline failure | Candidate failure |
|---|---|---|---|
| 104 | unchanged_failure | approach_collision | approach_collision |
| 105 | unchanged_failure | approach_collision | approach_collision |
| 114 | unchanged_failure | approach_collision | approach_collision |
| 119 | unchanged_failure | approach_collision | approach_collision |

## Interpretation

Approach-collision dominated seeds are concentrated in the official
dex_cube benchmark when initial placement geometry causes the gripper
to collide with the cube or surrounding workspace during the
approach phase.  These failures are independent of the grip-quality
micro-recovery axis and should be tracked by their own diagnosis route.

## FailureToHint v3.4 route

The `approach_collision_diagnosis` rule declares:

- `route_selection`: `diagnosis_only`
- `claim_level`: `diagnosis_only`
- `promotion_status`: `experimental`
- No `evidence_gate`: promotion is blocked until dedicated paired
  evidence for an approach-collision recovery candidate is available.

## Next steps

1. Keep approach-collision seeds out of the seed-24 micro-recovery
   promotion evidence.
2. If a future approach planner / reachability intervention is
   developed, evaluate it with its own paired no-regression sweep
   on these seeds.
3. Only promote to `candidate_recovery` when a dedicated gate
  (e.g. `paired_no_regression` on approach-collision seeds) is met.

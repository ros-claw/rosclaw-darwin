# FailureToHint v3.4 Evidence-Aware Promotion Report (Sprint 9)

**Date:** 2026-06-26  
**Plan:** [ROSClaw-Darwin v1.10 Implementation Plan](../plans/polished-weaving-pizza.md)

---

## Goal

Prevent unverified recovery claims from being promoted to
`candidate_recovery` or `validated_recovery`.  FailureToHint v3.4 adds an
`evidence_gate` to every recovery recipe and a `PromotionManager` that consumes
live paired-evaluation evidence to decide the honest promotion status.

- **No evidence → `experimental_only`.**
- **Evidence fails the gate → `experimental_only` with a reason.**
- **Evidence passes the gate → `candidate_recovery`.**
- **`blocked_external` / `human_escalation` routes are never promoted**, even if
  a gate is declared.

---

## New components

| Component | File | Purpose |
|---|---|---|
| `EvidenceStatus` | `rosclaw_darwin/evolution/evidence_status.py` | JSON-serializable promotion verdict for one recipe. |
| `PromotionManager` | `rosclaw_darwin/evolution/promotion_manager.py` | Evaluates a `HintRecipe` against a `PairedEvaluationSummary`. |
| v3.4 rules | `configs/skills/failure_signature_to_hint_rules_v34.yaml` | Recipes with explicit `evidence_gate` blocks and diagnosis-only routes. |
| Wiring | `rosclaw_darwin/evolution/failure_to_hint.py` | `evaluate_recipe_evidence()` returns `EvidenceStatus` list. |
| Audit | `scripts/diagnostics/audit_paired_infrastructure_failures.py` | Verifies that stderr infrastructure signals produce `invalid_pair` notes. |

### `EvidenceStatus` schema

- `recipe_name`
- `route_selection`
- `promotion_status` — `candidate_recovery`, `experimental_only`, `blocked_external`, `human_escalation`
- `evidence_gate_passed` — boolean
- `gate_reason` — human-readable explanation
- `paired_summary` — full `PairedEvaluationSummary` when available
- `required_evidence` — the gate declared in the recipe

### `PromotionManager` logic

1. Hard-block `blocked_external` / `human_escalation` / `abort_safe` routes.
2. If no `evidence_gate` is declared → `experimental_only`.
3. If gate type is unknown → `experimental_only`.
4. For `paired_no_regression` gates, check:
   - `rescued_count >= min_rescued_count`
   - `newly_failed_count <= max_newly_failed_count`
   - `candidate_success_rate >= min_candidate_success_rate`
   - observed new-failure rate <= `max_new_failure_rate`
5. Return `candidate_recovery` only if all checks pass.

---

## v3.4 rules

Four rules are defined in `configs/skills/failure_signature_to_hint_rules_v34.yaml`:

### `seed24_grip_quality_micro_recovery`

- Trigger tags: `grip_force_insufficient`, `low_object_z_at_grasp`, `gripper_too_open`
- Route: `conditional_micro_recovery`
- Evidence gate (`paired_no_regression`):
  - `min_rescued_count: 1`
  - `max_newly_failed_count: 0`
  - `min_candidate_success_rate: 0.95`
  - `max_new_failure_rate: 0.01`
  - Required task: `goal_pose_dex_cube_official`
  - Required seed range: `0:199`

### `large_yaw_torsional_slip`

- Trigger tags: `large_yaw_torsional_slip`, `rotation_induced_slip`, `yaw_not_transferred_to_object`
- Route: `blocked_external`
- No gate required; hard-blocked regardless of evidence.

### `approach_collision_diagnosis`

- Trigger tag: `approach_collision`
- Route: `diagnosis_only`
- No evidence gate declared; stays `experimental_only`.
- Purpose: keep approach-collision failures out of the grip-quality
  micro-recovery evidence pool.

### `generic_grip_quality_diagnosis`

- Trigger tag: `grip_force_insufficient`
- Route: `diagnosis_only`
- No evidence gate declared → stays `experimental_only`.

---

## Evidence input

The paired evaluation used as evidence:

- Source: `data_v20/paired/official_seed24_micro_recovery_0_199/paired_summary.json`
- Baseline: `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`
- Candidate: `configs/policies/heuristic_servo_goal_pose_v3_seed24_micro_recovery.yaml`
- Seeds covered: `0:199` (200 total pairs, 200 valid pairs).

Summary fields:

| Field | Value |
|---|---|
| `total_pairs` | 200 |
| `valid_pairs` | 200 |
| `rescued_count` | 2 |
| `newly_failed_count` | 0 |
| `invalid_pair_count` | 0 |
| `baseline_success_rate` | 0.955 |
| `candidate_success_rate` | 0.965 |
| `mcnemar_p_value` | 0.5 |
| `paired_bootstrap_ci` | [0.0, 0.025] |

The dataset was re-audited for infrastructure failures in `stderr.log`; the
audit reports zero missed signals.

---

## Promotion verdicts

The generated evidence status artifact is
`data_v20/evolution/fth_v34_evidence_status.json`.

### `seed24_grip_quality_micro_recovery`

- **Promotion status:** `candidate_recovery`
- **Evidence gate passed:** `true`
- **Reason:** `paired_no_regression gate passed`

The corrected full `0:199` official benchmark shows zero regressions, two
rescued seeds (24 and 198), and a candidate success rate of **0.965**, which
meets the declared 0.95 gate. The micro-recovery is therefore promoted to
`candidate_recovery`. The earlier report (2026-06-25) classified it as
`experimental_only` because infrastructure failures in `stderr.log` were
misclassified as policy failures, depressing the observed candidate success
rate to 0.87.

### `large_yaw_torsional_slip`

- **Promotion status:** `blocked_external`
- **Evidence gate passed:** `false`
- **Reason:** `Route is outside the policy's control (blocked_external).`

Large-yaw torsional slip is classified as a physics/force-control problem that
cannot be solved by the current kinematic-only policy. The v3.4 rule therefore
blocks any recovery claim and routes the diagnosis to external escalation.

### `approach_collision_diagnosis`

- **Promotion status:** `experimental_only`
- **Evidence gate passed:** `false`
- **Reason:** `No evidence_gate declared; recipe remains experimental.`

This diagnosis-only route intentionally has no promotion gate; it keeps
approach-collision failures separate from the grip-quality recovery evidence
pool until a dedicated approach-collision recovery candidate is evaluated.

### `generic_grip_quality_diagnosis`

- **Promotion status:** `experimental_only`
- **Evidence gate passed:** `false`
- **Reason:** `No evidence_gate declared; recipe remains experimental.`

The weak-signal diagnosis-only recipe intentionally has no promotion gate;
it stays experimental until paired evidence supports a stronger claim.

---

## Tests

- `tests/unit/test_evidence_status.py` — JSON round-trip and schema validation.
- `tests/unit/test_promotion_manager.py` — synthetic paired evaluations:
  - `blocked_external` stays blocked even with a passing gate.
  - Paired gate passes → `candidate_recovery`.
  - `newly_failed_count > 0` → `experimental_only`.
  - Missing summary → `experimental_only`.
- `tests/unit/test_fth_v34_rules.py` — loads the v3.4 YAML and asserts every
  rule has a structurally valid `evidence_gate` (or a blocked/diagnosis route).
- `tests/unit/test_arena_runner.py` — infrastructure-failure detection in stderr
  (`BlockingIOError`, traceback, HDF5 lock, `CUDA out of memory`,
  `No space left on device`).
- `scripts/diagnostics/audit_paired_infrastructure_failures.py` — end-to-end
  invariant check on the live paired directory (0 missed after re-run).

All unit/integration tests pass and the live audit is clean.

---

## Artifacts

- `rosclaw_darwin/evolution/evidence_status.py`
- `rosclaw_darwin/evolution/promotion_manager.py`
- `configs/skills/failure_signature_to_hint_rules_v34.yaml`
- `data_v20/evolution/fth_v34_evidence_status.json`

---

## Conclusion

FailureToHint v3.4 successfully converts promotion from a static YAML claim
into an evidence-aware decision:

- The seed-24 micro-recovery is **promoted to `candidate_recovery`** on the
  corrected full `0:199` official benchmark: zero regressions, two rescued
  seeds (24 and 198), and a candidate success rate of **0.965** that meets the
  declared 0.95 gate.
- The earlier report (2026-06-25) classified it as `experimental_only` only
  because infrastructure failures in `stderr.log` had been misclassified as
  policy failures, artificially depressing the observed success rate to 0.87.
- Large-yaw torsional slip is **hard-blocked** as `blocked_external`.
- Approach-collision failures are **diagnosis-only**, kept out of the grip-quality
  recovery evidence pool.
- Generic grip-quality diagnosis stays **experimental_only**.

This is the intended behavior: v3.4 prevents false recovery promotion and
forces every candidate to earn its status with paired, no-regression evidence.
Once the absolute success-rate bar is met, promotion happens automatically.

---

## Next steps

1. Use the two rescued seeds (24, 198) as positive training examples for
   residual dataset v2 and for refining the micro-recovery trigger.
2. Investigate the seven remaining `unchanged_failure` seeds; the four
   approach-collision seeds (`104, 105, 114, 119`) are already routed to the
   independent `approach_collision_diagnosis` route.
3. Add additional gate types (e.g., `offline_replay_safety`, `arena_pilot`) as
   more forms of evidence become available.
4. Any future candidate that changes the policy must pass a fresh paired
   `0:199` evaluation before its FTH v3.4 status can be updated.

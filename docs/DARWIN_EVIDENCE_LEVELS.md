# ROSClaw-Darwin Evidence Levels

Darwin uses a small, ordered set of evidence levels. Each level determines what claims are allowed and what claims are blocked.

---

## Levels

### `rejected`

- The candidate was evaluated and found harmful, invalid, or unsupported.
- Example: a recovery that increases failure rate or violates safety limits.
- **Allowed claims:** none.
- **Blocked claims:** all.

### `diagnosis_only`

- The system can identify and describe the failure but cannot propose a safe automatic fix.
- Example: complex collision patterns that require human analysis.
- **Allowed claims:** Darwin can diagnose this failure class.
- **Blocked claims:** Darwin can fix it; Darwin has a validated recovery.

### `blocked_external`

- The failure is outside the current system's capabilities because of missing sensors, environment defects, or physics limitations.
- Examples: large-yaw torsional slip without force/tactile feedback; procedural cube fallback with invalid collision geometry.
- **Allowed claims:** Darwin can honestly block false promotion; Darwin can route the failure to external escalation.
- **Blocked claims:** Darwin solved it; candidate recovery validated.

### `human_escalation`

- The candidate requires human review before any promotion decision.
- Example: a recovery with promising but incomplete evidence, or a safety-sensitive intervention.
- **Allowed claims:** The candidate is under human review.
- **Blocked claims:** Any autonomous promotion.

### `experimental_only`

- The code runs, but there is no live gain on the benchmark.
- Example: learned trigger + bounded residual on `0:199`: safe (`newly_failed_count = 0`) but `rescued_count = 0`.
- **Allowed claims:** The component is implemented, offline gates pass, and live control is safe.
- **Blocked claims:** It improves success rate; it is a promoted recovery.

### `candidate_recovery`

- The candidate passes paired no-regression evaluation and rescues at least one baseline failure.
- Example: seed-24 micro-recovery: `rescued_count = 2`, `newly_failed_count = 0`, candidate success rate 0.965.
- **Allowed claims:** The recovery is a no-regression candidate on the evaluated seed/task set.
- **Blocked claims:** Transferable skill; validated on independent task; universal fix.

### `validated_recovery`

- The candidate recovery replicates its no-regression benefit on an independent hold-out task or seed distribution.
- **Allowed claims:** The recovery is validated on the specific hold-out set.
- **Blocked claims:** Transferable skill across objects/embodiments.

### `validated_transferable_skill`

- The recovery or skill generalizes across tasks, objects, or seed distributions without regressing the official baseline.
- **Allowed claims:** The skill is transferable within the demonstrated scope.
- **Blocked claims:** Universal robot capability; official Arena leaderboard result unless accepted.

---

## Promotion rules

| From | To | Required evidence |
|---|---|---|
| `experimental_only` | `candidate_recovery` | paired no-regression + `rescued_count > 0` + success-rate gate |
| `candidate_recovery` | `validated_recovery` | independent hold-out or task-variant replication |
| `validated_recovery` | `validated_transferable_skill` | cross-task / cross-object / cross-seed replication, no baseline regression |
| any | `blocked_external` | external limitation demonstrated and documented |
| any | `human_escalation` | safety or evidence ambiguity requiring human decision |
| any | `rejected` | harmful regression or invalid intervention |

**Hard blocks:**
- `blocked_external` can never be promoted to any recovery level.
- `diagnosis_only` cannot be promoted without a separate intervention evaluation.
- `experimental_only` cannot be promoted without live rescue evidence.

---

## Evidence-card fields

Every evidence card must state:

- `status`: current promotion level.
- `passed_gates`: list of gates satisfied.
- `failed_gates`: list of gates not satisfied.
- `allowed_claims`: what the evidence honestly supports.
- `blocked_claims`: what must not be claimed.
- `next_required_evidence`: what is needed to advance to the next level.

---

## Examples in v1.0

| Candidate | Status | Passed gates | Blocked claims |
|---|---|---|---|
| official_goalpose_baseline | v1.0 baseline | validity, 99/100 success | transferable skill, leaderboard |
| seed24_micro_recovery | candidate_recovery | paired no-regression, 2 rescued | validated_recovery, transferable skill |
| procedural_fallback | blocked_external | invalid environment detected | OOD adaptation success |
| large_yaw_torsional_slip | blocked_external | honest diagnosis | large-yaw solved |
| learned_trigger_bounded_residual | experimental_only | safe live control | rescue claim, promotion |

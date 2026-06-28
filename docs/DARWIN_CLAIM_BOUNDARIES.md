# ROSClaw-Darwin v1.0 Claim Boundaries

## Honest Claim Policy

ROSClaw-Darwin v1.0 is an evidence engine for evolving physical policies safely. Every public claim must be backed by an evidence card with a matching promotion status. Claims outside the supported evidence level are blocked.

## Allowed Claims by Evidence Level

### `experimental_only`

- The component is implemented.
- Offline safety and schema gates pass.
- Live control is safe (no new failures introduced on evaluated seeds).
- It is a candidate for further evaluation.

### `candidate_recovery`

- The recovery is a no-regression candidate on the evaluated seed/task set.
- Paired evaluation shows `newly_failed_count == 0` and `rescued_count > 0`.
- It may be enabled for runtime in a supervised or A/B context.

### `validated_recovery`

- The recovery is validated on a specific hold-out set or task variant.
- It does not regress the baseline on that hold-out set.

### `validated_transferable_skill`

- The skill is transferable within the demonstrated scope (tasks, objects, seeds).
- It does not regress the baseline across the demonstrated scope.

### `blocked_external`

- Darwin can honestly block false promotion.
- The failure is routed to external escalation (Arena, hardware, human expert).
- Darwin does not have a validated recovery for this failure class.

### `diagnosis_only`

- Darwin can diagnose this failure class.
- Darwin cannot automatically fix it with current capabilities.

## Disallowed Claims (Hard Blocks)

These claims must not appear in any v1.0 report, card, or documentation unless new independent evidence is produced and a new evidence card is generated:

- "validated transferable skill" — without `validated_transferable_skill` evidence card.
- "large-yaw solved" — without reproducible cross-seed evidence.
- "official Arena leaderboard result" — without Arena acceptance.
- "procedural OOD success" — not claimed; the procedural cube fallback is invalid environment; any claim must be scoped to valid OOD cube only.
- "Darwin replaces RL training" — Darwin augments, not replaces, RL.
- "universal robot capability" — all claims are scoped to evaluated tasks.

## Claim Linter

Run before release:

```bash
python scripts/quality/check_claim_boundaries.py
```

The linter scans `docs/`, `reports/`, and `cards/` for disallowed phrases. Failing the linter blocks the release gate.

## Escalation Path

If a team member believes a disallowed claim should be allowed, the required evidence must be produced first:

1. Run paired no-regression evaluation on the new scope.
2. Generate an evidence card with the new status.
3. Update the registry.
4. Re-run the claim linter.

No claim may be promoted by editing prose alone.

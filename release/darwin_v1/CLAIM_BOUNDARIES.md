# ROSClaw-Darwin v1.0 Claim Boundaries

## Allowed claims

Darwin v1.0 can claim:

- It can validate benchmark environments and reject invalid ones.
- It can diagnose structured physical-policy failures.
- It can perform paired no-regression evaluation.
- It can promote a candidate recovery based on paired evidence.
- It can block invalid or externally dependent failures.
- It generates auditable evidence cards for every promotion decision.
- It exposes an evidence registry with a read-only runtime query interface.

## Disallowed claims

Darwin v1.0 must **not** claim:

- It automatically solves all robot tasks.
- It has proven transferable skills.
- It has solved large-yaw torsional slip.
- Its results are official Arena leaderboard results unless accepted.
- It replaces RL training.
- It is a generic benchmark runner.
- It is only a dashboard visualization project.
- Procedural OOD success is not claimed.

## Evidence required to unlock claims

| Claim | Required evidence |
|---|---|
| `validated_recovery` | `candidate_recovery` + independent holdout or task-variant replication. |
| `validated_transferable_skill` | `validated_recovery` + cross-task/object/seed replication without baseline regression. |
| `large-yaw solved` | Reproducible cross-seed rescue of large-yaw slip seeds with no regression. |
| `official Arena leaderboard result` | Arena acceptance of submitted run is required. |
| `procedural OOD success` | Valid procedural environment with collision geometry and correct bbox is required. |

## Hard blocks

The following transitions are prohibited:

- `blocked_external` → `candidate_recovery`
- `blocked_external` → `validated_recovery`
- `blocked_external` → `validated_transferable_skill`
- `invalid_environment` → any skill claim

## Verification

Run the claim linter before release:

```bash
python scripts/quality/check_claim_boundaries.py
```

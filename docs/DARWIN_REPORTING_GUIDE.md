# ROSClaw-Darwin v1.0 Reporting Guide

## Purpose

This guide defines how ROSClaw-Darwin v1.0 evidence is reported, consumed, and promoted. It replaces version-numbered experiment indexes as the primary entry point for product status.

## Report Hierarchy

```
reports/
  INDEX_V1.md              <- Start here
  current/
    benchmark_validity/    <- Environment validity audits
    failure_diagnosis/     <- Failure signatures and diagnosis
    paired_promotion/      <- Paired no-regression evaluations
    evidence_cards/        <- Productized evidence cards
  demos/
    goal_pose/             <- Official baseline + seed24 micro-recovery
    procedural_invalidity/ <- Procedural cube fallback invalidity
    large_yaw/             <- Large-yaw torsional slip, blocked external
  archive/
    v13_to_v20/            <- Historical v1.3–v1.10 experiment reports
```

## Evidence Levels

| Level | Meaning | Can be promoted to runtime? |
|---|---|---|
| `rejected` | Does not meet minimum bar. | No |
| `diagnosis_only` | Darwin can identify the failure class. | No |
| `blocked_external` | Outside current system capability; escalated. | No |
| `human_escalation` | Requires human review. | No |
| `experimental_only` | Implemented and safe, but no proven live gain. | No |
| `candidate_recovery` | Paired no-regression evidence with rescued seeds. | Yes |
| `validated_recovery` | Candidate recovery replicated on independent hold-out. | Yes |
| `validated_transferable_skill` | Validated across tasks/objects/seeds without baseline regression. | Yes |

## Claim Boundaries

### Allowed Claims

- Darwin can validate benchmark environments and block invalid ones.
- Darwin can diagnose structured physical-policy failures.
- Darwin can run paired no-regression evaluation.
- Darwin can promote a candidate recovery based on paired evidence.
- Darwin can block invalid or externally dependent failures.
- Darwin generates auditable evidence cards for every promotion decision.

### Disallowed Claims

- Darwin automatically solves all robot tasks.
- Darwin has proven transferable skills.
- Darwin has solved large-yaw torsional slip.
- Darwin results are official Arena leaderboard results unless explicitly accepted.
- Darwin replaces RL training.
- Darwin is a generic benchmark runner.
- Darwin is only a dashboard visualization project.

## How to Read an Evidence Card

Each card (`cards/{name}.card.yaml` + `.card.md`) contains:

1. **Summary** — One-sentence product status.
2. **Task validity** — Scope and validity verdict.
3. **Candidate** — Intervention type and promotion status.
4. **Allowed claims** — What Darwin can honestly say.
5. **Blocked claims** — What Darwin must not say.
6. **Limitations** — Scope boundaries and next evidence needed.
7. **Artifacts** — Links to raw evidence files.

## How to Update Reports

1. Do not edit historical reports in `archive/`.
2. Add new evidence to `current/` under the correct product category.
3. Regenerate affected evidence cards with `rosclaw darwin card`.
4. Update `reports/INDEX_V1.md` with the new status.
5. Run `python scripts/quality/check_claim_boundaries.py` before committing.

## See Also

- `reports/INDEX_V1.md` — Current product status.
- `docs/DARWIN_CLAIM_BOUNDARIES.md` — Detailed claim language.
- `docs/DARWIN_EVIDENCE_LEVELS.md` — Evidence level definitions.
- `docs/DARWIN_PRODUCT_DEFINITION.md` — Product scope.

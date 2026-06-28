# ROSClaw-Darwin v1.0 Release Notes

## Version

`1.0.0`

## What is v1.0?

ROSClaw-Darwin v1.0 is the first productized release of the evidence engine. It does not introduce new robot-learning experiments; it turns existing v1.3–v1.10 research evidence into a deliverable system for policy promotion.

## Delivered capabilities

1. **Validity Gate** — reject invalid benchmark environments.
2. **Paired No-Regression Evaluator** — compare baseline and candidate on the same seeds.
3. **Failure Diagnosis Engine** — structured failure signatures from traces.
4. **Candidate Recovery / Skill Registry** — ledger of interventions and evidence.
5. **Evidence Card Generator** — YAML + Markdown evidence summaries.
6. **Promotion Decision Engine** — map evidence to promotion level and blocked claims.
7. **Unified CLI** — `darwin <subcommand>`.
8. **Dashboard** — product-focused web views.
9. **Demo Pack** — runnable smoke demos.
10. **Release Gate** — automated claim-boundary checks.

## Evidence cards

- `official_goalpose_baseline` — valid official asset + clean baseline.
- `seed24_micro_recovery` — candidate recovery with paired no-regression evidence.
- `procedural_fallback_invalid_environment` — invalid environment blocked.
- `large_yaw_torsional_slip_blocked_external` — externally blocked failure.
- `learned_trigger_bounded_residual_experimental` — experimental-only component.

## Known limitations

- `franka_ik_abs` is a local patch unless accepted by Arena.
- Large-yaw torsional slip remains `blocked_external`.
- Learned trigger + bounded residual is safe but not yet effective.
- No `validated_transferable_skill` evidence exists yet.
- Procedural cube fallback is an invalid environment for skill evaluation.
- Evidence level stops at `candidate_recovery` on simulation.

## CLI commands

```bash
darwin validate-env
darwin run
darwin diagnose
darwin pair-eval
darwin promote
darwin card
darwin registry add
darwin report
darwin dashboard
```

## Tests

- Unit tests: `pytest tests/unit -q`
- Integration tests: `pytest tests/integration -q`
- Release gate: `python scripts/quality/run_darwin_v1_release_gate.py`

## Date

2026-06-28

# ROSClaw-Darwin v1.0 Release Report

**Date:** 2026-06-28  
**Version:** 1.0.0  
**Release gate:** PASSED

## 1. What is Darwin v1.0?

ROSClaw-Darwin v1.0 is the **evidence engine for evolving physical policies safely**. It turns every proposed robot-policy change into auditable evidence and enforces honest claim boundaries.

The v1.0 release does **not** introduce new robot-learning experiments. It productizes the existing v1.3–v1.10 research evidence into a deliverable system.

## 2. Delivered product capabilities

| # | Capability | Status |
|---|---|---|
| 1 | Validity Gate | v1.0 |
| 2 | Paired No-Regression Evaluator | v1.0 |
| 3 | Failure Diagnosis Engine | v1.0 |
| 4 | Candidate Recovery / Skill Registry | v1.0 |
| 5 | Evidence Card Generator | v1.0 |
| 6 | Promotion Decision Engine | v1.0 |
| 7 | Unified CLI | v1.0 |
| 8 | Dashboard product views | v1.0 |
| 9 | Demo Pack | v1.0 |
| 10 | Release gate + claim linter | v1.0 |

## 3. CLI commands

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

See `demo_pack/commands.sh` for a runnable smoke demo.

## 4. Schemas

The canonical schema surface is in `rosclaw_darwin/schemas/`:

- `task_validity.py`
- `failure_signature.py`
- `intervention.py`
- `paired_evidence.py`
- `promotion_decision.py`
- `evidence_card.py`
- `run_artifact.py`

Old direct imports continue to work.

## 5. Evidence cards

| Card | Type | Status |
|---|---|---|
| `official_goalpose_baseline` | baseline | v1.0 baseline |
| `seed24_micro_recovery` | recovery | candidate_recovery |
| `procedural_fallback_invalid_environment` | blocked_external | invalid environment |
| `large_yaw_torsional_slip_blocked_external` | blocked_external | blocked external |
| `learned_trigger_bounded_residual_experimental` | recovery | experimental_only |

Copies are in `release/darwin_v1/EVIDENCE_CARDS/`.

## 6. Demos

The `demo_pack/` directory contains six demos:

1. Official goal_pose baseline
2. Seed 24 micro-recovery
3. Procedural fallback invalidity
4. Large-yaw torsional slip
5. Learned trigger + bounded residual
6. Valid OOD suite

All run in `--mock` mode.

## 7. Current evidence level

The highest evidence level achieved in v1.0 is **candidate_recovery** for `seed24_micro_recovery` based on paired no-regression evaluation over seeds 0:199.

No `validated_recovery` or `validated_transferable_skill` evidence exists yet.

## 8. What cannot be claimed

- Darwin automatically solves all robot tasks.
- Darwin has proven transferable skills.
- Darwin has solved large-yaw torsional slip.
- Darwin results are official Arena leaderboard results unless accepted.
- Darwin replaces RL training.
- Procedural OOD success is not claimed.

## 9. Test results

| Suite | Result |
|---|---|
| Unit tests | PASS |
| Integration tests | PASS |
| CLI smoke | PASS |
| Dashboard loaders | PASS |
| Claim boundaries | PASS |
| Docs exist | PASS |

Run the gate:

```bash
python scripts/quality/run_darwin_v1_release_gate.py
```

## 10. Roadmap

### Roadmap A: Dojo / RL integration
- Feed Darwin evidence into Dojo training loops.
- Use Darwin as the promotion gate for RL-discovered policies.

### Roadmap B: Contact / force integration
- Upgrade large-yaw diagnosis once contact/force sensing is available.
- Move large-yaw from `blocked_external` to `candidate_recovery` if sensor evidence supports it.

### Roadmap C: Transferable skill evidence
- Run cross-task/object replication studies.
- Produce a `validated_transferable_skill` evidence card.

## 11. Release package

The release package is in `release/darwin_v1/`:

- `README.md`
- `RELEASE_NOTES.md`
- `CHECKLIST.md`
- `DEMO_GUIDE.md`
- `CLAIM_BOUNDARIES.md`
- `EVIDENCE_CARDS/`

## 12. Sign-off

- Engineering implementation: complete.
- Release gate: PASSED.
- Product owner review: pending.
- Release tag: pending.

---

*ROSClaw-Darwin v1.0 — any robot skill that wants to enter ROSClaw runtime must first pass through Darwin's evidence-based admission flow.*

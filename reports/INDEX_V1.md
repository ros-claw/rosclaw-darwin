# ROSClaw-Darwin v1.0 Product Index

> **Start here** for the current product status. Historical experiment reports remain in `reports/archive/v13_to_v20/`.

## What is ROSClaw-Darwin v1.0?

ROSClaw-Darwin is the evidence engine for evolving physical policies safely. It turns robot-policy evidence into auditable promotion decisions: validate environments, diagnose failures, run paired no-regression evaluation, promote recoveries, and block unsupported claims.

## Current Status (2026-06-28)

| Capability | Status | Evidence |
|---|---|---|
| Validity Gate | v1.0 | Procedural cube fallback blocked as invalid environment. |
| Paired No-Regression Evaluator | v1.0 | Seed 24 micro-recovery: 2 rescued, 0 newly failed on 0:199. |
| Failure Diagnosis | v1.0 | Seed 24 post-lift slip, large-yaw torsional slip, procedural invalidity. |
| Promotion Decision Engine | v1.0 | FailureToHint v3.4 + paired evidence gate. |
| Promotion Registry | v1.0 | `seed24_micro_recovery` registered as `candidate_recovery`. |
| Evidence Card Generator | v1.0 | 5 demo cards generated in `cards/`. |
| Unified CLI | v1.0 | `rosclaw darwin <subcommand>` with `--mock` smoke mode. |
| Dashboard | v1.0 | Product overview, evidence cards, registry, blocked-external views. |
| Learned Trigger + Bounded Residual | experimental | Safe, no seeds rescued in paired evaluation. |
| Transferable Skill | not proven | No cross-task/object validated evidence yet. |

## Evidence Cards

All cards live in `cards/`:

1. `official_goalpose_baseline.card.yaml` — Official dex_cube baseline, 99/100 success.
2. `seed24_micro_recovery.card.yaml` — `candidate_recovery`, rescued 2 seeds without regression.
3. `procedural_fallback_invalid_environment.card.yaml` — `blocked_external`, invalid environment.
4. `large_yaw_torsional_slip_blocked_external.card.yaml` — `blocked_external`, outside current capability.
5. `learned_trigger_bounded_residual_experimental.card.yaml` — `experimental_only`, safe but not effective.

## Quick CLI Demo

```bash
# Validate environment
rosclaw darwin validate-env --task configs/tasks/goal_pose_dex_cube_official.yaml --mock

# Run paired no-regression evaluation
rosclaw darwin pair-eval \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --baseline configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --candidate configs/policies/heuristic_servo_goal_pose_v3_seed24_micro_recovery.yaml \
  --seeds 0:4 --mock

# Generate evidence card
rosclaw darwin card --candidate seed24_micro_recovery --mock

# Register promoted recovery
rosclaw darwin registry add --name seed24_micro_recovery --card cards/seed24_micro_recovery.card.yaml

# Query runtime recoveries
rosclaw darwin registry recoveries --task seed24
```

## What Darwin Does Not Claim

- It does not solve all robot tasks.
- It does not have proven transferable skills.
- It does not solve large-yaw torsional slip.
- It is not an official Arena leaderboard result.
- It does not replace RL training.

## Directory Guide

- `rosclaw_darwin/schemas/` — Canonical evidence schemas.
- `rosclaw_darwin/cli/darwin_app.py` — Unified CLI.
- `rosclaw_darwin/evidence/` — Evidence card generator.
- `rosclaw_darwin/registry/` — Promotion registry and policy.
- `rosclaw_darwin/dashboard/` — Product dashboard.
- `demo_pack/` — Runnable demos.
- `scripts/quality/` — Release gates and claim linter.

## Next Roadmap

- **Roadmap A**: Dojo / RL integration for broader skill acquisition.
- **Roadmap B**: Contact / force integration for slip-aware recovery.
- **Roadmap C**: Transferable skill evidence across tasks and objects.

## See Also

- `docs/DARWIN_PRODUCT_DEFINITION.md` — Product definition.
- `docs/DARWIN_SCOPE_BOUNDARY.md` — Scope and boundaries.
- `docs/DARWIN_EVIDENCE_LEVELS.md` — Evidence levels.
- `docs/DARWIN_REPORTING_GUIDE.md` — How to read and write reports.
- `docs/DARWIN_CLAIM_BOUNDARIES.md` — Detailed claim language.

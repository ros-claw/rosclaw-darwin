# ROSClaw-Darwin v1.0 Release Checklist

## Code quality

- [x] `ruff check rosclaw_darwin tests scripts` passes.
- [x] Unit tests pass: `pytest tests/unit -q`.
- [x] Integration tests pass: `pytest tests/integration -q`.

## CLI

- [x] `darwin --help` works.
- [x] `darwin validate-env --help` works.
- [x] `darwin pair-eval --help` works.
- [x] `darwin card --help` works.
- [x] `darwin registry --help` works.

## Evidence

- [x] All 5 required evidence cards exist in `cards/`.
- [x] Each card has `allowed_claims` and `blocked_claims`.
- [x] `seed24_micro_recovery` is marked `candidate_recovery`.
- [x] `large_yaw_torsional_slip_blocked_external` is marked `blocked_external`.
- [x] `procedural_fallback_invalid_environment` is marked invalid.

## Registry

- [x] `PromotionRegistry` persists to JSON.
- [x] `blocked_external` cannot be promoted.
- [x] `seed24_micro_recovery` can be registered.

## Dashboard

- [x] `/` overview renders.
- [x] `/validity`, `/baselines`, `/paired-evaluations`, `/promotions`, `/evidence-cards`, `/registry`, `/blocked-external`, `/demos` render.
- [x] Product navigation is visible.

## Documentation

- [x] `README.md` is product-focused.
- [x] `docs/DARWIN_PRODUCT_DEFINITION.md` exists.
- [x] `docs/DARWIN_SCOPE_BOUNDARY.md` exists.
- [x] `docs/DARWIN_EVIDENCE_LEVELS.md` exists.
- [x] `docs/DARWIN_CLAIM_BOUNDARIES.md` exists.
- [x] `docs/DARWIN_REPORTING_GUIDE.md` exists.
- [x] `docs/DARWIN_ARCHITECTURE.md` exists.

## Demo pack

- [x] `demo_pack/README.md` is self-contained.
- [x] `demo_pack/commands.sh` runs in `--mock` mode.
- [x] 5 demos map to 5 evidence cards.

## Release gate

- [x] `python scripts/quality/check_claim_boundaries.py` passes.
- [x] `python scripts/quality/run_darwin_v1_release_gate.py` passes.

## Claim boundaries

- [x] No unsupported claims in v1.0 documents.
- [x] No `blocked_external` item marked `validated`.
- [x] No invalid environment used for skill claim.

## Sign-off

- [ ] Product owner review.
- [ ] Engineering lead review.
- [ ] Release tag created.

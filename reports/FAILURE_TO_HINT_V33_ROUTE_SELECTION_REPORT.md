# FailureToHint v3.3 Route Selection Report

## Summary

FailureToHint v3.3 extends v3.2 by adding explicit **route selection** and **claim-level** metadata.  A route answers the question: *if this hint is triggered at runtime, what should actually be executed?*  The claim level prevents the engine from advertising a recovery it cannot perform.

## New Schema Fields

### `HintRecipe`

- `route_selection`: one of `conditional_micro_recovery`, `abort_safe`, `human_escalation`, `diagnosis_only`, `blocked_external`.
- `monitor`: the sensor/proxy that justifies the route, e.g. `grip_quality_monitor`, `slip_monitor`.
- `claim_level`: `diagnosis_only`, `recovery_candidate`, or `validated`.
- `promotion_status`: `experimental`, `boundary_recovery_candidate`, `validated_transferable_skill`, or `blocked_external`.

### `SkillHint`

Each emitted `SkillHint` now carries the selected route and claim level:

- `route_selection`
- `monitor`
- `claim_level`
- `promotion_status`

## Route Selection Logic

`rosclaw_darwin.evolution.failure_to_hint.select_recovery_route(tags, registry, task_id)`:

1. Query the `HintRecipeRegistry` for recipes matching the failure-signature tags.
2. Prefer task-validated recipes, then recipes by source trust and confidence.
3. If a matched recipe defines a `route_selection`, use it.
4. Otherwise fall back to tag-based heuristics:
   - Seed-24-like tags (`grip_force_insufficient`, `low_object_z_at_grasp`, `gripper_too_open`) → `conditional_micro_recovery`.
   - Large-yaw / torsional-slip tags → `blocked_external` / `diagnosis_only`.
   - Everything else → `diagnosis_only`.

## Config: `configs/skills/failure_signature_to_hint_rules_v33.yaml`

Two illustrative rules are included:

- `seed24_grip_quality_micro_recovery`: experimental, recovery candidate, monitor `grip_quality_monitor`.
- `large_yaw_torsional_slip`: blocked external, diagnosis only, monitor `slip_monitor`.

## Validation

Unit tests in `tests/unit/test_fth_v33_route_selection.py` cover:

- Seed-24 tag route selection.
- Large-yaw blocked-external route selection.
- Unknown-tag default to diagnosis only.
- Recipe-level override of default routes.
- Propagation of route/claim into `SkillHint` via `suggest_from_signatures`.
- Loading of the v3.3 YAML config.

All tests pass:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/unit/test_failure_to_hint.py tests/unit/test_failure_signature_to_hint_rules.py tests/unit/test_fth_v33_route_selection.py -q
```

Result: **30 passed**.

## Status

- Code implementation: **complete**.
- Config: **complete**.
- Unit tests: **complete**.
- Live Arena validation: **pending** (blocked behind Sprint 1 Docker verification).

## Claim

v3.3 is an experimental schema extension.  No live Arena gain has been measured yet, so no recipe is promoted above `experimental` / `recovery_candidate` (seed24) or `blocked_external` / `diagnosis_only` (large yaw).

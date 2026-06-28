# FailureToHint v3.2 — Recovery Policy Selection Report

**Date:** 2026-06-23  
**Sprint:** v1.8 Sprint 7  
**Status:** Schema implemented, unit/integration tests passing, runtime wiring ready for Sprint 6 recovery strategies.

---

## 1. Goal

Upgrade FailureToHint from *parameter/structural hint selection* (v3.1) to *recovery-policy selection* (v3.2).  Instead of only telling the policy "tighten grasp" or "move slower", v3.2 recommends a **closed-loop recovery strategy** complete with:

- the monitor/proxy that watches for failure (e.g. `SlipMonitor`),
- the activation condition (score threshold, phase whitelist, consecutive steps),
- concrete parameter overrides for that strategy,
- the success metric that decides whether recovery worked,
- a nested fallback policy if the first recovery fails.

This lets the evolution loop propose complete interventions such as "when torsional slip exceeds 3.5 for 3 consecutive steps in LIFT/ALIGN/HOLD, run `best_combined` recovery; if it still fails, `abort_safe`".

---

## 2. What changed

### 2.1 New schema — `rosclaw_darwin/evolution/recovery_hint.py`

Pydantic models added:

| Model | Purpose |
|-------|---------|
| `MonitorConfig` | Selects and configures the sensor/proxy (`slip_monitor`, `contact_proxy`, `none`). |
| `ActivationCondition` | Thresholds/phases that must be true before a recovery is triggered. |
| `SuccessMetric` | Metric + optional threshold used to judge recovery success. |
| `RecoveryPolicy` | The full recovery intervention, including a recursive `fallback_policy`. |
| `RecoveryHint` | A `SkillHint`-like carrier that also holds a `RecoveryPolicy`. |

Example instantiation:

```python
RecoveryPolicy(
    type="best_combined",
    max_attempts=2,
    monitor=MonitorConfig(type="slip_monitor", enabled=True, event_score_threshold=3.5, min_event_steps=5),
    activation_condition=ActivationCondition(
        slip_score_gt=3.5,
        phase_in=["LIFT", "REORIENT", "ALIGN", "HOLD", "VERIFY_OBJECT_FOLLOWING"],
        consecutive_slip_steps=3,
        any_slip=True,
    ),
    parameter_overrides={
        "slip_recovery_pause_steps": 10,
        "slip_recovery_lower_delta_z": 0.05,
        "slip_recovery_place_push_max_steps": 40,
        "slip_recovery_place_push_yaw_step": 0.10,
        "slip_recovery_abort_yaw_threshold": 0.5,
    },
    success_metric=[
        SuccessMetric(metric="orientation_achieved_rate"),
        SuccessMetric(metric="slip_recovery_success_rate"),
    ],
    fallback_policy=RecoveryPolicy(type="abort_safe", max_attempts=1),
)
```

### 2.2 `HintRecipe` now carries an optional policy

`rosclaw_darwin/evolution/hint_recipe.py`

- Added `recovery_policy: RecoveryPolicy | None = None` to `HintRecipe`.
- `HintRecipeRegistry.select_hints()` now returns **six values**:
  ```python
  selected_hints, parameter_overrides, matched_recipes,
  structural_overrides, strategy_switches, recovery_policy
  ```
- Conflict resolution still uses the existing precedence/incompatibility rules for hints; the first matched recipe that defines a `recovery_policy` wins.

### 2.3 `SkillHint` carries the merged policy

`rosclaw_darwin/evolution/failure_to_hint.py`

- Added `recovery_policy: RecoveryPolicy | None = None` to `SkillHint`.
- `FailureToHintEngine.suggest_from_signatures()` now unpacks the six return values from `select_hints()` and attaches the merged `recovery_policy` to every emitted `SkillHint`.
- The coarse `suggest(failure_types)` engine still works and does **not** attach recovery policies (it has no recipe context).

### 2.4 New v3.2 rule file

`configs/skills/failure_signature_to_hint_rules_v32.yaml`

Three recovery-policy rules:

1. **torsional_slip_recovery** → `best_combined` (fallback `abort_safe`)  
   Triggered by `torsional_slip`, `large_yaw_failure`, `rotation_induced_slip`, `object_lifted`.
2. **vertical_slip_recovery** → `lower_regrip` (fallback `abort_safe`)  
   Triggered by `vertical_slip`, `lifted_then_dropped`, `drop_after_lift`.
3. **residual_yaw_abort_recovery** → `abort_residual_yaw` (fallback `abort_safe`)  
   Triggered by `eef_yaw_failure`, `yaw_not_transferred_to_object`.

The old v3.1 rule file (`failure_signature_to_hint_rules.yaml`) is unchanged; v3.2 is opt-in by loading the new YAML path.

---

## 3. Test coverage

New tests:

- `tests/unit/test_recovery_hint_schema.py`
  - `RecoveryPolicy` defaults and nested fields
  - `HintRecipeRegistry` merge of the first non-None `recovery_policy`
  - `FailureToHintEngine` coarse engine correctly leaves `recovery_policy` empty
  - `SkillHint` JSON round-trip with a nested policy
  - v3.2 YAML loads and contains at least one policy

Updated tests:

- `tests/unit/test_failure_signature_to_hint_rules.py`
- `tests/unit/test_hint_conflict_resolution.py`
- `scripts/ablations/run_valid_ood_cube_matrix.py`

All updated to unpack the new six-value return from `select_hints()`.

Integration tests:

- `tests/integration/test_v18_schemas.py`
  - Validates slip-recovery aggregate schema once ablation data exists.
  - Validates valid OOD cube task-config metadata.
  - Validates v3.2 rules load and contain policies.

### Test command and result

```bash
pytest tests/unit/test_recovery_hint_schema.py \
       tests/unit/test_failure_signature_to_hint_rules.py \
       tests/unit/test_hint_conflict_resolution.py \
       tests/integration/test_v18_schemas.py -q
```

Result: **19 passed**, 1 unrelated `httpx` deprecation warning.

---

## 4. v3.1 → v3.2 comparison

| Capability | v3.1 | v3.2 |
|------------|------|------|
| Parameter hints | ✅ | ✅ |
| Structural overrides | ✅ | ✅ |
| Strategy switches | ✅ | ✅ |
| Monitor/proxy selection | ❌ | ✅ |
| Activation condition (threshold + phase) | ❌ | ✅ |
| Success metric for recovery | ❌ | ✅ |
| Fallback policy on failure | ❌ | ✅ |
| Nested policy recursion | ❌ | ✅ |

---

## 5. Backward compatibility

- `RecoveryPolicy` is optional everywhere.
- v3.1 YAML still loads because `recovery_policy` defaults to `None`.
- Existing callers of `select_hints()` were updated to unpack six values; new callers must do the same.
- `SkillHint.model_dump(mode="json")` serializes `recovery_policy` only when present, so downstream consumers that ignore the field are unaffected.

---

## 6. Honest limitations

- **Not yet validated in live Arena:** the schema and wiring are in place, but the actual closed-loop recovery policies are only starting to be ablated in Sprint 6.  No claim is made that `best_combined` or `lower_regrip` solve large-yaw torsional slip until Sprint 6 data is in.
- **Policy execution is still heuristic-side:** the `RecoveryPolicy` is emitted as a hint/artifact; the live `heuristic_policy.py` state machine must read the equivalent parameter overrides (`slip_recovery_strategy`, `slip_recovery_pause_steps`, etc.) to act on it.
- **Fallback depth is currently one level** in the rules; the schema supports arbitrary recursion, but no runtime executor exercises deeper nesting yet.

---

## 7. Files modified / added

- `rosclaw_darwin/evolution/recovery_hint.py` **(new)**
- `rosclaw_darwin/evolution/hint_recipe.py`
- `rosclaw_darwin/evolution/failure_to_hint.py`
- `configs/skills/failure_signature_to_hint_rules_v32.yaml` **(new)**
- `tests/unit/test_recovery_hint_schema.py` **(new)**
- `tests/unit/test_failure_signature_to_hint_rules.py`
- `tests/unit/test_hint_conflict_resolution.py`
- `tests/integration/test_v18_schemas.py` **(new)**
- `scripts/ablations/run_valid_ood_cube_matrix.py`

---

## 8. Conclusion

FailureToHint v3.2 closes the loop between diagnosis and intervention: failure signatures now map not only to parameter tweaks but to full closed-loop recovery policies.  The schema is tested, backward-compatible, and ready to consume the results of the Sprint 6 slip-aware recovery ablation.  The next step is to wire the winning recovery strategy from Sprint 6 into the default rule set and validate that the emitted policies actually improve large-yaw orientation success.

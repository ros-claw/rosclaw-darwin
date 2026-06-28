# Final Darwin v1.8 Status Report

**Date:** 2026-06-23  
**Status:** v1.8 implementation **complete**. All planned Sprints (0–8) are finished, reports and dashboard are updated, and unit/integration tests pass. The official dex_cube line remains **99/100**; no new policy was promoted because every seed-24 fix and every large-yaw recovery strategy either regressed the benchmark or failed to improve orientation success.

---

## Executive Summary

v1.8 executed the planned Sprints in order:

| Sprint | Topic | Result |
|---|---|---|
| 0 | v1.7 milestone freeze + escalation packages | ✅ milestone frozen; two Arena escalation packages ready |
| 1 | Seed 24 post-lift slip forensics | ✅ deterministic root cause identified (`grip_force_insufficient` due to low object z at grasp) |
| 2 | Seed 24 minimal fix + official regression | ❌ all three fixes repair seed 24 but regress 0:99; no promotion |
| 3 | Build valid OOD cube benchmark | ✅ 7 local validated cube variants pass object-validity audit |
| 4 | Valid OOD baseline + ObjectGeometryAdapter | ⚠️ benchmark works, but adapter shows **no gain** over baseline |
| 5 | Closed-loop slip detection | ✅ kinematic `SlipMonitor` exceeds high-quality bar on v1.7 large-yaw traces |
| 6 | Closed-loop slip-aware recovery | ⚠️ infrastructure works, no strategy improves large-yaw orientation |
| 7 | FailureToHint v3.2 recovery policies | ✅ schema implemented, tested, backward-compatible |
| 8 | Dashboard, tests, report index | ✅ 5 new views, 268 unit/integration tests pass, lint clean |

**Bottom line:** v1.8 advanced the *infrastructure* for closed-loop recovery and produced a local valid OOD benchmark, but it did **not** move the official success line past 99/100 and did **not** solve large-yaw torsional slip.

---

## Level A — Proven

### A.1 v1.7 official benchmark remains frozen at 99/100

- Policy: `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`
- Result: **99/100 success (99.0%)**, Wilson 95% CI [94.55%, 99.82%]
- Zero asset fallback, zero physics anomaly, zero metric parser error, zero approach collision
- Report: `reports/DEX_CUBE_GOAL_POSE_100_SEED_POST_REACHABILITY_REPORT.md`

No v1.8 candidate improved this line without regression, so the v1.7 promoted config stays official.

### A.2 v1.7 milestone and escalation packages are finalized

- `reports/MILESTONE_DARWIN_V17_OFFICIAL_GOALPOSE_BREAKTHROUGH.md`
- `reports/V17_MILESTONE_AND_ESCALATION_REPORT.md`
- `external_reviews/procedural_cube_fallback_invalidity_escalation.md`
- `external_reviews/large_yaw_torsional_slip_escalation.md`

Both escalation packages contain reproduction commands, evidence tables, artifact paths, and explicit asks. They are **ready to submit** but have **not been submitted** pending user authorization.

### A.3 Seed 24 failure is deterministic and root-caused

- 10/10 repeats failed with the same signature.
- Root cause: `grip_force_insufficient` — the gripper stays at ~0.0388 m while lifted instead of closing to the blocked width (~0.024 m).
- Trigger: low object z at GRASP (~0.021 m vs 0.025–0.028 m in successful seeds).
- Report: `reports/SEED24_POST_LIFT_SLIP_FORENSICS_REPORT.md`

### A.4 Valid OOD cube benchmark is locally constructible and valid

- 7 variants: 0.04, 0.05, 0.06, 0.08, 0.10 m cubes, low-friction, heavy.
- Object-validity audit: 7 variants × 20 seeds × 5 episodes = 700 episodes audited.
- `valid_rate = 1.0`, `collision_enabled_rate = 1.0`, `bbox_valid_rate = 1.0`, `rigid_body_enabled_rate = 1.0` for every variant.
- Report: `reports/VALID_OOD_CUBE_BENCHMARK_CONSTRUCTION_REPORT.md`

### A.5 Closed-loop kinematic slip monitor passes high-quality detection bar

- Dataset: 40 v1.7 large-yaw traces (20 per yaw).
- Recall on failures: **0.974**
- Precision: **1.000**
- FPR on successes: **0.0**
- Median early detection: **2099 steps** before episode end.
- Report: `reports/SLIP_MONITOR_VALIDATION_REPORT.md`

### A.6 FailureToHint v3.2 schema is implemented and tested

- `RecoveryPolicy`, `MonitorConfig`, `ActivationCondition`, `SuccessMetric`, recursive `fallback_policy`.
- `HintRecipe` and `SkillHint` carry optional `recovery_policy`.
- v3.2 rule file loads; 19 unit/integration tests pass; backward-compatible with v3.1.
- Report: `reports/FAILURE_TO_HINT_V32_RECOVERY_POLICY_REPORT.md`

### A.7 Dashboard and test infrastructure are updated and green

- New dashboard views: `/official-v18`, `/valid-ood`, `/slip-monitor`, `/slip-recovery`, `/external-blockers`.
- Unit + integration tests: **268 passed**, 1 unrelated `httpx` deprecation warning.
- Dashboard integration test: **10/10 passed**.
- `ruff check` clean on changed v1.8 files.
- Report: `reports/SLIP_AWARE_RECOVERY_ABLATION_REPORT.md` (Sprint 6); this report (Sprint 9).

---

## Level B — Preliminary Evidence

### B.1 Seed-24 fixes repair the single seed but regress the benchmark

Three successive pre-grasp-orientation fixes were ablated:

| Fix | Seed 24 focused ablation | 0:99 regression |
|---|---|---|
| v1 | 10/10 success | 84/100 |
| v2 | 10/10 success | 95/100 |
| v3 | 10/10 success | 38/41 (0.927) before early stop |

All fixes clear the seed-24 target (≥8/10) but fail the no-regression gate (≥98/100 on 0:99). The fixes change grasp geometry enough to introduce new `unknown` failures and approach collisions elsewhere. Report: `reports/SEED24_FIX_AND_OFFICIAL_REGRESSION_REPORT.md`.

### B.2 Valid OOD benchmark runs, but ObjectGeometryAdapter shows no measurable gain

- 280 episodes across 7 variants × 4 conditions × 10 seeds.
- Aggregate success rate is ~0.686 for **all four conditions** (`baseline_no_adapter`, `object_geometry_adapter`, `adapter_mass_friction`, `adapter_structural`).
- Per-variant pattern:
  - 0.04–0.06 m cubes: **10/10 success**
  - 0.08–0.10 m cubes: **0/10 success** (reachability/grasp geometry boundary)
  - low-friction: **~8/10 success**
  - heavy: **10/10 success**
- The bottleneck on valid OOD is size/reachability and large-yaw slip, not threshold scaling. Report: `reports/VALID_OOD_OBJECT_GEOMETRY_ADAPTER_REPORT.md`.

### B.3 Closed-loop slip-aware recovery preserves lift but does not rescue orientation

- Pilot: 6 conditions × 2 yaws × 3 seeds = 36 serial Arena runs.
- Recovery triggers reliably (`recovery_triggered_rate = 1.0` for all non-baseline conditions).
- `lifted_rate` and `env_success_rate` remain 1.0 for all strategies except `abort_residual_yaw`.
- `abort_residual_yaw` is destructive: 0% lifted, 0% env success.
- Orientation achieved rate:
  - π/2: baseline 33.3%; no strategy improves it.
  - 2π/3: 0% across all conditions.
- Report: `reports/SLIP_AWARE_RECOVERY_ABLATION_REPORT.md`.

---

## Level C — Not Proven / Blocked

### C.1 100/100 official dex_cube success

- Seed 24 remains a deterministic residual failure.
- All seed-24 fixes that repair seed 24 regress the rest of the 0:99 distribution.
- No closed-loop recovery strategy improved the official line in the pilot.

### C.2 Large-yaw torsional slip solution

- Open-loop structural interventions (grasp-at-target-yaw, low-height incremental yaw, table push-align, tuned push-align) were rejected in v1.7.
- Closed-loop kinematic recovery strategies (pause, lower-regrip, place-push) do not improve `orientation_achieved_rate`.
- The problem remains unsolved with current sensors and actuators.

### C.3 Validated transferable skill on valid OOD cubes

- The benchmark is valid, but adaptation does not outperform the base policy.
- No recipe can be promoted to `validated_transferable_skill`.

### C.4 FailureToHint v3.2 runtime effectiveness

- Schema and wiring are proven, but the policies it can emit have not been shown to improve live Arena outcomes.
- The default rule set should **not** claim a validated closed-loop recovery for `torsional_slip` until a winning strategy exists.

---

## Level D — External Dependencies

1. **Arena acceptance of `franka_ik_abs`** as an official embodiment.
2. **Arena-side fix for procedural cube fallback** so that `collision_enabled=True` and `bbox_valid=True` without a local patch.
3. **Force / contact / tactile sensors** for slip-aware recovery.
4. **Gripper/contact mechanics changes** (anti-slip fingertips, adjustable grip force, compliant contact) to address large-yaw torsional slip.
5. **Arena response to the two escalation packages** once submitted.

---

## Summary Table

| Claim | Evidence | Status |
|---|---|---|
| v1.7 99/100 official benchmark frozen | `configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml`, post-reachability report | **Level A** |
| Seed 24 deterministic root cause identified | 10-repeat forensics, grip-force evidence | **Level A** |
| Seed 24 fix without regression | all candidates regress 0:99 | **Level C** |
| Valid OOD cube benchmark valid | 7 variants × 20 seeds audit, all validity rates 1.0 | **Level A** |
| ObjectGeometryAdapter improves valid OOD | 280 episodes, no condition outperforms baseline | **Level C** |
| Slip monitor detects large-yaw slip | 40 traces, recall 0.974, precision 1.0, FPR 0.0 | **Level A** |
| Slip-aware recovery solves large-yaw slip | 36-run pilot, no orientation improvement | **Level C** |
| FailureToHint v3.2 schema implemented | 19 tests pass, backward-compatible | **Level A** |
| Dashboard/tests updated | 268 tests pass, 10/10 dashboard loader tests, ruff clean | **Level A** |
| Validated transferable skill | no recipe validated on valid OOD | **Level C** |

---

## Answers to the v1.8 Follow-Up Questions

1. **Did seed 24 get fixed without regression?**  
   No. Three pre-grasp-orientation fixes repair seed 24 in focused ablation but all regress 0:99 (84/100, 95/100, 38/41). Seed 24 remains the single known deterministic residual failure.

2. **What is the deterministic root cause of seed 24?**  
   `grip_force_insufficient` caused by a low object z at GRASP (~0.021 m vs ~0.025–0.028 m in successes), which leaves the gripper too open after lift.

3. **Is there a valid local OOD benchmark?**  
   Yes. Seven `rosclaw_valid_cube` variants pass a full object-validity audit (`valid_rate`, `collision_enabled_rate`, `bbox_valid_rate` all 1.0).

4. **Does ObjectGeometryAdapter help on the valid OOD benchmark?**  
   No measurable gain. All four conditions score ~0.686 success rate. The dominant failure modes are size/reachability boundaries and large-yaw slip, not grasp-threshold scaling.

5. **Is the closed-loop SlipMonitor ready?**  
   Yes. It exceeds the high-quality detection bar on 40 v1.7 large-yaw traces and is wired into the policy state machine.

6. **Does closed-loop slip-aware recovery improve large-yaw orientation?**  
   No. The pilot preserves lift and triggers reliably, but orientation success does not improve over baseline. `abort_residual_yaw` is destructive and rejected.

7. **Is FailureToHint v3.2 implemented and tested?**  
   Yes. The recovery-policy schema is implemented, unit/integration tests pass, and it is backward-compatible with v3.1.

8. **Have the Sprint 6 results been fed back into the v3.2 rule set?**  
   The rule set should **not** claim a validated `torsional_slip` recovery because no strategy succeeded. The fallback remains `abort_safe` or human escalation.

9. **Are the v1.8 dashboard views and tests ready?**  
   Yes. Five new views are live, the INDEX is updated, and `pytest tests/unit tests/integration` passes (268 tests) plus 10/10 dashboard loader tests.

10. **Were the Arena escalation packages submitted?**  
    No. Both packages are finalized and ready, but outward submission requires user authorization and has not happened yet.

11. **Was a 100:199 holdout run completed?**  
    No. No candidate cleared the 0:99 no-regression gate, so no promotion triggered a holdout evaluation.

12. **What is the next frontier for 100/100?**  
    Force/contact sensing, gripper force/friction control, or Arena-side contact mechanics changes. Kinematic-only open-loop and closed-loop strategies have been exhausted.

---

## Tests and Lint

```bash
pytest tests/unit tests/integration -q
# 268 passed, 1 warning

pytest tests/integration/test_dashboard_v18_loaders.py -v
# 10 passed

ruff check rosclaw_darwin/dashboard/app.py rosclaw_darwin/dashboard/charts.py \
  tests/integration/test_dashboard_v18_loaders.py \
  rosclaw_darwin/evolution/recovery_hint.py \
  rosclaw_darwin/evolution/hint_recipe.py \
  rosclaw_darwin/evolution/failure_to_hint.py
# All checks passed
```

---

## Files Produced / Updated in v1.8

- `rosclaw_darwin/evaluation/slip_monitor.py`
- `rosclaw_darwin/evolution/recovery_hint.py`
- `rosclaw_darwin/evolution/hint_recipe.py`
- `rosclaw_darwin/evolution/failure_to_hint.py`
- `rosclaw_darwin/dashboard/app.py`
- `rosclaw_darwin/dashboard/charts.py`
- `rosclaw_darwin/dashboard/templates/*.html`
- `configs/skills/failure_signature_to_hint_rules_v32.yaml`
- `configs/tasks/goal_pose_rosclaw_valid_cube_*.yaml`
- `scripts/ablations/run_slip_aware_recovery_ablation.py`
- `scripts/diagnostics/run_slip_monitor_validation.py`
- `tests/integration/test_dashboard_v18_loaders.py`
- `tests/integration/test_v18_schemas.py`
- `reports/SLIP_AWARE_RECOVERY_ABLATION_REPORT.md`
- `reports/FAILURE_TO_HINT_V32_RECOVERY_POLICY_REPORT.md`
- `reports/FINAL_DARWIN_V18_STATUS_REPORT.md` (this report)
- `reports/INDEX.md`

---

## Conclusion

v1.8 completed its mission of **honestly probing the next frontier** after the v1.7 99/100 breakthrough. The infrastructure for closed-loop recovery is now in place, a valid local OOD benchmark exists, and the v3.2 policy schema can express complete recovery interventions. However:

- **Seed 24 is not fixed without regression.**
- **Large-yaw torsional slip is not solved by kinematic strategies.**
- **ObjectGeometryAdapter does not improve the valid OOD benchmark.**

The official dex_cube line stays at **99/100** with the v1.7 promoted config. The path to 100/100 and to validated transferable skills now depends on **Arena-side contact/gripper changes and force sensing**, not on further open-loop or kinematic-only tuning.

*ROSClaw-Darwin v1.8 final status — honest evidence summary.*

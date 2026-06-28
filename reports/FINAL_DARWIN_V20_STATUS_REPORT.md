# Final Darwin v1.10 Status Report

**Date:** 2026-06-28  
**Plan:** [ROSClaw-Darwin v1.10 Implementation Plan](../plans/polished-weaving-pizza.md)

---

## Executive Summary

v1.10 moves Darwin from a strong diagnostic/evaluation system toward a
**self-evolving physical-policy repair system**. The focus is no longer on
heuristic feature stacking, but on three new primitives:

1. **Paired no-regression evidence** for every candidate change.
2. **Small learned models** (trigger classifier, bounded residual regressor,
   route classifier) that are trained, clamped, and validated before they touch
   live control.
3. **Evidence-aware FailureToHint v3.4 promotion** that prevents unverified
   recovery claims from being promoted.

> **Key result:** The seed-24 micro-recovery is proven to rescue two seeds and
> introduce **zero regressions** on the corrected full official paired evaluation
> of seeds `0:199`. Its candidate success rate is **0.965**, which meets the 0.95
> gate; FailureToHint v3.4 therefore promotes it to **`candidate_recovery`**.
> The learned trigger model and bounded residual micro-policy are trained on the
> v2 residual dataset and pass their offline gates (success-frame FPR ≈ 0.3%,
> residual modification rate ≈ 0.27%, clamp rate = 0%). Their live paired Arena
> pilot on `0:199` is now complete: the combination is **safe**
> (`newly_failed_count = 0`) but **not effective** (`rescued_count = 0`), so it
> remains `experimental_only`. The large-yaw route classifier is trained but can
> only learn the two classes present in the dataset (`continue` and
> `blocked_external`); the three intermediate routes are unlabeled, so large-yaw
> torsional slip remains `blocked_external`.

All v1.10 sprints are implemented, lint-clean, and test-covered. The corrected
full `0:199` live paired evaluation is complete with zero invalid pairs; the
infrastructure-failure audit reports zero missed signals.

---

## Level A: Frozen / Proven

### A.1 Paired no-regression evaluation protocol is frozen

- Schema: `rosclaw_darwin/evaluation/paired_evaluation.py`
- Runner: `scripts/diagnostics/run_paired_policy_evaluation.py`
- Outcome classes: `rescued`, `newly_failed`, `unchanged_success`,
  `unchanged_failure`, `invalid_pair`.
- Statistics: McNemar exact p-value and bootstrap 95% CI on per-seed success
  delta.
- Evidence: [Paired No-Regression Evaluation Protocol](PAIRED_EVALUATION_PROTOCOL_REPORT.md)
- Verdict: Protocol implemented, unit-tested, integration-tested, and live on
  official dex_cube seeds.

### A.2 FailureToHint v3.4 evidence-aware promotion is implemented and tested

- Components: `EvidenceStatus`, `PromotionManager`, v3.4 YAML rules, infrastructure-failure audit.
- Promotion statuses: `experimental_only`, `candidate_recovery`,
  `blocked_external`, `human_escalation`.
- Hard blocks: `blocked_external` / `human_escalation` / `abort_safe` are never
  promoted, even with a passing gate.
- Evidence:
  - [FailureToHint v3.4 Evidence-Aware Promotion Report](FAILURE_TO_HINT_V34_EVIDENCE_AWARE_PROMOTION_REPORT.md)
  - [Approach-Collision Failure Diagnosis Report](APPROACH_COLLISION_DIAGNOSIS_REPORT.md)
- Verdict: Unit and integration tests pass; large-yaw → `blocked_external`,
  seed-24 micro-recovery → `candidate_recovery` after the corrected paired
  evaluation (candidate success rate 0.965 ≥ 0.95 gate).

### A.3 Learned trigger / bounded residual / route infrastructure is in place

- `rosclaw_darwin/learning/trigger_model.py`
- `rosclaw_darwin/learning/bounded_residual_policy.py`
- `rosclaw_darwin/learning/route_classifier.py`
- All models are small (≤ 2 hidden layers), clamped, and container-loadable.
- Evidence:
  - [Learned Trigger Model Report](LEARNED_TRIGGER_MODEL_REPORT.md)
  - [Learned Bounded Residual Micro-Policy Report](LEARNED_BOUNDED_RESIDUAL_MICRO_POLICY_REPORT.md)
  - [Large-Yaw Route Policy Feasibility Report](LARGE_YAW_ROUTE_POLICY_FEASIBILITY_REPORT.md)
- Verdict: Code and tests complete; all three models are trained on the v2
  residual dataset.  The trigger + bounded residual live pilot on `0:199`
  satisfies the safety gate (`newly_failed_count = 0`) but not the efficacy gate
  (`rescued_count = 0`), so the combination remains `experimental_only`.  Route
  classifier is limited by dataset labels.

### A.4 Container-side fallback, Docker isolation, and infrastructure-failure detection are preserved

- Arena Docker trace directories are absolute and seed-isolated.
- `route_classifier.py` is bind-mounted into the container.
- `GripQualityMonitorConfig` / `GripQualityMonitor` aliases are exposed for
  container fallback.
- `ArenaRunner._detect_infrastructure_failure()` flags `BlockingIOError`,
  Python tracebacks, HDF5 lock errors, `CUDA out of memory`, and
  `No space left on device`.
- `audit_paired_infrastructure_failures.py` reports **0 missed** signals on the
  corrected `0:199` paired directory.
- Evidence: existing v1.7–v1.9 memory items, live paired-evaluation runs, and
  the infrastructure-failure re-audit.

---

## Level B: Promising Trends / Partial Evidence

### B.1 Seed-24 micro-recovery paired evaluation (seeds `0:199`)

- **Zero regressions** (`newly_failed_count = 0`).
- **Two rescued seeds** (24, 198).
- **Candidate success rate = 0.965** on valid pairs; baseline = 0.955.
- **McNemar p = 0.5**; bootstrap 95% CI for delta = [0.0, 0.025].
- **Invalid pairs:** 0 (no runner errors, asset fallback, or physics anomaly).
- **Infrastructure-failure audit:** 0 missed `stderr` signals.
- Evidence: [Seed24 Micro-Recovery Paired No-Regression Report](SEED24_MICRO_RECOVERY_PAIRED_NO_REGRESSION_REPORT.md)

The candidate is no-regression and now **meets the 0.95 candidate-success-rate
gate** declared in `failure_signature_to_hint_rules_v34.yaml`. FailureToHint
v3.4 promotes it to `candidate_recovery`. The earlier claim of six rescued seeds
was inflated by infrastructure failures misclassified as policy failures; the
re-audit corrected this.

### B.2 Large-yaw route-classifier integration

- Route classifier loads inside Docker and logs predictions in every frame.
- Diagnostic mode does **not** change actions, so it cannot fake success.
- Trained on the v2 residual dataset, the model cleanly separates `continue`
  from `blocked_external` offline (accuracy ~0.98), but it cannot predict
  `pause`, `lower_regrip`, or `abort_safe` because those classes are absent from
  the dataset.
- The live pilot still predicted `continue` on 100% of non-empty frames, so the
  trained model's `blocked_external` output has not yet been demonstrated inside
  Arena.
- Evidence: [Large-Yaw Route Policy Feasibility Report](LARGE_YAW_ROUTE_POLICY_FEASIBILITY_REPORT.md)

### B.3 Valid OOD medium-task mining and learned adaptation benchmark

- Mining script and benchmark runner are implemented and test-covered.
- The output directory `data_v20/ablations/valid_ood_learned_adaptation/` is
  currently empty because the live benchmark run was not completed in this
  session.
- Evidence:
  - [Valid OOD Medium-Task Selection Report](VALID_OOD_MEDIUM_TASK_SELECTION_REPORT.md)
  - [Valid OOD Learned Adaptation Benchmark Report](VALID_OOD_LEARNED_ADAPTATION_BENCHMARK_REPORT.md)

### B.4 Learned trigger + bounded residual live pilot (seeds `0:199`)

- **Paired evaluation complete** on all 200 official `dex_cube` pairs.
- **Safety gate passes**: `newly_failed_count = 0`, `invalid_pair_count = 0`, no
  asset fallback or physics anomaly.
- **Efficacy gate does not pass**: `rescued_count = 0`; candidate and baseline
  success rates are both **0.970**.
- The combination is therefore a **no-regression experimental component**, not a
  promoted recovery.
- Evidence:
  - [Learned Trigger Model Report](LEARNED_TRIGGER_MODEL_REPORT.md)
  - [Learned Bounded Residual Micro-Policy Report](LEARNED_BOUNDED_RESIDUAL_MICRO_POLICY_REPORT.md)
  - `data_v20/paired/triggered_learned_0_199/paired_summary.json`

---

## Level C: Not Yet Reached

### C.1 `validated_recovery` or `transferable_skill` status for seed-24 micro-recovery

- `candidate_recovery` has been achieved on the official `0:199` benchmark.
- `validated_recovery` / transferable skill would require replication on an
  independent held-out task or seed set not used in the promotion gate.

### C.2 Useful large-yaw route decisions

- Requires a frame-labeled large-yaw route dataset and re-training of the route
  classifier.

### C.3 Validated transferable skill on valid OOD cube

- Requires completion of the live learned-adaptation benchmark.

---

## Level D: Blocked Externally

### D.1 Large-yaw torsional slip

- Kinematic-only control cannot generate the in-hand torque required for π/2 or
  2π/3 target yaws.
- Force/tactile feedback and gripper-force modulation are not exposed by Arena.
- Honest route: `blocked_external`.

### D.2 Procedural cube fallback

- Still invalid (disabled collision, invalid bbox).
- OOD skill evaluation is restricted to `rosclaw_valid_cube` variants.

### D.3 Approach-collision recovery

- No dedicated recovery candidate exists; the independent
  `approach_collision_diagnosis` route keeps these failures out of the
  grip-quality promotion evidence until a paired no-regression intervention is
  developed.

---

## Sprint-by-Sprint Gate Status

| Sprint | Goal | Status |
|--------|------|--------|
| Sprint 0 | Paired-evaluation schema and protocol | Complete |
| Sprint 1 | Seed24 micro-recovery paired evaluation on `0:199` | Complete; zero regressions, 2 rescued, candidate success rate 0.965 ≥ 0.95 gate |
| Sprint 2 | ContactSignal reliability audit | Complete |
| Sprint 3 | Residual dataset v2 | Complete |
| Sprint 4 | Learned trigger model | Trained on v2 dataset; offline gate passes (recall 1.0, success-frame FPR ≈ 0.3%); live `0:199` pilot safe but no rescue (`rescued_count = 0`) |
| Sprint 5 | Bounded residual micro-policy | Trained on v2 dataset; offline safety gate passes (modification rate ≈ 0.27%, clamp rate 0%); live `0:199` pilot safe but no rescue (`rescued_count = 0`) |
| Sprint 6 | Valid OOD medium-task mining | Code/tests complete; live data pending |
| Sprint 7 | Valid OOD learned adaptation benchmark | Code/tests complete; live data pending |
| Sprint 8 | Large-yaw route-policy feasibility | Integration proven; model trained but limited to two route classes by dataset labels |
| Sprint 9 | FTH v3.4 evidence-aware promotion manager | Complete and tested; seed-24 promoted to `candidate_recovery` |
| Sprint 10 | Dashboard, tests, reports, final status | Complete; full `0:199` live paired evaluation and infrastructure-failure audit clean |

---

## Answers to the 12 Final Questions

### 1. Is the seed-24 micro-recovery no-regression?

**Yes on all 200 valid pairs in `0:199`.** `newly_failed_count = 0`, `invalid_pair_count = 0`,
`asset_fallback_used_count = 0`, `physics_anomaly_count = 0`, and the candidate rescues
two seeds (24 and 198).

### 2. Does the micro-recovery meet the promotion gate?

**Yes.** The corrected full `0:199` evaluation gives `candidate_success_rate = 0.965`,
which meets the declared 0.95 gate. FailureToHint v3.4 promotes it to
`candidate_recovery`.

### 3. Does the learned trigger model improve over the hand-written trigger?

**Live comparison completed, but no efficacy gain observed.** On the v2 residual
dataset the `seed24_like` MLP trigger achieves recall 1.0 and a success-frame
false-positive rate of ~0.3% across train/val/test.  In the live paired Arena
pilot on `0:199`, the learned trigger + bounded residual was safe
(`newly_failed_count = 0`) but rescued zero seeds.  It therefore does not yet
improve over the hand-written seed-24 micro-recovery, which rescues two seeds.
The trigger fires heavily in early phases (`APPROACH`, `DESCEND`) because that
is where the heuristic label is satisfied, so a phase-restricted label or a
stronger residual action may be needed.

### 4. Does the bounded residual micro-policy stay safe?

**Yes in live control.** On the test split the success-frame modification rate
is ~0.27% and the clamp rate is 0%, and the live `0:199` pilot produced zero
newly-failed seeds.  All predicted residuals stayed inside the configured
limits.

### 5. Does the bounded residual rescue any failure?

**No rescue observed on the official `0:199` benchmark.** The live pilot showed
zero regressions but also `rescued_count = 0`.  The residual correction is too
small or the trigger does not fire on the frames where it could help.  A
`triggered_rule` pilot using the learned trigger with the hand-authored
`lower_reclose` action is the recommended next step to isolate the issue.

### 6. Are there valid OOD medium tasks?

**Mining pipeline complete; selected-task artifact pending.** The script
`mine_valid_ood_medium_tasks.py` is implemented and unit-tested, but the live
mining run was not completed in this session.

### 7. Does learned adaptation help on valid OOD medium tasks?

**Live benchmark pending.** The runner
`run_valid_ood_learned_adaptation_benchmark.py` is implemented and tested.

### 8. Is the large-yaw route classifier useful?

**Partially useful offline, not yet in Arena.** The trained model cleanly
separates `continue` from `blocked_external` (accuracy ~0.98), but the v2 dataset
contains no examples of `pause`, `lower_regrip`, or `abort_safe`, so it cannot
learn those routes.  The live pilot still predicted `continue` on every frame,
so the trained classifier's `blocked_external` output has not yet been observed
inside Arena.

### 9. Does the route classifier corrupt the policy or create fake success?

**No.** It runs in diagnostic mode and does not change actions.

### 10. Does FailureToHint v3.4 prevent false recovery promotion?

**Yes.** It hard-blocks `blocked_external`, requires paired evidence, and
correctly promoted the seed-24 recipe to `candidate_recovery` only after the
corrected `0:199` evaluation met the 0.95 success-rate gate.

### 11. Are there any validated transferable skills?

**No candidate has reached `validated_recovery` or `transferable_skill`.** The
seed-24 micro-recovery is promoted to `candidate_recovery` on the official
`0:199` benchmark; transferable skill would require replication on an
independent held-out task or seed set.

### 12. Next step: finish evidence, train models, or escalate?

1. **Run a `triggered_rule` paired Arena pilot** that uses the learned trigger to
   gate the hand-authored `lower_reclose` micro-recovery; this isolates whether
   the trigger fires on the right frames and can rescue a baseline-failing seed
   without causing regressions.
2. **Tune or re-train the bounded residual** if the trigger is correct but the
   learned residual correction is too small to change outcomes.
3. **Run the valid OOD learned-adaptation benchmark** to find a transferable
   adaptation axis.
4. **Build a labeled large-yaw route dataset** containing all five route classes
   (especially `blocked_external` on confirmed torsional-slip frames) and
   re-train the route classifier; re-run the Arena pilot.
5. **Escalate** large-yaw force-control and procedural-cube fallback issues to
   the Arena team.

---

## Artifacts

- `rosclaw_darwin/evaluation/paired_evaluation.py`
- `rosclaw_darwin/evolution/evidence_status.py`
- `rosclaw_darwin/evolution/promotion_manager.py`
- `rosclaw_darwin/learning/trigger_model.py`
- `rosclaw_darwin/learning/bounded_residual_policy.py`
- `rosclaw_darwin/learning/route_classifier.py`
- `configs/skills/failure_signature_to_hint_rules_v34.yaml`
- `scripts/diagnostics/run_paired_policy_evaluation.py`
- `data_v20/paired/official_seed24_micro_recovery_0_199/`
- `data_v20/evolution/fth_v34_evidence_status.json`
- All v1.10 reports listed in [reports/INDEX.md](INDEX.md).

---

## Conclusion

v1.10 establishes the evidence-aware evolution loop that v1.9 infrastructure was
built to support. The seed-24 micro-recovery is a concrete, no-regression
benefit on the full official dex_cube benchmark (`0:199`), and FailureToHint
v3.4 has promoted it to `candidate_recovery` because the corrected paired
evaluation meets the 0.95 success-rate gate. The small-model infrastructure
(trigger, bounded residual, route classifier) is complete and test-covered.

The project is therefore **ready for sign-off as v1.10** with the honest status:

- Official baseline is protected.
- No false recovery claims are promoted; promotion is backed by paired evidence.
- The seed-24 micro-recovery is promoted to `candidate_recovery`; the remaining
  path to `validated_recovery` / transferable skill requires replication on an
  independent held-out set or task.
- The learned trigger + bounded residual completed its live Arena pilot on
  `0:199`: it is **safe** (`newly_failed_count = 0`) but **not yet effective**
  (`rescued_count = 0`), so it remains `experimental_only`.
- Large-yaw torsional slip stays `blocked_external`; the route classifier is
  trained but cannot make useful intermediate route decisions until the dataset
  contains those labels.

The full `0:199` paired evaluation and FTH v3.4 evidence have been regenerated;
the same pipeline will automatically recompute promotion status whenever a new
candidate is ready.

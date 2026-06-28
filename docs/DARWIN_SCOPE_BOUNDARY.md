# ROSClaw-Darwin Scope Boundary

## Darwin is responsible for

1. **Environment validity checking**
   - Detect invalid assets (disabled collision, invalid bbox, missing rigid body).
   - Classify a task as `official_arena_asset`, `rosclaw_ood_diagnostic`, or `invalid_environment`.
   - Prevent invalid environments from being used for skill claims.

2. **Benchmark execution orchestration**
   - Run baseline and candidate policies on the same seeds.
   - Isolate per-seed artifacts and traces.
   - Detect infrastructure failures, asset fallback, and physics anomalies.

3. **Failure diagnosis**
   - Convert episode traces into structured failure signatures.
   - Identify failure type, phase at failure, grip/force/slip/contact signals, and root-cause level.
   - Distinguish policy failures from environment or infrastructure failures.

4. **Paired no-regression evaluation**
   - Compare baseline vs candidate per seed.
   - Classify outcomes: `rescued`, `newly_failed`, `unchanged_success`, `unchanged_failure`, `invalid_pair`.
   - Report McNemar p-value and bootstrap confidence interval.

5. **Candidate intervention evaluation**
   - Load a candidate recovery, residual, or skill.
   - Run it through the same paired protocol.
   - Measure rescue rate, regression rate, and trigger rate.

6. **Promotion decision**
   - Map paired evidence to a promotion status.
   - Block unsupported promotions (e.g., `blocked_external` cannot become `validated`).
   - Record passed gates, failed gates, allowed claims, and blocked claims.

7. **Evidence card generation**
   - Produce YAML + Markdown evidence cards per candidate.
   - Include scope, evidence, limitations, allowed claims, blocked claims, and next required evidence.

8. **Dashboard / report / CLI exposure**
   - Expose the evidence pipeline through a unified CLI.
   - Render product-focused dashboard views.
   - Maintain a report index that separates current evidence from archived research.

---

## Darwin is not responsible for

1. **Large-scale RL training**
   - Darwin evaluates policies; it does not train them.
   - Training happens in Dojo or other training environments.

2. **Simulation environment authoring**
   - Darwin validates tasks and assets; it does not author new Arena environments.

3. **Robot low-level controller implementation**
   - Darwin evaluates high-level policies; it does not implement joint controllers.

4. **Model serving**
   - Darwin evaluates model artifacts; it does not serve them at runtime.

5. **Raw data collection**
   - Darwin analyzes traces; it does not collect raw robot sensor logs.

6. **Skill runtime execution on robot**
   - Darwin decides promotion level; runtime execution is handled by ROSClaw runtime / How / Provider.

7. **Cloud asset marketplace**
   - Darwin does not manage asset distribution.

---

## Boundaries with external systems

### Arena

- Darwin runs policies through Arena adapters when available.
- Darwin does not modify Arena internals.
- Results are local unless explicitly submitted and accepted by Arena maintainers.

### ROSClaw runtime

- Darwin outputs a registry of promoted candidates.
- Runtime may query the registry, but Darwin does not deploy candidates automatically.

### Human reviewers

- `human_escalation` and `blocked_external` items require human action.
- Darwin surfaces evidence; humans decide whether to escalate to Arena team or accept risk.

---

## Scope enforcement

- A claim that exceeds the evidence level of a registry item is a scope violation.
- The claim linter (`scripts/quality/check_claim_boundaries.py`) scans docs and reports for forbidden phrases.
- The release gate blocks if unsupported claims are found or if `blocked_external` is marked as `validated`.

---

## Summary

| In scope | Out of scope |
|---|---|
| Validity gate | RL training |
| Paired evaluation | Environment authoring |
| Failure diagnosis | Low-level control |
| Promotion decision | Model serving |
| Evidence cards | Raw data collection |
| CLI / Dashboard / Reports | Runtime execution |
| Registry | Cloud marketplace |

# ROSClaw-Darwin Product Definition

## What is ROSClaw-Darwin?

ROSClaw-Darwin is the **policy promotion engine for Physical AI skills**.

It turns every proposed physical-policy change into auditable evidence:

1. Is the benchmark environment valid?
2. What failure does the baseline exhibit?
3. Does the candidate intervention rescue failures?
4. Does the candidate introduce regressions?
5. What promotion level does the evidence support?
6. What claims are allowed, and what claims are blocked?

Darwin does not promise to fix every robot failure. It promises that any claim about a fix is backed by structured evidence and cannot be inflated beyond what the data supports.

---

## What Darwin is not

ROSClaw-Darwin is **not**:

- A generic benchmark runner.
- A large-scale RL trainer.
- A low-level robot controller.
- A model-serving platform.
- A dashboard-only visualization project.
- An agent that automatically solves all manipulation tasks.
- Not an official Arena leaderboard submission system.

---

## Core users

- **Physical-AI skill developers** who need to know whether a policy patch is safe to promote.
- **Reviewers and release managers** who need an auditable record of why a recovery or skill was accepted, rejected, or blocked.
- **ROSClaw runtime operators** who need a registry of validated candidates and honest blockers.

---

## Core problem

Before Darwin, a typical workflow looked like:

> "I changed the policy and the success rate went up on my seed set. Let's merge it."

This workflow is dangerous because it conflates:

- Raw success-rate improvements with **no-regression guarantees**.
- Single-seed fixes with **transferable skills**.
- Invalid environments with **policy failures**.
- External limitations with **solvable bugs**.

Darwin replaces this with an evidence pipeline:

> Validate environment → run baseline → diagnose failures → evaluate candidate → compare baseline vs candidate → decide promotion level → generate evidence card → expose result.

---

## Deliverables

ROSClaw-Darwin v1.0 delivers eight core capabilities:

1. **Validity Gate** — reject invalid benchmark environments before they pollute evaluation.
2. **Paired No-Regression Evaluator** — compare baseline and candidate on the same seeds.
3. **Failure Diagnosis Engine** — turn episode traces into structured failure signatures.
4. **Candidate Recovery / Skill Registry** — ledger of interventions and their evidence.
5. **Evidence Card Generator** — human-readable and machine-readable evidence summaries.
6. **Promotion Decision Engine** — map evidence to a promotion level with allowed and blocked claims.
7. **Unified CLI** — run the full pipeline from a single command surface.
8. **Dashboard + Documentation + Demo Pack** — productized views and runnable demos.

---

## Boundaries with other ROSClaw modules

| Module | Responsibility | Darwin's relationship |
|---|---|---|
| **Dojo** | Training / simulation refinement. | Darwin consumes Dojo outputs for evaluation and promotion. |
| **Sandbox** | Safety verification. | Darwin treats Sandbox results as one input to promotion gates. |
| **Practice** | Collecting real-world traces. | Darwin's evidence levels can be upgraded by Practice traces, but Darwin does not collect them. |
| **Memory** | Long-term experience storage. | Darwin generates evidence cards that can be stored in Memory. |
| **How** | Runtime minimal-intervention hints. | Darwin decides which recoveries are promoted; How may query the registry at runtime. |
| **Provider** | Model / capability routing. | Darwin does not route models; it validates policy changes. |
| **Dashboard** | Visualization. | Darwin exposes evidence cards, registry, and promotion status to the Dashboard. |

---

## What v1.0 includes

- Product definition and claim-boundary documentation.
- Consolidated schema surface in `rosclaw_darwin/schemas/`.
- Unified CLI: `rosclaw darwin validate-env | run | diagnose | pair-eval | promote | card | registry | report`.
- Evidence Card generator and 5 demo cards.
- Promotion Registry with read-only runtime query interface.
- Dashboard product views: overview, validity, baselines, failures, paired evaluations, promotions, evidence cards, registry, blocked external, demos.
- Report index and claim-boundary guide.
- Demo pack with runnable smoke commands.
- Release gate and claim linter.

---

## What v1.0 does not include

- New robot-learning experiments.
- New heuristic feature stacks.
- New large-yaw recovery solutions.
- New valid-OOD adaptation results.
- Claims of validated transferable skill are not made.
- Official Arena leaderboard submissions are not performed.
- Real-robot validation (evidence level stops at `candidate_recovery` on simulation).

---

## One-sentence summary

> Any robot skill that wants to enter ROSClaw runtime must first pass through Darwin's evidence-based admission flow.

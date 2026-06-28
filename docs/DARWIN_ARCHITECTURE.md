# ROSClaw-Darwin Architecture

## Overview

ROSClaw-Darwin is the **policy promotion engine for Physical AI skills**. It wraps existing robot-learning artifacts (Arena runs, policy configs, failure traces) with an evidence layer that decides whether a candidate change is safe to promote.

## Logical layers

```
┌─────────────────────────────────────────────────────────────┐
│                     Presentation Layer                       │
│  CLI (Typer)  │  Dashboard (FastAPI + Jinja2)  │  Reports   │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│                     Evidence Engine                          │
│  Validity Gate → Diagnosis → Paired Eval → Promotion Decision │
│  Evidence Card Generator → Registry → Report Bundler          │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│                     Schema Surface                           │
│  rosclaw_darwin/schemas/ (re-exports + thin wrappers)         │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│                     Canonical Modules                        │
│  evaluation/  evolution/  adapters/  dashboard/  cli/         │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│                     External Systems                         │
│  IsaacLab-Arena  │  ROSClaw runtime  │  How / Memory / Dojo  │
└─────────────────────────────────────────────────────────────┘
```

## Data flow

```
validate-env → task_validity.json
run → run_artifact.json
diagnose → failure_signature.json
pair-eval → paired_summary.json
promote → promotion_decision.json
card → {candidate}.card.yaml + .card.md
registry add → registry.json
report → report_index.json
```

## Key components

### Validity Gate
- Reuses `ObjectValidityReport` from `rosclaw_darwin/evaluation/object_validity.py`.
- Blocks invalid environments (e.g., procedural cube fallback with disabled collision).

### Failure Diagnosis Engine
- Reuses `FailureSignature` from `rosclaw_darwin/evaluation/failure_signature.py`.
- Maps episode traces to structured failure classes.

### Paired No-Regression Evaluator
- Reuses `PairedEvaluationSummary` from `rosclaw_darwin/evaluation/paired_evaluation.py`.
- Compares baseline and candidate on identical seeds.
- Outputs `rescued_count` and `newly_failed_count`.

### Promotion Decision Engine
- Wraps `EvidenceStatus` from `rosclaw_darwin/evolution/evidence_status.py`.
- Maps evidence to a promotion level and blocked claims.

### Registry
- New `PromotionRegistry` in `rosclaw_darwin/registry/`.
- JSON persistence of promotion decisions with card references.
- Read-only runtime query interface.

### Evidence Cards
- YAML + Markdown summaries per candidate.
- Contain `allowed_claims` and `blocked_claims`.

### Dashboard
- FastAPI app exposing product views: overview, validity, baselines, paired evaluations, promotions, evidence cards, registry, blocked external, demos.

## Boundaries

| Module | Darwin's relationship |
|---|---|
| **Dojo** | Consumes outputs for evaluation and promotion. |
| **Sandbox** | Treats Sandbox results as one input to promotion gates. |
| **Practice** | Evidence levels can be upgraded by Practice traces, but Darwin does not collect them. |
| **Memory** | Generates evidence cards that can be stored in Memory. |
| **How** | Decides which recoveries are promoted; How may query the registry at runtime. |
| **Provider** | Does not route models; validates policy changes. |
| **Arena** | Execution backend for real evaluation. |

## File map

| Path | Responsibility |
|---|---|
| `rosclaw_darwin/schemas/` | Canonical schema surface. |
| `rosclaw_darwin/cli/main.py` | Main Typer app with `darwin` sub-typer. |
| `rosclaw_darwin/evidence/` | Card generator and Markdown renderer. |
| `rosclaw_darwin/registry/` | Promotion registry and policy. |
| `rosclaw_darwin/dashboard/` | FastAPI dashboard and templates. |
| `configs/release/darwin_v1_release_gate.yaml` | Release gate configuration. |
| `scripts/quality/` | Claim linter and release gate runner. |
| `demo_pack/` | Runnable smoke demos. |
| `release/darwin_v1/` | Release package. |

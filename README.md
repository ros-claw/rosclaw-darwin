# ROSClaw-Darwin

**Evidence engine for evolving physical policies safely.**

ROSClaw-Darwin turns every proposed robot-policy change into auditable evidence:

1. Is the benchmark environment valid?
2. What failure does the baseline exhibit?
3. Does the candidate intervention rescue failures?
4. Does the candidate introduce regressions?
5. What promotion level does the evidence support?
6. What claims are allowed, and what claims are blocked?

It does **not** promise to fix every robot failure. It promises that any claim about a fix is backed by structured evidence and cannot be inflated beyond what the data supports.

## What problem does Darwin solve?

Before Darwin, a typical workflow looked like:

> "I changed the policy and the success rate went up on my seed set. Let's merge it."

This is dangerous because it conflates:

- Raw success-rate improvements with **no-regression guarantees**.
- Single-seed fixes with **transferable skills**.
- Invalid environments with **policy failures**.
- External limitations with **solvable bugs**.

Darwin replaces this with an evidence pipeline:

```
Validate environment → run baseline → diagnose failures → evaluate candidate
→ compare baseline vs candidate → decide promotion level → generate evidence card → expose result.
```

## Quickstart

```bash
# Install
pip install -e ".[dev]"

# Check environment
darwin doctor

# Validate a benchmark environment
darwin validate-env --task configs/tasks/goal_pose_dex_cube_official.yaml --out demo_outputs/validity --mock

# Run a paired no-regression evaluation
darwin pair-eval \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --baseline configs/policies/heuristic_servo_goal_pose_v3_reachability_promoted.yaml \
  --candidate configs/policies/heuristic_servo_goal_pose_v3_seed24_micro_recovery.yaml \
  --seeds 0:4 --out demo_outputs/pair_seed24 --mock

# Generate an evidence card
darwin card --candidate seed24_micro_recovery --out demo_outputs/cards --mock

# Register a promoted recovery
darwin registry add --registry demo_outputs/registry \
  --name seed24_micro_recovery \
  --card demo_outputs/cards/seed24_micro_recovery.card.yaml

# Validate evidence artifacts
darwin evidence validate --cards demo_outputs/cards --reports reports

# Start the dashboard
darwin dashboard --data data --port 8080
```

See [`demo_pack/commands.sh`](demo_pack/commands.sh) for a full smoke demo.

## Core workflow

| Step | CLI command | Output |
|---|---|---|
| Validate environment | `darwin validate-env` | `task_validity.json` |
| Run baseline/candidate | `darwin run` | run artifacts |
| Diagnose failures | `darwin diagnose` | `failure_signature.json` |
| Paired no-regression eval | `darwin pair-eval` | `paired_summary.json` |
| Decide promotion | `darwin promote` | `promotion_decision.json` |
| Generate evidence card | `darwin card` | `{candidate}.card.yaml` + `.card.md` |
| Register result | `darwin registry add` | `registry.json` |
| Bundle report | `darwin report` | `report_index.json` |

## Evidence levels

| Level | Meaning |
|---|---|
| `experimental_only` | Runnable component, no measured live gain. |
| `candidate_recovery` | Paired no-regression evidence, rescued > 0 seeds. |
| `validated_recovery` | Candidate recovery + independent replication. |
| `validated_transferable_skill` | Validated recovery + cross-task/object evidence. |
| `blocked_external` | Outside current system capability. |
| `diagnosis_only` | Problem identified, no automatic fix. |
| `human_escalation` | Requires human review. |

## What Darwin does not claim

- It does not automatically solve all robot tasks.
- It does not prove transferable skills without cross-task evidence.
- It does not solve large-yaw torsional slip (currently `blocked_external`).
- Its results are not official Arena leaderboard results unless explicitly accepted.
- It does not replace RL training.

## Architecture

See [`docs/DARWIN_ARCHITECTURE.md`](docs/DARWIN_ARCHITECTURE.md).

## Development

```bash
ruff check rosclaw_darwin tests scripts
pytest tests/unit -q
pytest tests/integration -q
python scripts/quality/run_darwin_v1_release_gate.py
```

## Release package

The v1.0 release package is in [`release/darwin_v1/`](release/darwin_v1/).

## License

MIT

# ROSClaw-Darwin v1.0 Demo Guide

## Quick start

All demos run in `--mock` mode and do not require Arena Docker.

```bash
bash demo_pack/commands.sh
```

This executes the full evidence pipeline:
1. Validate official dex_cube environment.
2. Run paired no-regression evaluation on seeds 0:4.
3. Generate the seed24 evidence card.
4. Register the seed24 micro-recovery.
5. Bundle a report.

## Individual demos

| Demo | File | Evidence card |
|---|---|---|
| Official goal_pose baseline | `demo_official_goalpose_baseline.md` | `official_goalpose_baseline` |
| Seed 24 micro-recovery | `demo_seed24_micro_recovery.md` | `seed24_micro_recovery` |
| Procedural fallback invalidity | `demo_procedural_invalidity.md` | `procedural_fallback_invalid_environment` |
| Large-yaw torsional slip | `demo_large_yaw_blocked_external.md` | `large_yaw_torsional_slip_blocked_external` |
| Learned trigger + bounded residual | `demo_learned_trigger_experimental.md` | `learned_trigger_bounded_residual_experimental` |
| Valid OOD suite | `demo_valid_ood_suite.md` | (diagnostic baseline) |

## CLI primer

```bash
# Top-level help
darwin --help

# Validate a benchmark environment
darwin validate-env --task <task.yaml> --out <dir> [--mock]

# Run a paired evaluation
darwin pair-eval --task <task.yaml> --baseline <policy.yaml> --candidate <policy.yaml> --seeds 0:99 --out <dir> [--mock]

# Generate an evidence card
darwin card --candidate <name> --out <dir> [--mock]

# Register a result
darwin registry add --registry <dir> --name <name> --card <path>

# Start dashboard
darwin dashboard --data data --port 8080
```

## Expected outputs

After `commands.sh`:

```
demo_outputs/
├── validity_official/task_validity.json
├── pair_seed24/paired_summary.json
├── cards/seed24_micro_recovery.card.yaml
├── cards/seed24_micro_recovery.card.md
├── registry/registry.json
└── report/report_index.json
```

## Honest boundaries

The demos demonstrate the evidence pipeline. They do **not** prove:
- Transferable skills.
- Large-yaw solution.
- Official Arena leaderboard result is not claimed.
- RL replacement.

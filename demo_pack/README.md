# ROSClaw-Darwin v1.0 Demo Pack

This directory contains runnable smoke demos for the Darwin v1.0 evidence engine. All commands run in `--mock` mode so they do not require Arena Docker.

## Quick Start

```bash
bash demo_pack/commands.sh
```

This will:
1. Validate the official dex_cube environment.
2. Run a paired no-regression evaluation on seeds 0:4.
3. Generate the seed24 evidence card.
4. Register the seed24 micro-recovery in the promotion registry.
5. Bundle a report.

## Demos

| Demo | Evidence Card | What it shows |
|---|---|---|
| Official goal_pose baseline | `official_goalpose_baseline` | Valid official asset + clean baseline. |
| Seed 24 micro-recovery | `seed24_micro_recovery` | Paired no-regression candidate recovery. |
| Procedural fallback invalidity | `procedural_fallback_invalid_environment` | Invalid environment blocked. |
| Large-yaw torsional slip | `large_yaw_torsional_slip_blocked_external` | Externally blocked failure. |
| Learned trigger + bounded residual | `learned_trigger_bounded_residual_experimental` | Experimental-only component. |

## Expected Outputs

After running `commands.sh`, see:
- `demo_outputs/validity_official/task_validity.json`
- `demo_outputs/pair_seed24/paired_summary.json`
- `demo_outputs/cards/seed24_micro_recovery.card.yaml` + `.card.md`
- `demo_outputs/registry/registry.json`
- `demo_outputs/report/report_index.json`

## Honest Boundaries

These demos do **not** prove:
- Transferable skills.
- Large-yaw solution.
- Official Arena leaderboard result is not claimed.
- RL replacement.

They demonstrate the evidence pipeline and claim boundaries.

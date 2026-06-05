# Implementation Notes

## TDL Schema

See `rosclaw_darwin/tdl/schema.py` for the full Pydantic model.

Key types:
- `Task`: central model with scene, embodiment, objects, primitives, eval, mutation, provenance.
- `EvalSpec`: success/failure conditions, metrics, max_steps, max_episodes.
- `MutationSpec`: allowed mutators, difficulty, seed.
- `ProvenanceSpec`: source repo, native config for pass-through execution.

## CLI Commands

All commands are implemented in `rosclaw_darwin/cli/main.py` using Typer.

## Data Storage

MVP uses filesystem JSONL/YAML:
- `data/runs/{run_id}/run.json`
- `data/evolution_runs/{run_id}/evolution_report.json`
- `data/practice_events/events.jsonl`
- `data/memory/darwin_experiences.jsonl`
- `data/skills/registry.json`

For permission-restricted environments, bridges fall back to system temp directories.

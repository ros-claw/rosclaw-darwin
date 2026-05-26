# ROSClaw-Darwin 🧬

> **Evolutionary Embodied Intelligence Benchmark (EEIB)**
>
> The world's first benchmark infrastructure that measures not how strong an agent is,
> but how fast it evolves.

## Philosophy

Traditional benchmarks (BEHAVIOR-1K, LIBERO, Habitat) ask:

```
"Can the robot complete this task?"
```

Darwin asks:

```
"After the robot fails, how quickly does it learn to succeed?"
```

This is the shift from **static evaluation** to **evolutionary evaluation**.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     ROSClaw-Darwin                          │
├─────────────────────────────────────────────────────────────┤
│  Phase 1: Core Framework                                     │
│  ┌────────────┐  ┌──────────────┐  ┌─────────────────────┐  │
│  │ TDL Schema │  │ Task Loader  │  │ Environment Adapter │  │
│  │   (YAML)   │──│ (Multi-src)  │──│  (Arena / MuJoCo)   │  │
│  └────────────┘  └──────────────┘  └─────────────────────┘  │
│         │                                       │            │
│         └───────────────────────────────────────┘            │
│                         │                                    │
│  ┌──────────────────────▼──────────────────────┐             │
│  │           Base Evaluator                    │             │
│  │  (success_rate, time, path, collisions)     │             │
│  └──────────────────────┬──────────────────────┘             │
│                         │                                    │
│  Phase 2: Evolution Engine                                   │
│  ┌──────────────────────▼──────────────────────┐             │
│  │         Task Genome Engine                  │             │
│  │  (mutate, compose, generate_random)         │             │
│  └──────────────────────┬──────────────────────┘             │
│                         │                                    │
│  ┌──────────────────────▼──────────────────────┐             │
│  │         EvolutionRunner                     │             │
│  │  Loop 1 → Memory Consolidation → Loop 2     │             │
│  └──────────────────────┬──────────────────────┘             │
│                         │                                    │
│  ┌──────────────────────▼──────────────────────┐             │
│  │      MemoryEvolutionTracker                 │             │
│  │  (verify causal edges, skill extraction)    │             │
│  └──────────────────────┬──────────────────────┘             │
│                         │                                    │
│  Phase 3: Dashboard                                          │
│  ┌──────────────────────▼──────────────────────┐             │
│  │         EEIB Dashboard                      │             │
│  │  (SDR / MIE / SSI leaderboard)              │             │
│  └─────────────────────────────────────────────┘             │
└─────────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
┌─────────────────┐          ┌─────────────────────┐
│ rosclaw-practice│          │   rosclaw-memory    │
│  (PraxisEvent)  │          │     (SeekDB)        │
└─────────────────┘          └─────────────────────┘
```

## Quick Start

```bash
# 1. Install
cd rosclaw-darwin
pip install -e ".[dev]"

# 2. Run demo (mock mode, no Isaac Sim required)
python examples/demo.py

# 3. Run tests
python -m pytest tests/ -v

# 4. Start dashboard
python -m rosclaw_darwin.dashboard.app
# Open http://localhost:8080
```

## Task Definition Language (TDL)

```yaml
id: pick_place_milk_001
name: Pick and Place Milk
scene: kitchen_modern_01
primitives:
  - name: Navigate
    target: counter
  - name: Pick
    params: {force: 3.0}
    target: milk_carton
  - name: Place
    target: fridge
objects:
  - name: milk_carton
    object_type: graspable
    properties: {weight: 0.5}
constraints:
  - name: upright_placement
    constraint_type: physical
    weight: 2.0
eval_config:
  max_steps: 500
  metrics: [success_rate, completion_time, path_efficiency]
```

## Evolution Metrics

| Metric | Full Name | Meaning |
|--------|-----------|---------|
| **SDR** | Skill Discovery Rate | New skills discovered per episode |
| **MIE** | Memory Integration Efficiency | Errors avoided on retry thanks to memory |
| **SSI** | Swarm Synergy Index | Multi-agent coordination quality |
| **Evolution Score** | Composite | 0-1 score of loop1→loop2 improvement |

## Integration with rosclaw Ecosystem

- **rosclaw-practice**: `@practice_capture` decorator auto-records evaluation sessions as `PraxisEvent`
- **rosclaw-memory**: SeekDB stores causal edges (`[Grasp] -FAILS_ON-> [Transparent Cup]`)
- **rosclaw-know/how**: Extract failure patterns and generate skill templates

## Project Structure

```
rosclaw-darwin/
├── rosclaw_darwin/
│   ├── tdl/              # Task Definition Language
│   ├── environment/      # Simulator adapters (Arena, MuJoCo)
│   ├── evaluation/       # Metrics and evaluators
│   ├── evolution/        # Genome, Runner, Tracker
│   ├── integration/      # Practice + Memory bridges
│   └── dashboard/        # EEIB web leaderboard
├── configs/tasks/        # Example task YAMLs
├── tests/                # Pytest suite
└── examples/             # Demo scripts
```

## License

Apache 2.0

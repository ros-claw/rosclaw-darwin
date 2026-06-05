# Architecture

## Design Principles

1. **Don't reimplement simulators** — Darwin only does task description, evolution, evaluation loop.
2. **Mock first** — MockAdapter guarantees the logic loop without GPU.
3. **Semantic import first** — BEHAVIOR-1K is imported semantically before full physics migration.

## Core Modules

### TDL (Task Definition Language)
Unified intermediate representation for tasks from IsaacLab-Arena, LW-BenchHub, RoboTwin, BEHAVIOR-1K, and native sources.

### Adapters
- **MockAdapter**: CI/dev, no GPU, simulates success rates.
- **ArenaAdapter**: Wraps IsaacLab-Arena with deep integration (monkey-patches, procedural fallbacks).
- **RoboTwinArenaAdapter**: (planned) Subprocess wrapper for RoboTwin evaluation.

### Evolution Engine
- **Mutators**: Spatial, Object, Distractor, Lighting, Instruction, Constraint, Embodiment, Horizon.
- **Composer**: Chains tasks into long-horizon composites.
- **FailureDrivenGenerator**: (MVP rule-based) Generates targeted tasks from failure taxonomy.

### Integration Bridges
- **PracticeBridge**: Records evaluation events (JSONL / HTTP).
- **MemoryBridge**: Stores and consolidates experiences (JSONL / SeekDB).
- **HowBridge**: Rule-based skill extraction.
- **KnowBridge**: Task ontology hints.

# Roadmap

## Completed (MVP)

- [x] TDL schema, loader, validator, exporter
- [x] MockAdapter with run_policy and evolution simulation
- [x] EvaluationResult and metrics computation
- [x] 8 mutators + TaskComposer
- [x] Failure taxonomy and skill registry (rule-based)
- [x] EvolutionRunner with loop1/loop2 and evolution_score
- [x] PracticeBridge, MemoryBridge, HowBridge (file mode)
- [x] Source importers (LW, RoboTwin, BEHAVIOR-1K) — basic scanning
- [x] CLI (doctor, validate, import, mutate, compose, run, evolve, suite, dashboard)
- [x] Dashboard (FastAPI + HTML)
- [x] 20 Darwin MVP tasks
- [x] Pytest suite (26 tests passing)

## Phase 4: Arena Adapter Enhancement

- [ ] ArenaRunner subprocess wrapper
- [ ] eval job JSON builder
- [ ] stdout/stderr capture and parsing
- [ ] External environment class path support

## Phase 5-7: Importer Deep Integration

- [ ] Full LW-BenchHub task scanning (kitchen, loco-manipulation)
- [ ] RoboTwin data replay / convert / policy evaluation wrapper
- [ ] BEHAVIOR-1K BDDL full parser

## Phase 8+: Advanced Features

- [ ] LLM-guided task generation (evolve llm_genome.py)
- [ ] GROOT / NVIDIA remote policy bridge
- [ ] Real rosclaw-memory / rosclaw-practice service integration
- [ ] Docker profiles (mock-dev, arena-dev, full)

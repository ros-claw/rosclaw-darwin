# ROSClaw-Darwin

**Evolutionary Benchmark Layer for Embodied Agents**

ROSClaw-Darwin does not replace IsaacLab-Arena.
It extends Arena with task evolution, memory-aware evaluation, and evolution metrics.

- **IsaacLab-Arena** answers: *Can this policy solve this task?*
- **ROSClaw-Darwin** answers: *Can this agent learn from failure and solve increasingly complex task families?*

## What is ROSClaw-Darwin?

ROSClaw-Darwin 是一个面向 Physical AI / Embodied Agent 的进化型评测框架。

传统 Benchmark 评估：机器人现在有多强  
ROSClaw-Darwin 评估：机器人能否从失败中学习，并在越来越复杂的任务中持续变强

## Relationship with External Projects

| Project | Role in Darwin |
|---------|----------------|
| IsaacLab-Arena | 主执行底座（Scene / Embodiment / Task / Runner） |
| LW-BenchHub | 第一批可运行任务种子（kitchen, loco-manipulation, multi-robot） |
| RoboTwin IsaacLab-Arena Branch | 双臂操作与强 domain randomization 任务来源 |
| BEHAVIOR-1K | long-horizon task ontology / task genome 来源（语义导入） |

## Quickstart with MockAdapter

```bash
# Install
pip install -e ".[dev]"

# Check environment
darwin doctor

# Validate a task
darwin validate-task examples/tasks/open_fridge_take_milk.yaml

# Run mock evaluation
darwin run --adapter mock --task examples/tasks/open_fridge_take_milk.yaml --policy configs/policies/zero_action.yaml --episodes 20

# Run evolution evaluation
darwin evolve --adapter mock --task examples/tasks/open_fridge_take_milk.yaml --policy configs/policies/zero_action.yaml --loops 2

# Generate task variations
darwin mutate --task examples/tasks/open_fridge_take_milk.yaml --n 20 --out data/tasks/mutated

# Compose long-horizon tasks
darwin compose examples/tasks/open_fridge.yaml examples/tasks/pick_milk.yaml examples/tasks/close_fridge.yaml --out data/tasks/composed/open_pick_close.yaml

# Start dashboard
darwin dashboard --data data --port 8080
```

## Import Tasks

```bash
# LW-BenchHub
darwin import lw --repo /data/repos/LW-BenchHub --out data/tasks/lw --limit 30

# RoboTwin
darwin import robotwin --repo /data/repos/RoboTwin --out data/tasks/robotwin --limit 20

# BEHAVIOR-1K (semantic only)
darwin import behavior1k --repo /data/repos/BEHAVIOR-1K --semantic-only --out data/tasks/behavior1k --limit 100
```

## Metrics Explanation

### Traditional Metrics
- `success_rate`: 成功率
- `completion_time_mean`: 平均完成时间
- `collision_count_mean`: 平均碰撞次数

### Evolution Metrics
- `delta_success_rate`: 两次 loop 间的成功率变化
- `memory_integration_efficiency`: 记忆整合效率（重复错误减少程度）
- `skill_discovery_rate`: 新技能发现率
- `robustness_gain`: 鲁棒性提升
- `evolution_score`: 综合进化得分

```
evolution_score =
  0.4 * delta_success_rate
  + 0.2 * memory_integration_efficiency
  + 0.2 * skill_discovery_rate
  + 0.1 * completion_time_improvement
  + 0.1 * robustness_gain
```

## Dashboard

Darwin Dashboard 提供以下页面：

- `/` — Overview
- `/runs` — Evaluation runs
- `/evolution` — Evolution reports
- `/tasks` — Task registry
- `/task-graph` — Task lineage graph
- `/skills` — Skill discovery registry
- `/failures` — Failure taxonomy and frequency
- `/leaderboard` — Evolution leaderboard（按 evolution_score 排序）

## Architecture

```
Task Sources
  -> ROSClaw-TDL
  -> Task Graph
  -> Task Genome Engine
  -> Arena / Mock / RoboTwin Adapter
  -> Evolution Runner
  -> Practice / Memory / How Bridge
  -> Evolution Metrics
  -> Dashboard / Leaderboard
```

## Directory Structure

```
rosclaw-darwin/
├── rosclaw_darwin/
│   ├── cli/           # Typer CLI
│   ├── tdl/           # Task Definition Language
│   ├── sources/       # Importers (LW, RoboTwin, BEHAVIOR-1K)
│   ├── adapters/      # Environment adapters (mock, arena)
│   ├── evaluation/    # Metrics and results
│   ├── evolution/     # Genome, mutators, composer, runner
│   ├── integration/   # Practice / Memory / How / Know bridges
│   ├── dashboard/     # FastAPI dashboard
│   └── utils/         # Helpers
├── examples/tasks/    # Example TDL tasks
├── configs/           # Configurations
├── tests/             # Pytest suite
└── docs/              # Documentation
```

## Roadmap

- [x] Phase 0: 仓库骨架
- [x] Phase 1: TDL + MockAdapter + Metrics
- [x] Phase 2: Task Genome Engine
- [x] Phase 3: Evolution Runner + Memory/Skill MVP
- [ ] Phase 4: IsaacLab-Arena Adapter (subprocess runner)
- [ ] Phase 5: LW-BenchHub Importer (full scanning)
- [ ] Phase 6: RoboTwin Importer (full scanning)
- [ ] Phase 7: BEHAVIOR-1K Semantic Importer (BDDL parsing)
- [x] Phase 8: Dashboard MVP

## License

MIT

# ROSClaw-Darwin 测试报告

**测试日期**: 2026-06-05
**测试环境**: Linux 6.8.0-110-generic, Python 3.10.12
**版本**: rosclaw-darwin 0.1.0
**测试执行者**: Automated CI / Claude Code

---

## 1. 测试环境

| 组件 | 状态 | 详情 |
|------|------|------|
| Python | OK | 3.10.12 |
| rosclaw-darwin | OK | 0.1.0 |
| CUDA | OK | nvidia-smi available |
| Docker | OK | Docker 28.2.1 |
| IsaacLab-Arena | NOT FOUND | 未配置 ARENA_REPO |
| LW-BenchHub | NOT FOUND | 未配置 LW_BENCHHUB_REPO |
| RoboTwin | NOT FOUND | 未配置 ROBOTWIN_REPO |
| BEHAVIOR-1K | NOT FOUND | 未配置 BEHAVIOR1K_REPO |

**外部依赖状态**: 无真实 Arena/LW/RoboTwin/BEHAVIOR-1K 仓库，所有相关测试以 **graceful fallback** 模式执行。

---

## 2. 测试命令与结果

### L0: 代码质量与工程基础

| 测试项 | 命令 | 结果 |
|--------|------|------|
| ruff lint | `ruff check rosclaw_darwin tests` | ✅ 通过 |
| pytest | `pytest tests/ -q` | ✅ 26 passed |
| compileall | `python -m compileall rosclaw_darwin` | ⚠️ PermissionError（`data/` 目录为 root 所有，非代码问题）|
| CLI help | `darwin --help` | ✅ 9 个命令全部显示 |
| doctor | `darwin doctor` | ✅ 正常输出环境状态，缺少外部 repo 时不崩溃 |

### L1: CLI 合约验证

| 测试项 | 命令 | 结果 |
|--------|------|------|
| validate-task | `darwin validate-task examples/...` | ✅ 25/25 通过 |
| run (mock) | `darwin run --adapter mock ...` | ✅ 正常完成，生成 run.json/metrics.json/task.yaml/policy.yaml |
| evolve (mock) | `darwin evolve --adapter mock ...` | ✅ 正常完成，生成 evolution_report.json/loop_*/result.json/summary.md |
| mutate | `darwin mutate --n 100 ...` | ✅ 生成 100 个任务，但默认 `data/` 权限不足，回退到 `/tmp` |
| compose | `darwin compose ...` | ✅ 生成组合任务，但父目录需手动创建（`TaskExporter.to_yaml` 不自动建目录）|
| suite create | `darwin suite create --tasks ...` | ✅ 生成 suite YAML，glob 仅匹配顶层 5 个文件 |
| dashboard | `darwin dashboard --data ...` | ✅ 启动正常 |
| import (fallback) | `darwin import lw --repo /nonexistent` | ✅ 提示 "Repository not found"，exit code 1，无 traceback |

### L2: TDL 任务定义验证

| 测试项 | 结果 |
|--------|------|
| 25 个 example task YAML validate | ✅ 全部通过 |
| Roundtrip (YAML -> Pydantic -> YAML -> Pydantic) | ✅ id/name/domain/horizon/scene/embodiment/objects/primitives/eval/mutation 均一致 |

### L3: Task Genome 验证

| 测试项 | 结果 |
|--------|------|
| Mutate 100 个任务 | ✅ 100/100 生成成功 |
| Mutate id 唯一性 | ✅ 100 个 id 全部唯一 |
| Mutate parents | ✅ 100/100 包含原始 task id |
| Mutate validate | ✅ 100/100 validate 通过 |
| Mutate 可检测差异 | ✅ 大部分与 parent 有差异 |
| Compose horizon | ✅ `composite`（符合预期）|
| Compose primitives 顺序 | ✅ `open -> grasp -> close` |
| Compose parents | ✅ 包含 3 个 parent task id |
| Compose objects 合并 | ✅ 去重合并 |

### L4: Mock 进化闭环验证

| 测试项 | 结果 |
|--------|------|
| 单任务 evolve (loops=2) | ✅ 生成所有必需文件，Loop2 SR > Loop1 SR |
| 10 seed 稳定性 | ✅ 10/10 无崩溃，delta_success_rate 均 >= 0 |
| 极端参数 (difficulty=10, strength=0.0) | ✅ 不崩溃，success_rate=0.0 |
| 极端参数 (episodes=1000) | ✅ 不崩溃，正常完成 |

### L5: 指标正确性验证

| 测试项 | 结果 |
|--------|------|
| success_rate = 6/10 = 0.6 | ✅ 精确 |
| completion_time_mean | ⚠️ 当前计算所有 episodes（含失败的 time=0），与"仅算成功"预期有差异 |
| MIE 正常情况 (10->4) | ✅ 0.6 精确 |
| MIE loop1=0 | ⚠️ 不崩溃，但返回 -3.0（负数），需文档明确行为 |
| EvolutionScore 公式 | ✅ 计算精确 |

### L6: Practice / Memory / How Bridge

| 测试项 | 结果 |
|--------|------|
| PracticeBridge submit_event | ✅ 正常写入 JSONL |
| MemoryBridge record/query | ✅ 按 task_id 和 failure_type 均可查询 |
| MemoryBridge consolidate | ✅ 返回 memory_bonus >= 0 |
| HowBridge extract_skills | ✅ 提取 SkillCandidate |

### L7: Source Importer 验证

| 测试项 | 结果 |
|--------|------|
| LW-BenchHub (repo 不存在) | ✅ graceful fallback |
| RoboTwin (repo 不存在) | ✅ graceful fallback |
| BEHAVIOR-1K (repo 不存在) | ✅ graceful fallback |

### L8: ArenaAdapter 验证

| 测试项 | 结果 |
|--------|------|
| 环境未配置（无 traceback）| ✅ 修复后不再抛出 RuntimeError，返回 failed 状态 |
| Arena subprocess 错误回退 | ⚠️ `run_policy` 中 raise NotImplementedError，尚未实现 subprocess wrapper |

### L9: Dashboard 验证

| 测试项 | 结果 |
|--------|------|
| 8 页面渲染 | ✅ `/ /runs /evolution /tasks /task-graph /skills /failures /leaderboard` 全部 200 |
| API /api/runs | ✅ 正常返回 JSON |
| API /api/leaderboard | ✅ 正常返回 JSON |
| 空数据不崩溃 | ✅ 页面正常渲染 |

### L10: 报告与可复现性

| 测试项 | 结果 |
|--------|------|
| Run artifact 结构 | ✅ run.json + task.yaml + policy.yaml + metrics.json |
| Evolution artifact 结构 | ✅ evolution_report.json + loop_*/result.json + summary.md |
| 同一 seed 复现 | ⚠️ success_rate / delta_sr / MIE 一致，但 completion_time 有随机差异导致 ES 微小漂移 |

---

## 3. 通过项汇总

- ✅ **L0**: ruff + pytest 全过
- ✅ **L1**: CLI 全命令可用
- ✅ **L2**: TDL roundtrip 通过
- ✅ **L3**: 100 个 mutate task 可验证；compose 能生成 composite 任务
- ✅ **L4**: mock evolve 能稳定产生 Loop1 -> Loop2 报告
- ✅ **L5**: metrics 公式基本正确（SR、MIE、ES 计算正确）
- ✅ **L6**: Practice / Memory / How Bridge 可用
- ✅ **L7**: Importer graceful fallback
- ✅ **L8**: ArenaAdapter 无环境时优雅降级（已修复）
- ✅ **L9**: Dashboard 8 页面可渲染
- ✅ **L10**: 报告结构完整

---

## 4. 失败项与警告

| 编号 | 级别 | 问题 | 说明 |
|------|------|------|------|
| F1 | ⚠️ | `data/` 目录 root 拥有 | 导致 CLI 默认输出回退到 `/tmp`，不影响功能但影响体验 |
| F2 | ⚠️ | `TaskExporter.to_yaml` 不自动创建父目录 | `compose` 命令在目录不存在时抛出 FileNotFoundError |
| F3 | ⚠️ | `completion_time_mean` 包含失败 episodes | 当前计算所有 episodes 的均值（含 time=0 的失败），与"仅算成功"预期不符 |
| F4 | ⚠️ | MIE 当 loop1 failure=0 时返回负数 | `1.0 - loop2_failures / 1` 导致负值，需文档明确或 clamp |
| F5 | ⚠️ | ArenaAdapter subprocess 模式未实现 | `run_policy` 中 raise NotImplementedError |
| F6 | ⚠️ | 复现性：completion_time 有随机差异 | mock adapter 的 step time 逻辑引入随机性，导致 ES 微小漂移 |
| F7 | ⚠️ | SkillRegistry 三条件中的 Reusability 未完全验证 | HowBridge 生成的 skill 未跨 task 复用，当前 SDR 恒为 0 |
| F8 | ⚠️ | suite create glob 未递归 | `--tasks "examples/tasks/*.yaml"` 仅匹配 5 个顶层文件，未包含 native/ 子目录 |

---

## 5. 已知限制

1. **无 GPU 真实环境**: 当前机器未配置 IsaacLab-Arena / LW-BenchHub / RoboTwin / BEHAVIOR-1K 仓库，L7 真实导入和 L8 真实 Arena smoke test 无法执行。
2. **Mock 模式局限**: `MockAdapter.run_policy` 基于概率模拟，completion_time 和 collision_count 为随机生成，不具备物理真实性。
3. **Skill Discovery 当前为 0**: 由于 HowBridge 的 skill 提取逻辑较简单，且 SkillRegistry 的 Reusability 条件要求至少出现在 2 个 task 中，当前单任务 evolve 的 SDR 通常为 0。
4. **Docker 未测试**: `docker compose up` 未在本轮测试中执行。

---

## 6. 下一步建议

### 高优先级（影响 MVP 可信度）

1. **修复 `data/` 目录权限问题**: 在 `ensure_dir` 或 `TaskExporter.to_yaml` 中自动创建父目录，或在文档中明确指导用户设置数据目录权限。
2. **明确 `completion_time_mean` 定义**: 决定是仅计算成功 episodes 还是所有 episodes，并在指标文档中明确。
3. **明确 MIE 边界行为**: 当 loop1 failure=0 时，MIE 应 clamp 到 [0,1] 还是允许负值，需要文档化。
4. **实现 ArenaAdapter subprocess wrapper**: 将 `run_policy` 的 `else` 分支从 NotImplementedError 替换为真实的 subprocess 调用。

### 中优先级（增强 Benchmark 可信度）

5. **增强 Skill Discovery**: 让 HowBridge 支持跨 task 的 skill 复用追踪，使 SDR 能在多任务 evolve 中大于 0。
6. **修复 suite glob**: 支持递归 glob 或允许用户传入多个 pattern。
7. **降低 mock 随机性**: 使用固定 RNG seed 使 completion_time 在复现实验中完全一致。
8. **增加 failure-driven task generation 的针对性**: 当前 mutator 为通用变异，未针对 failure_type（如 `handle_grasp_failed`）做专门扩展。

### 低优先级（锦上添花）

9. **Docker 测试**: 在有 Docker 环境的机器上执行 `docker compose up darwin-mock`。
10. **真实 Arena smoke test**: 在配置好 Arena 的机器上跑 3 个任务各 3 episodes。
11. **大规模导入测试**: 配置真实 repo 后，导入 LW 30 个、RoboTwin 20 个、BEHAVIOR-1K 100 个任务。

---

## 7. 是否达到 MVP / Demo / Release 标准

| 标准 | 评估 |
|------|------|
| **MVP** | ✅ **通过** — 核心闭环（TDL -> Mutate -> Compose -> Mock Evolve -> Report -> Dashboard）已跑通 |
| **Demo** | ⚠️ **基本通过** — 可展示 Loop1->Loop2 进化、Task Graph、Leaderboard，但 Skill Discovery 为 0、无真实环境对接 |
| **Release** | ❌ **未通过** — Arena subprocess 未实现、指标定义有歧义、数据目录权限问题、缺少真实环境大规模验证 |

---

**结论**: ROSClaw-Darwin 已完成 MVP 级闭环，代码质量过关（ruff+pytest 全过），CLI 和 Dashboard 可用。当前主要缺口是：**指标边界行为需文档化**、**Arena subprocess 待实现**、**Skill Discovery 需跨 task 验证**。建议优先修复高优先级问题后进入 Demo 阶段。

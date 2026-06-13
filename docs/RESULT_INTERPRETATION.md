# ROSClaw-Darwin 成果口径说明

> 本文档规定 ROSClaw-Darwin 各类指标与报告的正确解读方式，防止把基础设施验证结果误宣传为真实能力证据。

## 1. 三类执行层级

| 层级 | 含义 | 典型示例 | 能否 claim capability |
|---|---|---|---|
| `mock` | 无真实物理模拟，基于配置参数和概率公式产生指标 | `MockAdapter` 跑 suite | ❌ 不能 |
| `arena_real` / `robotwin_replay` | 在真实执行后端（IsaacLab-Arena Docker、RoboTwin replay）上运行 | `ArenaAdapter` Docker rollout、replay policy | ✅ 可以 claim execution |
| `semantic_only` | 仅从任务本体导入，无执行环境 | BEHAVIOR-1K BDDL 导入 | ❌ 不能 claim execution |

## 2. 指标解读规则

### 2.1 `success_rate`

- 在 `mock` 模式下，`success_rate` 是 **模拟成功概率**，受 `strength`、`memory_bonus`、`skill_hints` 等配置直接影响；
- 在 `arena_real` 模式下，`success_rate` 是 **真实 rollout 的成功比例**；
- 在 `semantic_only` 模式下，不应计算 `success_rate`。

### 2.2 `skill_discovery_rate`（SDR）

- 旧版本曾用 skill candidate 数量计算 SDR，容易虚高；
- 从本阶段起，`skill_discovery_rate` 仅表示 **已验证 skill 数量 / task family episodes**；
- skill candidate 不等于 discovered skill，必须使用 ablation 验证 effectiveness。

### 2.3 `skill_transfer_gain`

- 定义：`metric_with_auto_hint - metric_without_hint`；
- 优先级：success_rate → progress → object_height_delta → failure reduction；
- 只有 `arena_real` 或 `robotwin_replay` 上的 ablation 才能产生可信的 `skill_transfer_gain`。

## 3. 报告与 summary 的元数据字段

所有 summary/report JSON 必须携带以下字段，以便 dashboard 和论文正确区分结果类型：

```json
{
  "metric_scope": "mock_ci | arena_real | robotwin_replay | semantic_only",
  "can_claim_capability": true | false,
  "claim_level": "infrastructure | execution | capability | evolution"
}
```

| `metric_scope` | `can_claim_capability` | `claim_level` | 说明 |
|---|---|---|---|
| `mock_ci` | `false` | `infrastructure` | 仅验证 pipeline 可跑通 |
| `semantic_only` | `false` | `infrastructure` | 仅用于任务本体/任务基因组 |
| `arena_real` | `true` | `execution` | 真实 Arena 执行 |
| `arena_real` + ablation | `true` | `evolution` | 证明 skill hint 带来可测提升 |

## 4. 禁止的表述

不要写：

```text
heuristic_suite success_rate = 0.750 proves policy works
Darwin 已经证明 memory 让 agent 变强
56 个任务都是真实 executable benchmark
BEHAVIOR-1K 任务已经能在 Arena 中真实执行
```

必须写：

```text
mock heuristic suite distinguishes policy configurations,
but real capability requires Arena execution.
```

## 5. 真实闭环的最低证据标准

要宣称 ROSClaw-Darwin 完成了“进化型 Benchmark”，必须同时满足：

1. 至少 3 个真实 Arena executable tasks 被执行；
2. 失败可被分类成 failure_type；
3. failure_type 能自动生成 skill hint；
4. Loop2 自动消费该 hint；
5. with-hint 与 without-hint 有可测的 progress / success / failure 改善；
6. Dashboard 能展示这条 evolution trace。

只有满足以上全部条件时，`claim_level` 才能设为 `evolution`。

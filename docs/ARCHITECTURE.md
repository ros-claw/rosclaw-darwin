# ROSClaw-Darwin 架构设计文档

> **版本**: 0.1.0  
> **日期**: 2026-05-26  
> **作者**: ROSClaw Team  

---

## 目录

1. [设计哲学](#1-设计哲学)
2. [整体架构](#2-整体架构)
3. [核心模块详解](#3-核心模块详解)
4. [数据流](#4-数据流)
5. [与 rosclaw 生态集成](#5-与-rosclaw-生态集成)
6. [Docker 部署架构](#6-docker-部署架构)
7. [扩展点](#7-扩展点)
8. [参考项目对比](#8-参考项目对比)

---

## 1. 设计哲学

### 1.1 核心命题

**传统 Benchmark 问**: "机器人现在有多强？"  
**Darwin 问**: "机器人变强得有多快？"

这是从 **静态评测** 到 **进化评测** 的范式跃迁。

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **Simulator Agnostic** | 不绑定单一模拟器，支持 Isaac Sim / MuJoCo / PyBullet |
| **Ecosystem First** | 与 rosclaw-practice / memory / know / how 深度集成 |
| **Mock for Dev** | 完整 Mock 模式支持本地开发，无需 GPU |
| **Docker for Prod** | 生产环境通过 Docker 运行，隔离复杂依赖 |
| **Infinite Tasks** | 任务不是写死的，而是动态生成和进化的 |

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Host Machine                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     ROSClaw-Darwin (Python)                         │    │
│  │                                                                      │    │
│  │  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐   │    │
│  │  │   TDL Layer  │──▶│  Task Graph  │──▶│  Task Genome Engine  │   │    │
│  │  │  (Schema +   │   │  (Registry)  │   │  (Mutate/Compose/    │   │    │
│  │  │   Loader)    │   │              │   │   Generate)          │   │    │
│  │  └──────────────┘   └──────────────┘   └──────────────────────┘   │    │
│  │           │                                      │                  │    │
│  │           ▼                                      ▼                  │    │
│  │  ┌─────────────────────────────────────────────────────────────┐   │    │
│  │  │              Environment Adapter Layer                       │   │    │
│  │  │  ┌────────────┐  ┌────────────┐  ┌────────────────────────┐ │   │    │
│  │  │  │   Mock     │  │  IsaacLab  │  │      MuJoCo (future)   │ │   │    │
│  │  │  │  Adapter   │  │  Adapter   │  │      Adapter           │ │   │    │
│  │  │  │  (No GPU)  │  │  (Docker)  │  │                        │ │   │    │
│  │  │  └────────────┘  └────────────┘  └────────────────────────┘ │   │    │
│  │  └─────────────────────────────────────────────────────────────┘   │    │
│  │           │                                                         │    │
│  │           ▼                                                         │    │
│  │  ┌─────────────────────────────────────────────────────────────┐   │    │
│  │  │              Evaluation Layer                                │   │    │
│  │  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │   │    │
│  │  │  │   Base      │  │   Darwin    │  │   Evolution Runner  │ │   │    │
│  │  │  │ Evaluator   │──▶│ Evaluator   │──▶│  (Loop 1 → Memory  │ │   │    │
│  │  │  │             │  │  (+Practice  │  │   → Loop 2)         │ │   │    │
│  │  │  │             │  │   +Memory)   │  │                     │ │   │    │
│  │  │  └─────────────┘  └─────────────┘  └─────────────────────┘ │   │    │
│  │  └─────────────────────────────────────────────────────────────┘   │    │
│  │           │                                                         │    │
│  │           ▼                                                         │    │
│  │  ┌─────────────────────────────────────────────────────────────┐   │    │
│  │  │              Output Layer                                    │   │    │
│  │  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │   │    │
│  │  │  │   Metrics   │  │   Memory    │  │   EEIB Dashboard    │ │   │    │
│  │  │  │  (SDR/MIE/  │──▶│  Tracker    │──▶│  (Leaderboard)     │ │   │    │
│  │  │  │   SSI)      │  │  (Verify)    │  │                     │ │   │    │
│  │  │  └─────────────┘  └─────────────┘  └─────────────────────┘ │   │    │
│  │  └─────────────────────────────────────────────────────────────┘   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│           │                    │                    │                        │
│           ▼                    ▼                    ▼                        │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────────────┐                │
│  │rosclaw-     │    │ rosclaw-     │    │  rosclaw-know/   │                │
│  │ practice    │    │ memory       │    │  how             │                │
│  │(PraxisEvent)│    │(SeekDB)      │    │  (Skill Extract) │                │
│  └─────────────┘    └──────────────┘    └──────────────────┘                │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     Docker Runtime                                   │    │
│  │  ┌───────────────────────────────────────────────────────────────┐  │    │
│  │  │  Container: rosclaw-darwin:latest                              │  │    │
│  │  │  ┌────────────┐  ┌────────────┐  ┌──────────────────────────┐ │  │    │
│  │  │  │ Isaac Sim  │  │ IsaacLab   │  │ rosclaw-darwin + Dashboard│ │  │    │
│  │  │  │ 6.0.0      │  │ 3.0        │  │                           │ │  │    │
│  │  │  │ (18.7GB)   │  │ (+2GB)     │  │ (+500MB)                  │ │  │    │
│  │  │  └────────────┘  └────────────┘  └──────────────────────────┘ │  │    │
│  │  └───────────────────────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心模块详解

### 3.1 TDL (Task Definition Language)

**职责**: 统一所有 Benchmark 的任务描述格式

```
BDDL (BEHAVIOR-1K)      ──┐
RoboCasa Config           ├──▶  TaskLoader ──▶  Task (Pydantic) ──▶  YAML
LIBERO JSON             ──┤                        │
IsaacLab-Arena Config   ──┤                        ▼
Native ROSClaw-TDL      ──┘              ┌─────────────────┐
                                         │  Task Genome    │
                                         │  (Evolution)    │
                                         └─────────────────┘
```

**关键类**:
- `Task` - 任务定义，包含 primitives / objects / constraints / eval_config
- `TaskLoader` - 多源加载器，支持 YAML/JSON/BDDL/RoboCasa/LIBERO/Arena

**扩展点**: 新增格式支持只需在 `TaskLoader` 中添加 `_parse_xxx` 方法。

### 3.2 Environment Adapter

**职责**: 屏蔽模拟器差异，提供统一的 gym-like 接口

```python
class BaseEnvironmentAdapter(ABC):
    def build(self) -> None          # 从 Task 构建环境
    def reset(self) -> dict          # 重置环境
    def step(self, action) -> tuple  # 执行动作
    def close(self) -> None          # 释放资源
```

**实现矩阵**:

| Adapter | 状态 | 依赖 | 启动时间 |
|---------|------|------|----------|
| `MockAdapter` | ✅ 就绪 | 无 | 毫秒 |
| `ArenaAdapter` | ⚠️ 部分 | Isaac Sim Kit | 45-90s |
| `MuJoCoAdapter` | 📋 规划 | MuJoCo | 秒级 |

**设计决策**: `ArenaAdapter` 使用延迟导入，模块在无 IsaacLab 时仍可加载。

### 3.3 Evaluation Layer

**职责**: 运行评测并计算指标

**指标体系**:

| 指标 | 类型 | 计算方式 |
|------|------|----------|
| `success_rate` | 传统 | 成功次数 / 总次数 |
| `completion_time` | 传统 | 实际耗时 |
| `path_efficiency` | 传统 | 直线距离 / 实际路径 |
| **SDR** | 进化 | 技能发现率 = 新技能数 / 回合数 |
| **MIE** | 进化 | 记忆整合效率 = 1 - (Loop2错误 / Loop1错误) |
| **SSI** | 进化 | 多智能体协同指数 (预留) |
| **evolution_score** | 进化 | 综合 Loop1→Loop2 改善度 |

**DarwinEvaluator 核心流程**:

```
evaluate(policy)
  ├── super().evaluate(policy)          # 基础评测
  ├── practice_hook.submit(...)          # 提交 PraxisEvent
  └── memory_hook.query(...)             # 获取历史经验
```

### 3.4 Evolution Engine

**职责**: 任务进化和进化评测

**Task Genome Engine**:
- `mutate()` - 随机变异（添加 primitive / 替换 object / 添加 constraint / 升级难度）
- `compose()` - 任务组合（将多个任务链式组合为长程任务）
- `generate_random()` - 从基因池随机生成新任务

**EvolutionRunner 双循环**:

```
Task
  │
  ▼
Loop 1 (First Encounter)
  │──▶ evaluate(task, policy)
  │──▶ record_experience(session_1, "failure")
  │
  ▼
[Memory Consolidation]  (等待 Practice → SeekDB 写入)
  │──▶ force_memory_consolidation()
  │
  ▼
Loop 2 (Retry after Learning)
  │──▶ evaluate(task, policy)
  │──▶ record_experience(session_2, "success")
  │
  ▼
Evolution Score = delta(Loop1, Loop2)
```

**MemoryEvolutionTracker**:
- 验证 SeekDB 中是否形成因果边
- 检查失败模式是否被正确识别
- 确认技能模板是否被提取

---

## 4. 数据流

### 4.1 单次评测数据流

```
┌──────────┐    ┌─────────────┐    ┌──────────────┐    ┌──────────────┐
│  Task    │───▶│  Adapter    │───▶│  Evaluator   │───▶│  Metrics     │
│  YAML    │    │  .build()   │    │  .evaluate() │    │  JSON        │
└──────────┘    └─────────────┘    └──────────────┘    └──────────────┘
                                              │
                                              ▼
                                       ┌──────────────┐
                                       │ PracticeBridge│
                                       │ .submit()     │
                                       │ (PraxisEvent) │
                                       └──────────────┘
                                              │
                                              ▼
                                       ┌──────────────┐
                                       │ MemoryBridge  │
                                       │ .record_exp() │
                                       │ (SeekDB)      │
                                       └──────────────┘
```

### 4.2 进化评测数据流

```
┌─────────────┐         ┌─────────────┐         ┌─────────────┐
│   Loop 1    │ ──────▶ │  Memory     │ ──────▶ │   Loop 2    │
│   Result    │         │ Consolidate │         │   Result    │
│  (failure)  │         │  (2s delay) │         │  (success)  │
└─────────────┘         └─────────────┘         └─────────────┘
       │                                               │
       ▼                                               ▼
┌─────────────┐                                 ┌─────────────┐
│ Memory.query│                                 │ Memory.query│
│ (before)    │                                 │ (after)     │
└─────────────┘                                 └─────────────┘
       │                                               │
       └───────────────────┬───────────────────────────┘
                           ▼
                    ┌─────────────┐
                    │ Evolution   │
                    │ Score =     │
                    │ delta()     │
                    └─────────────┘
```

---

## 5. 与 rosclaw 生态集成

### 5.1 集成矩阵

| rosclaw 组件 | 集成方式 | Darwin 用途 |
|-------------|----------|------------|
| **rosclaw-practice** | `PracticeBridge` | 评测时自动捕获 `PraxisEvent` |
| **rosclaw-memory** | `MemoryBridge` | 查询/记录 SeekDB 经验 |
| **rosclaw-know** | 预留接口 | 知识蒸馏，任务生成依据 |
| **rosclaw-how** | 预留接口 | 技能模板提取 |

### 5.2 数据格式对齐

**PraxisEvent (rosclaw-practice)**:
```python
{
    "practice_id": "darwin_evo_xxx",
    "robot_id": "darwin_agent",
    "cognitive_context": {
        "semantic_intent": "Evaluate task pick_place_milk_001",
        "llm_cot": "Evolution loop 1"
    },
    "physical_feedback": {
        "status": "FAILED_EVAL",  # or SUCCESS
        "reward": 0.0,            # or 1.0
        "error_log": ""
    },
    "data_pointers": {
        "mcap_path": "/data/rosclaw/mcap/xxx.mcap"
    }
}
```

**SeekDB 集合 (rosclaw-memory)**:
- `darwin_experiences` - 存储每次评测结果
- 查询: `memory.query("task_id:pick_place_milk_001")`

---

## 6. Docker 部署架构

### 6.1 镜像分层

```
Layer 3: rosclaw-darwin:latest  (~500MB)
  ├── rosclaw-darwin source (mounted)
  ├── fastapi / uvicorn
  └── entrypoint config

Layer 2: rosclaw-darwin:arena-base  (~22GB)
  ├── IsaacLab-Arena (+ deps)
  ├── IsaacLab (+ submodules)
  └── apt / pip packages

Layer 1: nvcr.io/nvidia/isaac-sim:6.0.0-dev2  (~18.7GB)
  ├── Omniverse Kit
  ├── Isaac Sim
  └── CUDA / PhysX / USD
```

### 6.2 服务拓扑 (docker-compose)

```
┌─────────────────────────────────────────────────────────────┐
│                     Docker Network                           │
│                                                              │
│  ┌─────────────────────────┐  ┌─────────────────────────┐  │
│  │   darwin (dev profile)  │  │  dashboard (profile)    │  │
│  │   ──────────────────    │  │  ────────────────────   │  │
│  │   Port: 5678 (debugpy)  │  │  Port: 8080 (web)      │  │
│  │   Volume: source (live) │  │  Volume: darwin-data   │  │
│  │   Command: tail -f      │  │  Command: dashboard    │  │
│  │   Purpose: development  │  │  Purpose: leaderboard  │  │
│  └─────────────────────────┘  └─────────────────────────┘  │
│                                                              │
│  ┌─────────────────────────┐                                │
│  │   eval (one-shot)       │                                │
│  │   ──────────────────    │                                │
│  │   No ports              │                                │
│  │   Command: demo.py      │                                │
│  │   Purpose: CI/batch     │                                │
│  └─────────────────────────┘                                │
│                                                              │
│  Shared Volumes:                                             │
│    - darwin-data     → /data/rosclaw (MCAP, fallback)       │
│    - darwin-seekdb   → /data/seekdb                         │
│    - host datasets   → /data/datasets                       │
│    - host models     → /data/models                         │
│    - host eval       → /data/eval                           │
└─────────────────────────────────────────────────────────────┘
```

### 6.3 部署流程

```
[Host]
  │
  ├──▶ ./scripts/deploy.sh
  │       │
  │       ├──▶ Check prerequisites (Docker, GPU, NGC login)
  │       ├──▶ Download IsaacLab-Arena (if missing)
  │       ├──▶ Initialize submodules (IsaacLab, GR00T)
  │       ├──▶ Patch Dockerfile (apt mirror, pip index)
  │       ├──▶ Build base image (~20-30 min)
  │       ├──▶ Build full image (~1-2 min)
  │       └──▶ Smoke test
  │
  ├──▶ make run          (interactive development)
  ├──▶ make demo         (run demo)
  ├──▶ make test         (run tests)
  ├──▶ make dashboard    (start web UI)
  └──▶ make eval         (evaluate task)
```

---

## 7. 扩展点

### 7.1 添加新模拟器

```python
# 1. 继承 BaseEnvironmentAdapter
class MuJoCoAdapter(BaseEnvironmentAdapter):
    name = "mujoco"

    def build(self) -> None:
        from mujoco import MjModel, MjData  # 延迟导入
        # ...

# 2. 在 ArenaAdapter 选择逻辑中添加
if backend == "mujoco":
    return MuJoCoAdapter(task)
```

### 7.2 添加新任务源

```python
# 在 TaskLoader 中添加解析器
@staticmethod
def _parse_myformat(data: dict, name: str) -> Task:
    return Task(
        id=f"myformat_{name}",
        name=data.get("task_name"),
        source="myformat",
        primitives=[Primitive(name=p) for p in data["actions"]],
    )
```

### 7.3 添加新进化算子

```python
# 在 TaskGenomeEngine 中添加
class TaskGenomeEngine:
    def _crossover(self, task1: Task, task2: Task) -> Task:
        """交叉两个任务的 primitives。"""
        # ...
```

### 7.4 添加新指标

```python
# 在 EvaluationMetrics 中添加字段
@dataclass
class EvaluationMetrics:
    # ... existing fields
    energy_efficiency: float = 0.0  # 新增

# 在 compute_metrics 中计算
```

---

## 8. 参考项目对比

| 项目 | Darwin 借鉴了什么 | Darwin 补充了什么 |
|------|------------------|------------------|
| **BEHAVIOR-1K** | BDDL 任务定义、任务本体论 | 任务进化（∞ Tasks vs 1000 Tasks） |
| **IsaacLab-Arena** | Scene+Embodiment+Task 三原语 | Evolution Runner、Memory 集成 |
| **LW-BenchHub** | Collect→Train→Eval 闭环 | 将闭环扩展为 ∞ Loop（进化飞轮） |
| **LIBERO** | 程序化任务生成管道 | 与 SeekDB 深度集成 |
| **CALVIN** | 长程语言条件任务 | 进化指标（SDR/MIE/SSI） |
| **EmbodiedBench** | 能力评测（非任务成功率） | 进化能力评测 |
| **Embodied-Arena** | 多 benchmark 统一框架 | 进化飞轮 + 排行榜 |

---

## 附录 A: 文件索引

| 文件 | 说明 |
|------|------|
| `rosclaw_darwin/tdl/schema.py` | TDL Pydantic 模型 |
| `rosclaw_darwin/tdl/loader.py` | 多源任务加载器 |
| `rosclaw_darwin/environment/base.py` | 适配器基类 |
| `rosclaw_darwin/environment/arena_adapter.py` | IsaacLab-Arena 适配器 |
| `rosclaw_darwin/evaluation/metrics.py` | 评测指标 |
| `rosclaw_darwin/evaluation/base.py` | 基础/Darwin 评测器 |
| `rosclaw_darwin/evolution/genome.py` | 任务基因组引擎 |
| `rosclaw_darwin/evolution/runner.py` | 进化运行器 |
| `rosclaw_darwin/evolution/tracker.py` | 记忆进化追踪器 |
| `rosclaw_darwin/integration/practice.py` | rosclaw-practice 桥接 |
| `rosclaw_darwin/integration/memory.py` | rosclaw-memory 桥接 |
| `rosclaw_darwin/dashboard/app.py` | EEIB 排行榜 |
| `docker/Dockerfile` | Docker 构建定义 |
| `docker/build.sh` | 镜像构建脚本 |
| `docker/run.sh` | 容器运行脚本 |
| `scripts/deploy.sh` | 一键部署脚本 |
| `Makefile` | 便捷命令 |
| `docker-compose.yml` | 服务编排 |
| `docs/DEPLOY.md` | 部署指南 |
| `docs/DOCKER.md` | Docker 使用手册 |
| `docs/ARCHITECTURE.md` | 本文档 |

---

## 附录 B: 术语表

| 术语 | 英文 | 说明 |
|------|------|------|
| TDL | Task Definition Language | 任务定义语言 |
| EEIB | Evolutionary Embodied Intelligence Benchmark | 进化型具身智能评测 |
| SDR | Skill Discovery Rate | 技能发现率 |
| MIE | Memory Integration Efficiency | 记忆整合效率 |
| SSI | Swarm Synergy Index | 群体协同指数 |
| PraxisEvent | Praxis Event | rosclaw-practice 定义的执行事件 |
| SeekDB | Seek Database | rosclaw-memory 使用的向量数据库 |
| MCP | Model Context Protocol | 模型上下文协议 |
| Kit | Omniverse Kit | NVIDIA 的应用框架 |

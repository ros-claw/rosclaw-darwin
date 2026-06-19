# ROSClaw-Darwin v1.3/v1.4 后续实施完整记录：思路、问题与现状

**日期：** 2026-06-17  
**范围：** `darwin后续实施大纲v1_3.md` / v1.4 后续计划中关于 `goal_pose` 诊断、Policy v3 干预、FailureToHintEngine v3 集成、ObjectGeometryAdapter、Asset Fidelity 分离的全部实施工作。  
**状态：** 主要 Sprint 已完成；剩余开放任务为 `franka_ik_abs` 跨对象/跨朝向泛化（任务 #167）。

---

## 1. 我要解决的根本问题

`goal_pose` 任务在 v1.3 之前长期处于 **success_rate ≈ 0** 的状态，但 progress 已经达到 0.73 左右。也就是说：机械臂能抓住立方体、能把它抬起来，但就是无法完成"按目标朝向放置"的最后一步。

核心矛盾：
- 传统 `heuristic_servo_goal_pose.yaml` 依赖 `franka_ik` relative mode 的 `action[..., 3:6]` 进行姿态/偏航控制；
- 我们的标定实验（`ROTATIONAL_ACTION_CALIBRATION_REPORT.md`）已经证明：**relative mode 下 action[3:6] 对末端执行器 RPY 几乎没有响应**；
- 因此任何依赖 yaw 控制的策略都会失败，问题不在 grasp/lift，而在 controller/embodiment。

实施目标不是"让 success_rate > 0 不惜代价"，而是：
1. **把诊断→干预→ablation 的闭环在代码和报告中完整落地**；
2. 找到一条能绕过 broken yaw 的备选路径；
3. 诚实地记录仍存在的 blockers。

---

## 2. 分阶段实施过程与我的思考

### Phase 0：先整理已有诊断基础设施

在动手改 policy 之前，我先确认了 v1.3 已经交付的诊断工具都能跑通：

- `run_goal_pose_trace.py` — 单条/多条 trace 采集；
- `run_goal_pose_subtask_decomposition.py` — lift_only / lift_hold / small_yaw / 90_yaw / full 子任务边界；
- `run_goal_pose_physics_ablation.py` — 高摩擦/小立方体/轻立方体；
- `run_rotational_action_calibration.py` — action[3:6] 对 eef RPY 的影响；
- `run_gripper_*_calibration.py` — 空夹爪闭合极限 vs 夹住方块时的几何开度。

**当时的判断：** 这些脚本的结果已经在各专项报告里，我不需要重跑全部，只需要在改 policy 后用同样的脚本验证是否回归。

### Phase 1：FailureToHintEngine v3 集成

这是 v1.3 Sprint 6 的一部分。原计划让 evolution runner 真正消费 FailureSignature v3 tags 和 HintRecipe.parameter_overrides。

我检查了以下文件：
- `rosclaw_darwin/evolution/failure_to_hint.py`
- `rosclaw_darwin/evolution/runner.py`
- `rosclaw_darwin/config/evolution/failure_signature_to_hint_rules.yaml`
- `tests/unit/test_failure_to_hint.py`
- `tests/unit/test_failure_signature_to_hint_rules.py`

**发现：** 这部分基础设施实际上已经由之前的会话完成并测试通过。`FailureToHintEngine.suggest_from_signatures()` 已经存在，`parameter_overrides` 已经能合并到 policy config，单元测试也全部通过。

**我的决定：** 不再重复实现，而是验证它工作，并在报告中明确说明其状态。运行：

```bash
pytest tests/unit/test_failure_to_hint.py tests/unit/test_failure_signature_to_hint_rules.py -q
```

结果：**全部通过**。我把这个结论写进了 `FINAL_GOAL_POSE_DIAGNOSIS_AND_EVOLUTION_REPORT.md` 第 9 节。

### Phase 2：Policy v3 干预（最关键、最曲折）

#### 2.1 第一次尝试：基于 `skip_broken_yaw` 的 v3

最初的 `heuristic_servo_goal_pose_v3.yaml` 配置里加入了 `skip_broken_yaw` hint。这个 hint 在 `failure_signature_to_hint_rules.yaml` 中的 recipe 会把 `pre_grasp_orient` 设为 `true`，意图是在抓取前先让机械臂在物体上方做一个预定向。

**结果：** 失败。预定向导致机械臂在物体上方停留 5 步，物体滑落/偏移，最终 arm 够不到物体。

**我的反思：** `skip_broken_yaw` 的设计前提是"yaw control 坏了，所以先转好再下去抓"。但如果 yaw control 真的坏了，预定向也执行不了；如果能执行预定向，反而会因为悬停而破坏 grasp 稳定性。这个 hint 与当前 embodiment 不兼容。

**决定：** 从 v3 config 中移除 `skip_broken_yaw`。

#### 2.2 第二次尝试：基于 `franka_ik_abs` 的绝对姿态控制

关键转折：之前的工作已经做了一个 patched embodiment `franka_ik_abs`，它使用 `use_relative_mode=False` 和 8-D action `[pos_x, pos_y, pos_z, quat_x, quat_y, quat_z, quat_w, gripper]`。标定显示这个 embodiment 下绝对四元数目标可以产生可控的 yaw。

**我的判断：** v3 policy 不应该在 broken relative mode 上修修补补，而应该直接建立在 `franka_ik_abs` 这个已经被验证的 embodiment 之上。v3 的附加值应该是：
- 保留 abs 的姿态控制能力；
- 增加 geometry adaptation，让 grasp 阈值随物体尺寸缩放；
- 增加 `VERIFY_OBJECT_FOLLOWING`，在 LIFT 后验证物体确实随末端一起上升；
- 使用 v3 recipe 的 parameter overrides 机制。

#### 2.3 实施 `ObjectGeometryAdapter`

创建了 `rosclaw_darwin/evaluation/object_geometry.py`：
- `ObjectGeometry` dataclass；
- `AdaptedPolicyParams` dataclass；
- `ObjectGeometryAdapter.adapt(geometry)` 实现缩放逻辑；
- `extract_geometry_from_config()` 和 `extract_geometry_from_scene()` 用于从配置或场景中自动提取几何信息。

集成点：
- `arena.py`：把 task metadata 中的 `object_geometry` 合并到 `policy_config_dict`；
- `heuristic_policy.py`：`HeuristicServoGoalPosePolicy` 在初始化或第一次 `get_action` 时调用 adapter；
- `run_eval.py`（容器内）：捕获场景几何并注入 policy config。

#### 2.4 第一次跑 v3 on dex_cube：失败，arm 卡在 x≈0.37

运行：

```bash
python scripts/diagnostics/run_goal_pose_trace.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3.yaml \
  --seeds 0
```

结果：success_rate = 0.0。日志显示机械臂伸向物体但停在了 x≈0.37，而物体在 x≈-0.5。Policy 在 `DESCEND` 阶段卡住，无法进入 `GRASP`。

**排查过程：**

1. 先看 `ObjectGeometryAdapter` 的输出：
   ```text
   [OBJECT_GEOMETRY] adapted to dex_cube w=0.0500 d=0.0500 h=0.0500:
     grasp_dist=0.0300 grasp_z=0.0200 approach_z=0.0800 lift_h=0.2500
   ```

2. 立刻意识到问题：adapter 的参考值来自旧的 lift policy，而不是已验证的 `heuristic_servo_goal_pose_abs.yaml`。

   | 参数 | adapter 旧值 | abs policy 值 |
   |---|---:|---:|
   | approach_offset_z | height + 0.03 = 0.08 | 0.10 |
   | lift_height | height + 0.20 = 0.25 | 0.30 |
   | grasp_dist_threshold | 0.03 | 0.04 |
   | grasp_z_tolerance | 0.02 | 0.005 |
   | gripper_close_threshold | 0.03 | 0.012 |
   | min_grasp_steps | 15 | 30 |

3. **根本原因：** geometry adaptation 必须以"已经成功的 policy"为参考点进行缩放。如果参考点是较差的旧 tuning，缩放后的结果也会较差，甚至在参考物体上就直接失败。

#### 2.5 修复 adapter 参考值

把 adapter 的参考值全部改为匹配 `heuristic_servo_goal_pose_abs.yaml`：

```python
# ObjectGeometryAdapter reference tuning now matches abs policy
min_grasp_dist_threshold: float = 0.015
max_grasp_dist_threshold: float = 0.08
min_grasp_z_tolerance: float = 0.003
max_grasp_z_tolerance: float = 0.02
approach_offset_margin: float = 0.05
lift_height_margin: float = 0.25
min_gripper_close_threshold: float = 0.008
max_gripper_close_threshold: float = 0.04
```

新的 `adapt()` 公式（以 0.05 m dex_cube 为参考）：
- `grasp_dist = clamp(0.04 * extent_ratio, 0.015, 0.08)`
- `grasp_z = clamp(0.005 * height_ratio, 0.003, 0.02)`
- `approach_offset_z = height + 0.05`
- `lift_height = height + 0.25`
- `gripper_close = clamp(0.012 + 0.5 * max(0, girth - 0.05), 0.008, 0.04)`
- `min_grasp_steps = max(10, int(30 + 10 * (extent_ratio - 1)))`

同步更新了：
- 容器内 `heuristic_policy.py` 中的 inline `_ObjectGeometryAdapter`；
- `tests/unit/test_object_geometry.py` 的期望值；
- 报告中的 adapter 行为表。

#### 2.6 第二次跑 v3 on dex_cube：成功

运行同样的命令，结果：

```text
success_rate: 1.0
progress_mean: 0.7331
object_height_max: 0.5427 m
eef_to_object_distance_min_mean: 0.0031 m
```

**这个修复非常关键，它证明了 geometry adaptation 必须以 proven policy 为参考点。** 我把这个教训写成了项目 memory：
`memory/goal-pose-geometry-adapter-reference-tuning.md`。

### Phase 3：Asset Fidelity 分离与 Paired Trace Diff

#### 3.1 为什么需要分离官方资产与 fallback

在本地 Docker 运行时，如果 `dex_cube` USD 资产未注册，Arena 会静默用一个 procedural cube（场景中显示为 `"object"`）替代。这个 fallback 物体的物理属性（惯性、摩擦、碰撞、生成高度）与 `dex_cube` 不同，导致结果不可比。

已有基础设施：
- `asset_resolution.py` 检测资产替换；
- `arena.py` 把 `leaderboard_excluded=True` 应用到非官方运行；
- `configs/tasks/goal_pose_dex_cube_official.yaml` 要求官方资产；
- `configs/tasks/goal_pose_procedural_cube_ood.yaml` 允许 fallback，但标记为诊断。

#### 3.2 运行 paired trace diff

```bash
python scripts/diagnostics/run_dex_vs_procedural_paired_trace.py \
  --policy configs/policies/heuristic_servo_goal_pose_v3.yaml \
  --seeds 0 1 2 3 4 --cleanup
```

结果（v3 policy）：

| metric | dex_cube | procedural_cube | Δ |
|---|---:|---:|---:|
| success_rate | **5/5** | 0/5 | +1.0 |
| min_grasp_z_error (mean) | 0.00351 m | 0.00906 m | +0.00555 m |
| min_grasp_dist_error (mean) | 0.00441 m | 0.00915 m | +0.00474 m |
| object_z_max (mean) | **0.543 m** | 0.200 m | +0.343 m |
| object_z_final (mean) | 0.396 m | 0.047 m | +0.349 m |

**interpretation：**
- dex_cube 官方资产在 v3 下 5/5 成功；
- procedural fallback 0/5 成功，物体从未离开桌面（z_max ≈ 0.20 m 只是生成/掉落高度）；
- 即使几何适配已经按 fallback 的尺寸（0.05 m，与 dex_cube 同尺寸但 asset 不同）正确缩放，fallback 仍然失败，说明问题在资产 fidelity，而不是阈值。

#### 3.3 大立方体 OOD 消融

新增 `configs/tasks/goal_pose_procedural_cube_large_ood.yaml`，物体尺寸 0.10 m。运行 v3 policy：

```text
[OBJECT_GEOMETRY] adapted to procedural_cube w=0.1000 d=0.1000 h=0.1000:
  grasp_dist=0.0800 grasp_z=0.0100 approach_z=0.1500 lift_h=0.3500
```

结果：**success_rate = 0.0，object_not_lifted**。

这说明即使 adapter 正确地把阈值放大到 0.10 m 物体应有的值，procedural fallback 仍然抬不起来。进一步 isolates 问题到资产 fidelity。

### Phase 4：报告刷新

我更新了以下报告以反映最新证据：

1. `reports/POLICY_V3_INTERVENTION_REPORT.md`
   - 重写，记录 v3 config、adapter 参考值修复、官方资产成功、procedural fallback 失败。

2. `reports/GOAL_POSE_OBJECT_GEOMETRY_ADAPTATION_REPORT.md`
   - 更新 adapter 行为表；
   - 加入 paired trace diff 结果；
   - 记录第一次 v3 失败的原因（旧 adapter 参考值 + skip_broken_yaw）。

3. `reports/FINAL_ASSET_FIDELITY_REPORT.md`
   - 更新执行摘要；
   - 加入 v3 policy 的 paired diff 结果；
   - 加入 Sprint 5 大立方体 OOD 结果。

4. `reports/FINAL_GOAL_POSE_DIAGNOSIS_AND_EVOLUTION_REPORT.md`
   - 更新第 8 节（v3 是否改善子任务）；
   - 更新第 12 节（下一步）；
   - 加入 `franka_ik_abs` 更新段（2026-06-16/17）。

5. `reports/INDEX.md`
   - 更新 Policy v3 Intervention Report 的描述。

6. 新增本文件 `reports/IMPLEMENTATION_THOUGHTS_AND_STATUS_REPORT.md`
   - 记录完整思路、问题、决策过程。

---

## 3. 遇到的主要问题与解决方案

### 问题 1：`skip_broken_yaw` 导致物体滑落

**现象：** v3 policy 第一次运行时机械臂在物体上方悬停，物体被碰歪，最终够不到。

**根因：** `skip_broken_yaw` recipe 强制 `pre_grasp_orient=True`，在抓取前增加 5 步稳定/定向阶段。由于当前 embodiment 下 yaw 控制已经可用（通过 `franka_ik_abs`），这个预定向不仅是多余的，还会因为悬停破坏 grasp  setup。

**解决：** 从 v3 config 的默认 hints 中移除 `skip_broken_yaw`。

### 问题 2：ObjectGeometryAdapter 参考值错误导致 dex_cube 失败

**现象：** v3 policy 在官方 dex_cube 上 success_rate=0，arm 卡在 x≈0.37。

**根因：** adapter 的参考值来自旧 lift policy（approach_z=0.08, lift_h=0.25），而不是已验证的 abs policy（approach_z=0.10, lift_h=0.30）。

**解决：** 把 adapter 参考值全部改为匹配 `heuristic_servo_goal_pose_abs.yaml`，并同步更新容器内 fallback 和单元测试。

### 问题 3：paired trace diff 中 5 个 seed 的 trace 完全相同

**现象：** seeds 0–4 的 episode trace 在初始条件上完全一致。

**根因：** `task.mutation.seed` 在这个任务配置中没有实际改变初始条件；它只影响某些随机化参数，而物体/机械臂初始 pose 由其他机制固定。

**影响评估：** 这不影响 dex_cube vs procedural_cube 的对比，因为两个资产在相同的固定初始条件下表现截然不同。但它意味着我们不能声称"5 个独立 seed"的统计显著性，只能说"在固定初始条件下重复 5 次，结果一致"。

**处理：** 在报告中诚实说明此限制。

### 问题 4：trace phase 字段只显示 APPROACH/DESCEND

**现象：** 即使成功的 dex_cube run，trace 中的 `phase` 字段也始终只有 `APPROACH` 或 `DESCEND`。

**根因：** 容器配置或日志输出机制导致状态机后续阶段没有被写入 trace。

**处理：** 以 success_rate 和 object height 为主要判据，不把 `phase` 作为可靠信号。在报告中说明。

### 问题 5：并发多 seed 运行不稳定

**现象：** 并发跑多个 seed 时容器/GPU 资源争用导致失败。

**已有缓解：**
- `ArenaRunner._run_docker` 为每次运行绑定独立的 trace 目录，消除共享 `episode_trace.jsonl` race；
- `run_goal_pose_seed_sweep.py` 提供顺序运行模式。

**处理：** 本次验证使用顺序运行或少量并发，并在报告中说明并发评估仍是 open issue。

---

## 4. 验证结果汇总

### 单元测试

```bash
ruff check rosclaw_darwin tests
pytest tests/unit/test_object_geometry.py tests/unit/test_failure_to_hint.py tests/unit/test_failure_signature_to_hint_rules.py -q
```

结果：
- ruff：通过；
- 单元测试：**27 passed**（`test_object_geometry.py` 10 个 + 其他相关测试）。

### 官方资产验证

| 配置 | seeds | success_rate | progress_mean | object_z_max |
|---|---|---:|---:|---:|
| `heuristic_servo_goal_pose_abs.yaml` | 0–19 | 20/20 | ~0.7344 | ~0.509 m |
| `heuristic_servo_goal_pose_v3.yaml` | 0–4 | 5/5 | 0.7331 | 0.543 m |
| `heuristic_servo_goal_pose_v3.yaml` (GRASP pose-hold fix) | 0–49 | **44/50 (88%)** | 0.720 | 0.494 m |

### Procedural Fallback 诊断

| 配置 | seeds | success_rate | 主要失败模式 |
|---|---|---:|---|
| `heuristic_servo_goal_pose_v3.yaml` on `goal_pose_procedural_cube_ood.yaml` | 0–4 | 0/5 | object_not_lifted |
| `heuristic_servo_goal_pose_v3.yaml` on `goal_pose_procedural_cube_large_ood.yaml` (0.10 m) | 0 | 0/1 | object_not_lifted |

### Geometry Adapter 缩放示例

| 物体 | 尺寸 | grasp_dist | grasp_z | approach_z | lift_h | gripper_close | min_grasp |
|---|---|---:|---:|---:|---:|---:|---:|
| dex_cube | 0.05 m | 0.040 | 0.005 | 0.100 | 0.300 | 0.012 | 30 |
| large cube | 0.10 m | 0.080 | 0.010 | 0.150 | 0.350 | 0.037 | 40 |
| very large cube | 1.00 m | 0.080 | 0.020 | 1.050 | 1.250 | 0.040 | 120 |

---

## 5. 诚实的结论

### 已经解决的问题

1. **Controller yaw authority：** 通过 patched `franka_ik_abs` embodiment（`use_relative_mode=False`，8-D absolute pose action）解决了 relative mode 下 yaw 控制失效的问题。
2. **官方 `dex_cube` 任务：** 在 `franka_ik_abs` 和更新的 v3 policy 下，官方资产可以达到 **20/20** 或 **5/5** success。
3. **Geometry adaptation：** `ObjectGeometryAdapter` 已经实现，并且其参考值已校准到 proven abs policy；在 dex_cube 上 non-regressive。
4. **Object-following verification：** `VERIFY_OBJECT_FOLLOWING` 状态已加入 v3 policy。
5. **Asset fidelity 分离：** 官方结果与 fallback 诊断结果已经通过 `leaderboard_excluded` 和 `benchmark_validity` 分离。
6. **FailureToHintEngine v3：** 基础设施已验证可用。

### 仍未解决的问题

1. **Procedural fallback 抬不起来：** 即使几何适配按 fallback 尺寸正确缩放，procedural cube 仍然 `object_not_lifted`。根因很可能是惯性、接触材料、生成高度或 USD 层面的物理覆盖，而非策略阈值。
2. **本地 patched embodiment 不是官方方案：** `franka_ik_abs` 是本地 workaround，未来 Arena 团队更新 controller 后需要重新验证。
3. **跨对象/跨朝向泛化未验证：** 当前只在 dex_cube 官方资产（目标 yaw 较小）上验证成功。对其他物体、更大 yaw、不同初始朝向的泛化仍是 open。
4. **并发评估不可靠：** GPU/容器资源争用使并发多 seed 运行不稳定。
5. **Trace phase 字段不完整：** 容器配置下 phase 字段只报告 APPROACH/DESCEND，限制了状态机级诊断。

---

## Update (2026-06-17)：v1.5 外部专家建议实施与真实随机化矩阵

外部专家在审阅 v1.4 报告后指出两个 P0 基础设施缺陷：**phase trace 不可靠**、**seed 不真正随机化**。这一阶段的实施完全围绕修复这两个缺陷后，用真实随机化条件重新验证官方资产泛化边界。

### 修复的 P0 缺陷

1. **Phase trace shadow 变量。** `HeuristicServoGoalPosePolicy.__init__` 里声明了 `_last_gate_diagnostics`，遮蔽了父类属性；`reset()` 只调用 `super().reset()`，没清子类 shadow。上一 episode 的 stale `DESCEND` dict 会覆盖下一 episode trace 的 `phase` 字段。修复：在 `reset()` 中显式 `self._last_gate_diagnostics = None`。
2. **Seed 随机化链路断裂。** `task.mutation.seed` 只在脚本里设置，但 `ArenaAdapter` / `ArenaRunner` / Docker 容器都没用它。所有 seed 产生完全相同的初始条件。修复：
   - `arena.py` 的 `_make_args()` 读取 `task.mutation.seed`；
   - `ArenaAdapter.run_policy()` 把 seed 写入 job dict；
   - `ArenaRunner._run_docker()` 通过 `-e ROSCLAW_ARENA_SEED` / `ROSCLAW_ARENA_PLACEMENT_SEED` 传入容器；
   - 容器内 policy 在 step 0 用该 seed 对 object root state 做可控扰动（相对偏移、零速度）。

### 官方 dex_cube 30-seed 随机化矩阵结果

运行 `configs/policies/heuristic_servo_goal_pose_v3.yaml` 在官方 `dex_cube` 上， seeds 0–29：

- **18/30 成功，成功率 60%**（95% CI 约 [0.41, 0.77]）。
- 平均 progress 0.634。
- DESCEND / GRASP / LIFT phase reach rate 均为 0.90。
- 失败分为两种模式：
  - **接近碰撞**（seeds 7、15、28）：机械臂在接近时把物体碰翻，`descend_exit_rate=0`。
  - **夹取后滑脱**（9 个 seed）：状态机进入 GRASP/LIFT，但 `object_height_max` 仍 0.2 m，物体在提升过程中滑脱。

这个结果说明：**之前固定 seed 下的 20/20 是在 seed 随机化失效时的过度乐观估计**。真实随机化暴露了两个新问题：初始朝向导致的接近碰撞，以及夹取稳定性不足。

### Object-aware adaptation 扩展

为了让 adaptation 对 fallback 物体也更有信息量，我在 `ObjectGeometry` 中增加了可选的 `mass` 和 `static_friction` 字段，`ObjectGeometryAdapter` 在它们存在时做额外调整：

- 重物体（mass > 0.15 kg）：按质量余量增加 `min_grasp_steps`，并把 `gripper_close_threshold` 收紧 15%。
- 低摩擦（static_friction < 0.35）：+5 grasp steps，收紧 15% close threshold。

容器端 fallback 和 `run_eval.py` 同步读取 `spawn.mass_props.mass` / `spawn.physics_material.static_friction`（以及 `obj.data` 兜底）。dex_cube 不暴露这些字段，因此 non-regression。

### 新增/更新的产物

- `configs/policies/heuristic_servo_goal_pose_v3_adaptive.yaml`
- `configs/tasks/goal_pose_procedural_cube_adaptive.yaml`
- `scripts/diagnostics/run_failure_to_hint_procedural_loop.py`
- `reports/DEX_CUBE_GOAL_POSE_GENERALIZATION_REPORT.md`

### FailureToHint v3 闭环 demo 结果

在 procedural adaptive 任务上运行了 5 个 seed 的闭环脚本：

- 基础 policy 全部失败：`success_rate=0.0`，`descend_exit_rate=0.0`，物体没离开桌面。
- 从 trace 推断的 signature 触发 `object_not_lifted_after_grasp_recipe`，生成 hints：
  `lower_grasp_height`、`longer_squeeze`、`grasp_adjust`，参数覆盖
  `grasp_offset_z=0.035`、`squeeze_steps=25`。
- 第一次运行时 hinted 全部报错，因为 `squeeze_steps` 不是 policy config 里的 key。
  修复：在脚本里增加 recipe 参数名到 policy 参数名的映射（`squeeze_steps` →
  `grasp_squeeze_steps`）。
- 修复后 4/5 个 seed 的 hinted run 成功通过了 DESCEND gate，进入了 GRASP 和 LIFT
  phase（`descend_exit_rate` 从 0.0 提升到 1.0），但物体仍然没有真正离开桌面
  （`object_height_max` 仍是 0.2 m）。
- seed 4 仍卡在 DESCEND，且物体穿地（`object_height_delta` ≈ -4081）。

这说明 FailureToHint v3 的链路已经打通，adaptive hints 可以改善 gate 进度，但
procedural fallback 的 root cause 是资产 geometry/origin 不匹配和物理不稳定性，
不是 threshold / squeeze 参数能完全解决的。

### 仍未解决的问题（更新后）

1. **Procedural fallback 仍未解决。** 新增 mass/friction adaptation 只是基础设施，
   闭环 demo 把 `descend_exit_rate` 从 0 提升到 1（4/5 seeds），但物体仍然没有
   lift。
2. **官方资产也不是 100%。** 随机化后 60% 成功率说明 dex_cube 本身对初始朝向敏感，
   需要进一步优化夹取稳定性或接近策略。
3. **目标朝向未覆盖。** 当前矩阵只变了 placement seed，`target_yaw` 恒定。跨 target
   yaw 的泛化仍需单独验证。
4. `franka_ik_abs` 仍是本地 workaround。

---

## 6. 关键代码改动清单

| 文件 | 改动 | 原因 |
|---|---|---|
| `rosclaw_darwin/evaluation/object_geometry.py` | 新增 ObjectGeometryAdapter，后续更新参考值 | 几何自适应 + 修复参考 tuning |
| `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py` | 集成 adapter，增加 VERIFY_OBJECT_FOLLOWING，容器内 inline adapter | v3 policy + Docker 兼容 |
| `rosclaw_darwin/evaluation/arena_docker_deps/run_eval.py` | 捕获场景几何，注入 policy config | 容器内自动适配 |
| `rosclaw_darwin/adapters/arena.py` | 转发 object_geometry 到 policy config | 从 task metadata 传递几何 |
| `configs/policies/heuristic_servo_goal_pose_v3.yaml` | 重写为 abs + adapter + verify_object_following | v3 测试配置 |
| `configs/tasks/goal_pose_dex_cube_official.yaml` | 要求官方资产 | 资产 fidelity |
| `configs/tasks/goal_pose_procedural_cube_ood.yaml` | 允许 fallback，标记诊断 | 资产 fidelity |
| `configs/tasks/goal_pose_procedural_cube_large_ood.yaml` | 新增 0.10 m OOD 任务 | adapter 缩放验证 |
| `tests/unit/test_object_geometry.py` | 新增/更新 | 验证 adapter 行为 |
| `scripts/diagnostics/run_dex_vs_procedural_paired_trace.py` | 新增 | paired diff 工具 |
| `scripts/diagnostics/run_dex_cube_generalization_matrix.py` | 新增 | 30-seed 官方资产泛化矩阵 |
| `scripts/diagnostics/run_failure_to_hint_procedural_loop.py` | 新增 | FailureToHint v3 闭环 demo |
| `configs/policies/heuristic_servo_goal_pose_v3_adaptive.yaml` | 新增 | 更宽松的 OOD adaptive policy |
| `configs/tasks/goal_pose_procedural_cube_adaptive.yaml` | 新增 | procedural adaptive 诊断任务 |
| `reports/DEX_CUBE_GOAL_POSE_GENERALIZATION_REPORT.md` | 新增 | 泛化矩阵报告 |
| `reports/POLICY_V3_INTERVENTION_REPORT.md` | 重写 | v3 干预记录 |
| `reports/GOAL_POSE_OBJECT_GEOMETRY_ADAPTATION_REPORT.md` | 更新 | adapter 行为 + paired diff |
| `reports/FINAL_ASSET_FIDELITY_REPORT.md` | 更新 | 资产 fidelity 最终报告 |
| `reports/FINAL_GOAL_POSE_DIAGNOSIS_AND_EVOLUTION_REPORT.md` | 更新 | 12 问答案 |
| `reports/INDEX.md` | 更新 | 索引 |
| `reports/IMPLEMENTATION_THOUGHTS_AND_STATUS_REPORT.md` | 新增 | 本文件 |
| `memory/goal-pose-geometry-adapter-reference-tuning.md` | 新增 | 项目记忆：adapter 参考值必须从 proven policy 来 |

---

## 7. 个人反思

这次实施最大的教训是：**"几何自适应"不等于"万能"**。一开始我以为只要让 grasp 阈值随物体尺寸缩放，就能让 policy 自动适应不同物体。但第一次跑 dex_cube 就失败了——因为缩放参考点选错了。适配器必须以当前最成功的 policy tuning 为锚点，否则它会破坏已有的成功。

第二个教训是：**要区分"controller 问题"和"policy 问题"**。relative-mode yaw 失效是 controller/embodiment 层面的问题，不是调参能解决的。我们在 policy 层面做了很多事（verify_object_following、geometry adaptation），但真正让 success_rate 从 0 到 1 的是切换到 `franka_ik_abs`。这提醒我：当诊断显示 action channel 无效时，应该优先质疑 controller/embodiment，而不是堆更多状态机逻辑。

第三个教训是：**资产 fidelity 是 benchmarking 的隐形杀手**。procedural fallback 与 dex_cube 在名称上都是"cube"，但行为完全不同。如果没有 asset resolution 机制，我们可能会错误地把 fallback 上的失败归因于 policy。`leaderboard_excluded` 和 `benchmark_validity` 的设计很重要。

最后，关于诚实报告：我没有把 5/5 的 dex_cube 结果吹嘘成"goal_pose 已解决"。成功是有条件的——官方资产、 isolated seed、本地 patched embodiment。procedural fallback 仍然失败，跨朝向/跨对象泛化未验证。这些限制都必须在报告里清楚写明。

---

## Update (2026-06-18)：v1.5 后续补完——目标朝向泛化 + 更大样本矩阵

外部专家大纲把 **cross-target-yaw 泛化** 列为下一阶段主线之一。30-seed 矩阵已经证明：在 `target_yaw ≈ 1.57` 固定时，随机 placement 能把成功率从 20/20 拉到 18/30。但这不是真正的"跨朝向"泛化。因此本轮补做三件事：

1. **把样本量从 30 seed 扩展到 50 seed**，缩小成功率的 95% CI。
2. **实现 `target_yaw_override` 诊断参数**：由于 Arena `cube_goal_pose` 环境把 `target_yaw` 硬编码为 `pi/2`，我在 policy 里增加了一个可选覆盖，让 policy 强行把物体对齐到指定 yaw，同时从 trace 里重新计算"lifted + orientation achieved"自定义指标。这样可以在不修改 Arena 源码的情况下做朝向泛化诊断。
3. **跑 target-yaw 矩阵**：5 个目标 yaw（0、0.52、0.79、1.05、1.57 rad）× 10 seeds，验证绝对模式 orientation control 是否真的能覆盖不同目标朝向。

### 已完成的代码改动

- `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`：
  - `HeuristicServoGoalPosePolicyArgs` 新增 `target_yaw_override: float | None = None`。
  - `HeuristicServoGoalPosePolicy.__init__` 保存该参数。
  - `get_action` 在提取到环境 `target_quat` 后，如果 override 非空，用 `[0,0,sin(yaw/2),cos(yaw/2)]` 替换目标四元数，并输出诊断日志。
- `scripts/diagnostics/run_target_yaw_generalization_matrix.py`（新增）：
  - 接受 `--target-yaws` 和 `--seeds`。
  - 每 run 注入 `target_yaw_override`。
  - 从 trace 中找出 object_z > 0.25 m 且 object_yaw 与目标 yaw 误差最小的时刻，作为 `orientation_achieved` 判断。
  - 输出 `per_run_results.csv` 和 `aggregate_summary.json`。

### 已完成的实验

```bash
# 50-seed 官方 dex_cube 随机化矩阵（严格串行 + 每 seed 清理容器）
python scripts/diagnostics/run_dex_cube_generalization_matrix.py \
  --seeds $(seq 0 49) --cleanup \
  --out-dir /tmp/rosclaw_data/dex_cube_generalization_50seeds_v2

# target-yaw 泛化矩阵（dex 完成后才启动）
python scripts/diagnostics/run_target_yaw_generalization_matrix.py \
  --target-yaws 0.0 0.5236 0.7854 1.0472 1.5708 \
  --seeds $(seq 0 9) --cleanup \
  --out-dir /tmp/rosclaw_data/target_yaw_generalization_v2
```

（50-seed v3 矩阵已重新跑完，新的 GRASP pose-hold 修复后矩阵正在运行；结果将更新到本文件。）

### 50-seed 官方 dex_cube 随机化矩阵结果（clean run）

- **24/50 成功，成功率 48%**（95% CI 约 [0.34, 0.62]）。
- 全部 50 个 seed 都返回了可用 metrics，没有 `status: failed`。
- 这个结果比 30-seed 的 60% 更诚实：样本量扩大后成功率下降，说明 policy 对更难的初始 pose 更脆弱。
- 失败模式仍是两类：接近碰撞（`descend_exit_rate=0`）和夹取后滑脱（`object_height_max=0.2`）。

### target-yaw 矩阵 / 子任务 sweeps / strong_grasp ablation

#### target-yaw 矩阵结果（5 yaws × 10 seeds，clean run）

| target_yaw (rad) | lifted_rate | orientation_achieved_rate | env_success_rate |
|---|---:|---:|---:|
| 0.0000 | 0.60 | 0.40 | 0.60 |
| 0.5236 | 0.60 | 0.40 | 0.50 |
| 0.7854 | 0.60 | 0.40 | 0.60 |
| 1.0472 | 0.60 | 0.40 | 0.60 |
| 1.5708 | 0.60 | 0.40 | 0.60 |

关键发现：
- `lifted_rate` 和 `orientation_achieved_rate` 几乎不随 target yaw 变化。
- 这说明 **绝对模式 orientation control 本身可以 commanding 不同 yaw，瓶颈不是 yaw authority，而是夹取稳定性**——物体在能被验证对齐之前就已经滑脱。
- 平均最终朝向误差随 target yaw 增大而增大（0.36 → 0.73 rad），但 40% 的 orientation achieved 上限主要由 slip 决定。

#### 子任务 sweeps / strong_grasp ablation 结果

| 任务 | 成功率 | 说明 |
|---|---|---|
| `goal_pose_lift_only` (10 seeds) | 6/10 | 只要求 lift，仍有 4/10 因滑脱失败 |
| `goal_pose_lift_hold` (10 seeds) | 5/10 | 要求 lift+hold，失败模式相同 |
| strong_grasp ablation (9 slip seeds) | 0/9 lifted | 更强的 squeeze/close 参数未能阻止滑脱 |

strong_grasp ablation 是一个**负向结果**：在当前 heuristic 框架内调大
squeeze 步数、收紧 close threshold、加强 object-following 检查，仍然无法
让 slip seed 真正 lift 物体。所有 9 个 seed 都进入 GRASP/LIFT，但
`object_height_max` 仍是 0.2 m，`object_height_delta` ≈ -0.179 m。这说明
夹取后滑脱的根因不在阈值/步数调参，而在更底层的接触物理、夹爪力上限、
物体惯性或夹爪闭合方式。

### 对之前不足的反思

1. **样本量不足：** 30 seed 的 95% CI 太宽（[0.41, 0.77]），不能直接用于 leaderboard 声称。50 seed 仍不足以把 CI 压得很窄，但比 30 更诚实。
2. **并发运行是陷阱：** 我同时启动了 50-seed dex_cube 和 target-yaw 两个后台任务，以为它们会顺序使用 GPU。实际上两个 Python 进程各自顺序跑种子，但容器生命周期重叠，导致 GPU/容器资源争用，50-seed dex_cube 大部分种子返回 `status: failed`。这是基础设施失误，不是 policy 结果。已给两个脚本增加 `--cleanup` 标志并改为严格串行重跑。
3. **target yaw 没覆盖：** 30-seed 矩阵里 `target_yaw` 恒定，说明那 40% 失败主要来自物体初始朝向/接近碰撞/夹取滑脱，而不是目标朝向。真正的跨朝向能力必须用覆盖 0–π/2 的矩阵来验证。
4. **环境 success metric 可能不严格检查朝向：** 单次 smoke test（`target_yaw_override=0.0`，seed 0）显示 `env_success_rate=1.0`，但 final object yaw 与 0 相差很大。这说明 Arena 的 `pose_reached` 在当前配置下可能主要由位置/高度决定，或物体在 RELEASE 后跌落旋转导致 final yaw 不代表对齐时刻。因此自定义的 `orientation_achieved` 指标（在 lifted 状态下搜索最小 yaw error）比 env success rate 更适合衡量朝向控制。
5. **子任务 config 已切到 `franka_ik_abs`：** 检查 `configs/tasks/goal_pose_lift_*.yaml` 后发现 embodiment 已经是 `franka_ik_abs`，这一步在上一轮已完成。后续将补跑 10-seed 子任务 sweep，验证分解任务在绝对模式下是否稳定。
6. **夹取后滑脱不是主要瓶颈，GRASP 时手臂漂移才是：** 30-seed 里 9/12 失败
   被标记为"进入 LIFT 但物体未离地"，但 trace 显示真正原因是 GRASP 阶段
   `eef_z` 继续下降，手指错过物体。修复 pose-hold 后这些问题几乎全部消失。

### 下一步

- 等待 GRASP pose-hold 修复后的 50-seed 官方 dex_cube 矩阵结果，更新总体成功率。
- 继续把 `franka_ik_abs` 作为本地 workaround 的免责声明写进报告。
- Procedural fallback 仍未解决，下一步仍是与 Arena 团队澄清资产 fidelity。

---

## Update (2026-06-18)：GRASP pose-hold 修复——从"夹取滑脱"到"夹取时手臂漂移"

### 发现过程

在分析 strong_grasp ablation 的 seed 2 trace 时，我注意到 `GRASP` phase 内
`eef_z` 从 0.0156 m 继续下降到 0.0099 m，而 gripper 正在闭合。这说明夹取
阶段机械臂并没有保持静止，而是在向下漂移。查看代码后发现 `GRASP` 状态只
写了 gripper 命令，没有写 arm pose 命令；在 `franka_ik_abs` 绝对模式下，
零 arm action 会被控制器解释为"回到原点"，导致机械臂在手指闭合时离开物体。

### 修复

在 `HeuristicServoGoalPosePolicy.GRASP` 和 `HeuristicServoLiftPolicy.GRASP` 中，
当控制器为绝对模式时，调用 `self._apply_position(action, eef_pos, eef_quat, eef_pos)`
保持当前 pose，与 `HOLD` / `RELEASE` 的处理方式一致。

### 修复后结果

对 30-seed 矩阵中 9 个"滑脱" seed 重跑：

| policy | 成功数 / 9 | 备注 |
|---|---|---|
| base v3 | **8/9** | 只有 seed 24 仍失败 |
| strong_grasp | **8/9** | seed 2 出现异常的 `object_height_max=0.961` |

相比修复前的 **0/9**，这是根本性改善。它说明之前归因为"接触物理/夹爪力"
的瓶颈实际上是 **GRASP 状态缺少 pose-hold 命令**。也解释了为什么
strong_grasp ablation 和子任务 sweeps 都显示同样失败：所有进入 GRASP 后
发生微小向下漂移的 seed 都会让手指错过物体。

完整 50-seed 官方 dex_cube 随机化矩阵（seeds 0–49）在修复后跑完：

| 指标 | 数值 |
|---|---|
| 总 seed 数 | 50 |
| 成功 seed 数 | **44** |
| 总体成功率 | **0.88** |
| 平均 progress | 0.720 |
| 失败 seed | 7, 15, 24, 28, 37, 48 |

这相比修复前的 **24/50 (48%)** 是巨大提升。剩余 6 个失败中 5 个是**接近碰撞**
（object 初始 yaw 在 +0.10 ~ +0.25 rad 附近），1 个（seed 24）是 grasp 对齐
误差系统性偏大。

### 反思

1. **不要轻易归因到物理/接触参数**：当出现"夹住但滑脱"的迹像时，先检查
   动作命令是否真正让机械臂保持静止。绝对模式控制器对零 action 的语义
   与相对模式完全不同。
2. **Trace 分析比调参更重要**：如果只看 aggregate metrics，会以为是 squeeze
   时间不够；只有看到 `eef_z` 在 GRASP 阶段下降，才能定位到 missing pose
   hold。
3. **状态机每个 phase 都要考虑绝对/相对模式差异**：HOLD/RELEASE 已经做了
   pose-hold，但 GRASP 遗漏了。今后任何新增 phase 都要检查零 action 的
   语义。

### 下一步

- 官方 dex_cube 在随机 placement 下已达到 **88% 成功率**；剩余 12% 主要是
  接近碰撞，可考虑优化 approach 路径或预抓取定向。
- 用修复后的 policy 重新跑 target-yaw 5×10 矩阵，验证跨朝向泛化。
- 继续把 `franka_ik_abs` 作为本地 workaround 的免责声明写进报告。
- Procedural fallback 仍未解决，下一步仍是与 Arena 团队澄清资产 fidelity。

## Update (2026-06-18)：target-yaw 矩阵重跑结果——小角度鲁棒，大角度在夹爪内打滑

用修复后的 policy 重新跑了 5×10 target-yaw 矩阵：

| target_yaw (rad) | lifted_rate | orientation_achieved_rate | env_success_rate |
|---|---:|---:|---:|
| 0.0000 | 0.90 | 0.90 | 0.90 |
| 0.5236 | 0.90 | 0.20 | 0.90 |
| 0.7854 | 0.90 | 0.20 | 0.90 |
| 1.0472 | 0.80 | 0.20 | 0.80 |
| 1.5708 | 0.30 | 0.10 | 0.30 |

- **小角度（≈0 rad）非常鲁棒**：9/10 seed 同时达成 lift 和 orientation。
- **大角度时物体在夹爪内旋转**：trace 显示 gripper 的 `desired_eef_yaw`
  准确跟踪了 override，但物体相对于手指发生了转动（如 seed 0、target=0.5236
  时 object_yaw 漂到 -2.6 rad）。这说明不是 yaw authority 问题，而是
  **夹取接触不足以支撑大角度旋转**。
- **π/2 override 表现差于环境默认 π/2**：placement 矩阵（环境默认目标）
  达到 88% 成功，而 override π/2 只有 30%。原因是 override 构造的是纯世界 yaw
  四元数，经过 base-frame 转换后的姿态可能与 Arena 原生命令的 roll/pitch
  组合不同，导致夹爪需要以更易打滑的姿态去转动物体。

### 反思

1. **GRASP pose-hold 修复把瓶颈从“手臂漂移”转移到“夹爪内旋转”**：这是更真实的
   物理瓶颈，也解释了为什么之前 target-yaw 矩阵看起来“平坦”——手臂漂移
   在夹取阶段就破坏了所有种子，掩盖了后续的方向差异。
2. **纯 yaw override 不是完美的跨朝向 benchmark**：它只改变 policy 的目标
   四元数，没有改变环境 success metric 的构成。真正的跨朝向验证需要
   Arena 把 `target_yaw` 作为 task/environment 参数暴露。
3. **下一步不再是调 threshold/squeeze，而是改善夹取接触模型**：可能的
   方向包括增大夹爪闭合力度、增加接触摩擦、在旋转前做更稳定的预对准、
  或让 Arena 团队提供支持力控/力反馈的 embodiment。

### Approach-collision ablation 结果

对 50-seed 矩阵中剩余 5 个 approach-collision seed 做了快速消融：

| 干预 | 修复数 / 5 | 说明 |
|---|---|---|
| `approach_offset_z=0.25` | 0/5 | 不是高度问题。 |
| `pre_grasp_orient=true` | 0/5 | 在物体上方暂停对准并不能帮助到达。 |
| `align_yaw_during_approach`, `approach_yaw_offset=π` | 0/5 | 保持 gripper-object yaw 关系，但无法解锁 workspace，还导致 previously successful seeds 回归。 |
| `align_yaw_during_approach`, `approach_yaw_offset=π/2` | 3/5 | 在 3 个 seed 上到达 GRASP/LIFT，但破坏了最终对齐所需的 yaw 关系。 |

结论：剩余 12% 的 approach collision **不是参数问题**，而是 `franka_ik_abs`
默认复位姿态对桌子正 y 侧物体的可达 workspace 限制。要把成功率从 88% 再提升，
需要不同的接近路径/规划器、不同的初始机器人位姿，或 Arena 端改变
embodiment/workspace。我已经在 policy 里加了可选的 `align_yaw_during_approach`
和 `approach_yaw_offset` 参数，但默认关闭，仅供后续实验。

### 小目标朝向 50-seed 验证：去掉 π/2 旋转后天花板为 90%

为了区分 workspace 限制和 π/2 重朝向的影响，用 `target_yaw_override=0.0`
重新跑了完整的 50-seed 矩阵：

| 指标 | 数值 |
|---|---|
| 总 seed 数 | 50 |
| 成功 seed 数 | **45** |
| 总体成功率 | **0.90** |
| lifted_rate | 0.90 |
| orientation_achieved_rate | 0.90 |

唯一失败的仍是那 **5 个 approach-collision seed**（7、15、28、37、48）。
默认 π/2 矩阵中失败的 seed 24 在 target_yaw=0.0 时成功。这说明：

- 默认 88% 矩阵的 6 个失败 = **5 个 workspace 边界 + 1 个 π/2 旋转打滑**。
- 去掉大角度重朝向后，诚实天花板提升到 **90%**。
- 剩余 10% 不是 threshold/squeeze 问题，而是 embodiment workspace 限制。

### 下一步

- 官方 dex_cube 在随机 placement + 默认 π/2 目标下达到 **88% 成功率**；
  去掉 π/2 重朝向后可达 **90%**。
- 剩余 10% 是 `franka_ik_abs` 默认复位姿态对正 y 侧物体的 workspace 边界。
- 跨小角度朝向已验证；跨大角度朝向受限于夹爪内旋转，需要接触模型或
  embodiment 支持。
- 继续把 `franka_ik_abs` 作为本地 workaround 的免责声明写进报告。
- Procedural fallback 仍未解决，下一步仍是与 Arena 团队澄清资产 fidelity。


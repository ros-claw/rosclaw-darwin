# Darwin 后续实施大纲 v1.5 总实施报告

**日期：** 2026-06-18  
**对应计划：** `/code/rosclaw/rosclaw_darwin/darwin后续实施大纲v1_5.md`  
**总负责会话任务：** `#167 Generalize franka_ik_abs goal_pose policy across orientations and objects`

---

## 1. 执行摘要

`darwin后续实施大纲v1_5.md` 的核心目标是：在修复 **phase trace 不可靠**、**seed 不真正随机化** 两个 P0 基础设施缺陷后，用真实随机化条件重新验证官方 `dex_cube` 泛化边界，并对 procedural fallback 做 gate audit 与最小 object-aware adaptation，最终形成完整的 FailureToHint v3 闭环 demo。

本报告汇总了该计划的全部实施结果、代码改动、验证数据与诚实结论。

### 关键结果速览

| 交付物 | 状态 | 关键结果 |
|---|---|---|
| Phase 0：P0 基础设施修复 | ✅ 完成 | phase trace 已可靠；seed 经 `task.mutation.seed` → Docker env → 容器 step-0 扰动完整转发 |
| Phase 1：官方 dex_cube 泛化矩阵 | ✅ 完成 | 修复 GRASP pose-hold 后，默认 π/2 目标 50 seeds 达到 **44/50 (88%)**；去掉大角度重朝向后达 **45/50 (90%)** |
| Phase 2：Procedural fallback gate audit | ✅ 完成 | 5 seeds paired diff 完成；`DESCEND→GRASP` gate diagnostics 已可记录；根因为 **asset-fidelity-induced policy-object geometry/gate mismatch** |
| Phase 3：Object-aware procedural adaptation | ✅ 基础设施完成 | `ObjectGeometryAdapter` 扩展 mass/friction 感知；adaptive config 已创建；procedural 仍未 full success |
| Phase 4：FailureToHint v3 闭环 demo | ✅ 完成 | 脚本可运行；hint 把 procedural seed 的 `descend_exit_rate` 从 0 提升到 1（4/5），但物体仍未离地 |
| Phase 5：报告刷新 | ✅ 完成 | 4+ 份报告更新，新增 `DEX_CUBE_GOAL_POSE_GENERALIZATION_REPORT.md`，`INDEX.md` 已更新 |

---

## 2. 计划背景与目标

外部专家在审阅 v1.4 报告后指出，ROSClaw-Darwin 项目需要从“单任务成功 + fallback 失败”升级为证明 **official benchmark clean success + OOD asset-drift diagnosis + object-aware adaptive recovery**。

v1.5 大纲把下一阶段拆成 5 个阶段：

1. **Phase 0：修复 P0 基础设施 bug**（phase trace、seed randomization、子任务 embodiment 切到 `franka_ik_abs`）。
2. **Phase 1：官方 dex_cube 泛化矩阵验证**（真实随机化 seed、target-yaw 矩阵、报告）。
3. **Phase 2：Procedural fallback 的 gate audit**（paired diff、gate diagnostics、报告更新）。
4. **Phase 3：Object-aware procedural adaptation**（mass/friction 感知、adaptive gate、配置）。
5. **Phase 4：FailureToHintEngine v3 闭环 demo**（procedural OOD 上的 signature → hint → parameter_override → metric 链路）。
6. **Phase 5：报告与索引刷新**。

本报告逐条汇报实施情况。

---

## 3. Phase 0：P0 基础设施修复

### 3.1 修复 phase trace：清除 shadowed `_last_gate_diagnostics`

**问题：** `HeuristicServoGoalPosePolicy.__init__` 声明了 `self._last_gate_diagnostics`，遮蔽了父类属性；`reset()` 调用 `super().reset()` 只清除了父类属性，子类属性保留上一 episode 的 stale `DESCEND` dict，导致 trace 的 `phase` 被覆盖。

**改动：** 在 `HeuristicServoGoalPosePolicy.reset()` 中显式：

```python
self._last_gate_diagnostics = None
```

**影响：** trace 现在可以完整记录 `APPROACH → DESCEND → GRASP → LIFT → ALIGN → HOLD` 的真实序列。

### 3.2 修复 seed randomization：让 `task.mutation.seed` 真正影响初始条件

**问题：** 脚本设置了 `task.mutation.seed`，但 host adapter、Docker runner 和容器内 policy 都没有消费它，所有 seed 产生完全相同的初始条件。

**修复链路：**

| 位置 | 改动 |
|---|---|
| `rosclaw_darwin/adapters/arena.py::_make_args()` | 从 `task.mutation.seed` 读取 seed，传入 Arena 参数 |
| `ArenaAdapter.run_policy()` | 把 `seed` / `placement_seed` 写入 Docker job dict |
| `ArenaRunner._run_docker()` | 注入 `-e ROSCLAW_ARENA_SEED` 和 `-e ROSCLAW_ARENA_PLACEMENT_SEED` |
| `run_eval.py`（容器内） | 读取 env var，在 step 0 对 object root state 做可控相对扰动（xy ±0.03 m、yaw ±30°、零速度） |

**验证：** `--seed 0` 与 `--seed 1` 的 `object_x_initial`、`object_y_initial`、`object_yaw_initial` 现在出现可观测差异。

### 3.3 子任务 embodiment 切到 `franka_ik_abs`

检查了 `configs/tasks/goal_pose_lift_*.yaml`，embodiment 已经是 `franka_ik_abs`，无需改动。

---

## 4. Phase 1：官方 dex_cube 泛化矩阵验证

### 4.1 新增/复用脚本

- `scripts/diagnostics/run_dex_cube_generalization_matrix.py`：50 seeds 官方资产顺序矩阵，支持 `--cleanup` 避免 GPU/容器争用。
- `scripts/diagnostics/run_target_yaw_generalization_matrix.py`：5 目标 yaw × 10 seeds 朝向泛化矩阵。

### 4.2 30-seed 随机化矩阵（修复前）

| 指标 | 数值 |
|---|---:|
| seeds | 0–29 |
| success | 18/30 |
| 成功率 | **0.60** |
| 失败模式 | 3 个 approach collision + 9 个 grasp slip after LIFT |

这是修复 seed 和 phase trace 后的第一次真实随机化结果，证明了之前的固定-seed 20/20 是过度乐观的。

### 4.3 50-seed 随机化矩阵（GRASP pose-hold 修复前）

| 指标 | 数值 |
|---|---:|
| seeds | 0–49 |
| success | 24/50 |
| 成功率 | **0.48** |

说明样本扩大后更难，policy 对困难初始 pose 更脆弱。

### 4.4 GRASP pose-hold 修复

**发现：** 在 `GRASP` 阶段，policy 只写了 gripper 命令，arm 命令为零；在 `franka_ik_abs` 绝对模式下，零 pose 命令被解释为“回到原点”，导致手指闭合时手臂向下漂移，错过物体。这就是之前被误判为“grasp slip after LIFT”的根本原因。

**改动：** 在 `HeuristicServoGoalPosePolicy.GRASP`（以及 `HeuristicServoLiftPolicy.GRASP`）中为绝对模式显式保持当前 eef pose：

```python
if not self._relative_mode and eef_pos is not None:
    self._apply_position(action, eef_pos, eef_quat, eef_pos)
```

### 4.5 50-seed 随机化矩阵（GRASP pose-hold 修复后）

| 指标 | 数值 |
|---|---:|
| seeds | 0–49 |
| success | **44/50** |
| 成功率 | **0.88** |
| 平均 progress | 0.720 |
| 失败 seed | 7, 15, 24, 28, 37, 48 |

- 5 个失败是 **approach collision**（正 y 侧 workspace 边界）。
- 1 个失败（seed 24）是 **π/2 重朝向打滑**。

### 4.6 target-yaw 泛化矩阵（修复后）

由于 Arena `cube_goal_pose` 环境把 `target_yaw` 硬编码为 π/2，policy 增加了可选的 `target_yaw_override`，构造纯世界 yaw 四元数覆盖环境目标，并自定义 `orientation_achieved` 指标（lifted 状态下 yaw error < 0.5 rad）。

| target_yaw (rad) | lifted_rate | orientation_achieved_rate | env_success_rate |
|---|---:|---:|---:|
| 0.0000 | 0.90 | 0.90 | 0.90 |
| 0.5236 | 0.90 | 0.20 | 0.90 |
| 0.7854 | 0.90 | 0.20 | 0.90 |
| 1.0472 | 0.80 | 0.20 | 0.80 |
| 1.5708 | 0.30 | 0.10 | 0.30 |

**结论：**
- 小角度重朝向非常鲁棒。
- 大角度时物体在夹爪内旋转打滑，不是 yaw authority 问题，而是 **夹取接触不足以支撑大角度旋转**。
- π/2 override 比环境默认 π/2 差，因为纯世界 yaw 经 base-frame 转换后的 roll/pitch 组合不同。

### 4.7 approach-collision 消融

对 5 个 approach-collision seed 做了 4 组快速消融：

| 干预 | 修复数 / 5 | 说明 |
|---|---|---|
| `approach_offset_z=0.25` | 0/5 | 不是高度问题 |
| `pre_grasp_orient=true` | 0/5 | 悬停对准无助于 reach |
| `align_yaw_during_approach`, `approach_yaw_offset=π` | 0/5 | 保持 gripper-object yaw 关系，但不解锁 workspace，还回归了原本成功的 seed |
| `align_yaw_during_approach`, `approach_yaw_offset=π/2` | 3/5 | 3 个 seed 到达 GRASP/LIFT，但破坏了最终对齐所需的 yaw 关系 |

**结论：** 剩余 12% 的 approach collision 是 **workspace/kinematic 边界**，不是 policy 参数问题。`franka_ik_abs` 默认复位姿态对桌子正 y 侧物体可达性不足。

### 4.8 小目标朝向 50-seed 验证（`target_yaw_override=0.0`）

为了区分 workspace 限制和 π/2 重朝向影响，用 `target_yaw_override=0.0` 跑完整 50 seeds：

| 指标 | 数值 |
|---|---:|
| total seeds | 50 |
| success | **45/50** |
| 成功率 | **0.90** |
| lifted_rate | 0.90 |
| orientation_achieved_rate | 0.90 |

唯一失败仍是那 5 个 approach-collision seed；seed 24 在去掉 π/2 重朝向后成功。

**核心结论：**
- 默认 88% 矩阵 = **5 workspace 失败 + 1 π/2 旋转打滑**。
- 去掉大角度重朝向后，诚实天花板提升到 **90%**。
- 剩余 10% 需要 approach 路径/规划器、初始机器人位姿或 Arena-side workspace 改动才能继续突破。

---

## 5. Phase 2：Procedural fallback 的 gate audit

### 5.1 用真实随机化 seed 重跑 paired trace diff

```bash
python scripts/diagnostics/run_dex_vs_procedural_paired_trace.py \
  --dex-task configs/tasks/goal_pose_dex_cube_official.yaml \
  --procedural-task configs/tasks/goal_pose_procedural_cube_ood.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3.yaml \
  --seeds 0 1 2 3 4 --cleanup
```

### 5.2 结果

| metric | dex_cube | procedural_cube | Δ |
|---|---:|---:|---:|
| success_rate | **5/5** | 0/5 | +1.0 |
| min_grasp_z_error (mean) | 0.00351 m | 0.00906 m | +0.00555 m |
| min_grasp_dist_error (mean) | 0.00441 m | 0.00915 m | +0.00474 m |
| object_z_max (mean) | **0.543 m** | 0.200 m | +0.343 m |
| object_z_final (mean) | 0.396 m | 0.047 m | +0.349 m |

### 5.3 Gate diagnostics

`HeuristicServoGoalPosePolicy` 在 `DESCEND` 阶段记录 gate diagnostics：

- `grasp_dist_error`
- `grasp_z_error`
- `condition_dist_ok`
- `condition_z_ok`
- `transition_allowed`
- `transition_blocking_reason`

容器内 `run_eval.py` 聚合 `descend_exit_rate`、`grasp_phase_reached_rate`、`dominant_blocking_reason_distribution`。

### 5.4 根因结论

procedural fallback 的失败 **不是简单的 threshold 问题**，而是 **asset-fidelity-induced policy-object geometry/gate mismatch**。可能来源包括 object frame/origin、settle pose、bbox metadata、grasp target computation、gate thresholds、inertia/contact material 或未暴露的 USD/runtime override。几何适配按尺寸正确缩放后仍无法 lift，说明 mismatch 在更深的 asset/物理层。

---

## 6. Phase 3：Object-aware procedural adaptation

### 6.1 扩展 `ObjectGeometryAdapter`

在 `ObjectGeometry` 中增加可选字段：

- `mass: float | None`
- `static_friction: float | None`

`ObjectGeometryAdapter.adapt()` 新增两条规则：

- **重物体**（`mass > 0.15 kg`）：按质量余量增加 `min_grasp_steps`，`gripper_close_threshold` 收紧 15%。
- **低摩擦**（`static_friction < 0.35`）：`min_grasp_steps + 5`，`gripper_close_threshold` 收紧 15%。

容器端 fallback 和 `run_eval.py` 读取 `spawn.mass_props.mass` / `spawn.physics_material.static_friction`（以及 `obj.data` 兜底）。dex_cube 不暴露这些字段，因此 non-regression。

### 6.2 新增配置

- `configs/policies/heuristic_servo_goal_pose_v3_adaptive.yaml`：更宽松的 gate 参数 + geometry adaptation。
- `configs/tasks/goal_pose_procedural_cube_adaptive.yaml`：procedural adaptive 诊断任务。
- `configs/tasks/goal_pose_procedural_cube_large_ood.yaml`：0.10 m 大立方体 OOD 诊断任务。

### 6.3 大立方体 OOD 结果

对 0.10 m procedural cube（几何适配已正确放大阈值）：

| metric | value |
|---|---:|
| success_rate | 0.0 |
| failure_type | object_not_lifted |
| object_z_max | 0.200 m |

阈值缩放正确，但物体仍无法 lift，进一步确认 mismatch 在 asset/物理层。

---

## 7. Phase 4：FailureToHintEngine v3 闭环 demo

### 7.1 新增脚本

`scripts/diagnostics/run_failure_to_hint_procedural_loop.py`：

1. Loop 1：用 base v3 policy 跑 procedural cube seed，提取 failure signature（如 `object_not_lifted` + `descend_gate_blocked`）。
2. 调用 `FailureToHintEngine.suggest_from_signatures()` 生成 hints 和 parameter overrides。
3. Loop 2：把 hints 注入 policy config，重跑同一 seed。
4. 比较 `success`、`object_lifted`、`progress`。

### 7.2 运行结果

- 基础 policy 5/5 seed 全部失败：`success_rate=0.0`，`descend_exit_rate=0.0`。
- signature 触发 `object_not_lifted_after_grasp_recipe`，生成 hints：`lower_grasp_height`、`longer_squeeze`、`grasp_adjust`。
- 第一次 hinted run 全部报错，因为 recipe 参数 `squeeze_steps` 与 policy key `grasp_squeeze_steps` 名称不一致。
- **修复：** 脚本中增加 `_RECIPE_PARAM_MAP`：
  ```python
  {"squeeze_steps": "grasp_squeeze_steps"}
  ```
- 修复后 **4/5 seed** 的 hinted run 成功通过 DESCEND gate，`descend_exit_rate` 从 0.0 提升到 1.0，进入 GRASP/LIFT phase；但物体仍未离地（`object_height_max` 仍为 0.2 m）。
- seed 4 仍卡在 DESCEND，且出现物体穿地异常（`object_height_delta` ≈ -4081）。

### 7.3 结论

FailureToHint v3 链路已打通，adaptive hints 能改善 gate 进度，但 procedural fallback 的根因是 asset geometry/origin 不匹配和物理不稳定性，不是 threshold / squeeze 参数能完全解决的。

---

## 8. 关键代码改动清单

| 文件 | 改动内容 |
|---|---|
| `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py` | 修复 `reset()` shadow 变量；GRASP pose-hold；`target_yaw_override`；`align_yaw_during_approach` / `approach_yaw_offset`；adapter 集成 |
| `rosclaw_darwin/evaluation/arena_docker_deps/run_eval.py` | 读取 seed env vars 并扰动 object pose；捕获场景几何；asset resolution；gate diagnostics 聚合 |
| `rosclaw_darwin/adapters/arena.py` | `_make_args()` 读取 `task.mutation.seed`；forward seed / geometry 到 Docker job |
| `rosclaw_darwin/evaluation/arena_runner.py` | `_run_docker()` 注入 `ROSCLAW_ARENA_SEED` / `ROSCLAW_ARENA_PLACEMENT_SEED` |
| `rosclaw_darwin/evaluation/object_geometry.py` | `ObjectGeometry` 可选 mass/friction；adapter 重/低摩擦规则；参考值匹配 proven abs policy |
| `rosclaw_darwin/evaluation/asset_resolution.py` | 官方 vs fallback 资产检测；`leaderboard_excluded`；`benchmark_validity` |
| `configs/policies/heuristic_servo_goal_pose_v3.yaml` | abs + geometry adaptation + verify_object_following |
| `configs/policies/heuristic_servo_goal_pose_v3_strong_grasp.yaml` | 更强 squeeze ablation |
| `configs/policies/heuristic_servo_goal_pose_v3_adaptive.yaml` | 更宽松 gate + adaptation |
| `configs/tasks/goal_pose_dex_cube_official.yaml` | 要求官方资产 |
| `configs/tasks/goal_pose_procedural_cube_ood.yaml` | 允许 fallback，标记诊断 |
| `configs/tasks/goal_pose_procedural_cube_adaptive.yaml` | procedural adaptive 诊断任务 |
| `configs/tasks/goal_pose_procedural_cube_large_ood.yaml` | 0.10 m OOD 诊断任务 |
| `scripts/diagnostics/run_dex_cube_generalization_matrix.py` | 官方资产泛化矩阵；`--cleanup`；`--policy-overrides` |
| `scripts/diagnostics/run_target_yaw_generalization_matrix.py` | 5×10 目标 yaw 矩阵；自定义 `orientation_achieved` |
| `scripts/diagnostics/run_dex_vs_procedural_paired_trace.py` | paired trace diff |
| `scripts/diagnostics/run_failure_to_hint_procedural_loop.py` | FailureToHint v3 闭环 demo；recipe 参数名映射 |
| `tests/unit/test_object_geometry.py` | adapter 行为单元测试 |
| `memory/goal-pose-geometry-adapter-reference-tuning.md` | 项目记忆：adapter 参考值必须从 proven policy 来 |
| `memory/arena-seed-forwarding-through-docker.md` | 项目记忆：seed 转发链路 |

---

## 9. 验证与质量检查

```bash
ruff check rosclaw_darwin tests scripts/diagnostics
pytest tests/unit -q
```

- **ruff**：通过。
- **pytest tests/unit**：**145 passed**。

关键单元测试：

- `tests/unit/test_object_geometry.py`：adapter 缩放、mass/friction 规则、clamp、config/scene 解析。
- `tests/unit/test_failure_to_hint.py` / `test_failure_signature_to_hint_rules.py`：FailureToHint v3 基础设施。

---

## 10. 诚实结论

### 10.1 已解决的问题

1. **Phase trace 不可靠** → 已修复，trace 现在能记录完整 phase 序列。
2. **Seed 不真正随机化** → 已修复，host → Docker → 容器完整转发，初始条件随 seed 变化。
3. **官方 dex_cube 在固定 seed 下成功** → 已确认；在真实随机化 + GRASP pose-hold 修复后达到 **88%**。
4. **跨 target-yaw 能力** → 已验证：小角度非常鲁棒，大角度受限于夹爪内旋转打滑。
5. **ObjectGeometryAdapter 参考值** → 已校准到 proven abs policy，dex_cube non-regression。
6. **Asset fidelity 分离** → 官方结果与 fallback 诊断已用 `leaderboard_excluded` 和 `benchmark_validity` 分离。
7. **FailureToHint v3 闭环链路** → 已打通，能改善 procedural gate 进度。

### 10.2 仍未解决的问题

1. **Procedural fallback 仍未 lift**：即使几何适配、mass/friction 感知、adaptive gate、FailureToHint hints 都加上，物体仍未离地。根因是 asset-fidelity-induced policy-object geometry/gate mismatch，需要 Arena 团队澄清资产/物理差异。
2. **官方 dex_cube 默认 π/2 目标不是 100%**：88% 是 honest ceiling；剩余 12% 中 10% 是 workspace 边界、2% 是 π/2 重朝向打滑。
3. **跨大角度朝向受限**：大角度重朝向时物体在夹爪内打滑，需要更强的接触模型、力控或预对准策略。
4. **`franka_ik_abs` 仍是本地 patched embodiment**：不是官方 leaderboard embodiment，未来 Arena 更新 controller 后需重新验证。
5. **并发 Arena Docker 评估仍不稳定**：已用 `--cleanup` + 严格串行缓解，但大规模并发仍是 open issue。

### 10.3 当前最准确的项目结论

> **在官方 `dex_cube` + `franka_ik_abs` + v3 policy 路径上，`goal_pose` 已达到 88% 成功率（默认 π/2 目标）和 90% 成功率（去掉大角度重朝向后）。剩余失败主要来自 embodiment workspace 边界和夹爪内大角度旋转打滑。procedural fallback 仍是独立的 asset-fidelity 阻塞问题，尚未解决。**

---

## 11. 下一步建议

1. **推进 Arena issue tracker**：把 procedural fallback、franka_ik_abs workspace、target_yaw task 参数三个问题正式提给 Arena 团队。
2. **继续突破官方 dex_cube ceiling**：
   - 尝试不同的 approach 路径或预抓取位姿；
   - 尝试调整初始机器人位姿以解锁正 y 侧 workspace；
   - 探索力控/力反馈 embodiment 以解决夹爪内旋转打滑。
3. **把 ObjectGeometryAdapter 从 non-regression 推进到真正的跨对象验证**：在官方提供的其他 block 资产上跑矩阵。
4. **FailureToHint v3 的 metric 闭环**：把 `descend_exit_rate` / `object_lifted_rate` 提升作为明确的 adaptation 目标，即使还不是 full success。
5. **扩大样本量**：在基础设施稳定后跑 100-seed 官方矩阵，进一步收紧 success rate 的置信区间。

---

## 12. 相关报告索引

| 报告 | 内容 |
|---|---|
| `reports/DEX_CUBE_GOAL_POSE_GENERALIZATION_REPORT.md` | 官方 dex_cube 随机化矩阵完整结果 |
| `reports/POLICY_V3_INTERVENTION_REPORT.md` | v3 policy 设计、GRASP pose-hold 修复、ablation |
| `reports/GOAL_POSE_OBJECT_GEOMETRY_ADAPTATION_REPORT.md` | ObjectGeometryAdapter 设计与 paired diff |
| `reports/FINAL_ASSET_FIDELITY_REPORT.md` | 官方资产与 fallback 分离 |
| `reports/FINAL_GOAL_POSE_DIAGNOSIS_AND_EVOLUTION_REPORT.md` | 12 问答案与演进路线 |
| `reports/IMPLEMENTATION_THOUGHTS_AND_STATUS_REPORT.md` | 第一人称实施记录与反思 |
| `reports/ARENA_ISSUE_TRACKER.md` | 向 Arena 团队提出的问题清单 |

---

*本报告由 Claude Code 根据 `darwin后续实施大纲v1_5.md` 的实施过程汇总生成，旨在为外部专家和项目团队提供一份完整、诚实的 v1.5 阶段总结。*

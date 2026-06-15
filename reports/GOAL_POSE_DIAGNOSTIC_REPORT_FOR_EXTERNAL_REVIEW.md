# Goal Pose 抓取稳定性：深度诊断与实施报告（供外部专家审阅）

## 1. 背景与本轮目标

ROSClaw-Darwin 当前在真实 IsaacLab-Arena Docker 中的状态：

| Task | 当前 success_rate | 状态 |
|---|---|---|
| `lift_object` | ~0.38（auto hints 有正向趋势，但不显著） | 需要更大样本验证 |
| `pick_object` | **1.0000** | 已解决（success metric 与任务定义对齐） |
| `goal_pose` | **0.0000** | 仍是主要瓶颈 |

本轮目标是：对 `goal_pose_001` 做一次**单 episode 的逐帧 trace 诊断**，定位 cube 被 lift 后为什么还会掉落，并给出完整的实施报告供外部专家分析。

---

## 2. 实验设置

### 2.1 任务与环境

- ROSClaw task: `configs/tasks/goal_pose.yaml`
- Arena environment: `cube_goal_pose`
- Object: `dex_cube`（在本地 Docker 中 fallback 为 procedural cube）
- Robot: `franka_ik`
- Success 条件（来自 `GoalPoseTask`）：
  - `object_z` 进入 `[0.2, 1.0]`
  - 物体 yaw 与目标 yaw（90°）误差 `< 0.2 rad`

### 2.2 Policy

- Policy class: `HeuristicServoGoalPosePolicy`
- 关键参数：
  - `kp = 3.0`
  - `grasp_dist_threshold = 0.04`
  - `gripper_close_threshold = 0.012`（manual hints 后变为 `0.0096`）
  - `min_grasp_steps = 30`，`grasp_squeeze_steps = 15`（manual hints 后 +5/+10）
  - `max_lift_delta_z = 0.08`
  - `pre_grasp_orient = true`（manual hints 触发）
  - `reorient_before_align = true`（manual hints 触发）
  - `grasp_target_yaw_offset = π/2`

### 2.3 Manual hints

```text
orientation_aware_grasp
two_stage_reorientation
lower_lift_acceleration
stabilize_lift
longer_gripper_close
```

### 2.4 Trace 采集方式

为了把容器内的逐帧 trace 持久化到宿主机，做了以下改动：

- `rosclaw_darwin/evaluation/arena_runner.py`：Docker run 增加 bind mount
  `-v /tmp/rosclaw_data/traces:/workspace/data/traces`
- `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`：
  - trace 路径改为 `/workspace/data/traces/episode_trace.jsonl`
  - goal_pose trace 增加 `object_yaw`、`target_yaw`、`orientation_error`
- 新增脚本：`scripts/diagnostics/run_goal_pose_trace.py`

运行命令：

```bash
export ROSCLAW_ARENA_MODE=docker
export PYTHONPATH=/code/rosclaw/rosclaw_darwin/rosclaw-darwin:$PYTHONPATH
python scripts/diagnostics/run_goal_pose_trace.py
```

原始 trace 文件：

```text
/tmp/rosclaw_data/traces/goal_pose_trace_1781508868.jsonl
```

共 **2500 steps**，每步包含：

```json
{
  "episode", "step",
  "eef_x", "eef_y", "eef_z",
  "object_x", "object_y", "object_z",
  "target_x", "target_y", "target_z",
  "gripper_pos", "action_norm", "phase",
  "object_yaw", "target_yaw", "orientation_error"
}
```

---

## 3. 关键时间线

| step | phase 转移 | eef_z | object_z | gripper_pos | orientation_error | 说明 |
|---|---:|---:|---:|---:|---:|---|
| 0 | APPROACH | 0.245 | 0.200 | 0.0400 | 1.571 | 初始 object 在空中，随后落到桌面 (~0.021) |
| 89 | → PRE_GRASP_ORIENT | 0.116 | 0.021 | 0.0400 | 1.571 | 到达 object 上方 |
| 119 | → DESCEND | 0.121 | 0.021 | 0.0400 | 1.571 | 预旋转 30 步后进入下降 |
| 231 | → GRASP | 0.026 | 0.021 | 0.0351 | 1.571 | 到达抓取高度，开始合拢 |
| 306 | → LIFT | 0.044 | 0.030 | **0.0240** | 1.475 | 合拢 75 步后开始提升 |
| 352 | → REORIENT | 0.272 | 0.258 | 0.0240 | 1.468 | 升到安全高度，开始旋转 |
| 545 | (REORIENT peak) | ~0.31 | **0.379** | 0.0238 | — | object 达到最高点 |
| 753 | → HOLD | 0.310 | 0.304 | 0.0238 | 1.130 | 方向大致对齐，进入保持 |
| 1216 | (HOLD) | — | **0.050** | 0.0238 | — | object 从高点跌落，低于桌面 |
| 2500 | end | — | **-0.215** | 0.0238 | 1.938 | object 已掉到地面以下 |

---

## 4. 核心发现

### 4.1 gripper 无法闭合到设定阈值

Manual hints 把 `gripper_close_threshold` 从 `0.012` 降到 `0.0096`，但实际运行中：

| phase | gripper_pos 最小值 | 平均值 |
|---|---:|---:|
| GRASP | 0.0240 | 0.0255 |
| LIFT | 0.0240 | 0.0240 |
| REORIENT | 0.0238 | 0.0238 |
| HOLD | 0.0238 | 0.0238 |

**gripper 从未低于 0.0238**。这说明：

- 要么 gripper 被 cube 几何卡住，闭合极限就是 ~0.024；
- 要么 controller 没有输出足够的闭合力/位置；
- 当前把 "抓取成功" 判定为 `gripper_pos < 0.0096` 是不现实的。

由于闭合度不够，cube 在提升/旋转过程中被重力拉脱。

### 4.2 object 被提到 0.38m，但随后掉落

- object 最高点 `z = 0.379`（step 545，REORIENT 阶段）。
- 之后缓慢下滑，到 step 1216 时 `z < 0.05`，最终 `z = -0.215`。
- 下落发生在 **HOLD 阶段**，此时 eef 仍在 target 附近，但 cube 已从 gripper 中滑出。

### 4.3 预旋转没有真正改变 gripper yaw

- PRE_GRASP_ORIENT 阶段（step 89–119）的 `orientation_error` 始终 ≈ 1.571 rad（90°）。
- 说明 gripper 的 yaw 没有实际响应 `action[..., 5]` 的旋转指令。
- 因此手指仍以初始方向接触 cube，很可能是“夹住棱角”而不是“夹住平面”，进一步降低稳定性。

### 4.4 REORIENT 阶段 orientation_error 有改善，但为时已晚

- REORIENT 结束时（step 753）`orientation_error` 降至 1.130 rad。
- 但 cube 随后掉落，最终 orientation_error 反而增大到 1.938 rad（cube 自由翻滚）。

---

## 5. 根因假设（按可能性排序）

### 假设 1：gripper-cube 接触力不足（最可能）

- gripper 被 cube 几何限制在 ~0.024 的开度；
- 该开度下手指与 cube 之间的正压力/摩擦力不足以支撑 cube 重量；
- 提升或旋转时的惯性/重力使 cube 滑脱。

### 假设 2：yaw 控制通道无响应或方向错误

- PRE_GRASP_ORIENT 阶段发出 yaw 指令但 orientation_error 不变；
- 可能 relative-mode 下 `action[..., 5]` 并不控制 gripper yaw，或缩放/阻尼使其无效；
- 手指始终以对角/棱角接触 cube，接触不稳定。

### 假设 3：lift 过程中存在未补偿的 xy 扰动

- LIFT/REORIENT 阶段 `lift_horizontal_scale = 0.0`，策略只命令垂直运动；
- 但 eef-object 水平距离在 LIFT/REORIENT 阶段保持在 ~0.019，说明 eef 并没有明显拖拽 object；
- 因此 xy 扰动不是主因。

### 假设 4：object 初始位置 / 摩擦参数不利

- object 在 step 0 时 z=0.2，但 physics settle 后落到 z≈0.021；
- 如果 procedural cube 的摩擦系数被设得很低，也可能导致滑脱；
- 但 `lift_object` 任务中同一 gripper 能稳定抓起 cube 并提升，说明摩擦不是唯一问题；
- 差异可能在于 `goal_pose` 需要**保持抓取的同时旋转**，对力 closure 要求更高。

---

## 6. 已经尝试过的方法

| 方法 | 结果 |
|---|---|
| 增加 squeeze 时间（30→35 step + 15→25 step） | gripper 仍停在 0.024，未进一步闭合 |
| 降低 lift 加速度（cap 0.08 m/步） | object 能被提到 0.38m，但仍掉落 |
| 两阶段 reorientation | orientation_error 改善到 1.13 rad，但 cube 随后掉落 |
| pre-grasp 旋转 | orientation_error 未改善，yaw 控制疑似无效 |
| stabilize_lift / reduce_xy_motion | horizontal 运动已被抑制，不是主因 |

---

## 7. 需要外部专家帮助的问题

### 7.1 关于 gripper / object 接触

1. 在 IsaacLab-Arena 的 `franka_ik` embodiment 中，gripper 的 `joint_pos` 读数（最后两个 finger joints）的物理含义是什么？
   - 0.04 = 完全张开？
   - 0.0 = 完全闭合？
   - 0.024 是否已经是被 cube 阻挡后的机械极限？
2. `dex_cube` fallback 为 procedural cube 后，其尺寸、质量、摩擦系数与真实 dex_cube 是否一致？
3. 是否有推荐的 `gripper_close_threshold` 或抓取成功判定标准（例如 `gripper_pos < 0.025` 且持续多步）？
4. Franka gripper 的闭合是否受 force/torque limit 限制？如何在 IsaacLab-Arena 中提高 gripper 的闭合力？

### 7.2 关于相对模式 yaw 控制

1. `franka_ik` 在 relative mode 下，`action[..., 5]` 是否对应 gripper 的 yaw 旋转？
2. 如果 `action[..., 5]` 无效，应该使用哪个轴或哪种方式控制末端执行器的 yaw？
3. 在 `cube_goal_pose` 环境中，有没有已知能稳定完成任务的 teleop / heuristic / learned policy 示例？

### 7.3 关于 grasp 策略

1. 对于当前 object 初始 pose（z≈0.021，yaw=0）和目标 pose（z≈0.3，yaw=90°），推荐采用哪种 grasp 策略？
   - top-down pinch？
   - side grasp 后 lift + rotate？
   - 双阶段：先 lift 到安全高度，再 rotate？
2. 是否需要调整 object 的初始 pose 或 success tolerance，使其更适合当前 gripper？

---

## 8. 代码与数据清单

### 8.1 本轮新增/修改文件

| 文件 | 说明 |
|---|---|
| `rosclaw_darwin/evaluation/arena_runner.py` | Docker 增加 `/tmp/rosclaw_data/traces` bind mount |
| `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py` | trace 路径改到 `/workspace/data/traces`；goal_pose trace 增加 orientation 字段；新增 `PRE_GRASP_ORIENT` / `REORIENT` 状态 |
| `rosclaw_darwin/adapters/arena.py` | 把 `success_conditions` 传入 Arena job（用于 pick_object 指标对齐） |
| `rosclaw_darwin/evaluation/arena_docker_deps/run_eval.py` | task-aware success 判定 |
| `configs/policies/heuristic_servo_goal_pose.yaml` | v2 默认参数 |
| `scripts/diagnostics/run_goal_pose_trace.py` | 单 episode trace 采集脚本 |
| `reports/PICK_OBJECT_SUCCESS_GAP_REPORT.md` | pick_object 已解决 |
| `reports/GOAL_POSE_GRASP_STABILITY_REPORT.md` | goal_pose v2 结果 |
| `reports/GOAL_POSE_SKILL_HINT_ABLATION_REPORT.md` | v2 ablation 结果 |
| `reports/CROSS_TASK_TRANSFER_SUMMARY_REPORT.md` | 更新 transfer level |
| `reports/FINAL_EVOLUTION_BENCHMARK_STATUS_REPORT.md` | 最终状态 |

### 8.2 数据文件

```text
/tmp/rosclaw_data/traces/goal_pose_trace_1781508868.jsonl
```

共 2500 steps，可直接用于逐帧分析。

### 8.3 验证状态

```bash
ruff check rosclaw_darwin tests          # passed
pytest tests/unit tests/integration -q   # 145 passed
```

---

## 9. 结论与下一步建议

### 9.1 结论

- `goal_pose` 的 `success_rate = 0` 不是因为 policy 没接近目标，而是因为 **cube 在提升/旋转过程中从 gripper 滑脱**。
- 滑脱的直接原因是 **gripper 无法闭合到足够小的开度**（实际最小 ~0.024，策略期望 <0.0096）。
- 预旋转 gripper 以夹住 cube 平面的尝试**没有生效**，yaw 控制通道疑似无效或被阻尼抵消。
- 按实施指南 v1.2 的标准，本轮已达到 **“progress 提升、掉落减少”** 的最低要求；但要达到 **success_rate > 0**，需要解决 gripper 闭合/摩擦或 yaw 控制的根本问题。

### 9.2 下一步建议

1. **优先确认 gripper 闭合极限**：
   - 在空场景中命令 gripper 完全闭合，记录 `gripper_pos` 能达到的最小值；
   - 在 cube 存在时记录最小值；
   - 确认 0.024 是机械/碰撞极限还是 controller 输出限制。
2. **验证 yaw 控制通道**：
   - 在空场景中命令不同幅值的 `action[..., 5]`，观察 eef yaw 是否变化；
   - 确认 relative mode 下 yaw 对应的轴索引和缩放。
3. **测试更高摩擦或更小 cube**：
   - 如果可修改 procedural cube 的物理属性，临时提高摩擦系数，验证是否成功；
   - 这能帮助区分是摩擦问题还是几何问题。
4. **求助外部专家**：
   - 将本报告、trace 文件、以及上述问题提交给 IsaacLab-Arena 维护者或仿真专家；
   - 重点询问：推荐 gripper 参数、已知稳定 grasp 示例、relative mode yaw 控制正确用法。

---

## 10. 对外可 Claim / 不可 Claim

**可以 claim：**

```text
ROSClaw-Darwin has implemented a task-aware success metric, a failure-signature-driven
hint pipeline, and a phase-based servo policy for goal_pose.  Detailed per-step tracing
shows the policy can lift the cube to 0.38 m, but the cube slips because the gripper
cannot close tighter than ~0.024 m and the yaw controller does not effectively reorient
the fingers to stable grasp faces.
```

**不可以 claim：**

```text
ROSClaw-Darwin has solved goal_pose.
The grasp-stability hints are validated transferable skills.
Universal cross-task skill transfer is proven.
```

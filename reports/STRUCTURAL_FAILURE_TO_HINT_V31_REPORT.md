# Structural FailureToHint v3.1 实施报告

**日期：** 2026-06-19

**目标：** 把 FailureToHint 从 parameter-only 升级到 structural strategy switch，支持 regrasp / contact verify / lift verify，为 procedural OOD 提供 object-aware adaptive recovery 基础设施。

---

## 1. 核心改动

### 1.1 Policy 状态机扩展

文件：`rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`

在 `HeuristicServoGoalPosePolicy` 中新增三个阶段：

- `CONTACT_VERIFY`：GRASP 结束后保持当前位姿，根据 gripper width 和 object/eef 相对运动推断 `contact_proxy`。
- `LIFT_VERIFY`：做一次短距离 guarded lift（+0.06 m），测量 `lift_response_z`。
- `REGRASP`：若 lift response 不足且未达最大尝试次数，打开 gripper，退到 approach 高度，按 `regrasp_xy_offsets` 横向偏移 grasp target，重新进入 `DESCEND`。

新增 trace 字段：

- `contact_proxy`
- `regrasp_attempt`
- `grasp_effective`
- `lift_response_z`

新增 policy 参数（`HeuristicServoGoalPosePolicyArgs`）：

```yaml
enable_regrasp: true
max_regrasp_attempts: 2
regrasp_xy_offsets:
  - [0.005, 0.0]
  - [-0.005, 0.0]
verify_lift_response_steps: 10
min_lift_response_z: 0.01
```

### 1.2 Contact proxy 分类器

`_classify_contact_proxy()` 根据 gripper aperture 和物体相对位移把接触分为四类：

| proxy | 判定依据 |
|---|---|
| `no_contact` | 闭合后 gripper width 仍 > 0.08 m |
| `pushed_away` | 闭合期间物体远离 gripper > 0.02 m |
| `likely_contact` | gripper 被 block 在 close threshold 以上，物体仍靠近 |
| `weak_contact_no_lift` | gripper 基本闭合，但物体未随动 |
| `unknown` | 信息不足 |

### 1.3 配置与规则

- 新建 `configs/policies/heuristic_servo_goal_pose_v3_regrasp.yaml`
- 新建 `configs/skills/failure_signature_to_hint_rules_v31.yaml`：
  - `weak_contact_no_lift_recipe`
  - `no_contact_after_grasp_recipe`
  - `object_pushed_away_recipe`
  - `unstable_grasp_structural_recipe`
  - `precision_alignment_structural_recipe`

这些 recipe 同时提供 `parameter_overrides`、`structural_overrides` 和 `strategy_switches`。

### 1.4 EvolutionRunner 合并 structural overrides

`rosclaw_darwin/evolution/runner.py` 在 loop 2 中：

- 合并 `parameter_overrides` 与 `structural_overrides` 到 `policy_config_dict`；
- 把 `strategy_switches` 写入 `policy_config_dict["strategy_switches"]`；
- 在 `_hint_source` metadata 中记录 `structural_overrides` 和 `strategy_switches`。

### 1.5 单元测试

- 在 `tests/unit/test_failure_signature_to_hint_rules.py` 新增 `test_select_hints_structural_overrides_and_strategy_switches`，验证 structural override 合并与 strategy switch 去重。
- `pytest tests/unit -q`：**164 passed**。

---

## 2. 验证

### 2.1 官方 dex_cube seed 0 smoke test

```bash
python scripts/diagnostics/run_goal_pose_trace.py \
  --task configs/tasks/goal_pose_dex_cube_official.yaml \
  --policy configs/policies/heuristic_servo_goal_pose_v3_regrasp.yaml \
  --seed 0
```

结果：

| 指标 | 数值 |
|---|---:|
| status | completed |
| success_rate | **1.0** |
| progress_mean | 0.7843 |
| object_height_max_mean | 0.5047 m |
| object_height_delta_mean | 0.2388 m |
| asset_info_official_asset | 1.0 |

结论：regrasp 状态机没有破坏官方 `dex_cube` 的成功路径。

### 2.2 单 seed 状态机追踪

在 seed 0 的 trace 中可以观察到 `GRASP → CONTACT_VERIFY → LIFT_VERIFY → VERIFY_OBJECT_FOLLOWING → ...` 的完整序列，contact proxy 被正确记录为 `likely_contact`，regrasp 未触发。

---

## 3. 诚实结论

1. **Structural FailureToHint v3.1 基础设施已打通**：policy 能消费 structural overrides / strategy switches，trace 能记录 contact proxy 和 lift response，runner 能合并 structural config。
2. **官方 dex_cube 上 regrasp 不造成回归**：seed 0 仍成功。
3. **procedural OOD 仍未解决**：procedural fallback 在 seed 0 上连 `DESCEND` 都无法通过（`descend_exit_rate = 0.0`），物体甚至穿地/飞离（`object_height_delta = -6250 m`）。这说明根因仍是 **asset-fidelity-induced policy-object geometry/gate mismatch**，regrasp 无法修复一个根本接触不到的物体。
4. **contact proxy 需要 object 被 reachable 才有意义**：当前 procedural fallback 的失败发生在 DESCEND 之前，contact proxy 为空。需要先解决 reachability/geometry mismatch，contact diagnosis 才能给出 actionable signal。

---

## 4. 下一步

1. 在 procedural OOD 中筛选能到达 GRASP 的 seed（或调整 geometry adaptation），让 contact proxy 有数据。
2. 运行 `scripts/diagnostics/run_procedural_contact_diagnosis.py` 多 seeds，得到 baseline vs regrasp 的 contact_proxy 分布。
3. 运行 `scripts/ablations/run_procedural_ood_adaptive_recovery.py`，用 FBA 指标量化每种策略的边界推进效果。
4. 若 structural hints 只能推进 FBA 但不能 lifting，则诚实地写入报告：当前 adaptive recovery 是 local hint，不是 transferable skill。

---

## 5. 文件变更

- `rosclaw_darwin/evaluation/arena_docker_deps/heuristic_policy.py`
- `rosclaw_darwin/evolution/runner.py`
- `configs/policies/heuristic_servo_goal_pose_v3_regrasp.yaml`
- `configs/skills/failure_signature_to_hint_rules_v31.yaml`
- `scripts/diagnostics/run_procedural_contact_diagnosis.py`
- `scripts/ablations/run_procedural_ood_adaptive_recovery.py`
- `tests/unit/test_failure_signature_to_hint_rules.py`
- `reports/STRUCTURAL_FAILURE_TO_HINT_V31_REPORT.md`（本报告）

# 阶段5：对照实验、消融与最终评估 — 交付报告

- 日期：2026-10-26
- 交付脚本：`experiments/state_recovery/scripts/evaluate_versions.py`（离线确定性对照引擎）
- 输出：`experiments/state_recovery/results/version_comparison/comparison.json` + `fault_injection.json`
- 执行方式：**离线可复现对照为主**（用户确认）；无随机数，同命令两次运行输出完全一致

## 0. 结论先行（不预设 V4 优于 V0，以受控指标支撑）

1. **V0/V1/V2 在三类"可成功"场景下恢复率完全一致（1.0）**：RecoveryState/Trace（V1）与动作契约（V2）**不改变恢复结果**，只增加状态记录与执行证据——这是预期中的零成本改造，消融结论为"保留但不宣称提升成功率"。
2. **V3/V4 的价值体现在失败场景的成本控制与安全终止**，不是成功率提升：
   - 始终无法清除时，V0/V1/V2 盲跑满 3 轮（max_iter_exceeded 92.9%），V3/V4 第 2 轮早停（max_iter_exceeded 0%，no_progress 91.6%），Planner 调用减少 33%、Execute 减少 34%。
   - 验证不确定时 V3/V4 先 OBSERVE 补证，绝不直接宣布成功（V0/V1/V2 盲跑满）。
3. **V4（动态调度）相对 V3（静态 Policy）的唯一离线可测量差异是"外部清除证据 → 直接终验跳过第 2 轮执行"**（H41：V4 execute=1 vs V3 execute=2）与"工具连续失败 → OBSERVE"（H42）。其余场景 V3 与 V4 行为相同——动态开关可消融，V4 未引入新的错误终止。
4. **V3/V4 在"首轮即成功"场景恢复率 0.9861 略低于 V0 的 1.0**：2 个任务（baidubrowser_13/15）的真实 recovery_tasks 未覆盖授权目标，Policy 正确拒绝（plan_rejected）而非盲执行。这是保守但正确的行为，代价是乐观场景下的恢复率 -1.4%。
5. **无污染任务（154 个）不混入任何恢复率分母**（truth_cleared=None，口径由 H39b 强制校验）。

## 1. 任务A：对照组与一致性

| 版本 | 离线实现语义 | 对应 run_pipeline |
|---|---|---|
| V0 | 原始 Workflow：固定循环 generate→execute→verify，无 RecoveryState 约束、无动作契约、无 Policy、无预算/重复/无进展控制 | `--harness v1`（旧行为） |
| V1 | V0 + RecoveryState + Trace：状态记录与轨迹，决策不变 | v1 + `--trace` |
| V2 | V1 + 动作前置条件 + 动作后三分离验证：动作契约拦截越权/预算/目标不明/前置不成立 | `--harness v2` |
| V3 | V2 + Policy Engine 静态版（阶段3）：预算/重复/无进展/授权/终止控制，`dynamic=False` | v3 的静态开关 |
| V4 | V3 + Harness 动态控制循环（阶段4）：RE_AUDIT / 证据直接终验 / 工具失败 OBSERVE，`dynamic=True` | `--harness v3` |

**一致性**：五个版本吃**完全相同**的真实输入——同一批 309 个 ledger（Audit 推断）、同一批 recovery_tasks（Planner 产出，qwen3-vl-plus）、同一组确定性注入的执行/验证结果。唯一差异是控制机制本身。模型/Prompt/数据集/GUI 环境/任务目标/污染清单全程一致，无任何版本单独改模型或 Prompt。

## 2. 任务B：统一统计口径

| 口径 | 定义 |
|---|---|
| 总任务数 | 309（base_canonical run，含 155 个 this_task 污染任务 + 154 个无直接污染任务） |
| 有污染任务分母 | 含 `attribution=this_task` 污染的任务（155） |
| 无污染任务处理 | 不进入恢复循环，直接成功；`truth_cleared=None`，**不混入任何恢复率分母** |
| 人工门控任务 | targets 全部 halted 的任务（11 个）单列 `halted_tasks`，不进入自主恢复率分母 |
| 自主恢复任务分母 | 155 - 11 = 144 |
| 恢复成功 | `decision==STOP_SUCCESS` 且注入 ground truth 显示污染确实清除 |
| 最终验证成功 | 与恢复成功同义（STOP_SUCCESS 由最终验证裁决） |
| 错误成功（误恢复） | `STOP_SUCCESS` 但 ground truth 未清除 |
| 一次成功 | iterations==1 且恢复成功 |
| 平均迭代次数 | 自主任务 iterations 均值 |
| 动作次数 | actions_total（V2 计入契约动作，V0/V1 为 0） |
| 模型调用次数 | llm_calls（V3/V4 统计 generate+verify+reaudit 级调用） |
| 失败原因 | termination_reason 枚举：max_iter_exceeded / no_progress / repeated_plan / plan_rejected / budget_exhausted / needs_human |
| 任务唯一 ID | task_id（如 `qq_10`），无重复计数 |

## 3. 任务C：主要/次要指标（两层呈现）

### 第一层：全量真机数字（V0 基线，来源=2026-10-26 全量真机 pipeline，标注于记忆记录）

> ⚠️ 该数字来自历史真机实验汇总，本地结果文件不在工作树（见阶段5 前置核对），此处仅作 V0 基线引用：
> 总任务 310，155 个存在待恢复污染，154 个无直接污染，1 个运行出错；**恢复成功率 63.23%，一次成功率 40%，平均迭代 1.51**（V0 固定循环，max_iter=3）。

### 第二层：离线确定性受控对照（evaluate_versions.py，同一批真实任务 × 场景注入）

#### 3.1 恢复成功率（主要指标，分母=自主任务 144）

| 场景 | V0 | V1 | V2 | V3 | V4 |
|---|---|---|---|---|---|
| clean_first（首轮即清除） | 1.0000 | 1.0000 | 1.0000 | 0.9861 | 0.9861 |
| clear_round2（第 2 轮清除） | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| 错误成功（误恢复） | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 安全终止率（无法清除时不误报） | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |

#### 3.2 成本与效率（次要指标，persistent_fail 场景，分母=144）

| 指标 | V0/V1/V2 | V3 | V4 |
|---|---|---|---|
| Planner 调用 | 432 | **288**（-33%） | **288** |
| Execute 调用 | 432 | **284**（-34%） | **284** |
| Verify 调用 | 432 | 284 | 284 |
| 平均迭代 | 2.7871 | **1.8452** | **1.8452** |
| max_iter_exceeded 比例 | 0.929 | **0.0** | **0.0** |
| 无进展早停比例 | 0.0 | **0.916** | **0.916** |
| 意外终止（max_rounds/replan_error） | 0 | 0 | 0 |

#### 3.3 其他指标

- 一次成功率：clean_first 场景 V0-V2=1.0，V3/V4=0.9861（同恢复率差异来源）
- LLM 调用：V3/V4 恒为 generate+verify 双计数（llm=570 vs V0 432）——Policy 循环每轮显式记账，如实反映模型成本不降低
- 验证不确定场景：V3/V4 先 OBSERVE 补证（verify 426 > 正常 284），V0/V1/V2 无此路径、盲跑满

## 4. 任务D：故障注入（8 类，独立 ground truth 判定，不依赖 LLM 自报）

| # | 故障场景 | 注入证据 | V0-V2 行为 | V3/V4 行为 | 预期响应达成 |
|---|---|---|---|---|---|
| 1 | 点击没有生效 | executed/unchanged/not_cleared | 盲跑满 3 轮 | 第 2 轮 no_progress 早停 | ✅ |
| 2 | 页面延迟更新 | unchanged | 盲跑满 3 轮 | no_progress 早停 | ✅ |
| 3 | 控件位置变化 | execution_status=blocked | 盲跑满 3 轮 | no_progress 早停 | ✅（V2+ 真机 precheck 会 block） |
| 4 | 初始清单与当前状态不一致 | clearance=cleared 动作证据 | 第 2 轮仍执行 | **V4 跳过第 2 轮执行直接终验（execute=1 < V3 的 2）** | ✅（仅 V4） |
| 5 | 相同动作连续失败 | execution_status=error ×2 | 盲跑满 3 轮 | **V4 先 OBSERVE 重新观察**（V3 不 OBSERVE） | ✅（仅 V4） |
| 6 | 误将历史污染作为恢复目标 | 计划含 carried_over 目标 | 盲执行 3 轮 | **plan_rejected 不执行（execute=0）** | ✅ |
| 7 | Planner 生成前置条件不成立计划 | 空 recovery_goal/max_steps=0 | 盲执行 3 轮 | **plan_rejected 不执行** | ✅ |
| 8 | 验证证据不足 | verdicts cleared=None | 盲跑满 3 轮 | **OBSERVE 补证一次，不宣布成功** | ✅ |

**独立评测方法**：每个故障场景的 ground truth 是注入的真实清除状态（truth 函数），与版本是否宣布成功独立判定——恢复成功要求 `STOP_SUCCESS 且 truth=True`，误恢复要求 `STOP_SUCCESS 且 truth=False`，两类均不依赖参与执行的 LLM 自我宣布。

## 5. 任务E：统计分析

- **可复现性**：全部确定性（无随机）；H39a 强制"同输入两次运行结果一致"
- **配对比较**：五个版本处理相同任务（同 ledger/recovery_tasks）、相同注入（同初始环境），结果差异可归因于版本；H40-H44 以单任务配对断言
- **不预设 V4 > V0**：离线受控对照显示 V3/V4 在乐观场景恢复率略低（0.9861 vs 1.0，2 个保守拒绝），成本上 Planner 调用反而因 Policy 循环记账不下降（LLM 双计数）。**明确结论：若只看恢复成功率，V3/V4 无增益；其价值集中在失败场景的早停/安全终止/证据调度**
- **置信区间**：离线确定性场景注入下无随机性，不适用 CI；真机随机性实验受约束未发起，作为后续工作

## 6. 消融实验结论

| 模块 | 消融对比 | 结论 | 建议 |
|---|---|---|---|
| RecoveryState + Trace（V1） | V0 vs V1 | 恢复率/成本完全一致，仅增加状态记录与可追溯性 | **保留**（零成本、可重建、可追溯） |
| 动作契约（V2） | V1 vs V2 | 恢复率一致；提供三分离证据供诊断（V4 依赖）；拦截越权/前置不成立 | **保留**（证据基础设施，供 V4 诊断） |
| Policy Engine 静态版（V3） | V2 vs V3 | 无进展/重复场景早停，max_iter_exceeded 0.929→0；乐观场景恢复率 -1.4%（保守拒绝） | **保留**（预算/终止控制必要） |
| 动态控制循环（V4） | V3 vs V4 | 仅"证据足够直接终验"与"工具失败 OBSERVE"两条路径有差异；未引入新错误终止 | **保留但标注有限增益**；若真机显示这两条路径不触发，可考虑简化 |

## 7. 典型案例

- **成功（V3/V4 早停收益）**：`articlenews_0` persistent_fail —— V0 盲跑 3 轮（planner=3, execute=3），V3/V4 第 2 轮 no_progress 停止（planner=2, execute=2），保留现场证据。
- **保守拒绝（V3/V4 恢复率 -1.4% 来源）**：`baidubrowser_13/15` —— 真实 recovery_tasks 未覆盖授权目标，V3/V4 plan_rejected 安全终止不执行；V0 会盲执行 3 轮。这是"宁可安全终止也不处理不可信计划"的边界案例。
- **V4 独有调度**：`ledger_stale` 故障回放 —— V4 检测到动作级 clearance=cleared 证据后跳过第 2 轮执行直接终验（execute=1 vs V3 的 2）；`same_action_repeat_fail` —— V4 先 OBSERVE 再继续。

## 8. 回退方式（任务D 保持可回退）

- `--harness {v1,v2,v3}` 配置切换新旧控制循环；v1 固定循环始终保留为基线（H38 断言语义不变）
- Policy 引擎内置 `dynamic` 开关（默认 True），`False` 即精确退回阶段3 静态行为（H44 消融）
- 新 Harness 未删除任何原有执行逻辑；对照实验未证明 V4 增益前，V1 基线仍可随时启用

## 9. 最终架构图与优化优先级

```
┌────────────────────────────────────────────────────────────────┐
│                      RecoveryState（唯一可信状态）               │
│   targets / budget / attempt_history / per_iteration / trace    │
└───────────────┬────────────────────────────────────────────────┘
                │ policy_dict()
┌───────────────▼────────────────────────────────────────────────┐
│                     Policy Engine（确定性 decide）               │
│   预算检查 → 无进展检测 → [V4:新污染→RE_AUDIT] → 分阶段决策       │
│   REPLAN / EXECUTE_PLAN / VERIFY / OBSERVE / STOP_*             │
└───────┬────────────────────┬────────────────────┬──────────────┘
        │ replan             │ execute            │ verify
┌───────▼──────┐    ┌────────▼────────┐   ┌──────▼─────────────┐
│  Planner      │    │  Executor       │   │  Verify（最终裁决） │
│ (LLM 产出计划)│    │ (动作契约 pre/post│   │ 只由 VERIFY 调用   │
│  受校验/授权  │    │  三分离 + 拦截)  │   │  唯一 success 来源  │
└──────────────┘    └─────────────────┘   └────────────────────┘
```

**优化优先级（建议后续）**：
1. 真机对照验证 V4 的两条动态路径（证据直接终验/工具失败 OBSERVE）在实际执行中是否触发；若不触发，评估简化 dynamic 开关
2. 修复 2 个 plan_rejected 边界（baidubrowser_13/15）：调查真实 recovery_tasks 未覆盖授权目标的原因（Planner 遗漏 or ledger 门控误判）
3. 若需真机置信区间，按任务类型分层抽样重跑（受约束，需授权）
4. LLM 调用双计数是否需合并记账（当前 Policy 循环每轮显式记账，成本如实显示）

## 10. 测试

selftest.py H39-H44（44 项总量基础上新增 6 项，共 50 项全绿）：
- H39a 离线对照可复现；H39b 无污染任务不混入恢复率分母
- H40 V3/V4 无进展早停（迭代 < V0 盲跑满，不靠加大 max_iter）
- H41 外部清除证据 → V4 直接终验（execute=1 < V3 的 2）
- H42 工具连续失败 → V4 OBSERVE（V3 不 OBSERVE）
- H43 越权目标授权拒绝且不执行（V0 盲执行）
- H44 动态开关可消融且 V4 无意外终止

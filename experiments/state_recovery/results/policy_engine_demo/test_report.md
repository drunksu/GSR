# 阶段3+4：确定性 Policy Engine + Harness 驱动的动态控制循环 — 交付报告

- 日期：2026-10-26
- 模式：`--harness v3`（v3 = v2 动作契约 + Policy Engine + 动态调度；v1 固定循环始终保留为可回退基线）
- 设计决策：不引入状态机框架。现有 pipeline 是普通过程式循环，直接用**纯函数 `decide()` + 注入式 `run_loop()`** 实现（对齐阶段3提示词"不要为了引入状态机而强制迁移框架"）。

## 0. 阶段4总览

阶段4**改变控制机制而不新增模块**：把固定循环 `Audit → Planner → Execute → Audit → Planner` 升级为按需调度——每轮依据当前状态、执行结果证据、历史进展与预算，只调用必要模块。

- 任务A：按需调度（`decide()` 多路分支，非每轮全调用）
- 任务B：有限动态策略（第一版为确定性策略，不引入自由 LLM 策略选择器；触发条件与 schema 约定在 §9 说明）
- 任务C：失败诊断与恢复策略切换（`_diagnose()` 只读执行结果与状态证据，不猜错误字符串）
- 任务D：可回退（v1 固定循环保留为基线，`--harness` 配置切换，§10）

## 1. 交付物

| 交付物 | 位置 |
|---|---|
| Policy Engine 源码 | `experiments/state_recovery/scripts/policy_engine.py` |
| RecoveryState（record_reaudit） | `experiments/state_recovery/scripts/recovery_state.py` |
| Pipeline 接线（v3 reaudit 回调） | `experiments/state_recovery/scripts/run_pipeline.py` |
| 状态转换表 | `experiments/state_recovery/results/policy_engine_demo/transition_table.json` |
| 单元测试（H26–H38，44 项全绿） | `experiments/selftest.py` |
| 对照结果（7 场景 + 受控汇总） | `experiments/state_recovery/results/policy_engine_demo/comparison.json` |

## 2. 任务A：策略输入与输出

**输入**（`decide(st, ctx)` 纯函数）：
- 当前 RecoveryState（`policy_dict()` 完整视图：targets/budget/attempt_history/per_iteration/phase/success）
- 最近审计/验证结果（per_iteration 中 `verify.verdicts`，逐目标 cleared）
- 最近动作执行结果（per_iteration `actions`，来自动作契约）
- 历史失败与进展（attempt_history 的 accepted_plan + verify_success；no_progress_trail）
- 剩余预算（从 state 确定性反推：iter_remaining / llm_calls / actions_total，可随状态重建）
- **阶段4新增**：`_diagnose()` 证据诊断（tool_failures / page_changed / stale_judgment_cleared / new_contamination_signals / verify_uncertain）

**输出**：8 种结构化决策，每种都有明确触发条件与状态转换：

| 决策 | 触发条件 | 转换 |
|---|---|---|
| REPLAN | 无计划（init）/ 计划被拒（首次）/ 验证失败但有进展 / 补证后仍无进展 | → planned |
| EXECUTE_PLAN | 计划通过校验且被接受 | → executed |
| VERIFY | 本轮执行完毕 / 证据已足够（外部清除）直接终验 | → verified |
| OBSERVE | 验证证据不确定 **或工具执行失败**（阶段4） | verified（补证一次，不宣布结果） |
| **RE_AUDIT**（阶段4） | **新污染出现在授权目标范围**且每轮限 1 次 | planned（重审计后重新规划） |
| STOP_SUCCESS | 全部 this_task 目标已核实清除（含已清除且证据足够时直接终验，避免过度保守） | → terminal |
| STOP_FAILURE | 预算耗尽 / 连续无进展 / 计划重复被拒 / 连续两次被拒 | → terminal |
| STOP_NEEDS_HUMAN | 全部目标被人工门控挂起 / 计划引用门控目标 | → terminal |

## 3. 任务B：确定性约束

- **最大恢复迭代次数**：max_iter（LLM 无法修改）
- **最大 GUI 动作次数**：actions_cap = max_iter × 5（v2 每轮动作上限叠加）
- **模型调用预算**：llm_cap = max_iter × 2 + 1（统计 Planner + Verify + **重审计**级调用）
- **连续失败检测**：no_progress_trail ≥ 2 → 早停（**不以加大 max_iter 为默认解**，按每轮核实清除目标数判断有效进展）
- **无进展与重复动作检测**：结构化签名 `(mutation_id, recovery_goal)` + 此前验证失败；不引入语义相似度模型；**重复被拒时要求改变策略，禁止原样重试**
- **污染目标授权检查**：只允许 this_task；carried_over / preexisting 一律拒绝
- **明确终止状态**：terminal 幂等，重建后可继续；失败时现场与证据保留在 RecoveryState（targets/evidence_refs/attempt_history）
- **失败保留现场**：trajectory / ledger / task_dir 引用全部落盘

## 4. 任务C：LLM 决策权限控制

- Planner 只产出计划（replan 返回 `(task_path, plan_sig, plan)`）；是否调用、是否接受、是否重新规划由 Policy 决定
- Executor 只提出动作意图；实际执行必须走动作契约统一接口（precheck block / 三分离后验证）
- LLM 不能：修改预算与 max_iter、改变污染归属、自行写入验证成功状态（record_verify 只由 Policy 的 VERIFY 路径调用）、绕过权限检查、用自由文本覆盖停止条件（decide 优先级高于任何模型输出）

## 5. 任务D：避免过度保守

- 证据足够且目标已清除（如外部清除 / 动作级 clearance=cleared）→ 直接进入最终验证（decide planned 分支），不反复调用 Planner/Executor
- 证据不足 → OBSERVE 补证一次，仍不足 → REPLAN；绝不直接判成功或盲目重试

## 6. 阶段4 任务C：失败诊断与恢复策略切换（`_diagnose()`）

诊断**只依赖执行结果与状态证据**，不读取/猜测错误字符串：

| 状态证据（动作契约三分离字段） | 诊断结论 | 策略切换 |
|---|---|---|
| `execution_status=error` ≥ TOOL_FAILURE_REOBSERVE（2） | 工具执行失败 | OBSERVE（检查工具状态并重新观察），仍失败 → REPLAN |
| `gui_changed=changed` 且未清除 | 页面状态已变化 | 进入 REPLAN 前由计划校验/证据检查兜底（旧计划失效） |
| `clearance=cleared`（动作级证据） | 原污染判断不再成立 | 直接终验（VERIFY），不重复执行 |
| `new_contamination_signal` 且 target_id 在授权范围 | 新污染出现 | RE_AUDIT 重新审计并调整目标状态（每轮限 1 次） |
| verdicts 缺失/不确定 | 验证不确定 | 补证 OBSERVE 一次，仍不确定 → 安全终止或 REPLAN |

## 7. 单元测试（selftest H26–H38，44 项全绿）

| 测试 | 对应要求 | 结果 |
|---|---|---|
| H26 | 预算耗尽正确停止（budget_exhausted） | PASS |
| H27a | 相同计划重复不重复执行（repeated_plan，execute=1） | PASS |
| H27b | 连续无进展按 NO_PROGRESS_LIMIT 早停（iter=2<max_iter=3） | PASS |
| H28 | 验证成功后不再调用 Planner（replan=1） | PASS |
| H29a/b | carried_over 目标被授权检查拒绝；越权计划两次被拒安全终止且不执行 | PASS |
| H30 | 计划被拒后重新规划可成功（replan=2, execute=1） | PASS |
| H31 | 验证不确定不得直接宣布成功（即使 verify 谎称 success=True） | PASS |
| H32a/b/c | 失败后状态可重建（targets/attempt/accepted_plan 保留），重建后重跑安全终止 | PASS |
| H33 | 终止态 decide 幂等且输出 STOP_* | PASS |
| H34a | 外部清除→直接终验：v3 execute=1 < v1 execute=2（不再重复执行） | PASS |
| H34b | 受控对照：v3 重复被拒提前终止（execute=1），v1 盲跑满 max_iter（execute=3） | PASS |
| H34c | 动态调度不引入新错误终止，decision_log 完整可重建 | PASS |
| H35 | 工具执行失败→OBSERVE 重新观察（诊断只读执行结果/状态证据） | PASS |
| H36 | 新污染影响授权目标→RE_AUDIT 且计入 LLM 预算 | PASS |
| H37 | Trace 的 policy.decide 事件可重建完整决策过程（事件序列 == decision_log） | PASS |
| H38 | v1 固定循环基线保留且可配置回退（--harness v1 语义不变） | PASS |

## 8. 对照结果（comparison.json，相同初始条件 ledger_demo.json，max_iter=3）

### 8.1 受控汇总（7 场景同预算）

| 指标 | v1 固定循环 | v3 动态调度 |
|---|---|---|
| Planner 调用合计 | 18 | **16** |
| Execute 调用合计 | 18 | **9** |
| Verify 调用合计 | 18 | **9** |
| 意外终止（max_rounds/replan_error） | — | **0** |

结论（**不因架构更灵活而宣称更优，以受控指标支撑**）：在相同初始条件与相同预算下，v3 通过"证据足够直接终验 / 无进展早停 / 重复拒绝"减少了不必要的 Planner/Executor 调用（execute/verify 减半），全部终止均为显式确定性原因，未引入新的错误终止类别。

### 8.2 动态调度案例（阶段4新增）

| 场景 | v1 | v3 | 动态调度点 |
|---|---|---|---|
| external_cleared_direct_final_verify | execute=2（盲执行第 2 轮） | execute=1，**STOP_SUCCESS** | 动作级 clearance=cleared → 跳过第 2 轮执行直接终验 |
| tool_failure_reobserve | 盲跑 3 轮 | decision_log 含 **OBSERVE**（先重新观察）后安全终止 | execution_status=error → 不猜错误字符串，先补证 |
| new_contamination_reaudit | 盲跑 3 轮 | decision_log 含 **RE_AUDIT**（重新审计）后重新规划 | 新污染影响授权目标 → 重审计并评估风险 |

## 9. 任务B（阶段4）：LLM 策略选择器约定

第一版**优先采用确定性策略**（当前已覆盖全部调度场景）。若未来需要 LLM 选择高层策略，约定如下（尚未启用）：
- 结构化输出 schema：`{"strategy": "<OBSERVE|VERIFY|EXECUTE_PLAN|REPLAN|RE_AUDIT|STOP_*>"}`
- 限制可选动作：仅上述集合，且不得输出自由文本覆盖
- 验证输出格式与参数：解析失败 / 越界 / 无效 → 回退安全确定性策略（当前 decide）
- 记录选择依据与实际结果（写入 Trace 事件）
- 保留最大迭代次数与其他预算约束不变

## 10. 任务D（阶段4）：回退方式

- 新旧控制循环通过 `--harness {v1, v2, v3}` 配置切换
- v1 始终保留为固定循环基线：`run_pipeline` 中 harness=None 时走旧 `generate → execute → verify` 循环，不经过 Policy Engine，语义与阶段0-1 完全一致
- 新 Harness（v2/v3）不覆盖、不删除原有执行逻辑；在对照实验证明 v3 价值之前，v1 仍可作为对照组随时回退

## 11. 实施中修复的关键缺陷

1. **计划重复误判**：`record_generate` 在校验前写入 accepted_plan，导致当前计划被自己误判为重复。修复：`detect_plan_repeat` 只统计已执行并验证过的 attempt。
2. **计数不持久化**：`decide` 计算 reject/repeat_count 后未写回，导致被拒计划无限 REPLAN 直到安全轮数上限。修复：计数随决策输出持久化，计划被接受执行时清零。
3. **状态重建缺失**：`to_dict` 的扩展字段被 TraceLogger 挂接门控，v3 不开 --trace 时 targets/attempt_history 不落盘。修复：扩展输出由调用方 `extended` 参数决定（v2/v3 模式始终落盘完整状态）。
4. **demo 场景 state 引用错位（阶段4）**：`_steppers(state=_mk_state(led1))` 创建的 state 实例被丢弃，动作记录写入错误对象导致诊断读不到动作。修复：先建 state 再传给 `_steppers`（场景 5/6/7）。
5. **诊断读取 None（阶段4）**：`_diagnose` 对无 actions 键的迭代 `.get("actions")` 返回 None 后迭代崩溃。修复：`per[-1].get("actions") or []`。
6. **demo 输出路径不一致（阶段4）**：`--out` 默认为 cwd 相对路径，导致对照写到项目根目录而非交付目录。修复：默认改为脚本相对路径 `results/policy_engine_demo`。

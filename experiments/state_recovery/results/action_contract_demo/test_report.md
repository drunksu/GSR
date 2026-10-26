# 阶段2 测试报告：动作契约与独立验证

日期：2026-10-26
范围：`experiments/state_recovery/scripts/action_contract.py`（新增）、
`third_party/mobilebench-ol-main/mobilebench/utils/agent.py`（钩子补丁）、
`third_party/mobilebench-ol-main/mobilebench/utils/task_executor.py`（回调补丁）、
`experiments/state_recovery/scripts/recovery_state.py`（record_action）、
`experiments/state_recovery/scripts/run_pipeline.py`（--harness v2 接线）、
`experiments/selftest.py`（H15-H25）。
执行方式：`mobile\Scripts\python.exe experiments\selftest.py` —— 全部 34 项 PASS，退出码 0。
说明：本阶段不引入自由动态控制策略、不调整模型参数、不加 LLM 调用；全部验证为确定性代码。

## 8 类要求场景的覆盖与结果

| 要求场景 | 测试项 | 断言结论 |
|---|---|---|
| 工具调用失败 | H15 | execution_status=error，gui=unchanged，clearance=not_cleared（三分离） |
| 工具无报错但状态未改变 | H16 | executed / unchanged / not_cleared 分开记录 |
| 目标控件不存在或无法定位 | H17a/b | click 无 position → block；显式 id 不在页面 → block |
| 页面变化、前置条件失效 | H18 | 目标控件在当前页面确定不存在 → block，返回 Harness |
| 动作已执行，但污染仍然存在 | H19 | executed / changed / not_cleared 三分离 |
| 污染已被外部操作清除 | H20 | executed / changed / cleared（XML 开关状态翻转可判） |
| 验证证据不足 | H21 | 观察缺失或污染类型无可靠谓词 → uncertain，绝不默认成功 |
| 恢复操作引入新的污染 | H22 | type 输入残留 → new_contamination_signal=True |

## 附加覆盖

- H23a/b：动作记录含全部 10 个契约字段（action_id/target_id/action_type/
  target_description/preconditions/expected_effect/tool_result/execution_status/
  observation_ref/error_reason）+ 三分离扩展；blocked / not_executed 状态正确。
- H24：越权目标（target_id 不在授权集合）、预算耗尽 → block 级拦截。
- H25：动作记录进入 per_iteration.actions、Trace 事件 execute.action、
  validate_state 对 actions 字段的校验全部通过。
- 开关状态翻转进入 XML 签名（修复了"开关已翻转却被判 GUI 未变化"的缺陷）。

## 代表性执行轨迹

`results/action_contract_demo/representative_records.json` —— 8 条完整动作记录，
每类场景一条，含 10 契约字段与三分离验证结果。

## 行为等价性（v1 不变）

agent.py 的 pre/post 钩子与 task_executor.py 的 step 回调默认均为 None：
未挂接任何钩子时，step() 与 run() 的执行路径与原代码逐语句一致
（H12 语义等价测试继续通过）。

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evaluate_versions.py —— 阶段5：V0-V4 离线确定性对照引擎。

对照实验框架：所有版本吃**完全相同的真实输入**（同一批污染清单 ledger、
同一批 Planner 产出 recovery_tasks、同一组注入的执行/验证结果），只切换
控制机制本身，从而把 V0-V4 的差异归因到 Harness 改造，而不是模型/Prompt/
数据集/GUI 环境差异（阶段5 任务A）。

版本定义（离线实现语义与 run_pipeline --harness 对应）：
  V0  原始 Workflow：固定循环 generate→execute→verify，无 RecoveryState
       约束、无动作契约、无 Policy、无预算/重复/无进展控制。
  V1  V0 + RecoveryState + Trace：状态记录与轨迹，但循环决策不变。
  V2  V1 + 动作前置条件 + 动作后三分离验证：动作契约拦截越权/预算/目标
       不明/前置不成立的执行。
  V3  V2 + Policy Engine（阶段3 静态版）：deterministic decide，含预算/
       重复/无进展/授权/终止控制；dynamic=False。
  V4  V3 + Harness 动态控制循环（阶段4）：RE_AUDIT / 证据直接终验 /
       工具失败 OBSERVE / 按需调度；dynamic=True。

离线可复现：全部注入确定性结果，无随机数；同一命令两次运行输出完全一致。
没有真机执行/验证结果的地方，用「场景注入」替代，并在指标中同时记录
ground truth（注入的污染真实清除状态），以便区分恢复成功 / 错误成功
（误恢复）/ 正确安全终止（阶段5 任务C、任务D 独立评测）。

用法::

    python evaluate_versions.py [--limit N] [--out ..\\results\\version_comparison]

输出:
  results/version_comparison/comparison.json —— 任务×场景×版本明细 + 汇总
  results/version_comparison/fault_injection.json —— 8 类故障注入回放
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEDGER_ROOT = HERE.parent / "results" / "ledgers" / "base_canonical"
TASK_ROOT = HERE.parent / "results" / "recovery_tasks" / "base_canonical"
OUT_DIR = HERE.parent / "results" / "version_comparison"

sys.path.insert(0, str(HERE))
import mutation_taxonomy as tax  # noqa: E402
import recovery_state as rs  # noqa: E402
import policy_engine as pe  # noqa: E402
import recovery_task as rt  # noqa: E402
import action_contract as ac  # noqa: E402

VERSIONS = ("V0", "V1", "V2", "V3", "V4")
MAX_ITER = 3


# ============================================================ 版本循环实现

def _mk_state(task: dict) -> rs.RecoveryState:
    st = rs.RecoveryState(task["task_id"], task["run_id"], MAX_ITER)
    st.load_ledger(task["ledger_path"])
    return st


def run_v0(task: dict, scn: dict) -> dict:
    """V0：固定循环（无 RecoveryState 约束、无 Policy）。"""
    calls = {"replan": 0, "execute": 0, "verify": 0}
    if not task["has_this_task"]:
        return {"iterations": 0, **calls, "decision": "STOP_SUCCESS",
                "termination_reason": "recovered", "llm_calls": 0,
                "actions_total": 0, "decision_log": [],
                "truth_cleared": None, "erroneous_success": False}
    for i in range(1, MAX_ITER + 1):
        calls["replan"] += 1
        plan = scn["plan"](i)
        if plan is None:
            return {"iterations": i, **calls, "decision": "STOP_FAILURE",
                    "termination_reason": "replan_error", "llm_calls": calls["replan"],
                    "actions_total": 0, "decision_log": [],
                    "truth_cleared": scn["truth"](i), "erroneous_success": False}
        calls["execute"] += 1
        rec = scn["execute"](i, plan)
        if rec.get("error"):
            return {"iterations": i, **calls, "decision": "STOP_FAILURE",
                    "termination_reason": "execute_error", "llm_calls": calls["replan"],
                    "actions_total": 0, "decision_log": [],
                    "truth_cleared": scn["truth"](i), "erroneous_success": False}
        calls["verify"] += 1
        v = scn["verify"](i)
        if v["success"]:
            return {"iterations": i, **calls, "decision": "STOP_SUCCESS",
                    "termination_reason": "recovered", "llm_calls": calls["replan"],
                    "actions_total": 0, "decision_log": [],
                    "truth_cleared": scn["truth"](i),
                    "erroneous_success": not scn["truth"](i)}
    return {"iterations": MAX_ITER, **calls, "decision": "STOP_FAILURE",
            "termination_reason": "max_iter_exceeded", "llm_calls": calls["replan"],
            "actions_total": 0, "decision_log": [],
            "truth_cleared": scn["truth"](MAX_ITER), "erroneous_success": False}


def run_v1(task: dict, scn: dict) -> dict:
    """V1：固定循环 + RecoveryState + Trace（决策不变，仅记录）。"""
    calls = {"replan": 0, "execute": 0, "verify": 0}
    if not task["has_this_task"]:
        return {"iterations": 0, **calls, "decision": "STOP_SUCCESS",
                "termination_reason": "recovered", "llm_calls": 0,
                "actions_total": 0, "decision_log": [],
                "truth_cleared": None, "erroneous_success": False}
    st = _mk_state(task)
    for i in range(1, MAX_ITER + 1):
        st.begin_iteration(i)
        calls["replan"] += 1
        plan = scn["plan"](i)
        st.record_generate(ok=plan is not None,
                           task_path="tasks.json" if plan else None)
        if plan is None:
            break
        calls["execute"] += 1
        rec = scn["execute"](i, plan)
        st.record_execute(ok=not rec.get("error"), rec=rec)
        if rec.get("error"):
            break
        calls["verify"] += 1
        v = scn["verify"](i)
        st.record_verify(v)
        if v["success"]:
            st.finish(True, i == 1, "clean")
            return {"iterations": i, **calls, "decision": "STOP_SUCCESS",
                    "termination_reason": "recovered",
                    "llm_calls": calls["replan"],
                    "actions_total": 0, "decision_log": [],
                    "truth_cleared": scn["truth"](i),
                    "erroneous_success": not scn["truth"](i)}
    st.finish(False, False, "contaminated",
              failure_reason="max_iter_exceeded",
              termination_reason="max_iter_exceeded")
    return {"iterations": MAX_ITER, **calls, "decision": "STOP_FAILURE",
            "termination_reason": "max_iter_exceeded",
            "llm_calls": calls["replan"], "actions_total": 0,
            "decision_log": [], "truth_cleared": scn["truth"](MAX_ITER),
            "erroneous_success": False}


def run_v2(task: dict, scn: dict) -> dict:
    """V2：固定循环 + 动作前置条件 + 动作后三分离验证（动作契约拦截）。

    与 V1 的差别：execute 走 precheck（越权/预算/目标不明/前置不成立 → block），
    动作记录含三分离字段；决策仍是固定循环。
    """
    calls = {"replan": 0, "execute": 0, "verify": 0}
    if not task["has_this_task"]:
        return {"iterations": 0, **calls, "decision": "STOP_SUCCESS",
                "termination_reason": "recovered", "llm_calls": 0,
                "actions_total": 0, "decision_log": [],
                "truth_cleared": None, "erroneous_success": False}
    st = _mk_state(task)
    ctx = {"enabled": True, "recovery_id": st.recovery_id,
           "target_ids": [t["mutation_id"] for t in st.targets
                          if t.get("recovery_status") != "verified_cleared"],
           "target_id": (task["tasks"][0].get("mutation_id")
                         if task["tasks"] else None),
           "budget": dict(st.budget), "max_actions": 10,
           "action_log": [], "record": st.record_action}
    blocked = 0
    for i in range(1, MAX_ITER + 1):
        st.begin_iteration(i)
        calls["replan"] += 1
        plan = scn["plan"](i)
        st.record_generate(ok=plan is not None,
                           task_path="tasks.json" if plan else None)
        if plan is None:
            break
        # 动作契约：执行前检查（授权/预算/目标）
        pre = ac.precheck_action({"action": "click",
                                  "params": {"position": [1, 2]}}, "", ctx)
        if not pre["allow"]:
            blocked += 1
            rec = {"error": "precheck_blocked",
                   "traj": {"history_action": [], "success": False},
                   "task_dir": f"iter{i}", "final_img": None}
            st.record_execute(ok=False, rec=rec)
            break
        calls["execute"] += 1
        rec = scn["execute"](i, plan, contract=True)
        st.record_execute(ok=not rec.get("error"), rec=rec)
        if rec.get("error"):
            break
        calls["verify"] += 1
        v = scn["verify"](i)
        st.record_verify(v)
        if v["success"]:
            st.finish(True, i == 1, "clean")
            return {"iterations": i, **calls, "decision": "STOP_SUCCESS",
                    "termination_reason": "recovered",
                    "llm_calls": calls["replan"],
                    "actions_total": blocked + calls["execute"],
                    "decision_log": [],
                    "truth_cleared": scn["truth"](i),
                    "erroneous_success": not scn["truth"](i)}
    st.finish(False, False, "contaminated",
              failure_reason="max_iter_exceeded",
              termination_reason="max_iter_exceeded")
    return {"iterations": MAX_ITER, **calls, "decision": "STOP_FAILURE",
            "termination_reason": "max_iter_exceeded",
            "llm_calls": calls["replan"], "actions_total": blocked,
            "decision_log": [], "truth_cleared": scn["truth"](MAX_ITER),
            "erroneous_success": False}


def run_v3v4(task: dict, scn: dict, dynamic: bool) -> dict:
    """V3（dynamic=False）与 V4（dynamic=True）：Policy Engine 循环。"""
    st = _mk_state(task)
    if not task["has_this_task"]:
        return {"iterations": 0, "replan": 0, "execute": 0, "verify": 0,
                "decision": "STOP_SUCCESS", "termination_reason": "recovered",
                "llm_calls": 0, "actions_total": 0, "decision_log": [],
                "truth_cleared": None, "erroneous_success": False}
    holder = {"plan": None}
    calls = {"replan": 0, "execute": 0, "verify": 0}

    def _replan():
        calls["replan"] += 1
        plan = scn["plan"](calls["replan"])
        holder["plan"] = plan
        if plan is None:
            return None
        sig = {t.get("mutation_id"): t.get("recovery_goal")
               for t in plan.get("tasks") or []}
        return "tasks.json", sig, plan

    def _execute():
        calls["execute"] += 1
        rec = scn["execute"](calls["execute"], holder["plan"],
                             contract=True)
        # 动作契约记录写入 state（供 _diagnose 读取执行证据）
        for a in rec.get("actions") or []:
            st.record_action(dict(a))
        return rec

    def _verify():
        calls["verify"] += 1
        return scn["verify"](calls["verify"])

    ledger_ro = rs.load_ledger_immutable(task["ledger_path"])
    final = pe.run_loop(st, replan=_replan, execute=_execute, verify=_verify,
                        observe=_verify,
                        reaudit=(lambda: {"reaudited": True})
                        if dynamic else None,
                        plan_validator=rt.validate_task_set,
                        ledger=ledger_ro, dynamic=dynamic)
    return {"iterations": final["iterations"],
            "replan": calls["replan"], "execute": calls["execute"],
            "verify": calls["verify"],
            "decision": final["decision"],
            "termination_reason": final["termination_reason"],
            "llm_calls": final["llm_calls"],
            "actions_total": final["actions_total"],
            "decision_log": [d["decision"] for d in final["decision_log"]],
            "truth_cleared": scn["truth"](calls["verify"]),
            "erroneous_success": (final["decision"] == "STOP_SUCCESS"
                                  and not scn["truth"](calls["verify"]))}


def run_version(version: str, task: dict, scn: dict) -> dict:
    if version == "V0":
        return run_v0(task, scn)
    if version == "V1":
        return run_v1(task, scn)
    if version == "V2":
        return run_v2(task, scn)
    if version == "V3":
        return run_v3v4(task, scn, dynamic=False)
    if version == "V4":
        return run_v3v4(task, scn, dynamic=True)
    raise ValueError(version)


# ============================================================ 场景注入

def make_scenarios(task: dict) -> dict[str, dict]:
    """构造确定性场景注入器（ground truth 明确，可复现）。

    所有场景对五个版本注入**完全相同**的 plan / execute / verify 结果，
    唯一区别是各版本控制机制不同 —— 结果差异可归因于 Harness。
    """
    # 场景定义基于当前任务的真实 targets 与真实 recovery_tasks
    tid_targets = [t["mutation_id"] for t in task["targets"]]
    real_plan = task["pset"]  # 完整任务集（结构校验需要）

    def _plan_fixed(i):
        # 返回完整任务集（schema/task_id/run_id/human_gate 保留），
        # 只把 tasks 过滤到授权目标 —— 与真实 pipeline replan 输出一致。
        # i>=2 时改变 recovery_goal（模拟真实 Planner 每轮可能给出不同方案），
        # 否则 V3/V4 的「计划重复拒绝」会把公平对照误伤。
        plan = dict(real_plan)
        plan["tasks"] = [t for t in real_plan.get("tasks") or []
                         if t.get("mutation_id") in tid_targets]
        if i >= 2:
            plan["tasks"] = [dict(t, **(
                {"recovery_goal": t.get("recovery_goal", "")
                 + f"（第 {i} 轮方案）"}) if t.get("mutation_id") in tid_targets
                else t) for t in plan["tasks"]]
        return plan

    def _execute_ok(i, plan, contract=False):
        return {"traj": {"history_action":
                         [{"action": "click", "params": {"position": [1, 2]}}],
                         "success": True},
                "task_dir": f"iter{i}", "final_img": f"iter{i}.png"}

    def _verify_ok(i):
        return {"success": True, "reason": "reaudit",
                "verdicts": [{"mutation_id": m, "cleared": True}
                             for m in tid_targets]}

    def _verify_fail(i):
        return {"success": False, "reason": "reaudit",
                "verdicts": [{"mutation_id": m, "cleared": False}
                             for m in tid_targets]}

    def _verify_uncertain(i):
        return {"success": False, "reason": "reaudit",
                "verdicts": [{"mutation_id": m, "cleared": None}
                             for m in tid_targets]}

    def _verify_first_fail(i):
        return _verify_ok(i) if i >= 2 else _verify_fail(i)

    # 场景定义（每个注入器 + ground truth 判定）
    scns = {
        "clean_first": {   # 第 1 轮执行即清除 → 所有版本都应第 1 轮成功
            "plan": _plan_fixed, "execute": _execute_ok,
            "verify": _verify_ok, "truth": lambda i: True,
        },
        "clear_round2": {  # 第 2 轮才清除 → V0-V2 盲执行第 1 轮，V3/V4 同
            "plan": _plan_fixed, "execute": _execute_ok,
            "verify": _verify_first_fail, "truth": lambda i: i >= 2,
        },
        "persistent_fail": {  # 始终未清除 → V0-V2 盲跑满，V3/V4 早停
            "plan": _plan_fixed, "execute": _execute_ok,
            "verify": _verify_fail, "truth": lambda i: False,
        },
        "verify_uncertain": {  # 验证不确定 → 不得宣布成功
            "plan": _plan_fixed, "execute": _execute_ok,
            "verify": _verify_uncertain, "truth": lambda i: False,
        },
    }
    return scns


# ============================================================ 汇总指标

def compute_metrics(rows: list[dict]) -> dict:
    """统一统计口径（阶段5 任务B/C）。

    分母定义（**无污染任务不混入任何恢复率分母**，truth_cleared=None）：
      contaminated    = 含 this_task 污染的任务（有恢复责任）
      denom_true      = 污染任务中注入 ground truth 显示污染确实被清除
      denom_false     = 污染任务中注入 ground truth 显示污染未被清除
    分子定义：
      恢复成功 final_recovery   = decision==STOP_SUCCESS 且 truth_cleared=True
      错误成功 erroneous_success = decision==STOP_SUCCESS 但 truth=False（误恢复）
      安全终止 safe_termination = decision!=STOP_SUCCESS 且 truth=False
                                  （正确不宣布成功）
      一次成功 first_try        = iterations==1 且恢复成功（污染任务）
    """
    contam = [r for r in rows if r.get("truth_cleared") is not None]
    # 人工门控任务（halted 目标，Policy 应转人工而非自主恢复）不进入
    # 自主恢复率分母；单列报告。
    auto = [r for r in contam if not r.get("halted")]
    denom_true = sum(1 for r in auto if r["truth_cleared"])
    denom_false = sum(1 for r in auto if not r["truth_cleared"])
    rec = [r for r in auto if r["decision"] == "STOP_SUCCESS"
           and r["truth_cleared"]]
    err = [r for r in auto if r["decision"] == "STOP_SUCCESS"
           and not r["truth_cleared"]]
    safe = [r for r in auto if r["decision"] != "STOP_SUCCESS"
            and not r["truth_cleared"]]
    needs_human = [r for r in contam
                   if r["decision"] == "STOP_NEEDS_HUMAN"]
    first = [r for r in rec if r["iterations"] == 1]
    max_iter = [r for r in auto
                if r["termination_reason"] == "max_iter_exceeded"]
    no_prog = [r for r in auto
               if r["termination_reason"] in ("no_progress", "repeated_plan")]
    replan = sum(r["replan"] for r in auto)
    execute = sum(r["execute"] for r in auto)
    verify = sum(r["verify"] for r in auto)
    llm = sum(r["llm_calls"] for r in auto)
    acts = sum(r["actions_total"] for r in auto)
    iters = [r["iterations"] for r in auto]
    return {
        "tasks": len(rows),
        "contaminated": len(contam),
        "halted_tasks": len(contam) - len(auto),
        "autonomous_tasks": len(auto),
        "truth_cleared_true": denom_true,
        "truth_cleared_false": denom_false,
        "final_recovery_rate":
            round(len(rec) / denom_true, 4) if denom_true else None,
        "erroneous_success_rate":
            round(len(err) / denom_false, 4) if denom_false else None,
        "safe_termination_rate":
            round(len(safe) / denom_false, 4) if denom_false else None,
        "needs_human_count": len(needs_human),
        "first_try_rate":
            round(len(first) / denom_true, 4) if denom_true else None,
        "avg_iterations":
            round(sum(iters) / len(contam), 4) if contam else None,
        "planner_calls": replan,
        "execute_calls": execute,
        "verify_calls": verify,
        "llm_calls_total": llm,
        "actions_total": acts,
        "max_iter_exceeded_ratio":
            round(len(max_iter) / len(contam), 4) if contam else None,
        "no_progress_iteration_ratio":
            round(len(no_prog) / len(contam), 4) if contam else None,
        "unexpected_terminations":
            [r["decision_log"] for r in contam
             if r["termination_reason"] in ("max_rounds", "replan_error")],
    }


# ============================================================ 故障注入（任务D）

def fault_injection(tasks: list[dict]) -> dict:
    """8 类故障场景回放：每类注入差异化执行证据/验证结果，V0-V4 都吃
    相同注入，检查预期响应（阶段5 任务D）。

    使用独立 ground truth（注入的真实清除状态）判定，不依赖 LLM 自报；
    也记录每类故障的 V4 预期响应供人工核验。
    """
    out = []
    # 取一个真实含污染任务做回放模板
    t0 = next(t for t in tasks if t["has_this_task"])
    tid = t0["task_id"]
    tid_targets = [x["mutation_id"] for x in t0["targets"]]
    real_plan = t0["pset"]

    def _p(i):
        plan = dict(real_plan)
        plan["tasks"] = [x for x in (real_plan.get("tasks") or [])
                         if x.get("mutation_id") in tid_targets]
        if i >= 2:
            plan["tasks"] = [dict(t, **(
                {"recovery_goal": t.get("recovery_goal", "")
                 + f"（第 {i} 轮方案）"}) if t.get("mutation_id") in tid_targets
                else t) for t in plan["tasks"]]
        return plan

    def _vf(i):
        return {"success": False, "reason": "reaudit",
                "verdicts": [{"mutation_id": m, "cleared": False}
                             for m in tid_targets]}

    def _vu(i):
        return {"success": False, "reason": "reaudit",
                "verdicts": [{"mutation_id": m, "cleared": None}
                             for m in tid_targets]}

    def _vo(i):
        return {"success": True, "reason": "reaudit",
                "verdicts": [{"mutation_id": m, "cleared": True}
                             for m in tid_targets]}

    def _act(**kw):
        base = {"action_id": "f.iter1.step1", "target_id": tid_targets[0],
                "action_type": "click", "execution_status": "executed",
                "gui_changed": "changed", "clearance": "not_cleared",
                "new_contamination_signal": False}
        base.update(kw)
        return base

    def _exe(acts):
        def _run(i, plan, contract=False):
            return {"traj": {"history_action":
                             [{"action": "click",
                               "params": {"position": [1, 2]}}],
                             "success": True},
                    "task_dir": f"iter{i}", "final_img": f"iter{i}.png",
                    "actions": acts}
        return _run

    cases = {
        # 1) 点击没有生效：executed/unchanged/not_cleared
        "click_no_effect": {"expected": "V3/V4 无进展早停（不重复盲跑）",
                            "plan": _p,
                            "execute": _exe([_act(gui_changed="unchanged",
                                                  clearance="not_cleared")]),
                            "verify": _vf, "truth": lambda i: False},
        # 2) 页面延迟更新：页面未变（unchanged）
        "page_delay_update": {"expected": "V3/V4 无进展早停",
                              "plan": _p,
                              "execute": _exe([_act(gui_changed="unchanged",
                                                    clearance="not_cleared")]),
                              "verify": _vf, "truth": lambda i: False},
        # 3) 控件位置变化：目标未找到 → 前置不成立
        "control_moved": {"expected": "V2+ precheck/校验拦截，不执行盲动",
                          "plan": _p,
                          "execute": _exe([_act(execution_status="blocked",
                                                gui_changed="unchanged",
                                                clearance="not_cleared")]),
                          "verify": _vf, "truth": lambda i: False},
        # 4) 初始污染清单与当前状态不一致：动作级证据显示已清除
        "ledger_stale": {"expected": "V4 证据足够直接终验（跳过第 2 轮执行）",
                         "plan": _p,
                         "execute": _exe([_act(clearance="cleared")]),
                         "verify": lambda i: _vo(i) if i >= 2 else _vf(i),
                         "truth": lambda i: i >= 2},
        # 5) 相同动作连续失败：execution_status=error ×2
        "same_action_repeat_fail": {
            "expected": "V4 tool_failure_run → OBSERVE 重新观察",
            "plan": _p,
            "execute": _exe([_act(execution_status="error",
                                  error_reason="adb timeout"),
                             _act(execution_status="error",
                                  error_reason="adb timeout")]),
            "verify": _vf, "truth": lambda i: False},
        # 6) 误将历史污染作为当前恢复目标：计划含 carried_over
        "historical_pollution_target": {
            "expected": "V2+ 授权检查拒绝越权目标（不执行）",
            "plan": lambda i: {"tasks": [x for x in (real_plan.get("tasks")
                                                     or [])
                                         if x.get("mutation_id") in
                                         tid_targets]
                               + [{"mutation_id": "c999",
                                   "recovery_goal": "处理历史遗留污染",
                                   "max_steps": 10}]},
            "execute": _exe([_act()]), "verify": _vf,
            "truth": lambda i: False},
        # 7) Planner 生成前置条件不成立的计划：结构校验拒绝
        "planner_invalid_precondition": {
            "expected": "V3/V4 计划校验拒绝 → REPLAN 或安全终止",
            "plan": lambda i: {"tasks": [{"mutation_id": tid_targets[0],
                                          "recovery_goal": "",
                                          "max_steps": 0}]},
            "execute": _exe([_act()]), "verify": _vf,
            "truth": lambda i: False},
        # 8) 验证证据不足：verdicts 不确定
        "verify_insufficient": {"expected": "V3/V4 OBSERVE 补证一次，"
                                            "不宣布成功",
                                "plan": _p,
                                "execute": _exe([_act()]),
                                "verify": _vu, "truth": lambda i: False},
    }
    for name, cfg in cases.items():
        scn = {"plan": cfg["plan"], "execute": cfg["execute"],
               "verify": cfg["verify"], "truth": cfg["truth"]}
        row = {"fault": name, "expected_v4_response": cfg["expected"],
               "versions": {v: run_version(v, t0, scn) for v in VERSIONS}}
        out.append(row)
    return out


# ============================================================ 主流程

def load_tasks(limit: int | None = None) -> list[dict]:
    tasks = []
    for tf in sorted(TASK_ROOT.glob("*_tasks.json")):
        tid = tf.name.replace("_tasks.json", "")
        lp = LEDGER_ROOT / f"{tid}_ledger.json"
        if not lp.exists():
            continue
        pset = json.loads(tf.read_text(encoding="utf-8"))
        ledger = json.loads(lp.read_text(encoding="utf-8"))
        tasks.append({
            "task_id": tid, "run_id": "base_canonical",
            "ledger_path": str(lp),
            "has_this_task": any(m.get("attribution") == "this_task"
                                 for m in ledger.get("mutations", [])),
            "targets": rs.build_target_states(
                rs.filter_targets(ledger)["targets"],
                tax.gate_decision(ledger)),
            "pset": pset,  # 完整任务集（结构校验需要 schema/task_id/human_gate）
            "tasks": pset.get("tasks") or [],
            "human_gate": pset.get("human_gate") or [],
        })
        if limit and len(tasks) >= limit:
            break
    return tasks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None, help="只取前 N 个任务")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    tasks = load_tasks(args.limit)
    print(f"任务数: {len(tasks)}，含 this_task 污染: "
          f"{sum(1 for t in tasks if t['has_this_task'])}")

    # 逐任务构造场景（每个任务用自己真实的 targets / recovery_tasks 注入，
    # 保证五个版本在相同任务上吃到完全相同的输入）
    scn_names = tuple(make_scenarios(tasks[0])) if tasks else ()
    detail, summary = [], {}
    for ver in VERSIONS:
        summary[ver] = {name: [] for name in scn_names}
    for t in tasks:
        scns = make_scenarios(t)
        halted = all(x.get("recovery_status") == "halted"
                     for x in t["targets"]) if t["targets"] else False
        for scn_name, scn in scns.items():
            for ver in VERSIONS:
                r = run_version(ver, t, scn)
                r["halted"] = halted
                detail.append({"task_id": t["task_id"], "scenario": scn_name,
                               "version": ver, **r})
                summary[ver][scn_name].append(r)
    summary = {ver: {name: compute_metrics(rows)
                     for name, rows in by_scn.items()}
               for ver, by_scn in summary.items()}

    faults = fault_injection(tasks)

    payload = {
        "schema": "version-comparison/v0.1",
        "setup": {
            "model": "qwen3-vl-plus（Audit/Planner 共用）",
            "max_iter": MAX_ITER,
            "dataset": "base_canonical（真实 ledger + recovery_tasks）",
            "injection": "确定性场景注入，无随机；可复现",
            "versions": {
                "V0": "原始 Workflow（固定循环，无约束）",
                "V1": "V0 + RecoveryState + Trace（决策不变）",
                "V2": "V1 + 动作契约（precheck/三分离）",
                "V3": "V2 + Policy Engine 静态版（dynamic=False）",
                "V4": "V3 + Harness 动态控制循环（dynamic=True）",
            },
        },
        "summary": summary,
        "fault_injection": faults,
        "detail": detail,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "comparison.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    (args.out / "fault_injection.json").write_text(
        json.dumps(faults, ensure_ascii=False, indent=2), encoding="utf-8")

    # 控制台汇总表
    print("\n=== 各版本 × 场景 指标（全部任务，同输入同注入）===")
    for ver in VERSIONS:
        for scn_name, m in summary[ver].items():
            print(f"{ver} {scn_name:18s} 恢复={m['final_recovery_rate']} "
                  f"误成功={m['erroneous_success_rate']} "
                  f"安全终止={m['safe_termination_rate']} "
                  f"一次={m['first_try_rate']} 迭代={m['avg_iterations']} "
                  f"planner={m['planner_calls']} exec={m['execute_calls']} "
                  f"verify={m['verify_calls']} llm={m['llm_calls_total']} "
                  f"意外终止={len(m['unexpected_terminations'])}")
    print(f"\n输出: {args.out / 'comparison.json'}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

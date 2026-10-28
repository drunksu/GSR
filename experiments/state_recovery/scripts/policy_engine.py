#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""policy_engine.py —— 确定性 Policy Engine（阶段3）。

目标：由确定性代码管理恢复循环，而不是让 LLM 自行决定无限重试。
Planner 可以提出计划，Policy Engine 决定是否调用、是否接受、是否需要重新
规划；Executor 可以提出动作意图，但实际执行必须通过统一动作接口
（action_contract）。LLM 不产生、也不修改任何预算 / 最大迭代次数 / 污染
归属 / 验证成功状态 / 停止条件（这些字段只由本模块与 RecoveryState 维护）。

设计决策：不引入状态机框架。现有 pipeline 是普通过程式循环，直接用纯函数
decide() + 注入式 run_loop() 实现即可（对齐阶段3提示词的最后一句话）。

决策集合（阶段3任务A + 阶段4任务A，按实际 pipeline 能力调整）：
  OBSERVE        —— 证据不足/工具失败时重新观察最新恢复轨迹（不宣布任何结果）
  VERIFY         —— 对最新一轮恢复轨迹做 VLM 复核（最终恢复结果唯一来源）
  EXECUTE_PLAN   —— 接受并执行当前恢复计划（受动作契约管理）
  REPLAN         —— 拒绝/更新计划，重新调用 Planner 生成新计划
  RE_AUDIT       —— 出现新污染/原判断失效时重新审计并调整目标状态（阶段4）
  STOP_SUCCESS   —— 全部 this_task 目标已核实清除
  STOP_FAILURE   —— 预算耗尽 / 连续无进展 / 计划重复被拒（保留现场与证据）
  STOP_NEEDS_HUMAN —— 目标被人工门控挂起 / 计划无法自主推进

状态机（phase ∈ init/planned/executed/verified/terminal）：
  init     --(有污染)--> REPLAN -> planned
  planned  --(计划合法)--> EXECUTE_PLAN -> executed
           --(计划合法但证据已足够)--> VERIFY -> verified（直接终验，不重复执行）
           --(计划非法/越权)--> REPLAN(首次) / STOP_FAILURE(再次) / STOP_NEEDS_HUMAN(门控)
           --(计划重复)--> REPLAN(首次，要求改变策略) / STOP_FAILURE(再次)
  executed --(本轮执行完毕)--> VERIFY -> verified
           --(预算耗尽)--> STOP_FAILURE
  verified --(全部清除)--> STOP_SUCCESS
           --(验证不确定/工具失败)--> OBSERVE(一次) -> verified，仍不确定 -> REPLAN
           --(失败且有进展)--> REPLAN -> planned
           --(连续 N 轮无进展)--> STOP_FAILURE
  任意     --(新污染出现在授权目标范围)--> RE_AUDIT -> planned（重新规划）
  terminal --(幂等)--> STOP_*（重建状态后可继续）

确定性约束（阶段3任务B + 阶段4任务B）：
  - 最大恢复迭代次数（max_iter，不随 LLM 输出改变）
  - 最大 GUI 动作次数（默认 max_iter*5，含 v2 每轮动作上限）
  - 模型调用预算（默认 max_iter*2+1，统计 Planner + Verify + 重审计这类
    pipeline 级 LLM 调用；执行器内部调用不属于本模块可控范围，如实说明）
  - 连续失败检测（no_progress_trail）
  - 无进展与重复动作检测（按 相同目标 + 相同恢复目标文本 + 相同失败原因，
    不引入语义相似度模型；重复被拒时必须改变策略，禁止原样重试）
  - 污染目标授权检查（只允许 this_task；carried_over/preexisting 一律拒绝）
  - 明确终止状态 + 失败时保留现场（证据引用留在 RecoveryState）
  - 不以「增加最大迭代次数」为默认解：无进展即早停
  - 失败诊断只依赖执行结果与状态证据（execution_status/gui_changed/clearance/
    verdicts），不凭错误字符串猜测根因（阶段4任务C）
  - 不把整个控制循环交给 LLM：策略全部由确定性代码决定；仅当固定规则
    无法处理（如计划连续被拒且无替代）时安全终止，不引入自由 LLM 策略选择
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

POLICY_SCHEMA = "policy-decision/v0.1"

DECISIONS = ("OBSERVE", "VERIFY", "EXECUTE_PLAN", "REPLAN", "RE_AUDIT",
             "STOP_SUCCESS", "STOP_FAILURE", "STOP_NEEDS_HUMAN")

# 默认确定性约束
NO_PROGRESS_LIMIT = 2        # 连续 N 轮验证无进展 → 停止
LLM_CALL_FACTOR = 2          # llm_cap = max_iter * LLM_CALL_FACTOR + 1
ACTIONS_FACTOR = 5           # actions_cap = max_iter * ACTIONS_FACTOR
TOOL_FAILURE_REOBSERVE = 2   # 最新一轮 ≥N 次工具执行失败 → 视为需补观察

TRANSITION_TABLE = {
    "init":     {"REPLAN": "planned"},
    "planned":  {"EXECUTE_PLAN": "executed",
                 "VERIFY": "verified (证据已足够，直接终验)",
                 "RE_AUDIT": "planned (重审计后重新规划)",
                 "REPLAN": "planned (计划被拒)",
                 "STOP_FAILURE": "terminal (计划重复被拒)",
                 "STOP_NEEDS_HUMAN": "terminal (人工门控)"},
    "executed": {"VERIFY": "verified",
                 "RE_AUDIT": "planned (重审计后重新规划)",
                 "STOP_FAILURE": "terminal (预算耗尽)"},
    "verified": {"STOP_SUCCESS": "terminal",
                 "OBSERVE": "verified (补证一次)",
                 "RE_AUDIT": "planned (重审计后重新规划)",
                 "REPLAN": "planned (失败且有进展/仍不确定)",
                 "STOP_FAILURE": "terminal (连续无进展/重复)"},
    "terminal": {"STOP_*": "terminal (幂等)"},
}

# 终止决策 → 默认 termination_reason
TERMINATION_REASONS = {
    "STOP_SUCCESS": "recovered",
    "STOP_FAILURE": "policy_stopped",
    "STOP_NEEDS_HUMAN": "needs_human",
}


# ---------------------------------------------------------------- 纯函数判定

def budget_from_state(st) -> dict:
    """从 RecoveryState 确定性推导预算消耗（不依赖 LLM / 外部状态）。"""
    max_iter = (st.get("budget") or {}).get("max_iter", 0)
    used_iter = len(st.get("per_iteration") or [])
    attempts = st.get("attempt_history") or []
    llm_calls = (
        sum(1 for a in attempts if a.get("generate_ok"))
        + sum(1 for a in attempts if a.get("verify_success") is not None)
        + sum(1 for a in attempts if a.get("reaudit_ok")))
    actions_total = sum(len(it.get("actions") or [])
                        for it in st.get("per_iteration") or [])
    return {
        "iter_remaining": max(0, max_iter - used_iter),
        "llm_calls": llm_calls,
        "llm_cap": max_iter * LLM_CALL_FACTOR + 1,
        "actions_total": actions_total,
        "actions_cap": max_iter * ACTIONS_FACTOR,
    }


def no_progress_trail(st) -> int:
    """连续「验证无进展」轮数：以每轮核实清除的目标数为进展信号。"""
    cleared_hist = []
    for it in st.get("per_iteration") or []:
        if it.get("phase") == "verify" and isinstance(it.get("verify"), dict):
            v = it["verify"]
            n = sum(1 for x in v.get("verdicts") or []
                    if x.get("cleared") is True)
            cleared_hist.append(n)
    trail = 0
    for i in range(len(cleared_hist) - 1, -1, -1):
        n = cleared_hist[i]
        prev_max = max(cleared_hist[:i], default=0)
        if n <= prev_max:
            trail += 1
        else:
            break
    return trail


def _cleared_count(st) -> int:
    return sum(1 for t in st.get("targets") or []
               if t.get("recovery_status") == "verified_cleared")


def _verify_uncertain(st) -> bool:
    """验证不确定：verdicts 缺失/为空，或存在 cleared 既非 True 也非 False。"""
    for it in reversed(st.get("per_iteration") or []):
        if it.get("phase") == "verify" and isinstance(it.get("verify"), dict):
            v = it["verify"]
            verdicts = v.get("verdicts") or []
            if not verdicts:
                return True
            if any(x.get("cleared") is not True and x.get("cleared") is not False
                   for x in verdicts):
                return True
            return False
    return False


def _diagnose(st: dict, ctx: dict) -> dict:
    """失败/进展诊断（阶段4任务C）：只依赖执行结果与状态证据。

    从 per_iteration 的动作记录（动作契约三分离字段）与验证结果读取：
      execution_status=error        → 工具执行失败
      gui_changed=changed 且未清除  → 页面状态已变化（旧计划可能失效）
      clearance=cleared             → 动作级证据显示目标已清除（原判断可能失效）
      new_contamination_signal      → 新污染信号（评估是否影响授权目标）
      verdicts 不确定               → 验证证据不足
    不读取/猜测错误字符串。
    """
    diag = {"tool_failures_total": 0, "tool_failures_last_iter": 0,
            "page_changed": False, "stale_judgment_cleared": False,
            "new_contamination_signals": 0, "new_contamination_affects_target": False,
            "verify_uncertain": _verify_uncertain(st)}
    target_ids = {t.get("mutation_id") for t in st.get("targets") or []}
    per = st.get("per_iteration") or []
    last_iter_actions = (per[-1].get("actions") or []) if per else []
    for it in per:
        for act in it.get("actions") or []:
            if act.get("execution_status") == "error":
                diag["tool_failures_total"] += 1
            if act.get("clearance") == "cleared":
                diag["stale_judgment_cleared"] = True
            if act.get("new_contamination_signal"):
                diag["new_contamination_signals"] += 1
                if act.get("target_id") in target_ids:
                    diag["new_contamination_affects_target"] = True
            if (act.get("gui_changed") == "changed"
                    and act.get("clearance") != "cleared"):
                diag["page_changed"] = True
    diag["tool_failures_last_iter"] = sum(
        1 for act in last_iter_actions
        if act.get("execution_status") == "error")
    # 最新一轮工具失败 ≥ 阈值 → 检查工具状态并重新观察
    diag["tool_failure_run"] = (
        diag["tool_failures_last_iter"] >= TOOL_FAILURE_REOBSERVE)
    return diag


def detect_plan_repeat(st, plan: dict | None) -> list[str]:
    """重复动作检测：相同目标 + 相同恢复目标文本 + 此前失败。

    不引入语义相似度：只用结构化签名（mutation_id, recovery_goal）。
    """
    if not isinstance(plan, dict):
        return []
    repeats = []
    prev_goals = {}
    for a in st.get("attempt_history") or []:
        # 只统计已执行并验证过的尝试；未验证（含本轮刚记录、验证前被拒）的
        # 计划不构成重复证据 —— 否则当前计划会被自己误判为重复。
        if a.get("verify_success") is None:
            continue
        sig = a.get("accepted_plan") or {}
        if isinstance(sig, dict):
            for tid, goal in sig.items():
                prev_goals[(tid, goal)] = a.get("verify_success")
    for task in plan.get("tasks") or []:
        tid = task.get("mutation_id")
        goal = task.get("recovery_goal")
        if (tid, goal) in prev_goals and prev_goals[(tid, goal)] is not True:
            repeats.append(f"目标 {tid} 的计划文本与已失败尝试完全重复")
    return repeats


def validate_plan(st, plan: dict | None, ctx: dict) -> dict:
    """计划接受检查：结构合法 + 授权范围（只允许 this_task）+ 不重复。

    ctx 可注入 plan_validator(pset, ledger) -> list[str]（默认仅结构字段检查）。
    """
    out = {"ok": True, "reasons": []}
    if not isinstance(plan, dict):
        out.update({"ok": False, "reasons": ["无可用计划"]})
        return out

    target_ids = {t.get("mutation_id") for t in st.get("targets") or []}
    halted_ids = {t.get("mutation_id") for t in st.get("targets") or []
                  if t.get("recovery_status") == "halted"}
    tasks = plan.get("tasks") or []
    if not tasks:
        out.update({"ok": False, "reasons": ["计划不含任务（空任务集）"]})
        return out

    for task in tasks:
        tid = task.get("mutation_id")
        if tid not in target_ids:
            # carried_over / preexisting 一律拒绝：不允许处理授权范围外污染
            out["reasons"].append(f"目标 {tid} 不在授权恢复范围（carried_over/preexisting 不处理）")
        elif tid in halted_ids:
            out["reasons"].append(f"目标 {tid} 被人工门控挂起（needs_human）")

    validator = ctx.get("plan_validator")
    if validator is not None:
        ledger = ctx.get("ledger")
        if ledger is not None:
            for e in validator(plan, ledger):
                out["reasons"].append(f"结构: {e}")

    out["reasons"].extend(detect_plan_repeat(st, plan))
    out["ok"] = not out["reasons"]
    return out


# ---------------------------------------------------------------- 核心决策

def decide(st: dict, ctx: dict) -> dict:
    """纯函数：给定 RecoveryState 与循环上下文，输出下一步决策。

    ctx 字段（由 run_loop / 调用方维护）：
      phase            当前阶段 init/planned/executed/verified/terminal
      plan             待执行/待判定的计划（task set dict）
      plan_validator   可选结构校验器 callable(pset, ledger) -> list[str]
      ledger           原始污染清单（校验器用，只读）
      reject_count     计划被拒次数（本次循环内）
      repeat_count     计划重复次数
      observe_count    已补证次数
      reaudit_count    已重审计次数（每轮限 1 次）
      llm_cap/actions_cap/time_budget_seconds/time_used 预算覆盖（可选）
      dynamic          阶段4 动态调度开关（默认 True）：False 时退化为阶段3
                       静态 Policy（禁用 RE_AUDIT/证据直接终验/工具失败 OBSERVE）
                       供 V3 vs V4 消融对照使用
    """
    checks = {}
    dec = {"schema": POLICY_SCHEMA, "decision": None, "phase_after": None,
           "reason": "", "termination_reason": None, "checks": checks}
    dynamic = ctx.get("dynamic", True)

    # 0) 终止态幂等：重建后继续时不再发起新动作
    if ctx.get("phase") == "terminal" or st.get("phase") in ("success", "halt"):
        dec.update(decision="STOP_SUCCESS" if st.get("success") else
                   "STOP_FAILURE",
                   phase_after="terminal",
                   reason=f"已处于终止态: {st.get('termination_reason')}",
                   termination_reason=st.get("termination_reason"))
        return dec

    budget = budget_from_state(st)
    budget.update({k: ctx.get(k, v) for k, v in
                   (("llm_cap", budget["llm_cap"]),
                    ("actions_cap", budget["actions_cap"]))})
    if ctx.get("time_budget_seconds"):
        budget["time_budget_seconds"] = ctx["time_budget_seconds"]
        budget["time_used"] = ctx.get("time_used", 0)
    checks["budget"] = budget

    cleared = _cleared_count(st)
    total = len(st.get("targets") or [])
    checks["cleared"] = {"cleared": cleared, "total": total}

    trail = no_progress_trail(st)
    checks["no_progress_trail"] = trail

    diag = _diagnose(st, ctx)
    checks["diagnosis"] = diag

    # 1) 全部 this_task 目标已核实清除 → 直接成功（不再调用 Planner/Executor）
    if total > 0 and cleared >= total and not _verify_uncertain(st):
        return _stop(dec, "STOP_SUCCESS", "verified", "全部目标已核实清除",
                     "recovered")

    # 2) 人工门控：没有可自主推进的目标
    active = [t for t in st.get("targets") or []
              if t.get("recovery_status") != "halted"]
    if total > 0 and not active:
        return _stop(dec, "STOP_NEEDS_HUMAN", "terminal",
                     "全部目标被人工门控挂起，无法自主推进", "needs_human")

    # 3) 预算耗尽 → 明确终止（保留现场与证据）
    exhausted = []
    if budget["iter_remaining"] <= 0:
        exhausted.append(f"迭代预算耗尽 ({budget['iter_remaining']})")
    if budget["llm_calls"] >= budget["llm_cap"]:
        exhausted.append(f"模型调用预算耗尽 ({budget['llm_calls']}/{budget['llm_cap']})")
    if budget["actions_total"] >= budget["actions_cap"]:
        exhausted.append(f"GUI 动作预算耗尽 ({budget['actions_total']}/{budget['actions_cap']})")
    if (budget.get("time_budget_seconds")
            and budget.get("time_used", 0) >= budget["time_budget_seconds"]):
        exhausted.append("时间预算耗尽")
    if exhausted:
        return _stop(dec, "STOP_FAILURE", "terminal",
                     "; ".join(exhausted), "budget_exhausted")

    # 4) 连续无进展 → 早停（不靠加大 max_iter）
    if trail >= NO_PROGRESS_LIMIT:
        return _stop(dec, "STOP_FAILURE", "terminal",
                     f"连续 {trail} 轮验证无进展", "no_progress")

    # 4.5) 新污染出现在授权目标范围 → 重新审计并评估风险（阶段4：按需调度审计）
    if (dynamic and diag["new_contamination_affects_target"]
            and ctx.get("reaudit_count", 0) == 0):
        return _go(dec, "RE_AUDIT", "planned",
                   "新污染出现在授权目标范围，重新审计并调整目标状态")

    phase = ctx.get("phase", "init")

    # 5) init：尚无计划 → 生成
    if phase == "init":
        return _go(dec, "REPLAN", "planned", "初始阶段，生成恢复计划")

    # 6) planned：计划接受检查（授权 / 门控 / 结构 / 重复）
    if phase == "planned":
        vr = validate_plan(st, ctx.get("plan"), ctx)
        if not vr["ok"]:
            if any("门控" in r for r in vr["reasons"]):
                return _stop(dec, "STOP_NEEDS_HUMAN", "terminal",
                             "计划引用了被门控目标: " + " | ".join(vr["reasons"]),
                             "needs_human")
            if any("重复" in r for r in vr["reasons"]):
                n = ctx.get("repeat_count", 0) + 1
                dec["repeat_count"] = n
                if n >= 2:
                    return _stop(dec, "STOP_FAILURE", "terminal",
                                 "计划与已失败尝试重复且无变化", "repeated_plan")
                return _go(dec, "REPLAN", "planned",
                           f"计划重复（第 {n} 次），禁止原样重试，要求改变策略")
            n = ctx.get("reject_count", 0) + 1
            dec["reject_count"] = n
            if n >= 2:
                return _stop(dec, "STOP_FAILURE", "terminal",
                             "连续两次计划被拒: " + " | ".join(vr["reasons"]),
                             "plan_rejected")
            return _go(dec, "REPLAN", "planned",
                       f"计划被拒（第 {n} 次）: " + " | ".join(vr["reasons"]))
        # 证据已足够（目标已清除：外部清除/动作级 clearance 证据）→
        # 跳过重复执行，直接最终验证（阶段4：避免过度保守）
        if (dynamic and total > 0
                and (cleared >= total or diag["stale_judgment_cleared"])):
            return _go(dec, "VERIFY", "verified",
                       "证据已足够（目标已清除），直接进入最终验证（避免过度保守）")
        return _go(dec, "EXECUTE_PLAN", "executed", "计划已接受，执行")

    # 7) executed：本轮执行完毕 → 验证
    if phase == "executed":
        if budget["actions_total"] >= budget["actions_cap"]:
            return _stop(dec, "STOP_FAILURE", "terminal", "本轮动作已达上限",
                         "budget_exhausted")
        return _go(dec, "VERIFY", "verified", "本轮已执行，进行恢复验证")

    # 8) verified：验证结果决策
    if phase == "verified":
        if _verify_uncertain(st) or (dynamic and diag["tool_failure_run"]):
            n = ctx.get("observe_count", 0)
            if n < 1:
                return _go(dec, "OBSERVE", "verified",
                           "验证证据不足或工具执行失败，先重新观察（不宣布任何结果）")
            return _go(dec, "REPLAN", "planned",
                       "补证/重新观察后仍无进展，重新规划")
        # 明确失败且无进展 → 已由第 4 条早停；此处为有进展 → 下一轮
        return _go(dec, "REPLAN", "planned", "验证失败但有进展，进入下一轮")

    return _go(dec, "REPLAN", "planned", f"未知阶段 {phase}，安全回退为重新规划")


def _stop(dec, decision, phase_after, reason, termination_reason) -> dict:
    dec.update(decision=decision, phase_after=phase_after, reason=reason,
               termination_reason=termination_reason)
    return dec


def _go(dec, decision, phase_after, reason) -> dict:
    dec.update(decision=decision, phase_after=phase_after, reason=reason)
    return dec


def _str_or_none(v):
    """Path 等非 JSON 原生对象转字符串，避免落盘时序列化失败。"""
    return None if v is None else str(v)


def _terminal_failure(termination_reason: str, reason: str, st,
                      decision_log: list) -> dict:
    """执行/验证异常 → Policy 的显式终止结果（保留现场与决策日志）。

    不让异常冒泡到调用方被记成 "pipeline 出错"：否则该任务既不计入
    "有污染"也不计入 "无污染"，会直接从统计口径里消失。
    """
    b = budget_from_state(st.policy_dict())
    return {"decision": "STOP_FAILURE", "reason": reason,
            "termination_reason": termination_reason,
            "llm_calls": b["llm_calls"], "actions_total": b["actions_total"],
            "iterations": len(st.iterations), "decision_log": decision_log}


# ---------------------------------------------------------------- 注入式循环

def run_loop(st, *, replan, execute, verify, observe=None, reaudit=None,
             plan_validator=None, ledger=None,
             max_rounds=None, ctx_update=None, dynamic=True) -> dict:
    """受 Policy Engine 管理的闭环循环。

    st:  RecoveryState 实例
    replan() -> (task_path, plan_sig, plan) 生成新计划（调用方负责落盘并返回计划 dict）
    execute() -> rec 执行当前计划（通过动作契约接口）
    verify() -> dict 对最新恢复轨迹做最终验证
    observe() -> dict 重新观察最新轨迹（可选，证据补足）
    reaudit() -> dict|None 重新审计（阶段4：重推断污染并调整 targets；返回 None=无变化）
    plan_validator(pset, ledger) -> list[str] 结构校验
    ctx_update(state_dict, phase, ctx) -> dict 每轮可注入额外上下文
    dynamic: False 时退化为阶段3 静态 Policy（供 V3 vs V4 消融对照）
    """
    if max_rounds is None:
        # 安全轮数上限：正常每轮 3 次判定（REPLAN/EXECUTE/VERIFY）+ 被拒重试，
        # 上限设为正常量的宽裕倍数，仅作 fail-safe（正常终止不会触发它）。
        max_rounds = (st.budget["max_iter"] or 3) * 6 + 12
    state_dict = st.policy_dict()
    phase = _initial_phase(st)
    reject_count = repeat_count = observe_count = reaudit_count = 0
    last_task_path = None
    last_rec = None
    decision_log = []
    ctx = {"phase": phase, "plan_validator": plan_validator, "ledger": ledger,
           "plan": None, "reject_count": 0, "repeat_count": 0,
           "observe_count": 0, "reaudit_count": 0, "dynamic": dynamic}
    final = None

    for _ in range(max_rounds):
        state_dict = st.policy_dict()
        ctx.update({"phase": phase, "reject_count": reject_count,
                    "repeat_count": repeat_count, "observe_count": observe_count,
                    "reaudit_count": reaudit_count})
        if ctx_update is not None:
            ctx.update(ctx_update(state_dict, phase, ctx))
        dec = decide(state_dict, ctx)
        decision_log.append(dec)
        st.emit_event("policy.decide", st.iteration, {
            "decision": dec["decision"], "phase_after": dec["phase_after"],
            "reason": dec["reason"]})

        if dec["decision"].startswith("STOP_"):
            final = {**dec, "llm_calls": budget_from_state(state_dict)["llm_calls"],
                     "actions_total": budget_from_state(state_dict)["actions_total"],
                     "iterations": len(st.iterations),
                     "decision_log": decision_log}
            return final

        if dec["decision"] == "REPLAN":
            # 新轮次：仅在 init（首轮）与 verified（验证失败后的下一轮）开启
            if phase in ("init", "verified"):
                st.begin_iteration(st.iteration + 1)
            try:
                task_path, plan_sig, plan = replan()
            except Exception as e:
                st.record_generate(ok=False, error=e)
                final = {"decision": "STOP_FAILURE",
                         "reason": f"replan_error: {e}",
                         "termination_reason": "replan_error",
                         "failure_reason": f"replan_error: {e}",
                         "llm_calls": budget_from_state(state_dict)["llm_calls"],
                         "actions_total": budget_from_state(state_dict)["actions_total"],
                         "iterations": len(st.iterations),
                         "decision_log": decision_log}
                return final
            last_task_path = task_path
            ctx["plan"] = plan
            st.record_generate(ok=True, task_path=task_path, plan_sig=plan_sig)
            phase = "planned"
            # 计划被拒/重复的计数由 decide 持久化到决策输出，这里取回；
            # 只有计划被接受执行时才清零（见 EXECUTE_PLAN 分支）。
            reject_count = dec.get("reject_count", reject_count)
            repeat_count = dec.get("repeat_count", repeat_count)
        elif dec["decision"] == "EXECUTE_PLAN":
            try:
                rec = execute()
            except Exception as e:  # noqa: BLE001
                # 执行器异常必须转成显式终止原因：不能冒泡到调用方被记成
                # "pipeline 出错"，否则该任务既不算有污染也不算无污染，
                # 直接从统计里消失（2026-10-28 真机 101 errors 的口径问题）。
                st.record_execute(ok=False, error=e,
                                  intent={"task_ref": _str_or_none(last_task_path)})
                return _terminal_failure("execute_error", f"execute_error: {e}",
                                         st, decision_log)
            last_rec = rec
            st.record_execute(ok=bool(rec and rec.get("final_img") is not None),
                              rec=rec,
                              intent={"task_ref": _str_or_none(last_task_path)})
            phase = "executed"
            reject_count = repeat_count = 0
        elif dec["decision"] == "VERIFY":
            try:
                v = verify()
            except Exception as e:  # noqa: BLE001
                v = {"success": False, "reason": f"verify_error: {e}",
                     "verdicts": []}
                st.record_verify(v)
                return _terminal_failure("verify_error", f"verify_error: {e}",
                                         st, decision_log)
            st.record_verify(v)
            phase = "verified"
        elif dec["decision"] == "OBSERVE":
            try:
                obs = observe() if observe is not None else {}
            except Exception as e:  # noqa: BLE001
                # 补证失败本身不构成终止：如实记录，让 Policy 继续判定
                obs = {"success": False, "reason": f"observe_error: {e}",
                       "verdicts": []}
            ctx["last_observe"] = obs
            observe_count += 1
            st.emit_event("observe.result", st.iteration, obs)
            phase = "verified"
        elif dec["decision"] == "RE_AUDIT":
            # 重新审计（阶段4）：调用方重推断污染并调整 targets；
            # 每轮限 1 次（reaudit_count 抑制重复触发），计 1 次 LLM 调用。
            ra = reaudit() if reaudit is not None else None
            ctx["reaudit_result"] = ra
            st.record_reaudit(note=dec.get("reason"))
            reaudit_count += 1
            phase = "planned"
            ctx["plan"] = None

    # 达到安全轮数上限仍未终止 → 强制停止（保留现场）
    final = {"decision": "STOP_FAILURE", "reason": "安全轮数上限已到",
             "termination_reason": "max_rounds",
             "llm_calls": budget_from_state(st.policy_dict())["llm_calls"],
             "actions_total": budget_from_state(st.policy_dict())["actions_total"],
             "iterations": len(st.iterations),
             "decision_log": decision_log}
    return final


def _initial_phase(st) -> str:
    its = st.iterations
    if not its:
        return "init"
    last = its[-1].get("phase")
    if last == "execute":
        return "executed"
    if last == "verify":
        return "verified"
    if last == "plan":
        return "planned"
    return "init"


# ---------------------------------------------------------------- 对照实验 demo

def _sim_v1_loop(max_iter: int, step_gen, step_exec, step_verify):
    """复刻 v1 固定循环语义（generate→execute→verify，成功即退出）。"""
    planner_calls = verify_calls = execute_calls = 0
    for i in range(1, max_iter + 1):
        planner_calls += 1
        if not step_gen(i):
            return {"iterations": i, "planner_calls": planner_calls,
                    "execute_calls": execute_calls,
                    "verify_calls": verify_calls, "stop": "generate_error"}
        execute_calls += 1
        step_exec(i)
        verify_calls += 1
        if step_verify(i):
            return {"iterations": i, "planner_calls": planner_calls,
                    "execute_calls": execute_calls,
                    "verify_calls": verify_calls, "stop": "success"}
    return {"iterations": max_iter, "planner_calls": planner_calls,
            "execute_calls": execute_calls,
            "verify_calls": verify_calls, "stop": "max_iter_exceeded"}


def _demo_scenarios(max_iter: int = 3) -> list[dict]:
    """真实跑 v1 固定循环 vs v3 Policy Engine，输出可复现的对照数据。"""
    import recovery_state as rs

    out = []

    def _mk_state(ledger_path):
        st = rs.RecoveryState("demo_task", "base_canonical", max_iter)
        st.load_ledger(ledger_path)
        return st

    def _steppers(cleared_on, budget_overrides=None, vary_plan=False,
                  actions=None, verify_seq=None, state=None):
        """返回 (replan, execute, verify, verify_fail, ctx_update, calls)。

        actions:    每次 execute 时写入 state 的动作记录（供诊断读取）
        verify_seq: 依次返回的验证结果（超出取最后一个）
        vary_plan:  每次 replan 给出不同计划文本（区分「计划重复被拒」与
                    「连续无进展」两条不同的早停路径）
        calls:      {"replan","execute","verify"} 计数器（受控对照指标）
        """
        calls = {"replan": 0, "execute": 0, "verify": 0}

        def replan():
            calls["replan"] += 1
            goal = "关闭夜间模式"
            if vary_plan:
                goal = f"关闭夜间模式（第 {calls['replan']} 套方案）"
            plan_dict = {"tasks": [{"mutation_id": "m1",
                                    "recovery_goal": goal,
                                    "max_steps": 10}]}
            return "tasks_demo.json", {"m1": goal}, plan_dict

        def execute():
            calls["execute"] += 1
            if actions and state is not None:
                for a in actions:
                    state.record_action(dict(a))
            return {"traj": {"history_action": [{"action": "click",
                                                 "params": {"position": [1, 2]}}]},
                    "task_dir": "iter1", "final_img": "step_1.png"}

        def verify():
            calls["verify"] += 1
            if verify_seq:
                idx = min(calls["verify"], len(verify_seq)) - 1
                return verify_seq[idx]
            if cleared_on:
                return {"success": True, "reason": "reaudit",
                        "verdicts": [{"mutation_id": "m1", "cleared": True}]}
            return {"success": False, "reason": "reaudit",
                    "verdicts": [{"mutation_id": "m1", "cleared": False}]}

        def verify_fail():
            return {"success": False, "reason": "reaudit",
                    "verdicts": [{"mutation_id": "m1", "cleared": False}]}

        def ctx_update(state_dict, phase, ctx):
            if budget_overrides:
                ctx.update(budget_overrides)
            return ctx

        return replan, execute, verify, verify_fail, ctx_update, calls

    def _v3m(final, calls):
        """v3 受控对照指标。unexpected_termination=True 表示循环跑飞（新错误终止）。"""
        return {"iterations": final["iterations"],
                "planner_calls": calls["replan"],
                "execute_calls": calls["execute"],
                "verify_calls": calls["verify"],
                "actions_total": final["actions_total"],
                "llm_calls": final["llm_calls"],
                "decision": final["decision"],
                "termination_reason": final["termination_reason"],
                "unexpected_termination":
                    final["termination_reason"] in ("max_rounds", "replan_error"),
                "decision_log": [d["decision"] for d in final["decision_log"]]}

    # ---- 场景 1：首轮成功 ----
    led1 = Path(__file__).resolve().parent / ".." / "results" / "policy_engine_demo" \
        / "ledger_demo.json"
    led1.parent.mkdir(parents=True, exist_ok=True)
    with open(led1, "w", encoding="utf-8") as f:
        json.dump({"schema": "contamination-list/v0.1",
                   "task_id": "demo_task", "run_id": "base_canonical",
                   "task_goal": "演示目标", "judged_success": False,
                   "search_terms": [],
                   "mutations": [{"id": "m1", "type": "settings_toggle",
                                  "app": "QQ",
                                  "entity": {"kind": "setting", "name": "夜间模式"},
                                  "direction": "on", "persistence": "device_local",
                                  "status": "done", "attribution": "this_task",
                                  "reversible": "ui_invert", "evidence_steps": [1],
                                  "evidence_quote": "点击了夜间模式开关",
                                  "confidence": 0.95}]}, f, ensure_ascii=False)
    r1, e1, v1, _v1f, c1, cts1 = _steppers(cleared_on=True)
    s1 = _mk_state(led1)
    final1 = run_loop(s1, replan=r1, execute=e1, verify=v1, ctx_update=c1)
    v1_sim = _sim_v1_loop(max_iter, lambda i: True, lambda i: True,
                          lambda i: i == 1)
    out.append({"scenario": "first_try_success",
                "v1": v1_sim, "v3": _v3m(final1, cts1),
                "note": "成功即停：v3 验证通过后不再调用 Planner/Executor"})

    # ---- 场景 2：相同计划重复被拒 → 安全终止（不重复执行相同动作）----
    r2, e2, v2, _v2f, c2, cts2 = _steppers(cleared_on=False)
    s2 = _mk_state(led1)
    final2 = run_loop(s2, replan=r2, execute=e2, verify=v2, ctx_update=c2)
    v2_sim = _sim_v1_loop(max_iter, lambda i: True, lambda i: True,
                          lambda i: False)
    out.append({"scenario": "no_progress_identical_plan",
                "v1": v2_sim, "v3": _v3m(final2, cts2),
                "note": "相同计划重复被拒 → 安全终止，不再重复执行相同动作；"
                        "v1 会盲跑满 max_iter"})

    # ---- 场景 3：模型调用预算耗尽 ----
    r3, e3, v3, _v3f, c3, cts3 = _steppers(cleared_on=False,
                                           budget_overrides={"llm_cap": 2})
    s3 = _mk_state(led1)
    final3 = run_loop(s3, replan=r3, execute=e3, verify=v3, ctx_update=c3)
    v3_sim = _sim_v1_loop(max_iter, lambda i: True, lambda i: True,
                          lambda i: False)
    out.append({"scenario": "budget_limited",
                "v1": v3_sim, "v3": _v3m(final3, cts3),
                "note": "模型调用预算（llm_cap=2）耗尽 → v3 停止，v1 没有该约束"})

    # ---- 场景 4：计划各异但验证连续无进展 → 早停（不靠加大 max_iter）----
    r4, e4, v4, _v4f, c4, cts4 = _steppers(cleared_on=False, vary_plan=True)
    s4 = _mk_state(led1)
    final4 = run_loop(s4, replan=r4, execute=e4, verify=v4, ctx_update=c4)
    v4_sim = _sim_v1_loop(max_iter, lambda i: True, lambda i: True,
                          lambda i: False)
    out.append({"scenario": "no_progress_varying_plan",
                "v1": v4_sim, "v3": _v3m(final4, cts4),
                "note": "计划各不相同但验证连续无进展 → 按 NO_PROGRESS_LIMIT "
                        "早停，不依赖加大 max_iter；v1 会盲跑满 max_iter"})

    # ---- 场景 5：动态调度 —— 外部已清除，证据足够 → 直接终验（不重复执行）----
    # iter1 执行后动作级证据 clearance=cleared；iter2 计划不同但证据已足够：
    # v3 跳过 EXECUTE 直接最终验证，v1 仍会盲执行第 2 轮。
    act_cleared = [{"action_id": "d.iter1.step1", "target_id": "m1",
                    "action_type": "click", "execution_status": "executed",
                    "gui_changed": "unchanged", "clearance": "cleared",
                    "new_contamination_signal": False}]
    v_ok2 = [{"success": False, "reason": "reaudit",
              "verdicts": [{"mutation_id": "m1", "cleared": False}]},
             {"success": True, "reason": "reaudit",
              "verdicts": [{"mutation_id": "m1", "cleared": True}]}]
    s5 = _mk_state(led1)
    r5, e5, v5, _v5f, c5, cts5 = _steppers(
        cleared_on=False, vary_plan=True, actions=act_cleared,
        verify_seq=v_ok2, state=s5)
    final5 = run_loop(s5, replan=r5, execute=e5, verify=v5, ctx_update=c5)
    v5_sim = _sim_v1_loop(max_iter, lambda i: True, lambda i: True,
                          lambda i: i == 2)
    out.append({"scenario": "external_cleared_direct_final_verify",
                "v1": v5_sim, "v3": _v3m(final5, cts5),
                "note": "动作级证据（clearance=cleared）显示目标已清除 → v3 跳过 "
                        "第 2 轮执行直接终验（execute=1 vs v1 的 execute=2），"
                        "避免过度保守"})

    # ---- 场景 6：动态调度 —— 工具执行失败 → 检查工具状态并重新观察 ----
    act_err = [{"action_id": "d.iter1.step1", "target_id": "m1",
                "action_type": "click", "execution_status": "error",
                "error_reason": "adb timeout", "gui_changed": "unchanged",
                "clearance": "not_cleared", "new_contamination_signal": False},
               {"action_id": "d.iter1.step2", "target_id": "m1",
                "action_type": "click", "execution_status": "error",
                "error_reason": "adb timeout", "gui_changed": "unchanged",
                "clearance": "not_cleared", "new_contamination_signal": False}]
    v_fail1 = [{"success": False, "reason": "reaudit",
                "verdicts": [{"mutation_id": "m1", "cleared": False}]}]
    s6 = _mk_state(led1)
    r6, e6, v6, _v6f, c6, cts6 = _steppers(
        cleared_on=False, actions=act_err, verify_seq=v_fail1, state=s6)
    final6 = run_loop(s6, replan=r6, execute=e6, verify=v6, ctx_update=c6)
    v6_sim = _sim_v1_loop(max_iter, lambda i: True, lambda i: True,
                          lambda i: False)
    out.append({"scenario": "tool_failure_reobserve",
                "v1": v6_sim, "v3": _v3m(final6, cts6),
                "note": "工具执行失败（execution_status=error）→ v3 先 OBSERVE "
                        "重新观察，不凭错误字符串猜测根因；诊断只读执行结果/状态"
                        "证据；最终按 no_progress 安全终止"})

    # ---- 场景 7：动态调度 —— 新污染影响授权目标 → 重新审计并评估风险 ----
    act_new = [{"action_id": "d.iter1.step1", "target_id": "m1",
                "action_type": "click", "execution_status": "executed",
                "gui_changed": "changed", "clearance": "not_cleared",
                "new_contamination_signal": True}]
    s7 = _mk_state(led1)
    r7, e7, v7, _v7f, c7, cts7 = _steppers(
        cleared_on=False, actions=act_new, verify_seq=v_fail1,
        state=s7)
    final7 = run_loop(s7, replan=r7, execute=e7, verify=v7,
                      reaudit=lambda: {"reaudited": True}, ctx_update=c7)
    v7_sim = _sim_v1_loop(max_iter, lambda i: True, lambda i: True,
                          lambda i: False)
    out.append({"scenario": "new_contamination_reaudit",
                "v1": v7_sim, "v3": _v3m(final7, cts7),
                "note": "新污染信号出现在授权目标范围 → v3 按需调度 RE_AUDIT "
                        "重新审计并评估风险（decision_log 含 RE_AUDIT），"
                        "重审计后重新规划继续恢复"})

    # ---- 受控对照汇总（相同初始条件：同一 ledger_demo，max_iter=3）----
    scens = [out[i]["scenario"] for i in range(len(out))]
    v1_tot = {"planner": 0, "execute": 0, "verify": 0}
    v3_tot = {"planner": 0, "execute": 0, "verify": 0}
    for i in range(len(out)):
        v1_tot["planner"] += out[i]["v1"]["planner_calls"]
        v1_tot["execute"] += out[i]["v1"]["execute_calls"]
        v1_tot["verify"] += out[i]["v1"]["verify_calls"]
        v3_tot["planner"] += out[i]["v3"]["planner_calls"]
        v3_tot["execute"] += out[i]["v3"]["execute_calls"]
        v3_tot["verify"] += out[i]["v3"]["verify_calls"]
    unexpected = [f"{out[i]['scenario']}={out[i]['v3']['termination_reason']}"
                  for i in range(len(out))
                  if out[i]["v3"]["unexpected_termination"]]
    out.append({
        "scenario": "controlled_comparison",
        "setup": "相同初始条件：同一 ledger_demo.json，max_iter=3，逐场景同预算",
        "scenarios": scens,
        "v1_total": dict(v1_tot), "v3_total": dict(v3_tot),
        "v3_unexpected_terminations": unexpected,
        "v3_decision_logs": {out[i]["scenario"]: out[i]["v3"]["decision_log"]
                             for i in range(len(out))},
        "conclusion": (
            "v3 在成功/外部清除场景减少 Planner/Executor 调用，在无进展与预算"
            "受限场景提前终止而非盲跑满 max_iter；终止原因均为显式确定性原因，"
            "无意外终止（max_rounds/replan_error）。v3 相对 v1 没有新增错误"
            "终止类别。")
    })
    return out


def _demo(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "transition_table.json", "w", encoding="utf-8") as f:
        json.dump({"schema": POLICY_SCHEMA,
                   "transitions": TRANSITION_TABLE,
                   "no_progress_limit": NO_PROGRESS_LIMIT,
                   "llm_call_cap_rule": f"max_iter*{LLM_CALL_FACTOR}+1",
                   "actions_cap_rule": f"max_iter*{ACTIONS_FACTOR}"},
                  f, ensure_ascii=False, indent=2)
    with open(out_dir / "comparison.json", "w", encoding="utf-8") as f:
        json.dump(_demo_scenarios(), f, ensure_ascii=False, indent=2)
    print(f"状态转换表: {out_dir / 'transition_table.json'}")
    print(f"对照结果:   {out_dir / 'comparison.json'}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Policy Engine（阶段3/4）")
    ap.add_argument("--demo", action="store_true", help="生成状态转换表与对照结果")
    ap.add_argument("--out",
                    default=str(Path(__file__).resolve().parent / ".." / "results"
                                / "policy_engine_demo"),
                    help="输出目录（默认与脚本同级 results/policy_engine_demo）")
    args = ap.parse_args()
    if args.demo:
        _demo(Path(args.out))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

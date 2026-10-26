#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recovery_state.py —— 显式 RecoveryState：恢复闭环的确定性运行时状态（阶段1完整规格）。

设计要点（对齐阶段1需求）：
  - 状态对象含 recovery_id / task_id / run_id / phase / iteration / budget /
    targets / attempt_history / termination_reason；
  - targets：每项目标污染（仅 attribution=this_task）独立记录
    污染 ID 与原始条目引用 / 初始期望状态 / 当前恢复状态 / 已尝试次数 /
    最近一次验证状态 / 证据引用 / 最近一次失败原因；
    污染的当前状态（contamination_status）与恢复尝试结果（attempt_result）
    分开表达，不用单一 success/failed 字段混用；
  - 状态迁移只允许确定性代码执行；LLM 只产生内容（恢复目标、验证判定），
    不产生也不修改任何可信状态字段；
  - 原始污染清单（ledger）只读加载 + 严格校验，绝不回写（load_ledger_immutable）；
    carried_over / preexisting 只作为上下文（context）保留，不列入 targets；
  - 序列化结果与旧 *_pipeline.json 字段完全兼容（additive only），
    新增字段仅在 --trace 开启时输出；
  - 可选挂接 TraceLogger：record_* 方法自动发事件，保证每轮状态与决策可追溯。
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import mutation_taxonomy as tax

STATE_SCHEMA = "recovery-state/v0.1"

# 允许的阶段取值（确定性枚举）
PHASES = ("plan", "execute", "verify", "success", "halt", "error")
# 允许的终态取值
FINAL_STATES = ("clean", "contaminated", "pending", "error")
# 污染当前状态（对目标实体的判定）
CONTAMINATION_STATUS = ("present", "present_unconfirmed", "absent", "unknown")
# 恢复尝试结果
ATTEMPT_RESULT = ("not_attempted", "success", "failure", "noop", "blocked")
# 单个目标恢复状态
RECOVERY_STATUS = ("pending", "in_progress", "verified_cleared", "failed",
                   "halted", "not_dispatched")


def summarize_recovery_traj(traj: dict, task_dir: str) -> dict:
    """从恢复执行轨迹中确定性提取动作摘要（不依赖任何模型文本/判断）。"""
    actions = traj.get("history_action") or []
    images = traj.get("history_image_path") or []
    steps = []
    for i, act in enumerate(actions):
        if isinstance(act, dict):
            action_type = act.get("action", "")
            params = act.get("params") or {}
            if isinstance(params, dict):
                target = (params.get("text")
                          or params.get("position")
                          or params.get("id"))
            else:
                target = None
        else:
            action_type = str(act)
            target = None
        steps.append({
            "step_index": i,
            "action": action_type,
            "target": target,
            "screenshot": images[i] if i < len(images) else None,
        })
    return {
        "task_dir": task_dir,
        "step_count": len(actions),
        "steps": steps,
        "executor_success_flag": traj.get("success"),
        # 注意：executor_success_flag 只是执行器返回标志，不是恢复成功的证据。
    }


def load_ledger_immutable(path) -> dict:
    """只读加载污染清单并严格校验；格式非法时抛出明确错误，绝不静默修复关键字段。

    返回的 dict 视为不可变：任何下游（含 targets 构造）都只读它，
    本模块从不写回原始污染 JSON。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"污染清单不存在: {p}")
    with open(p, encoding="utf-8") as f:
        ledger = json.load(f)
    errs = tax.validate_ledger(ledger)
    if errs:
        raise ValueError(
            f"污染清单格式非法（不静默修复）: {p}\n  " + "\n  ".join(errs))
    return ledger


def expected_clean_state(mutation: dict) -> dict:
    """确定性推导目标的初始期望状态（不调用 LLM）。

    仅使用 mutation 的 type / entity / direction 等结构化字段。
    """
    mtype = mutation.get("type", "other")
    entity = mutation.get("entity") or {}
    name = entity.get("name") or entity.get("identifier") or mutation.get("id")
    direction = mutation.get("direction")
    if mtype == "search_history":
        return {"kind": "no_search_entry", "entity_name": name,
                "description": f"搜索历史中不再存在条目 {name}"}
    if mtype == "settings_toggle":
        desired = "off" if str(direction).lower() in ("on", "true", "active") else "on"
        return {"kind": f"setting_{desired}", "entity_name": name,
                "description": f"设置项 {name} 应处于 {desired} 状态"}
    if mtype == "relationship_request":
        return {"kind": "no_pending_request", "entity_name": name,
                "description": f"不存在待处理的好友申请（{name}）"}
    if mtype == "membership_change":
        return {"kind": "not_member", "entity_name": name,
                "description": f"不再属于该群/成员关系（{name}）"}
    if mtype == "content_lifecycle":
        return {"kind": "content_absent", "entity_name": name,
                "description": f"内容 {name} 已被删除/撤销"}
    if mtype == "message_send":
        return {"kind": "not_sent", "entity_name": name,
                "description": f"消息 {name} 已不存在于会话"}
    if mtype == "social_reaction":
        return {"kind": "not_reacted", "entity_name": name,
                "description": f"社交反应（关注/点赞/收藏）已取消（{name}）"}
    if mtype == "session_state":
        return {"kind": "session_closed", "entity_name": name,
                "description": f"会话/页面状态已恢复（{name}）"}
    if mtype == "login_session":
        return {"kind": "logged_out", "entity_name": name,
                "description": f"登录态已退出（{name}）"}
    return {"kind": "manual_check", "entity_name": name,
            "description": f"需人工确认的清理目标（{name}）"}


def filter_targets(ledger: dict) -> dict:
    """把污染清单拆成「恢复目标（this_task）」与「上下文（carried/preexisting）」。

    不修改 ledger；目标条目以深拷贝保存原始引用。
    """
    targets = []
    context = []
    for m in ledger.get("mutations", []):
        attr = m.get("attribution")
        if attr == "this_task":
            targets.append(m)
        else:
            entity = m.get("entity") or {}
            context.append({
                "mutation_id": m.get("id"),
                "attribution": attr,
                "carried_over_from_task": m.get("carried_over_from_task"),
                "entity_name": entity.get("name"),
                "type": m.get("type"),
            })
    return {"targets": targets, "context": context}


def build_target_states(target_mutations: list, gate: dict) -> list[dict]:
    """为目标 mutation 构造初始 TargetState 记录。

    gate 为 tax.gate_decision(ledger) 的结果（{"autonomous": [...], "halt": [...]}）。
    """
    halt_ids = {h.get("id") for h in gate.get("halt", [])}
    out = []
    for m in target_mutations:
        out.append({
            "mutation_id": m.get("id"),
            "mutation_ref": copy.deepcopy(m),          # 原始条目引用（副本，不共享可变）
            "initial_expected_state": expected_clean_state(m),
            "contamination_status": "present",
            "recovery_status": ("halted" if m.get("id") in halt_ids
                                else "pending"),
            "attempts": 0,
            "last_verify": None,
            "evidence_refs": [],
            "last_failure_reason": None,
        })
    return out


class RecoveryState:
    """单个任务的恢复闭环状态。所有字段由确定性代码写入。"""

    def __init__(self, task_id: str, run: str, max_iter: int):
        self.schema = STATE_SCHEMA
        self.recovery_id = f"{task_id}.{run}.{int(time.time())}"
        self.task_id = task_id
        self.run_id = run
        self.phase = "init"
        self.iteration = 0
        self.budget = {"max_iter": max_iter, "remaining": max_iter}
        self.trajectory_path: str | None = None
        self.ledger_path: str | None = None
        self.recovery_task: str | None = None
        self.has_contamination: bool | None = None
        self.targets: list[dict] = []
        self.context: list[dict] = []
        self.attempt_history: list[dict] = []
        self.iterations: list[dict] = []
        self.success = False
        self.first_try_success = False
        self.final_state = "pending"
        self.failure_reason: str | None = None
        self.termination_reason: str | None = None
        self.trace_enabled = False
        self._trace = None

    # ---- Trace 挂接 ----

    def attach_trace(self, logger) -> None:
        self._trace = logger
        self.trace_enabled = logger is not None
        self._trace_emit("state.init", 0, {
            "recovery_id": self.recovery_id,
            "max_iter": self.budget["max_iter"],
        })

    def emit_event(self, etype: str, iteration: int, payload: dict) -> None:
        """向已挂接的 Trace 追加自定义事件（只读记录，不改变任何状态字段）。"""
        self._trace_emit(etype, iteration, payload)

    def _trace_emit(self, etype: str, iteration: int, payload: dict) -> None:
        if self._trace is not None:
            self._trace.emit(etype, iteration, payload)

    # ---- 污染清单加载（只读 + 严格校验）----

    def load_ledger(self, ledger_path) -> None:
        """严格只读加载：非法格式抛明确错误，不静默修复。"""
        ledger = load_ledger_immutable(ledger_path)
        self.ledger_path = str(ledger_path)
        split = filter_targets(ledger)
        self.targets = build_target_states(split["targets"],
                                           tax.gate_decision(ledger))
        self.context = split["context"]
        self.has_contamination = bool(self.targets)
        self._trace_emit("state.ledger_loaded", 0, {
            "ledger": str(ledger_path),
            "target_count": len(self.targets),
            "context_count": len(self.context),
            "target_ids": [t["mutation_id"] for t in self.targets],
            "context_ids": [c["mutation_id"] for c in self.context],
        })

    # ---- 状态迁移（只允许确定性代码调用）----

    def begin_iteration(self, i: int) -> None:
        self.iteration = i
        self.phase = "plan"
        self.budget["remaining"] = self.budget["max_iter"] - i + 1
        self.iterations.append({"iter": i, "phase": "plan"})
        self.attempt_history.append({
            "iteration": i,
            "accepted_plan": None,
            "plan_reason": None,
            "generate_ok": None,
            "execute_ok": None,
            "verify_success": None,
            "error": None,
        })
        self._trace_emit("state.updated", i, self._state_snapshot())

    def record_generate(self, ok: bool, task_path=None, error=None,
                        plan_sig=None) -> None:
        it = self._current()
        att = self._current_attempt()
        it["phase"] = "plan"
        it["generate_ok"] = bool(ok)
        att["generate_ok"] = bool(ok)
        if ok:
            it["recovery_task"] = str(task_path)
            self.recovery_task = str(task_path)
            if plan_sig is not None:
                # 计划签名 {mutation_id: recovery_goal}：供 Policy Engine 做
                # 重复计划/重复动作检测（可随状态重建）
                it["accepted_plan"] = plan_sig
                att["accepted_plan"] = plan_sig
            self._trace_emit("planner.output", self.iteration, {
                "task_set": str(task_path),
                "accepted": True,
                "reason": "validate_task_set passed",
            })
        else:
            it["error"] = str(error)
            att["error"] = str(error)
            self._trace_emit("plan.rejected", self.iteration, {
                "reason": f"generate_error: {error}",
            })
        self._trace_emit("state.updated", self.iteration, self._state_snapshot())

    def record_reaudit(self, note: str | None = None) -> None:
        """记录一次重新审计（阶段4 Policy Engine）。

        重审计由确定性诊断触发（新污染影响授权目标等），调用方负责真正
        重推断污染并调整 targets；这里只记账：计入模型调用预算、
        写 trace 事件，供 Trace 重建决策过程。
        """
        it = self._current()
        att = self._current_attempt()
        it["reaudit"] = {"count": (it.get("reaudit") or {}).get("count", 0) + 1,
                         "note": note}
        att["reaudit_ok"] = True
        self._trace_emit("audit.reaudit", self.iteration, {
            "note": note,
        })
        self._trace_emit("state.updated", self.iteration, self._state_snapshot())

    def record_execute(self, ok: bool, rec=None, error=None, intent=None) -> None:
        it = self._current()
        att = self._current_attempt()
        it["phase"] = "execute"
        it["execute_ok"] = bool(ok)
        att["execute_ok"] = bool(ok)
        if error is not None:
            it["error"] = str(error)
            att["error"] = str(error)
        if rec is not None:
            it["final_screenshot"] = rec.get("final_img")
            it["recovery_task_dir"] = rec.get("task_dir")
            it["trajectory"] = summarize_recovery_traj(rec["traj"], rec.get("task_dir"))
        if intent is not None:
            it["intent"] = intent
        # 更新目标态：执行过即视为 in_progress，attempts +1
        for t in self.targets:
            if t["recovery_status"] in ("pending", "in_progress", "failed"):
                t["recovery_status"] = "in_progress"
                t["attempts"] += 1
        if rec is not None and rec.get("task_dir"):
            for t in self.targets:
                t["evidence_refs"].append(str(rec["task_dir"]))
        self._trace_emit("execute.result", self.iteration, {
            "execute_ok": bool(ok),
            "task_dir": (rec or {}).get("task_dir"),
            "final_screenshot": (rec or {}).get("final_img"),
            "error": str(error) if error is not None else None,
        })
        self._trace_emit("state.updated", self.iteration, self._state_snapshot())

    def record_action(self, record: dict) -> None:
        """追加一条动作契约记录（阶段2 Harness）到当前迭代。

        record 由 action_contract.compose_record() 生成；只做记录，
        不改变任何可信状态字段（恢复结果仍由 record_verify 判定）。
        """
        it = self._current()
        it.setdefault("actions", []).append(copy.deepcopy(record))
        self._trace_emit("execute.action", self.iteration, {
            "action_id": record.get("action_id"),
            "action_type": record.get("action_type"),
            "target_id": record.get("target_id"),
            "execution_status": record.get("execution_status"),
            "gui_changed": record.get("gui_changed"),
            "clearance": record.get("clearance"),
            "new_contamination_signal": record.get("new_contamination_signal"),
        })

    def record_verify(self, verify: dict) -> None:
        it = self._current()
        att = self._current_attempt()
        it["phase"] = "verify"
        it["verify"] = verify
        att["verify_success"] = bool(verify.get("success"))
        # 按 verdicts 逐目标更新：污染的当前状态 vs 恢复尝试结果分开记录
        for v in verify.get("verdicts", []):
            tid = v.get("mutation_id")
            for t in self.targets:
                if t["mutation_id"] == tid:
                    cleared = v.get("cleared")
                    t["last_verify"] = {
                        "round": self.iteration,
                        "verdict": copy.deepcopy(v),
                    }
                    t["contamination_status"] = (
                        "absent" if cleared is True
                        else "present" if cleared is False
                        else "unknown")
                    t["recovery_status"] = (
                        "verified_cleared" if cleared is True else "failed")
                    if cleared is not True:
                        t["last_failure_reason"] = (
                            "VLM 判定污染仍存在/无法确认")
        self._trace_emit("verify.result", self.iteration, {
            "success": bool(verify.get("success")),
            "reason": verify.get("reason"),
            "verdicts": verify.get("verdicts"),
        })
        self._trace_emit("state.updated", self.iteration, self._state_snapshot())

    def finish(self, success: bool, first_try: bool,
               final_state: str, failure_reason=None,
               termination_reason=None) -> None:
        self.success = bool(success)
        self.first_try_success = bool(first_try)
        self.final_state = final_state
        self.failure_reason = failure_reason
        self.termination_reason = (
            termination_reason
            or ("recovered" if self.success
                else "max_iter_exceeded" if isinstance(failure_reason, str)
                and failure_reason.startswith("max_iter")
                else "error" if failure_reason
                else "no_contamination"))
        self.phase = "success" if self.success else "halt"
        self._trace_emit("state.terminated", self.iteration, {
            "success": self.success,
            "final_state": self.final_state,
            "termination_reason": self.termination_reason,
            "failure_reason": self.failure_reason,
            "iterations": len(self.iterations),
        })

    # ---- 序列化 ----

    def _current(self) -> dict:
        if not self.iterations:
            raise RuntimeError("begin_iteration() 必须先于任何 record_* 调用")
        return self.iterations[-1]

    def _current_attempt(self) -> dict:
        if not self.attempt_history:
            raise RuntimeError("begin_iteration() 必须先于任何 record_* 调用")
        return self.attempt_history[-1]

    def _state_snapshot(self) -> dict:
        return {
            "phase": self.phase,
            "iteration": self.iteration,
            "budget_remaining": self.budget["remaining"],
            "targets": [{"mutation_id": t["mutation_id"],
                         "recovery_status": t["recovery_status"],
                         "contamination_status": t["contamination_status"],
                         "attempts": t["attempts"]} for t in self.targets],
        }

    def policy_dict(self) -> dict:
        """供 Policy Engine（阶段3）使用的完整状态视图。

        与 to_dict(extended) 不同：不受 --trace 门控影响 —— Policy 判定
        必须始终能读到 targets / budget / attempt_history / per_iteration，
        即使最终落盘文件仍按 trace 门控输出扩展字段（保持旧兼容性）。
        """
        return {
            "schema": self.schema,
            "phase": self.phase,
            "success": self.success,
            "termination_reason": self.termination_reason,
            "budget": self.budget,
            "targets": self.targets,
            "context": self.context,
            "attempt_history": self.attempt_history,
            "per_iteration": self.iterations,
        }

    def to_dict(self, extended: bool = True) -> dict:
        """base 字段与旧 *_pipeline.json 完全兼容（additive only）。

        extended=True 时追加 targets/budget/attempt_history 等扩展字段；
        是否扩展由调用方（run_pipeline 的 extended = trace or harness v2/v3）
        决定，不再受 TraceLogger 是否挂接影响 —— v2/v3 模式即使不开 --trace，
        也必须落盘完整状态以便失败后重建续跑。
        """
        d = {
            "schema": self.schema,
            "task_id": self.task_id,
            "run": self.run_id,
            "trajectory": self.trajectory_path,
            "ledger": self.ledger_path,
            "recovery_task": self.recovery_task,
            "has_contamination": self.has_contamination,
            "iterations": len(self.iterations),
            "success": self.success,
            "first_try_success": self.first_try_success,
            "final_state": self.final_state,
            "failure_reason": self.failure_reason,
            "per_iteration": self.iterations,
        }
        if extended:
            d.update({
                "recovery_id": self.recovery_id,
                "phase": self.phase,
                "budget": self.budget,
                "targets": self.targets,
                "context": self.context,
                "attempt_history": self.attempt_history,
                "termination_reason": self.termination_reason,
            })
        return d

    def save(self, path, extended: bool = True) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(extended), f, ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "RecoveryState":
        st = cls(d.get("task_id", ""), d.get("run", ""),
                 (d.get("budget") or {}).get("max_iter", 0))
        st.recovery_id = d.get("recovery_id", st.recovery_id)
        st.trajectory_path = d.get("trajectory")
        st.ledger_path = d.get("ledger")
        st.recovery_task = d.get("recovery_task")
        st.has_contamination = d.get("has_contamination")
        st.success = d.get("success", False)
        st.first_try_success = d.get("first_try_success", False)
        st.final_state = d.get("final_state", "pending")
        st.failure_reason = d.get("failure_reason")
        st.phase = d.get("phase", "init")
        st.termination_reason = d.get("termination_reason")
        st.targets = copy.deepcopy(d.get("targets") or [])
        st.context = copy.deepcopy(d.get("context") or [])
        st.attempt_history = copy.deepcopy(d.get("attempt_history") or [])
        st.iterations = copy.deepcopy(d.get("per_iteration") or [])
        st.iteration = len(st.iterations)
        if d.get("budget"):
            st.budget = copy.deepcopy(d["budget"])
        # 扩展字段存在即视为 trace 模式（保证 round-trip 后 extended 序列化不丢字段）
        st.trace_enabled = ("budget" in d and "targets" in d)
        return st


def validate_state(d: dict) -> list[str]:
    """校验 RecoveryState 序列化结果，返回违规清单（空 = 合法）。"""
    errs: list[str] = []
    if not isinstance(d, dict):
        return ["recovery state must be a dict"]
    if d.get("schema") != STATE_SCHEMA:
        errs.append(f"schema must be {STATE_SCHEMA!r}, got {d.get('schema')!r}")
    for key in ("task_id", "run", "trajectory", "ledger", "recovery_task",
                "has_contamination", "iterations", "success",
                "first_try_success", "final_state", "failure_reason"):
        if key not in d:
            errs.append(f"missing required key {key!r}")
    if d.get("final_state") not in FINAL_STATES:
        errs.append(f"final_state invalid: {d.get('final_state')!r}")
    for it in d.get("per_iteration") or []:
        if it.get("phase") not in PHASES:
            errs.append(f"iteration phase invalid: {it.get('phase')!r}")
        if it.get("generate_ok") is None and it.get("execute_ok") is None:
            errs.append(f"iteration missing generate_ok/execute_ok: {it!r}")
        acts = it.get("actions")
        if acts is not None and not isinstance(acts, list):
            errs.append(f"iteration actions must be a list: {it!r}")
    # 扩展字段（trace 开启时存在）：逐目标校验
    for t in d.get("targets") or []:
        if t.get("recovery_status") not in RECOVERY_STATUS:
            errs.append(f"target recovery_status invalid: {t.get('recovery_status')!r}")
        if t.get("contamination_status") not in CONTAMINATION_STATUS:
            errs.append(
                f"target contamination_status invalid: "
                f"{t.get('contamination_status')!r}")
        if "mutation_id" not in t or "mutation_ref" not in t:
            errs.append(f"target missing mutation_id/mutation_ref: {t!r}")
    if d.get("budget") and not isinstance(d.get("budget"), dict):
        errs.append(f"budget must be a dict, got {d.get('budget')!r}")
    return errs

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recovery_task.py —— Recovery Task（恢复任务）的枚举、schema 与校验。

版本：recovery-task-set/v0.1（与 docs/design.md §4 同步；改 schema 必须升版本号）。

命名说明：内部实现沿用旧变量名 packet/ledger，产品与文档口径分别为
「恢复任务（recovery task）」「污染清单（contamination list）」。

只依赖标准库，generate_tasks.py 与 score_tasks.py 共用这里的定义。
设计口径（2026-10-10 与负责人确认）：
  - 逐任务触发：只为污染清单里 attribution=this_task 的变更产出处置；
    carried_over / preexisting 不在本任务重复处理。
  - gate.autonomous 的变更产出可自动执行的恢复任务；
  - gate.halt 的变更只产出可读的人工挂起条目（human_gate），不自动执行。
"""

from __future__ import annotations

TASK_SET_SCHEMA = "recovery-task-set/v0.1"
TASK_SCHEMA = "recovery-task/v0.1"

RISK_LEVELS = ("low", "medium", "high")
ASSERTION_KINDS = ("vlm_judge",)
ASSERTION_EXPECTED = ("yes", "no")

MAX_STEPS_MIN, MAX_STEPS_MAX = 5, 25

# 可逆性类别 → 自动恢复任务的风险等级
REVERSIBILITY_RISK = {
    "ui_invert": "low",        # 开关/收藏/点赞/关注，再点一下即可
    "cancel_pending": "medium",  # 取消待审批申请，涉及对方可见状态
    "delete_created": "medium",  # 删除本任务自己创建的内容
}


def _norm(s) -> str:
    return "".join(str(s).split()).lower() if s is not None else ""


def _mutation_index(ledger: dict) -> dict:
    return {m.get("id"): m for m in ledger.get("mutations", [])}


def _this_task_ids(ledger: dict, kind: str) -> set:
    """本任务自己造成、且在指定 gate 列表里的变更 id。"""
    ids = {x["id"] if isinstance(x, dict) else x
           for x in ledger.get("_gate", {}).get(kind, [])}
    return {i for i in ids
            if (ledger.get("mutations") and
                _mutation_index(ledger).get(i, {}).get("attribution") == "this_task")}


def expected_autonomous_ids(ledger: dict) -> set:
    """应该生成自动恢复任务的全部 id（this_task ∩ gate.autonomous）。"""
    return _this_task_ids(ledger, "autonomous")


def expected_halt_ids(ledger: dict) -> set:
    """应该进入人工挂起清单的全部 id（this_task ∩ gate.halt）。"""
    return _this_task_ids(ledger, "halt")


def validate_task(pkt: dict, mutation: dict) -> list[str]:
    """校验单个恢复任务与其对应污染清单变更一致。返回错误列表，空 = 合法。"""
    errs: list[str] = []
    mid = mutation.get("id", "?")
    pfx = f"tasks[{mid}]"
    if not isinstance(pkt, dict):
        return [f"{pfx}: object required"]
    if pkt.get("schema") != TASK_SCHEMA:
        errs.append(f"{pfx}.schema must be {TASK_SCHEMA!r}, got {pkt.get('schema')!r}")
    if pkt.get("mutation_id") != mid:
        errs.append(f"{pfx}.mutation_id must be {mid!r}")

    goal = pkt.get("recovery_goal")
    if not isinstance(goal, str) or len(goal.strip()) < 8:
        errs.append(f"{pfx}.recovery_goal: 非空中文恢复指令（≥8 字）")

    # 实体接地：目标里必须逐字带上 App、实体名、硬标识（若污染清单有）
    ent = mutation.get("entity") or {}
    name = ent.get("name")
    ident = ent.get("identifier")
    app = mutation.get("app")
    if isinstance(goal, str):
        if app and _norm(app) not in _norm(goal):
            errs.append(f"{pfx}.recovery_goal 必须包含 App 名 {app!r}（接地）")
        if name and _norm(name) not in _norm(goal):
            errs.append(f"{pfx}.recovery_goal 必须逐字包含实体名 {name!r}（接地）")
        if ident and _norm(ident) not in _norm(goal):
            errs.append(f"{pfx}.recovery_goal 必须逐字包含硬标识 {ident!r}（接地，"
                        f"防止恢复操作找错对象）")

    # 风险等级必须与可逆性类别一致；自动恢复任务不允许 high
    risk = pkt.get("risk_level")
    want_risk = REVERSIBILITY_RISK.get(mutation.get("reversible"))
    if risk not in RISK_LEVELS:
        errs.append(f"{pfx}.risk_level invalid: {risk!r}")
    elif want_risk and risk != want_risk:
        errs.append(f"{pfx}.risk_level 应为 {want_risk!r}"
                    f"（reversible={mutation.get('reversible')}），got {risk!r}")
    elif risk == "high":
        errs.append(f"{pfx}: 高风险变更不允许产出自动恢复任务，应进 human_gate")

    # 前置检查：三段齐全；clean_if_state 必须明确写出"已干净长什么样"
    pre = pkt.get("precondition")
    if not isinstance(pre, dict):
        errs.append(f"{pfx}.precondition: object required")
    else:
        for k in ("target", "check_instruction", "clean_if_state"):
            v = pre.get(k)
            if not isinstance(v, str) or len(v.strip()) < 4:
                errs.append(f"{pfx}.precondition.{k}: 非空描述（≥4 字）")
        ci = pre.get("check_instruction", "")
        if isinstance(ci, str) and name and _norm(name) not in _norm(ci):
            errs.append(f"{pfx}.precondition.check_instruction 必须提到检查对象 "
                        f"{name!r}（接地）")

    # 终态断言：可由独立 VLM 用 yes/no 判定的具体问题，且必须提到检查对象
    ass = pkt.get("expected_end_state")
    if not isinstance(ass, dict):
        errs.append(f"{pfx}.expected_end_state: object required")
    else:
        if ass.get("kind") not in ASSERTION_KINDS:
            errs.append(f"{pfx}.expected_end_state.kind must be in {ASSERTION_KINDS}")
        q = ass.get("question")
        if not isinstance(q, str) or len(q.strip()) < 8 or "？" not in q + "?" \
                and "?" not in q:
            errs.append(f"{pfx}.expected_end_state.question: 必须是完整问句（含问号）")
        elif name and _norm(name) not in _norm(q) and not (
                ident and _norm(ident) in _norm(q)):
            errs.append(f"{pfx}.expected_end_state.question 必须提到实体 "
                        f"{name or ident!r}（断言接地，避免答非所问）")
        if ass.get("expected") not in ASSERTION_EXPECTED:
            errs.append(f"{pfx}.expected_end_state.expected must be "
                        f"one of {ASSERTION_EXPECTED}")

    steps = pkt.get("max_steps")
    if not isinstance(steps, int) or not (MAX_STEPS_MIN <= steps <= MAX_STEPS_MAX):
        errs.append(f"{pfx}.max_steps: int in [{MAX_STEPS_MIN},{MAX_STEPS_MAX}]")
    if pkt.get("idempotent") is not True:
        errs.append(f"{pfx}.idempotent 必须为 true（前置检查保证幂等）")
    return errs


def validate_human_gate(item: dict, mutation: dict, gate_reason: str) -> list[str]:
    """校验人工挂起条目。返回错误列表。"""
    errs: list[str] = []
    mid = mutation.get("id", "?")
    pfx = f"human_gate[{mid}]"
    if not isinstance(item, dict):
        return [f"{pfx}: object required"]
    if item.get("mutation_id") != mid:
        errs.append(f"{pfx}.mutation_id must be {mid!r}")
    for k in ("title", "reason", "suggested_manual_action"):
        v = item.get(k)
        if not isinstance(v, str) or len(v.strip()) < 4:
            errs.append(f"{pfx}.{k}: 非空中文描述（≥4 字）")
    # 挂起理由要与门控实际判定一致，不允许生成器自创理由
    if item.get("gate_reason") != gate_reason:
        errs.append(f"{pfx}.gate_reason 必须照污染清单门控填写 {gate_reason!r}，"
                    f"got {item.get('gate_reason')!r}")
    sug = item.get("suggested_manual_action", "")
    ent = mutation.get("entity") or {}
    if isinstance(sug, str):
        if ent.get("name") and _norm(ent["name"]) not in _norm(sug):
            errs.append(f"{pfx}.suggested_manual_action 必须提到实体 "
                        f"{ent['name']!r}（接地）")
    return errs


def validate_task_set(pset: dict, ledger: dict) -> list[str]:
    """校验整份恢复任务集与污染清单一致。返回错误列表，空 = 合法。"""
    errs: list[str] = []
    if not isinstance(pset, dict):
        return ["task set is not an object"]
    if pset.get("schema") != TASK_SET_SCHEMA:
        errs.append(f"schema must be {TASK_SET_SCHEMA!r}")
    for k in ("task_id", "run_id"):
        if pset.get(k) != ledger.get(k):
            errs.append(f"{k}: 必须与污染清单一致（{ledger.get(k)!r}）")

    midx = _mutation_index(ledger)
    want_auto = expected_autonomous_ids(ledger)
    want_halt = expected_halt_ids(ledger)

    tasks = pset.get("tasks")
    if not isinstance(tasks, list):
        errs.append("tasks: list required")
        tasks = []
    got_auto = set()
    for pkt in tasks:
        pid = pkt.get("mutation_id") if isinstance(pkt, dict) else None
        if pid not in midx:
            errs.append(f"tasks: mutation_id {pid!r} 不在污染清单中")
            continue
        if pid not in want_auto:
            errs.append(f"tasks[{pid}]: 该变更不应自动恢复"
                        f"（carried/preexisting 或在门控挂起列表）")
        got_auto.add(pid)
        errs.extend(validate_task(pkt, midx[pid]))
    missing = want_auto - got_auto
    if missing:
        errs.append(f"缺少自动恢复任务: {sorted(missing)}")

    gate = ledger.get("_gate", {})
    reason_by_id = {h["id"]: h.get("reason", "")
                    for h in gate.get("halt", []) if isinstance(h, dict)}
    human = pset.get("human_gate")
    if not isinstance(human, list):
        errs.append("human_gate: list required")
        human = []
    got_halt = set()
    for item in human:
        hid = item.get("mutation_id") if isinstance(item, dict) else None
        if hid not in midx:
            errs.append(f"human_gate: mutation_id {hid!r} 不在污染清单中")
            continue
        if hid not in want_halt:
            errs.append(f"human_gate[{hid}]: 该变更不应进入本任务人工清单"
                        f"（非 this_task 或门控未要求挂起）")
        got_halt.add(hid)
        errs.extend(validate_human_gate(item, midx[hid], reason_by_id.get(hid, "")))
    missing_h = want_halt - got_halt
    if missing_h:
        errs.append(f"缺少人工挂起条目: {sorted(missing_h)}（硬门控项必须可见）")
    return errs

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mutation_taxonomy.py —— 污染清单（contamination list）的枚举、schema 与校验。

版本：contamination-list/v0.1（与 docs/design.md §3 同步；改 schema 必须升版本号）。

命名说明：内部变量/落盘文件名沿用 ledger，产品与文档口径为「污染清单」。

只依赖标准库，infer_mutations.py 与 score_inference.py 共用这里的定义。
"""

from __future__ import annotations

# 内部常量名保留 LEDGER_SCHEMA；产品名 contamination-list/v0.1
LEDGER_SCHEMA = "contamination-list/v0.1"

# contamination-list/v0.1：由 mutation-ledger/v0.2 更名（字段不变）；
# 每条变更带 attribution（this_task/carried_over/preexisting），
# 用于利用前序任务污染清单做状态归因（design.md §3.3）

ATTRIBUTIONS = ("this_task", "carried_over", "preexisting")

# 置信度低于此阈值的变更禁止自主执行，只进人工门控
MIN_AUTONOMOUS_CONFIDENCE = 0.7

MUTATION_TYPES = (
    "settings_toggle",      # 夜间/深色/关怀/长辈/备孕模式、无痕、阅读模式
    "relationship_request", # 加好友请求
    "membership_change",    # 加群/退群
    "content_lifecycle",    # 创建/删除笔记、日程、帖子
    "message_send",         # 发消息（不可逆）
    "social_reaction",      # 关注/点赞/收藏
    "session_state",        # 播放、导航、页面栈（Home 即清）
    "search_history",       # 搜索框输入残留
    "login_session",        # 登录态
    "other",                # 兜底：必须低置信度 + 引原文
)

PERSISTENCE_LEVELS = ("server", "account", "device_local", "session")

STATUSES = ("done", "pending", "attempted_unknown", "not_done")

# 可逆性类别 → 是否允许执行器自主恢复
REVERSIBILITY = ("ui_invert", "cancel_pending", "counterparty", "delete_created",
                 "irreversible", "unknown")
# counterparty（删好友/退群，可能影响对方账号）与 irreversible（发消息/支付）
# 风险高：只生成 packet，不自主执行；unknown 同理
AUTONOMOUS_REVERSIBILITY = frozenset({"ui_invert", "cancel_pending", "delete_created"})

# type → 可逆性默认值（模型常不确定 reversible，代码兜底）
# 推断模型已明确判 irreversible/counterparty 的保留，unknown 用此表覆盖
# 推断模型判 unknown 时按 mutation.type 确定性回填：
#   settings_toggle → ui_invert（关开之间拨回）
#   search_history → ui_invert（删搜索记录）
#   social_reaction(collected/liked/followed) → ui_invert（取消收藏/取消关注）
#   session_state → ui_invert（切回前台/退出）
#   relationship_request(request_sent) → cancel_pending（取消待发送申请）
#   membership_change(joined) → counterparty（退群可能影响对方）
#   content_lifecycle(created) → delete_created（新建笔记可删）
#   content_lifecycle(deleted) → irreversible（删了还原不回）
#   message_send(sent) → irreversible（发出去撤回不可靠）
#   login_session → ui_invert（登出）
#   other → unknown（交给人工门控）
TYPE_DEFAULT_REVERSIBILITY = {
    "settings_toggle": "ui_invert",
    "search_history": "ui_invert",
    "social_reaction": "ui_invert",
    "session_state": "ui_invert",
    "relationship_request": "cancel_pending",
    "membership_change": "counterparty",
    "content_lifecycle": "delete_created",
    "message_send": "irreversible",
    "login_session": "ui_invert",
    "other": "unknown",
}

DIRECTIONS = ("on", "off", "created", "deleted", "sent", "joined",
              "followed", "liked", "collected", "request_sent")

# 模型有时把 JSON null 写成字符串，回填前统一按缺失处理
NULL_LIKE = {"", "null", "none", "n/a", "无", "没有"}

ENTITY_KINDS = ("setting", "friend", "group", "content", "message",
                "search", "account", "other")


def validate_ledger(ledger: dict) -> list[str]:
    """返回错误信息列表；空列表 = 合法。

    故意严格：schema 错了就大声报错，绝不让一条坏变更悄悄流进恢复执行。
    """
    errs: list[str] = []
    if not isinstance(ledger, dict):
        return ["ledger is not an object"]
    if ledger.get("schema") != LEDGER_SCHEMA:
        errs.append(f'schema must be {LEDGER_SCHEMA!r}, got {ledger.get("schema")!r}')
    for key in ("task_id", "run_id", "task_goal"):
        if not isinstance(ledger.get(key), str) or not ledger.get(key):
            errs.append(f"{key}: non-empty string required")
    if not isinstance(ledger.get("judged_success"), bool):
        errs.append("judged_success: bool required")
    if not isinstance(ledger.get("mutations"), list):
        errs.append("mutations: list required")
        return errs
    for i, m in enumerate(ledger["mutations"]):
        pfx = f"mutations[{i}]"
        if not isinstance(m, dict):
            errs.append(f"{pfx}: object required")
            continue
        mid = m.get("id", f"#{i}")
        pfx = f"mutations[{mid}]"
        if m.get("type") not in MUTATION_TYPES:
            errs.append(f"{pfx}.type invalid: {m.get('type')!r}")
        if not isinstance(m.get("app"), str) or not m.get("app"):
            errs.append(f"{pfx}.app: non-empty string required")
        ent = m.get("entity")
        if not isinstance(ent, dict) or ent.get("kind") not in ENTITY_KINDS:
            errs.append(f"{pfx}.entity.kind invalid: {ent!r:.80}")
        elif m.get("type") == "search_history":
            # 搜索历史的接地物是顶层 search_terms（逐字输入），entity 名允许为空
            if not ledger.get("search_terms"):
                errs.append(f"{pfx} search_history 需要顶层 search_terms 非空（接地）")
        elif not (ent.get("name") or ent.get("identifier")):
            errs.append(f"{pfx}.entity: name or identifier required (grounding)")
        if m.get("direction") not in DIRECTIONS:
            errs.append(f"{pfx}.direction invalid: {m.get('direction')!r}")
        elif m.get("type") == "search_history" and m.get("direction") != "created":
            errs.append(f"{pfx}: search_history 的 direction 必须是 created")
        if m.get("persistence") not in PERSISTENCE_LEVELS:
            errs.append(f"{pfx}.persistence invalid: {m.get('persistence')!r}")
        if m.get("status") not in STATUSES:
            errs.append(f"{pfx}.status invalid: {m.get('status')!r}")
        if m.get("attribution") not in ATTRIBUTIONS:
            errs.append(f"{pfx}.attribution invalid: {m.get('attribution')!r}"
                        f" (one of {ATTRIBUTIONS})")
        co = m.get("carried_over_from_task")
        if m.get("attribution") == "carried_over" and not (
                isinstance(co, str) and co):
            errs.append(f"{pfx}.attribution=carried_over 时必须给 "
                        f"carried_over_from_task")
        if m.get("reversible") not in REVERSIBILITY:
            errs.append(f"{pfx}.reversible invalid: {m.get('reversible')!r}")
        ev = m.get("evidence_steps")
        if not isinstance(ev, list) or not ev or not all(isinstance(x, int) for x in ev):
            errs.append(f"{pfx}.evidence_steps: non-empty list[int] required")
        quote = m.get("evidence_quote")
        if not isinstance(quote, str) or len(quote.strip()) < 4:
            errs.append(f"{pfx}.evidence_quote: non-empty quote from trajectory required")
        conf = m.get("confidence")
        if not isinstance(conf, (int, float)) or not 0.0 <= float(conf) <= 1.0:
            errs.append(f"{pfx}.confidence: number in [0,1] required")
    terms = ledger.get("search_terms")
    if not isinstance(terms, list):
        errs.append("search_terms: list required")
        terms = []
    has_search_mutation = any(
        m.get("type") == "search_history" for m in ledger["mutations"])
    if terms and not has_search_mutation:
        errs.append("search_terms 非空时必须有一条 type=search_history 的 mutation")
    if has_search_mutation and not terms:
        errs.append("type=search_history 的 mutation 必须在顶层 search_terms 逐字列出词")
    return errs


def canonicalize_reversibility(ledger: dict) -> list[str]:
    """把模型判 unknown 的 reversible 按 type-default 表确定性回填。

    模型常不确定 reversible 字段（type 已知但可逆性逻辑对模型太复杂），
    直接 unknown → gate halt → 全挂起。此函数原地覆盖 unknown，仅当
    模型已明确判 irreversible/counterparty 时保留。

    返回被覆盖的条目描述列表（用于日志）。
    """
    changed = []
    for m in ledger.get("mutations", []):
        cur = m.get("reversible", "unknown")
        if cur != "unknown":
            continue  # 模型已有明确判断，尊重
        t = m.get("type")
        default = TYPE_DEFAULT_REVERSIBILITY.get(t, "unknown")
        if default != "unknown" and default != cur:
            old = m["reversible"]
            m["reversible"] = default
            changed.append(f"{m.get('id')}: {t} reversible {old} → {default}")
    if changed:
        ledger.setdefault("_warnings", []).append(
            f"确定性回填 unknown reversible 共 {len(changed)} 条: {changed}")
    return changed


def gate_decision(ledger: dict) -> dict:
    """根据污染清单给出每个变更的门控初判（design.md §5）。

    返回 {"autonomous": [id...], "halt": [{"id","reason"}...], "noop": bool}。
    阶段 A 只产出建议，真正的状态机在阶段 B 的执行器里实现。

    2026-10-28: 自动先 canonicalize_reversibility——模型常不确定 reversible
    字段（type 已知但可逆性逻辑对模型太复杂），直接 unknown → gate halt →
    全挂起。代码回填能把 settings_toggle/search_history 等高频类型从
    unknown 修正为 ui_invert，恢复 autonomous 资格。
    """
    # 先确定性回填 unknown reversible，再做 gate 判定
    canonicalize_reversibility(ledger)

    autonomous, halt = [], []
    for m in ledger.get("mutations", []):
        # 未完成 / 仅会话态（Home 即清）不产生恢复动作
        if m["status"] == "not_done" or m["persistence"] == "session":
            continue
        if float(m["confidence"]) < MIN_AUTONOMOUS_CONFIDENCE:
            halt.append({"id": m["id"], "reason": f"confidence<{MIN_AUTONOMOUS_CONFIDENCE}"})
        elif m["reversible"] not in AUTONOMOUS_REVERSIBILITY:
            halt.append({"id": m["id"], "reason": f"reversible={m['reversible']} → human gate"})
        elif m["status"] == "attempted_unknown":
            halt.append({"id": m["id"], "reason": "status attempted_unknown"})
        else:
            autonomous.append(m["id"])
    return {"autonomous": autonomous, "halt": halt,
            "noop": not ledger.get("mutations")}

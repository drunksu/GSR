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


def gate_decision(ledger: dict) -> dict:
    """根据污染清单给出每个变更的门控初判（design.md §5）。

    返回 {"autonomous": [id...], "halt": [{"id","reason"}...], "noop": bool}。
    阶段 A 只产出建议，真正的状态机在阶段 B 的执行器里实现。
    """
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

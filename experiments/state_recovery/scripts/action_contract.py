#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""action_contract.py —— 动作契约与独立验证（阶段2）。

目标：把「动作是否执行成功」「GUI 是否发生预期变化」「目标污染是否已清除」
三件事**分开表示**，并且只有能拿到独立证据时才给出确定判定，否则标记
uncertain，绝不默认成功。

只依赖标准库；不调用 LLM；不调整模型参数。所有判定是确定性代码。

三层接口：
  1. compose_record() —— 每步 GUI 动作的结构化记录（对齐阶段2要求的 10 个字段）。
  2. precheck_action() —— 执行前检查（授权范围 / 前置条件 / 目标明确性 /
     动作集合 / 预算），任一 block 级检查不过 → allow=False，返回 Harness。
  3. postcheck_action() —— 执行后独立验证（三分离：execution_status /
     gui_changed / clearance），外加新污染信号（new_contamination_signal）。

动作类型集合与工具实际能力对齐（third_party/mobilebench-ol-main/
mobilebench/utils/adb_executor.py）：
  click / double_tap / long_press / type / swipe / scroll / drag /
  enter / home / back / open / wait_time / wait

验证证据口径（诚实声明）：
  - execution_status：由 adb 工具调用是否抛错决定（executed / error /
    blocked / not_executed / uncertain）；
  - gui_changed：由动作执行前/后的 UI 层次（XML）签名对比决定
    （changed / unchanged / uncertain），XML 取不到 → uncertain；
  - clearance：按污染类型使用 XML 谓词。settings_toggle（开关状态）、
    search_history（词条残留）可确定性判定；session_state 与其余类型
    （message_send / social_reaction / content_lifecycle / login_session
    / relationship_request / membership_change / other）无可靠确定性手段
    → 一律 uncertain，交由现有 VLM verify 环节裁决，绝不默认成功。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ACTION_CONTRACT_SCHEMA = "action-contract/v0.1"

# 与 adb_executor.py 实际支持的动作类型一致（不允许动作集合的权威来源）
ACTION_TYPES = ("click", "double_tap", "long_press", "type", "swipe", "scroll",
                "drag", "enter", "home", "back", "open", "wait_time", "wait")

# 需要 position 参数的动作
POSITION_ACTIONS = ("click", "double_tap", "long_press")
# 需要 text 参数的动作
TEXT_ACTIONS = ("type",)
# 滑动/拖拽类
SWIPE_ACTIONS = ("swipe", "scroll", "drag")
# 无实体绑定的系统导航动作（授权检查直接放行）
NAV_ACTIONS = ("home", "back", "enter", "open", "wait_time", "wait")

EXECUTION_STATUS = ("executed", "not_executed", "blocked", "error", "uncertain")
GUI_CHANGED = ("changed", "unchanged", "uncertain")
CLEARANCE = ("cleared", "not_cleared", "uncertain")
CHECK_RESULT = ("pass", "block", "unknown")

# 有可靠确定性 XML 谓词的污染类型；其余类型验证时标 uncertain
DETERMINISTIC_VERIFIABLE_TYPES = ("settings_toggle", "search_history", "session_state")


# ------------------------------------------------------------------ XML 工具

def _node_texts(xml: str) -> list[str]:
    """提取页面层级中可见文本 / 资源 id / 描述。空或非法 XML → []。"""
    if not xml:
        return []
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml)
    except Exception:
        return []
    out: list[str] = []
    for el in root.iter():
        for attr in ("text", "content-desc"):
            v = (el.attrib.get(attr) or "").strip()
            if v:
                out.append(v)
        rid = (el.attrib.get("resource-id") or "").strip()
        if rid:
            out.append(rid)
        # 开关/选中状态也进入签名：否则开关翻转会被误判为 GUI 未变化
        for attr in ("checked", "selected"):
            v = el.attrib.get(attr)
            if v is not None:
                out.append(f"{attr}:{v}")
    return out


def xml_signature(xml: str) -> str:
    """页面层级签名：去重文本排序后做 md5。空 XML → ""（视为无法比较）。"""
    if not xml:
        return ""
    parts = sorted(set(_node_texts(xml)))
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()


def _find_node(xml: str, query: str):
    """按 text / content-desc 精确或 resource-id 后缀匹配查找控件属性 dict。"""
    if not xml or not query:
        return None
    q = str(query).strip()
    if not q:
        return None
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml)
    except Exception:
        return None
    best = None
    for el in root.iter():
        if el.attrib.get("text") == q or el.attrib.get("content-desc") == q:
            return el.attrib
        rid = el.attrib.get("resource-id") or ""
        if rid and (rid == q or rid.endswith("/" + q) or q.endswith(rid)):
            best = el.attrib
    return best


def _target_description(action_type, params) -> str:
    """从动作参数中确定性提取目标描述（用于记录，不做语义判断）。"""
    if action_type in TEXT_ACTIONS:
        return str(params.get("text") or "")
    if isinstance(params.get("position"), (list, tuple)):
        return "position=" + str(list(params.get("position")))
    if params.get("id"):
        return "id=" + str(params.get("id"))
    if params.get("direction"):
        return "direction=" + str(params.get("direction"))
    return ""


# ------------------------------------------------------------------ 执行前检查

def precheck_action(action, xml: str, ctx: dict) -> dict:
    """执行前检查。返回 {"schema", "allow", "reason", "checks"}。

    ctx 字段（由 Harness 构造时提供）：
      target_ids:   本轮授权恢复范围（this_task mutation id 集合）
      target_id:    当前恢复任务对应的 mutation id
      mutation:     当前恢复的污染条目（用于相关度弱信号与后验证）
      recovery_task:恢复任务（precondition / expected_end_state）
      budget:       {"remaining": int}
      max_actions:  本轮动作数量上限
      action_log:   本轮已记录动作列表（步数预算）
    """
    if not isinstance(action, dict):
        action = {"action": None, "params": {}}
    action_type = action.get("action")
    params = action.get("params")
    if not isinstance(params, dict):
        params = {}

    checks: dict[str, dict] = {}

    # 1. 动作集合：不允许的动作一律 block
    if action_type in ACTION_TYPES:
        checks["action_allowed"] = {
            "result": "pass", "note": f"允许的动作类型 {action_type}"}
    else:
        checks["action_allowed"] = {
            "result": "block", "note": f"非法动作类型 {action_type!r}"}

    # 2. 目标明确性：结构不完整（点击无 position / 输入无 text / 滑动无方向）
    checks["target_clarity"] = _check_clarity(action_type, params)

    # 3. 目标控件可达性：带显式 id 的点击类，页面里确定找不到 → block
    checks["target_found"] = _check_target_found(action_type, params, xml)

    # 4. 前置条件（自由文本，只做弱检查；找不到不 block——可能需先导航）
    checks["precondition"] = _check_precondition(ctx, xml)

    # 5. 授权范围：本轮恢复目标必须属于授权集合；动作语义关联无法确定 → unknown
    checks["authorized"] = _check_authorized(ctx, action_type, params)

    # 6. 预算：闭环轮次预算 + 本轮动作数量上限
    checks["budget"] = _check_budget(ctx)

    blocked = [k for k, c in checks.items() if c["result"] == "block"]
    allow = not blocked
    reason = ("precheck passed"
              if allow else
              "; ".join(f"{k}: {checks[k]['note']}" for k in blocked))
    return {
        "schema": ACTION_CONTRACT_SCHEMA,
        "allow": allow,
        "reason": reason,
        "checks": checks,
    }


def _check_clarity(action_type, params) -> dict:
    if action_type in POSITION_ACTIONS:
        pos = params.get("position")
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            return {"result": "pass", "note": "点击类动作带明确 position"}
        return {"result": "block", "note": "点击类动作缺少明确 position 参数"}
    if action_type in TEXT_ACTIONS:
        text = params.get("text")
        if isinstance(text, str) and text.strip():
            return {"result": "pass", "note": "输入动作带非空 text"}
        return {"result": "block", "note": "输入动作缺少非空 text 参数"}
    if action_type in SWIPE_ACTIONS:
        if params.get("direction") or params.get("start_position") or params.get("position"):
            return {"result": "pass", "note": "滑动/拖拽类动作带方向或起止位置"}
        return {"result": "block", "note": "滑动/拖拽类动作缺少方向/位置参数"}
    if action_type in NAV_ACTIONS:
        return {"result": "pass", "note": "系统导航动作无需目标参数"}
    return {"result": "unknown", "note": "无法判定目标明确性"}


def _check_target_found(action_type, params, xml) -> dict:
    if action_type not in ("click", "double_tap", "long_press"):
        return {"result": "unknown", "note": "仅点击类检查控件可达性"}
    rid = params.get("id")
    if not rid:
        return {"result": "unknown",
                "note": "无显式 id（position 型），无法确定性验证可达性"}
    if _find_node(xml, rid) is not None:
        return {"result": "pass", "note": f"目标控件 {rid} 存在于当前页面"}
    return {"result": "block",
            "note": f"目标控件 {rid} 不在当前页面（前置条件不成立）"}


def _check_precondition(ctx, xml) -> dict:
    rt = ctx.get("recovery_task") or {}
    pre = rt.get("precondition") or {}
    target = (pre.get("target") or "").strip()
    if not target:
        return {"result": "unknown", "note": "恢复任务未提供前置条件描述"}
    texts = _node_texts(xml)
    hit = any(t and (t in target or target in t) for t in texts)
    if hit:
        return {"result": "pass", "note": "前置条件检查对象在当前页面可见"}
    return {"result": "unknown",
            "note": "前置条件无法确定性确认（自由文本，可能需先导航）"}


def _check_authorized(ctx, action_type, params) -> dict:
    if action_type in NAV_ACTIONS:
        return {"result": "pass", "note": "系统导航动作属于授权范围"}
    target_ids = ctx.get("target_ids") or []
    target_id = ctx.get("target_id")
    if target_id is not None and target_id not in target_ids:
        return {"result": "block",
                "note": f"恢复目标 {target_id} 不在本轮授权恢复范围"}
    mutation = ctx.get("mutation") or {}
    ent = mutation.get("entity") or {}
    name = ent.get("name") or ""
    desc = _target_description(action_type, params)
    if name and desc and (name in desc or desc in name):
        return {"result": "pass", "note": f"动作目标与恢复实体 {name} 直接关联"}
    return {"result": "unknown",
            "note": "动作目标与实体的语义关联无法确定性判定（不拦截）"}


def _check_budget(ctx) -> dict:
    remaining = (ctx.get("budget") or {}).get("remaining", 1)
    if remaining <= 0:
        return {"result": "block", "note": "闭环轮次预算耗尽"}
    step_count = len(ctx.get("action_log") or [])
    max_actions = ctx.get("max_actions") or 0
    if max_actions > 0 and step_count >= max_actions:
        return {"result": "block", "note": f"动作数已达本轮上限 {max_actions}"}
    return {"result": "pass",
            "note": f"剩余动作配额 {max(0, max_actions - step_count)}"}


# ------------------------------------------------------------------ 执行后验证

def postcheck_action(action, tool_result, xml_before: str, xml_after: str,
                     ctx: dict) -> dict:
    """执行后独立验证：三分离 + 新污染信号。

    tool_result: {"adb_ok": bool, "error": str|None} —— 来自 adb 工具调用。
    ctx: 同 precheck（需要 mutation 等）。
    返回 {"execution_status", "gui_changed", "clearance", "clearance_basis",
          "new_contamination_signal", "new_contamination_basis",
          "observation_ref"}。
    """
    if not isinstance(action, dict):
        action = {"action": None, "params": {}}
    action_type = action.get("action")
    params = action.get("params")
    if not isinstance(params, dict):
        params = {}

    # 1) 动作是否成功执行（与 GUI 是否变化、污染是否清除分开记录）
    if not isinstance(tool_result, dict):
        execution_status = "uncertain"
    elif tool_result.get("adb_ok") is True:
        execution_status = "executed"
    elif tool_result.get("adb_ok") is False:
        execution_status = "error"
    else:
        execution_status = "uncertain"

    # 2) GUI 是否发生预期变化（页面层级签名对比，独立于执行标志）
    sig_before = xml_signature(xml_before)
    sig_after = xml_signature(xml_after)
    if sig_before and sig_after:
        gui_changed = "changed" if sig_before != sig_after else "unchanged"
    else:
        gui_changed = "uncertain"

    # 3) 目标污染是否有证据证明已清除（按污染类型谓词，见模块 docstring）
    clearance, basis = _clearance_predicate(ctx, action_type, params, xml_after)

    # 4) 新污染信号：恢复动作是否把内容残留留在了界面上
    new_signal, new_basis = _new_contamination_signal(action_type, params, xml_after, ctx)

    return {
        "execution_status": execution_status,
        "gui_changed": gui_changed,
        "clearance": clearance,
        "clearance_basis": basis,
        "new_contamination_signal": new_signal,
        "new_contamination_basis": new_basis,
        "observation_ref": {
            "xml_before_sig": sig_before,
            "xml_after_sig": sig_after,
        },
    }


def _clearance_predicate(ctx, action_type, params, xml_after: str) -> tuple:
    """按污染类型返回 (clearance, basis)。确定性不足一律 uncertain。"""
    mutation = ctx.get("mutation") or {}
    mtype = mutation.get("type")
    ent = mutation.get("entity") or {}
    name = ent.get("name") or ""

    if mtype == "settings_toggle":
        node = _find_node(xml_after, name) if name else None
        if node is None:
            return "uncertain", "设置控件不在当前页面，无法用 XML 判定开关状态"
        raw = str(node.get("checked") or node.get("selected") or "").lower()
        if raw in ("true", "1"):
            return "not_cleared", f"设置项 {name} 仍处于开启状态"
        if raw in ("false", "0"):
            return "cleared", f"设置项 {name} 已关闭"
        return "uncertain", f"设置项 {name} 无明确开关状态属性 (checked={raw!r})"

    if mtype == "search_history":
        if not name:
            return "uncertain", "搜索词条名称缺失，无法判定"
        if not xml_after:
            return "uncertain", "执行后观察缺失"
        if name in _node_texts(xml_after):
            return "not_cleared", f"界面仍包含词条 {name}"
        return "cleared", f"界面中不再包含词条 {name}"

    if mtype == "session_state":
        return "uncertain", "会话类污染依赖完整轨迹验证，XML 谓词不足"

    return "uncertain", f"污染类型 {mtype} 无可靠确定性验证手段（需 VLM verify）"


def _new_contamination_signal(action_type, params, xml_after: str, ctx) -> tuple:
    """检测恢复动作是否引入新的残留（如输入内容留在界面）。"""
    if action_type not in TEXT_ACTIONS:
        return False, ""
    text = str(params.get("text") or "").strip()
    if not text or not xml_after:
        return False, ""
    mutation = ctx.get("mutation") or {}
    name = (mutation.get("entity") or {}).get("name") or ""
    if text in _node_texts(xml_after):
        if name and text == name:
            return False, ""  # 输入内容正是目标词条本身，不算新污染
        return True, f"输入内容 {text!r} 残留在界面文本中（潜在新污染）"
    return False, ""


# ------------------------------------------------------------------ 记录组装

def compose_record(*, action_id, target_id, action, precheck, tool_result,
                   postcheck=None, expected_effect=None,
                   observation_ref=None) -> dict:
    """组装一条完整动作记录（10 字段 + 三分离验证扩展）。

    precheck.allow=False  → execution_status=blocked；
    postcheck=None       → not_executed（未执行到观察阶段）。
    """
    if not isinstance(action, dict):
        action = {"action": None, "params": {}}
    params = action.get("params")
    if not isinstance(params, dict):
        params = {}
    action_type = action.get("action")

    if precheck is not None and precheck.get("allow") is False:
        execution_status = "blocked"
        gui_changed, clearance = "uncertain", "uncertain"
        basis = "动作被执行前检查拦截，未产生执行后观察"
        new_signal = False
    elif postcheck is None:
        execution_status = "not_executed"
        gui_changed, clearance = "uncertain", "uncertain"
        basis = "动作未执行，无执行后观察"
        new_signal = False
    else:
        execution_status = postcheck.get("execution_status", "uncertain")
        gui_changed = postcheck.get("gui_changed", "uncertain")
        clearance = postcheck.get("clearance", "uncertain")
        basis = postcheck.get("clearance_basis", "")
        new_signal = bool(postcheck.get("new_contamination_signal"))

    tr = tool_result if isinstance(tool_result, dict) else {}
    return {
        "schema": ACTION_CONTRACT_SCHEMA,
        "action_id": action_id,
        "target_id": target_id,
        "action_type": action_type,
        "target_description": _target_description(action_type, params),
        "preconditions": precheck,
        "expected_effect": expected_effect,
        "tool_result": tr,
        "execution_status": execution_status,
        "gui_changed": gui_changed,
        "clearance": clearance,
        "clearance_basis": basis,
        "new_contamination_signal": new_signal,
        "observation_ref": observation_ref
        or (postcheck or {}).get("observation_ref"),
        "error_reason": (tr.get("error")
                         if tr.get("adb_ok") is not True else None),
    }


# ------------------------------------------------------------------ 代表性轨迹

def _demo_xml(night_on: bool = True, keyword: str | None = None) -> str:
    rows = ['<hierarchy xmlns="android">',
            '<node text="设置" resource-id="com.qq:id/title"/>']
    rows.append(f'<node text="夜间模式" resource-id="com.qq:id/item" '
                f'checked="{"true" if night_on else "false"}"/>')
    if keyword:
        rows.append(f'<node text="{keyword}" resource-id="com.qq:id/history"/>')
    rows.append('</hierarchy>')
    return "\n".join(rows)


def _demo_records() -> list[dict]:
    """纯本地生成 8 类代表性场景的完整动作记录（阶段2测试要求）。"""
    ctx = {
        "target_ids": ["m1", "m2"],
        "target_id": "m1",
        "mutation": {"id": "m1", "type": "settings_toggle",
                     "entity": {"kind": "setting", "name": "夜间模式"}},
        "recovery_task": {
            "precondition": {"target": "夜间模式开关状态",
                             "check_instruction": "进入QQ设置查看夜间模式开关",
                             "clean_if_state": "夜间模式开关已关闭"},
            "expected_end_state": {"kind": "vlm_judge",
                                   "question": "夜间模式开关是否已关闭？",
                                   "expected": "yes"},
            "max_steps": 10,
        },
        "budget": {"max_iter": 3, "remaining": 3},
        "max_actions": 10,
        "action_log": [],
    }
    aid = "demo.recovery.base_canonical.iter1.step{n}"
    recs = []

    def emit(act, tool_result, xml_before, xml_after, tag):
        pre = precheck_action(act, xml_before, ctx)
        post = postcheck_action(act, tool_result, xml_before, xml_after, ctx)
        rec = compose_record(
            action_id=aid.format(n=len(recs) + 1),
            target_id="m1", action=act, precheck=pre, tool_result=tool_result,
            postcheck=post,
            expected_effect=ctx["recovery_task"]["expected_end_state"])
        rec["_scenario"] = tag
        ctx["action_log"].append(rec)
        recs.append(rec)

    on = _demo_xml(night_on=True)
    off = _demo_xml(night_on=False)
    no_xml = ""

    # 1. 工具调用失败
    emit({"action": "click", "params": {"position": [1, 2]}},
         {"adb_ok": False, "error": "adb: device not found"}, on, on,
         "tool_failure")
    # 2. 工具无报错但状态未改变
    emit({"action": "click", "params": {"position": [1, 2]}},
         {"adb_ok": True, "error": None}, on, on,
         "no_state_change")
    # 3. 目标控件不存在或无法定位（click 无 position）
    pre3 = precheck_action({"action": "click", "params": {}}, on, ctx)
    recs.append(compose_record(
        action_id=aid.format(n=len(recs) + 1), target_id="m1",
        action={"action": "click", "params": {}}, precheck=pre3,
        tool_result={"adb_ok": None, "error": pre3["reason"]},
        postcheck=None, expected_effect=ctx["recovery_task"]["expected_end_state"],
        ) | {"_scenario": "target_unlocatable"})
    ctx["action_log"].append(recs[-1])
    # 4. 页面变化，前置条件失效（带 id 的点击，目标控件不在当前页）
    pre4 = precheck_action({"action": "click", "params": {"id": "com.qq:id/toggle"}},
                           no_xml, ctx)
    recs.append(compose_record(
        action_id=aid.format(n=len(recs) + 1), target_id="m1",
        action={"action": "click", "params": {"id": "com.qq:id/toggle"}},
        precheck=pre4, tool_result={"adb_ok": None, "error": pre4["reason"]},
        postcheck=None, expected_effect=ctx["recovery_task"]["expected_end_state"],
        ) | {"_scenario": "precondition_invalid"})
    ctx["action_log"].append(recs[-1])
    # 5. 动作已执行，但污染仍然存在（GUI 变了、开关仍开）
    emit({"action": "click", "params": {"position": [1, 2]}},
         {"adb_ok": True, "error": None}, on,
         _demo_xml(night_on=True, keyword="其他页面"), "pollution_remains")
    # 6. 污染已被外部操作清除（动作后开关已关）
    emit({"action": "click", "params": {"position": [1, 2]}},
         {"adb_ok": True, "error": None}, on, off, "externally_cleared")
    # 7. 验证证据不足（观察缺失 → uncertain，不默认成功）
    emit({"action": "click", "params": {"position": [1, 2]}},
         {"adb_ok": True, "error": None}, on, no_xml, "insufficient_evidence")
    # 8. 恢复操作引入新的污染（输入内容残留在界面）
    ctx2 = dict(ctx)
    ctx2["mutation"] = {"id": "m2", "type": "search_history",
                        "entity": {"kind": "search", "name": "旧词条"}}
    emit({"action": "type", "params": {"text": "新残留词条"}},
         {"adb_ok": True, "error": None},
         _demo_xml(night_on=False, keyword="旧词条"),
         _demo_xml(night_on=False, keyword="新残留词条"), "new_contamination")
    return recs


def _demo(out: str) -> None:
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    recs = _demo_records()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"schema": ACTION_CONTRACT_SCHEMA, "records": recs},
                  f, ensure_ascii=False, indent=2)
    print(f"代表性执行轨迹已写入: {out_path}（{len(recs)} 条动作记录）")
    for r in recs:
        print(f"  [{r['_scenario']}] {r['action_type']} "
              f"status={r['execution_status']} gui={r['gui_changed']} "
              f"clearance={r['clearance']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="动作契约工具（阶段2）")
    ap.add_argument("--demo", action="store_true", help="生成代表性执行轨迹")
    ap.add_argument("--out", default="results/action_contract_demo/representative_records.json")
    args = ap.parse_args()
    if args.demo:
        _demo(args.out)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest.py —— 一条命令跑完所有不依赖模拟器 / API key 的验证。

    python experiments\selftest.py

覆盖：
  D. 统计函数正确性（Fisher 已知值、BH 单调性、bootstrap CI 覆盖真值）
     —— motivation_study 的 analyze_order_effects.py 是全部实验报告的口径，
        这些函数错了，所有 ΔSR / CI / victim 结论都不可信。
  G. 仓库自身的坑（回归守卫）：含中文的 .ps1 必须带 UTF-8 BOM；
     .cmd/.bat 必须是纯 ASCII。

（顺序构造 / 对抗序 / 样本量 / 合成数据端到端管道的 A/B/C/E/F 检查属于
AndroidWorld 支线，随其脚本一起移到了 backup/androidworld/。）

全部通过则退出码 0，任一失败退出码 1。
"""

from __future__ import annotations

import json
import os
import sys

# ---------------------------------------------------------------------------
# 让本脚本在中文 Windows 的默认 cmd（控制台代码页 GBK/cp936）里也能正常输出。
#
# ⚠️ 实测踩过：不加这段，`%PY% experiments\selftest.py` 在**新开的 cmd 窗口**里会直接崩：
#      UnicodeEncodeError: 'gbk' codec can't encode character '\u2705'
#    因为最后那行 print("✅ 全部通过…") 的 ✅ 无法用 GBK 编码。
#    后果比崩掉更糟 —— **它会看起来像"自检失败"**，而其实是输出编码问题。
#    （run_mbl.cmd / pilot.cmd 不会有这个问题：mobile.env.ps1 里设了
#      PYTHONUTF8=1 与 PYTHONIOENCODING=utf-8，但直接调 python 就没有。）
# ---------------------------------------------------------------------------
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001  (老 Python / 被重定向的流)
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "motivation_study", "scripts"))
sys.path.insert(0, os.path.join(HERE, "state_recovery", "scripts"))

import analyze_order_effects as ana  # noqa: E402
import mutation_taxonomy as tax  # noqa: E402
import recovery_task as rt  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def main() -> int:
    # ---- D. 统计函数 ---------------------------------------------------
    # Fisher：[[8,2],[2,8]] 应显著；[[5,5],[5,5]] 应 p=1
    p_sig = ana.fisher_exact_2x2(8, 2, 2, 8)
    p_null = ana.fisher_exact_2x2(5, 5, 5, 5)
    check("D1. Fisher 精确检验已知值", p_sig < 0.05 and p_null > 0.99,
          f"p(8/10 vs 2/10)={p_sig:.4f}, p(ns)={p_null:.4f}")

    qs = ana.benjamini_hochberg([0.001, 0.02, 0.5, 0.9])
    check("D2. BH FDR 单调且 ≥ 原 p 值", all(q >= p for q, p in zip(qs, [0.001, 0.02, 0.5, 0.9]))
          and qs == sorted(qs), f"q={[round(q, 4) for q in qs]}")

    lo, hi = ana.bootstrap_ci([0.2] * 200, n_boot=1000, seed=7)
    check("D3. bootstrap CI 覆盖真值且宽度≈0",
          lo - 1e-6 <= 0.2 <= hi + 1e-6 and (hi - lo) < 1e-9, f"[{lo}, {hi}]")

    # ---- G. 仓库自身的坑（回归守卫）------------------------------------
    # G1: PowerShell 5.1 会用本地代码页（中文 Windows = GBK）读**无 BOM** 的 .ps1，
    #     含中文的脚本会被读成乱码，轻则输出乱码、重则解析失败。
    #     .cmd/.bat 反过来必须纯 ASCII（同样是本地代码页）。
    root = os.path.abspath(os.path.join(HERE, ".."))
    bad_ps1, bad_cmd = [], []
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        if not os.path.isfile(p):
            continue
        raw = open(p, "rb").read()
        if name.endswith(".ps1"):
            has_bom = raw[:3] == b"\xef\xbb\xbf"
            has_nonascii = any(b > 127 for b in raw)
            if has_nonascii and not has_bom:
                bad_ps1.append(name)
        elif name.endswith((".cmd", ".bat")):
            if any(b > 127 for b in raw):
                bad_cmd.append(name)
    check("G1. 含中文的 .ps1 都带 UTF-8 BOM", not bad_ps1, f"缺 BOM: {bad_ps1}" if bad_ps1 else "OK")
    check("G2. .cmd/.bat 全是纯 ASCII", not bad_cmd, f"含非 ASCII: {bad_cmd}" if bad_cmd else "OK")

    # ---- H. state_recovery 确定性逻辑（不依赖 API/手机）----------------
    def _m(mid, **kw):
        m = {"id": mid, "type": "settings_toggle", "app": "QQ",
             "entity": {"kind": "setting", "name": "夜间模式"},
             "direction": "on", "persistence": "account", "status": "done",
             "reversible": "ui_invert", "evidence_steps": [1],
             "evidence_quote": "已开启夜间模式", "confidence": 0.9,
             "attribution": "this_task", "carried_over_from_task": None}
        m.update(kw)
        return m

    led = {"schema": tax.LEDGER_SCHEMA, "task_id": "t1", "run_id": "r1",
           "task_goal": "g", "judged_success": True, "search_terms": [],
           "mutations": [
               _m("m1"),  # this_task 可逆 → 自动
               _m("m2", type="message_send",
                  entity={"kind": "message", "name": "微笑emoji"},
                  direction="sent", reversible="irreversible",
                  persistence="server"),  # this_task 不可逆 → 挂起
               _m("c1", attribution="carried_over",
                  carried_over_from_task="t0"),  # 前序遗留 → 不处置
           ]}
    led["_gate"] = tax.gate_decision(led)
    check("H1. gate 自治/挂起分流正确",
          rt.expected_autonomous_ids(led) == {"m1"}
          and rt.expected_halt_ids(led) == {"m2"},
          f"auto={rt.expected_autonomous_ids(led)}, halt={rt.expected_halt_ids(led)}")

    good = {"schema": rt.TASK_SET_SCHEMA, "task_id": "t1", "run_id": "r1",
            "tasks": [{
                "schema": rt.TASK_SCHEMA, "mutation_id": "m1",
                "recovery_goal": "打开QQ设置，关闭夜间模式开关",
                "precondition": {"target": "夜间模式开关状态",
                                 "check_instruction": "进入QQ设置查看夜间模式开关是否开启",
                                 "clean_if_state": "夜间模式开关已关闭"},
                "expected_end_state": {"kind": "vlm_judge",
                                       "question": "夜间模式开关是否已经处于关闭状态？",
                                       "expected": "yes"},
                "idempotent": True, "risk_level": "low", "max_steps": 10}],
            "human_gate": [{
                "mutation_id": "m2", "title": "QQ 已发送的微笑emoji消息",
                "gate_reason": "reversible=irreversible → human gate",
                "reason": "发出的消息无法撤回式还原",
                "suggested_manual_action": "请人工确认微笑emoji消息如何处理"}]}
    check("H2. 合法恢复任务集通过校验", rt.validate_task_set(good, led) == [],
          "; ".join(rt.validate_task_set(good, led)))

    bad = json.loads(json.dumps(good))
    bad["tasks"][0]["recovery_goal"] = "打开App把那个模式调回去"  # 丢实体/接地
    bad["tasks"][0]["risk_level"] = "high"  # 自动恢复任务不允许
    bad["tasks"][0]["expected_end_state"]["question"] = "弄好了吗"  # 无问号无实体
    bad["human_gate"][0]["gate_reason"] = "模型觉得无所谓"  # 篡改门控理由
    errs = rt.validate_task_set(bad, led)
    check("H3. 接地/风险/断言/门控理由违规均被抓出", len(errs) >= 4,
          f"{len(errs)} 条: {errs}")

    # ---- H4-H6. 保守降级（v0.4，audit_grounding.conservatism_pass） ----
    import audit_grounding as ag

    def _resp(thought):
        return f"Thought: {thought}\nAction: click(point='<point>1 2</point>')"

    def _traj(goal, thoughts):
        return {"task_goal": goal,
                "history_action": [{"action": "click", "params": {"position": [1, 2]}}
                                   for _ in thoughts],
                "history_response": [_resp(t) for t in thoughts]}

    # H4：证据步后终局"用户不存在" → 社交写入强制降级门控
    t4 = _traj("去钉钉添加15010284323为我的好友", [
        "进入好友请求确认页，现在点击发送按钮提交好友请求",
        "当前掉进群聊页面，之前的操作可能未成功提交好友请求",
        "重新搜索，系统提示“该用户不存在”，无法添加为好友，终止任务"])
    l4 = {"schema": tax.LEDGER_SCHEMA, "task_id": "h4", "run_id": "r",
          "task_goal": t4["task_goal"], "judged_success": False,
          "search_terms": [],
          "mutations": [_m("m1", type="relationship_request", app="钉钉",
                           entity={"kind": "friend", "name": "倬倬",
                                   "identifier": "15010284323"},
                           direction="request_sent", persistence="server",
                           evidence_steps=[0])]}
    notes4 = ag.conservatism_pass(l4, t4)
    g4 = tax.gate_decision(l4)
    check("H4. 终局否定把高置信好友申请降级并挂起",
          l4["mutations"][0]["status"] == "attempted_unknown"
          and l4["mutations"][0]["confidence"] <= 0.4
          and any(h["id"] == "m1" for h in g4["halt"]),
          f"notes={notes4}")

    # H5：开关没找到+末尾设置子页点击无反馈+空清单 → 补录 attempted_unknown
    t5 = _traj("开启拼多多长辈模式", [
        "在设置里找了很久，仍未找到明确标有“长辈模式”的选项",
        "再次滚动设置页，还是未找到“长辈模式”入口，准备换路径",
        "我进入了“字体大小”设置页面，点击“确定”应用超大字体，"
        "但没有任何是否开启长辈模式的反馈"])
    l5 = {"schema": tax.LEDGER_SCHEMA, "task_id": "h5", "run_id": "r",
          "task_goal": t5["task_goal"], "judged_success": False,
          "mutations": [], "search_terms": []}
    notes5 = ag.conservatism_pass(l5, t5)
    g5 = tax.gate_decision(l5)
    v5, w5 = ag.grounding_checks(l5, t5)
    m5 = l5["mutations"][0] if l5["mutations"] else {}
    check("H5. 漏登的不确定开关点击被补录并挂起（接地通过）",
          len(l5["mutations"]) == 1 and m5.get("status") == "attempted_unknown"
          and "字体" in (m5.get("entity", {}).get("name") or "")
          and any(h["id"] == "m1" for h in g5["halt"])
          and tax.validate_ledger(l5) == [] and v5 == [],
          f"notes={notes5}, v={v5}")

    # H6：容器名确定性修复为接地的选项名
    t6 = _traj("去钉钉添加我的状态为下班了", [
        "选择状态“下班了”并保存，界面显示“保存成功”提示"])
    l6 = {"schema": tax.LEDGER_SCHEMA, "task_id": "h6", "run_id": "r",
          "task_goal": t6["task_goal"], "judged_success": False,
          "search_terms": [],
          "mutations": [_m("m1", type="settings_toggle", app="钉钉",
                           entity={"kind": "setting", "name": "我的状态"},
                           evidence_steps=[0],
                           evidence_quote="界面显示“保存成功”，状态为下班了")]}
    ag.conservatism_pass(l6, t6)
    check("H6. 容器名'我的状态'修复为选项名'下班了'",
          l6["mutations"][0]["entity"]["name"] == "下班了",
          f"name={l6['mutations'][0]['entity']['name']}")

    print()
    if FAILED:
        print(f"❌ {len(FAILED)} 项失败: {FAILED}")
        return 1
    print("✅ 全部通过（不依赖模拟器 / API key）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

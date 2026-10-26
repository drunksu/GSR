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
import recovery_state as rs  # noqa: E402
import policy_engine as pe  # noqa: E402

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

    # ---- H7-H9. RecoveryState 显式状态（Harness 阶段1）----
    import recovery_state as rs

    traj_sample = {
        "goal": "关闭夜间模式",
        "success": False,
        "history_action": [
            {"action": "click", "params": {"position": [1, 2]}},
            {"action": "type", "params": {"text": "夜间模式"}},
            {"action": "click", "params": {"id": "toggle"}},
        ],
        "history_response": ["Thought: a", "Thought: b", "Thought: c"],
        "history_image_path": ["/a/1.png", "/b/2.png", "/c/3.png"],
    }
    s = rs.summarize_recovery_traj(traj_sample, "recovery_iter1")
    check("H7. 执行轨迹摘要确定性提取",
          s["step_count"] == 3
          and s["steps"][1]["action"] == "type"
          and s["steps"][1]["target"] == "夜间模式"
          and s["steps"][2]["screenshot"] == "/c/3.png"
          and s["executor_success_flag"] is False,
          f"steps={len(s['steps'])}, flag={s['executor_success_flag']}")

    st = rs.RecoveryState("qq_10", "base_canonical", 3)
    st.trajectory_path = "/traj/trajectory.json"
    st.ledger_path = "/ledger/qq_10_ledger.json"
    st.has_contamination = True
    st.begin_iteration(1)
    st.record_generate(ok=True, task_path="/tasks/qq_10_tasks.json")
    st.record_execute(ok=True,
                      rec={"traj": traj_sample, "task_dir": "recovery_iter1",
                           "final_img": "/c/3.png"})
    st.record_verify({"success": False, "reason": "reaudit",
                      "verdicts": [{"mutation_id": "m1", "cleared": False}]})
    st.begin_iteration(2)
    st.record_generate(ok=True, task_path="/tasks/qq_10_tasks.json")
    st.record_execute(ok=True,
                      rec={"traj": traj_sample, "task_dir": "recovery_iter2",
                           "final_img": "/c/3.png"})
    st.record_verify({"success": True, "reason": "reaudit",
                      "verdicts": [{"mutation_id": "m1", "cleared": True}]})
    st.finish(True, False, "clean")
    d = st.to_dict()
    errs = rs.validate_state(d)
    check("H8. RecoveryState 迁移/序列化/校验",
          d["schema"] == rs.STATE_SCHEMA
          and d["success"] is True
          and d["iterations"] == 2
          and d["per_iteration"][1]["verify"]["success"] is True
          and d["per_iteration"][0]["trajectory"]["step_count"] == 3
          and errs == [],
          f"errs={errs}")

    bad = json.loads(json.dumps(d))
    bad["schema"] = "wrong/v1"
    bad["per_iteration"][0]["phase"] = "teleport"
    bad_errs = rs.validate_state(bad)
    check("H9. 非法 schema/阶段被校验抓出", len(bad_errs) >= 2,
          f"errs={bad_errs}")

    # ---- H10-H14. 阶段1完整规格：targets / 不可变 / Trace / 多轮 / 等价 ----
    import trace as tr
    import tempfile as _tf

    # H10: 污染目标过滤 + 原始 ledger 不可变
    led10 = {"schema": tax.LEDGER_SCHEMA, "task_id": "t1", "run_id": "r1",
             "task_goal": "g", "judged_success": True, "search_terms": [],
             "mutations": [
                 _m("m1"),
                 _m("m2", type="message_send",
                    entity={"kind": "message", "name": "消息A"},
                    direction="created"),
                 _m("m3", attribution="carried_over",
                    carried_over_from_task="t0",
                    entity={"kind": "setting", "name": "夜间模式"}),
                 _m("m4", attribution="preexisting",
                    entity={"kind": "setting", "name": "勿扰模式"}),
             ]}
    tmpdir = _tf.mkdtemp()
    led_path = os.path.join(tmpdir, "led.json")
    with open(led_path, "w", encoding="utf-8") as f:
        json.dump(led10, f, ensure_ascii=False, indent=2)
    loaded = rs.load_ledger_immutable(led_path)
    with open(led_path, encoding="utf-8") as f:
        disk_after = json.load(f)
    check("H10a. 严格加载的 ledger 与磁盘原文一致（未修改）",
          loaded == led10 and disk_after == led10,
          "ledger 被改动")
    split = rs.filter_targets(loaded)
    check("H10b. 目标=this_task、上下文=carried/preexisting",
          len(split["targets"]) == 2
          and len(split["context"]) == 2
          and all(c["attribution"] in ("carried_over", "preexisting")
                  for c in split["context"]),
          f"targets={len(split['targets'])}, context={len(split['context'])}")
    st10 = rs.RecoveryState("t1", "r1", 3)
    st10.load_ledger(led_path)
    check("H10c. 目标态含 mutation_ref 且恢复状态合法",
          len(st10.targets) == 2
          and st10.targets[0]["mutation_ref"]["id"] == "m1"
          and st10.targets[0]["recovery_status"] in ("pending", "halted"),
          f"targets={len(st10.targets)}")
    st10.targets[0]["mutation_ref"]["id"] = "X"
    check("H10d. mutation_ref 为深拷贝，原 ledger 不受影响",
          loaded["mutations"][0]["id"] == "m1",
          f"ledger id={loaded['mutations'][0]['id']}")

    # H11: Trace 事件 + 多轮累积 + 序列化 round-trip
    trace_path = os.path.join(tmpdir, "t1_trace.jsonl")
    st11 = rs.RecoveryState("t1", "r1", 3)
    st11.attach_trace(tr.TraceLogger(trace_path, st11.recovery_id, "t1", "r1"))
    st11.load_ledger(led_path)
    for i in (1, 2):
        st11.begin_iteration(i)
        st11.record_generate(ok=True, task_path="/tasks.json")
        st11.record_execute(ok=True,
                            rec={"traj": traj_sample, "task_dir": f"iter{i}",
                                 "final_img": f"iter{i}/last.png"},
                            intent={"task_ref": "/tasks.json"})
        st11.record_verify({"success": False, "reason": "reaudit",
                            "verdicts": [{"mutation_id": "m1",
                                          "cleared": False}]})
    st11.begin_iteration(3)
    st11.record_generate(ok=True, task_path="/tasks.json")
    st11.record_execute(ok=True,
                        rec={"traj": traj_sample, "task_dir": "iter3",
                             "final_img": "iter3/last.png"})
    st11.record_verify({"success": True, "reason": "reaudit",
                        "verdicts": [{"mutation_id": "m1", "cleared": True},
                                     {"mutation_id": "m2", "cleared": True}]})
    st11.finish(True, False, "clean")
    d11 = st11.to_dict()
    errs11 = rs.validate_state(d11)
    m1s = [t for t in d11["targets"] if t["mutation_id"] == "m1"][0]
    check("H11a. 三轮累积：attempts=3、verified_cleared、contamination=absent",
          d11["iterations"] == 3
          and len(d11["attempt_history"]) == 3
          and m1s["attempts"] == 3
          and m1s["recovery_status"] == "verified_cleared"
          and m1s["contamination_status"] == "absent"
          and errs11 == [],
          f"attempts={m1s['attempts']}, status={m1s['recovery_status']}, errs={errs11}")
    st11r = rs.RecoveryState.from_dict(d11)
    d11r = st11r.to_dict()
    check("H11b. from_dict round-trip 保留扩展字段",
          d11r["iterations"] == 3
          and d11r["success"] is True
          and len(d11r["targets"]) == 2
          and d11r["budget"]["max_iter"] == 3,
          f"iter={d11r['iterations']}, targets={len(d11r['targets'])}")
    with open(trace_path, encoding="utf-8") as f:
        events = [json.loads(l) for l in f if l.strip()]
    ok_env = all({"recovery_id", "task_id", "run_id", "iteration",
                  "ts", "type", "payload"} <= set(e) for e in events)
    types11 = {e["type"] for e in events}
    check("H11c. Trace 事件含统一信封与生命周期事件",
          ok_env and "state.terminated" in types11
          and "verify.result" in types11 and "execute.result" in types11,
          f"types={sorted(types11)}")

    # H12: 对照等价性（trace on/off 语义字段一致）
    st_off = rs.RecoveryState("t1", "r1", 3)
    st_on = rs.RecoveryState("t1", "r1", 3)
    st_on.attach_trace(tr.TraceLogger(
        os.path.join(tmpdir, "t1_trace_on.jsonl"), st_on.recovery_id, "t1", "r1"))
    for st in (st_off, st_on):
        for i in (1, 2):
            st.begin_iteration(i)
            st.record_generate(ok=True, task_path="/tasks.json")
            st.record_execute(ok=True,
                              rec={"traj": traj_sample, "task_dir": f"iter{i}",
                                   "final_img": "x.png"})
            st.record_verify({"success": False, "reason": "reaudit",
                              "verdicts": []})
        st.finish(False, False, "contaminated",
                  failure_reason="max_iter_exceeded (3)")
    do = st_off.to_dict()
    dn = st_on.to_dict()
    check("H12. trace 开关不改变恢复语义（success/iterations/final_state 一致）",
          do["success"] == dn["success"]
          and do["iterations"] == dn["iterations"]
          and do["final_state"] == dn["final_state"]
          and do["failure_reason"] == dn["failure_reason"]
          and do["per_iteration"] == dn["per_iteration"],
          "trace on/off 语义不一致")

    # H13: 日志写入失败 fail loudly
    bad_trace = os.path.join(tmpdir, "no_such_dir", "x.jsonl")
    try:
        tr.TraceLogger(bad_trace, "r", "t", "r")
        check("H13. 无法打开的 Trace 路径应抛错", False, "未抛错")
    except RuntimeError:
        check("H13. 无法打开的 Trace 路径应抛错", True, "")

    # H14: expected_clean_state 确定性
    e1 = rs.expected_clean_state(_m("m1"))
    e2 = rs.expected_clean_state(
        _m("m2", type="search_history",
           entity={"kind": "search", "name": "关键词"}))
    check("H14. 初始期望状态确定性推导",
          e1["kind"] == "setting_off" and e2["kind"] == "no_search_entry",
          f"e1={e1['kind']}, e2={e2['kind']}")

    # ---- H15-H22. 阶段2：动作契约与独立验证（8 类场景）----
    import action_contract as ac

    def _xml(night_on: bool, extra: str = "") -> str:
        rows = ['<hierarchy xmlns="android">',
                '<node text="设置" resource-id="com.qq:id/title"/>']
        rows.append(f'<node text="夜间模式" resource-id="com.qq:id/item" '
                    f'checked="{"true" if night_on else "false"}"/>')
        if extra:
            rows.append(f'<node text="{extra}" resource-id="com.qq:id/h"/>')
        rows.append('</hierarchy>')
        return "\n".join(rows)

    ON_XML = _xml(True)
    OFF_XML = _xml(False)
    XML2 = _xml(True, "其他页面")
    ctx2a = {
        "target_ids": ["m1"], "target_id": "m1",
        "mutation": {"id": "m1", "type": "settings_toggle",
                     "entity": {"kind": "setting", "name": "夜间模式"}},
        "recovery_task": {"precondition": {"target": "夜间模式开关状态"},
                          "expected_end_state": {"kind": "vlm_judge",
                                                 "question": "夜间模式开关是否已关闭？",
                                                 "expected": "yes"},
                          "max_steps": 10},
        "budget": {"max_iter": 3, "remaining": 3},
        "max_actions": 10, "action_log": [],
    }
    ctx2b = dict(ctx2a)
    ctx2b["mutation"] = {"id": "m1", "type": "search_history",
                         "entity": {"kind": "search", "name": "旧词条"}}
    ctx2b["recovery_task"] = {"max_steps": 10}

    # H15: 工具调用失败 → execution_status=error（不默认成功）
    post15 = ac.postcheck_action({"action": "click", "params": {"position": [1, 2]}},
                                 {"adb_ok": False, "error": "adb: device not found"},
                                 ON_XML, ON_XML, ctx2a)
    check("H15. 工具调用失败 → error / unchanged / not_cleared（三分离）",
          post15["execution_status"] == "error"
          and post15["gui_changed"] == "unchanged"
          and post15["clearance"] == "not_cleared",
          f"status={post15['execution_status']}, "
          f"gui={post15['gui_changed']}, clear={post15['clearance']}")

    # H16: 工具无报错但状态未改变 → executed / unchanged / not_cleared
    post16 = ac.postcheck_action({"action": "click", "params": {"position": [1, 2]}},
                                 {"adb_ok": True, "error": None},
                                 ON_XML, ON_XML, ctx2a)
    check("H16. 工具无报错但状态未改变 → executed / unchanged / not_cleared",
          post16["execution_status"] == "executed"
          and post16["gui_changed"] == "unchanged"
          and post16["clearance"] == "not_cleared",
          f"status={post16['execution_status']}, "
          f"gui={post16['gui_changed']}, clear={post16['clearance']}")

    # H17: 目标控件不存在或无法定位 → precheck block（click 无 position）
    pre17 = ac.precheck_action({"action": "click", "params": {}}, ON_XML, ctx2a)
    check("H17a. 点击无 position → target_clarity block",
          pre17["allow"] is False
          and pre17["checks"]["target_clarity"]["result"] == "block",
          pre17["reason"])
    pre17b = ac.precheck_action(
        {"action": "click", "params": {"id": "com.qq:id/nonexistent"}},
        ON_XML, ctx2a)
    check("H17b. 目标控件不在当前页面 → target_found block（前置不成立）",
          pre17b["allow"] is False
          and pre17b["checks"]["target_found"]["result"] == "block",
          pre17b["reason"])

    # H18: 页面变化、前置条件失效（目标 id 在空页面确定找不到）
    pre18 = ac.precheck_action(
        {"action": "click", "params": {"id": "com.qq:id/toggle"}}, "", ctx2a)
    check("H18. 页面变化致前置条件失效 → block 并返回 Harness",
          pre18["allow"] is False
          and pre18["checks"]["target_found"]["result"] == "block",
          pre18["reason"])

    # H19: 动作已执行但污染仍在 → executed / changed / not_cleared（三分离）
    post19 = ac.postcheck_action({"action": "click", "params": {"position": [1, 2]}},
                                 {"adb_ok": True, "error": None},
                                 ON_XML, XML2, ctx2a)
    check("H19. 动作已执行但污染仍存在 → executed / changed / not_cleared",
          post19["execution_status"] == "executed"
          and post19["gui_changed"] == "changed"
          and post19["clearance"] == "not_cleared",
          f"status={post19['execution_status']}, "
          f"gui={post19['gui_changed']}, clear={post19['clearance']}")

    # H20: 污染已被外部操作清除 → clearance=cleared（XML 开关状态翻转可判）
    post20 = ac.postcheck_action({"action": "click", "params": {"position": [1, 2]}},
                                 {"adb_ok": True, "error": None},
                                 ON_XML, OFF_XML, ctx2a)
    check("H20. 污染已被外部清除 → executed / changed / cleared",
          post20["execution_status"] == "executed"
          and post20["gui_changed"] == "changed"
          and post20["clearance"] == "cleared",
          f"status={post20['execution_status']}, "
          f"gui={post20['gui_changed']}, clear={post20['clearance']}")

    # H21: 验证证据不足 → uncertain，绝不默认成功
    post21a = ac.postcheck_action({"action": "click", "params": {"position": [1, 2]}},
                                  {"adb_ok": True, "error": None},
                                  ON_XML, "", ctx2a)
    post21b = ac.postcheck_action(
        {"action": "click", "params": {"position": [1, 2]}},
        {"adb_ok": True, "error": None}, ON_XML, ON_XML,
        {**ctx2a, "mutation": {"id": "m1", "type": "message_send",
                               "entity": {"kind": "message", "name": "微笑emoji"}}})
    check("H21. 验证证据不足 → uncertain（观察缺失/无可靠谓词均不默认成功）",
          post21a["gui_changed"] == "uncertain"
          and post21a["clearance"] == "uncertain"
          and post21b["clearance"] == "uncertain",
          f"a.gui={post21a['gui_changed']}, a.clear={post21a['clearance']}, "
          f"b.clear={post21b['clearance']}")

    # H22: 恢复操作引入新的污染 → new_contamination_signal=True（type 残留）
    post22 = ac.postcheck_action(
        {"action": "type", "params": {"text": "新残留词条"}},
        {"adb_ok": True, "error": None}, OFF_XML, _xml(False, "新残留词条"), ctx2b)
    check("H22. 恢复操作引入新污染 → new_contamination_signal=True",
          post22["new_contamination_signal"] is True
          and post22["clearance"] == "cleared",
          f"signal={post22['new_contamination_signal']}, "
          f"basis={post22['new_contamination_basis']}")

    # H23: compose_record 完整动作契约（10 字段）+ blocked/not_executed 状态
    pre23 = ac.precheck_action(
        {"action": "click", "params": {"position": [1, 2]}}, ON_XML, ctx2a)
    post23 = ac.postcheck_action({"action": "click", "params": {"position": [1, 2]}},
                                 {"adb_ok": True, "error": None}, ON_XML, OFF_XML, ctx2a)
    rec23 = ac.compose_record(
        action_id="r.iter1.step1", target_id="m1",
        action={"action": "click", "params": {"position": [1, 2]}},
        precheck=pre23, tool_result={"adb_ok": True, "error": None},
        postcheck=post23,
        expected_effect=ctx2a["recovery_task"]["expected_end_state"])
    req = {"action_id", "target_id", "action_type", "target_description",
           "preconditions", "expected_effect", "tool_result",
           "execution_status", "observation_ref", "error_reason"}
    check("H23a. 动作记录含全部 10 个契约字段 + 三分离验证",
          req <= set(rec23)
          and rec23["execution_status"] == "executed"
          and rec23["clearance"] == "cleared"
          and rec23["error_reason"] is None,
          f"keys={sorted(set(rec23) - req)}")
    rec23b = ac.compose_record(
        action_id="r.iter1.step2", target_id="m1",
        action={"action": "click", "params": {}}, precheck=pre17,
        tool_result={"adb_ok": None, "error": pre17["reason"]}, postcheck=None)
    check("H23b. 被拦截动作记录为 blocked、未执行动作为 not_executed",
          rec23b["execution_status"] == "blocked"
          and ac.compose_record(
              action_id="x", target_id=None, action={"action": "home"},
              precheck=None, tool_result={}, postcheck=None,
              )["execution_status"] == "not_executed",
          f"blocked={rec23b['execution_status']}")

    # H24: 授权范围 / 预算检查（blocked 级）
    ctx24 = dict(ctx2a)
    ctx24["target_id"] = "m999"
    pre24 = ac.precheck_action({"action": "click", "params": {"position": [1, 2]}},
                               ON_XML, ctx24)
    ctx24b = dict(ctx2a)
    ctx24b["budget"] = {"max_iter": 3, "remaining": 0}
    pre24b = ac.precheck_action({"action": "click", "params": {"position": [1, 2]}},
                                ON_XML, ctx24b)
    check("H24. 越权目标 / 预算耗尽 → block",
          pre24["checks"]["authorized"]["result"] == "block"
          and pre24b["checks"]["budget"]["result"] == "block"
          and pre24b["allow"] is False,
          f"auth={pre24['checks']['authorized']['result']}, "
          f"budget={pre24b['checks']['budget']['result']}")

    # H25: RecoveryState 动作记录 + trace 事件 + 校验（v2 接线核心）
    st25 = rs.RecoveryState("t1", "r1", 3)
    st25.attach_trace(tr.TraceLogger(os.path.join(tmpdir, "t1_v2.jsonl"),
                                     st25.recovery_id, "t1", "r1"))
    st25.load_ledger(led_path)
    st25.begin_iteration(1)
    st25.record_generate(ok=True, task_path="/tasks.json")
    st25.record_action(rec23)
    st25.record_action(rec23b)
    st25.record_execute(ok=True,
                        rec={"traj": traj_sample, "task_dir": "iter1",
                             "final_img": "x.png"})
    st25.record_verify({"success": True, "reason": "reaudit",
                        "verdicts": [{"mutation_id": "m1", "cleared": True}]})
    st25.finish(True, False, "clean")
    d25 = st25.to_dict()
    with open(os.path.join(tmpdir, "t1_v2.jsonl"), encoding="utf-8") as f:
        ev25 = [json.loads(l) for l in f if l.strip()]
    check("H25. 动作记录进 per_iteration.actions 且 trace 含 execute.action",
          d25["per_iteration"][0]["actions"][0]["action_id"] == "r.iter1.step1"
          and any(e["type"] == "execute.action" for e in ev25)
          and rs.validate_state(d25) == [],
          f"actions={len(d25['per_iteration'][0]['actions'])}, "
          f"validate={rs.validate_state(d25)}")

    # ---- H26-H33. 阶段3：确定性 Policy Engine（不依赖 API/手机）----
    pld = {"schema": tax.LEDGER_SCHEMA, "task_id": "pt1", "run_id": "pr1",
           "task_goal": "g", "judged_success": False, "search_terms": [],
           "mutations": [_m("m1", direction="on")]}
    pld["_gate"] = tax.gate_decision(pld)
    p_led_path = os.path.join(tmpdir, "policy_led.json")
    with open(p_led_path, "w", encoding="utf-8") as f:
        json.dump(pld, f, ensure_ascii=False, indent=2)

    def _mk_ps(max_iter=3):
        s = rs.RecoveryState("pt1", "pr1", max_iter)
        s.load_ledger(p_led_path)
        return s

    def _p_plan(tid="m1", goal="关闭夜间模式开关"):
        return {"tasks": [{"mutation_id": tid, "recovery_goal": goal,
                           "max_steps": 10}]}

    def _p_steppers(verify_fn, *, plan_seq=None, execute_counter=None):
        """plan_seq 依次返回计划（超出取最后一个）；返回 (replan, execute, calls, ex)。"""
        seq = plan_seq or [_p_plan()]
        calls, ex = {"n": 0}, {"n": 0}

        def replan():
            calls["n"] += 1
            idx = min(calls["n"], len(seq)) - 1
            plan = seq[idx]
            return ("tasks.json",
                    {t["mutation_id"]: t["recovery_goal"]
                     for t in plan["tasks"]}, plan)

        def execute():
            ex["n"] += 1
            if execute_counter is not None:
                execute_counter["n"] = ex["n"]
            return {"traj": {"history_action":
                             [{"action": "click",
                               "params": {"position": [1, 2]}}]},
                    "task_dir": f"iter{ex['n']}",
                    "final_img": f"iter{ex['n']}.png"}

        return replan, execute, verify_fn, calls, ex

    def _v_ok():
        return {"success": True, "reason": "reaudit",
                "verdicts": [{"mutation_id": "m1", "cleared": True}]}

    def _v_fail():
        return {"success": False, "reason": "reaudit",
                "verdicts": [{"mutation_id": "m1", "cleared": False}]}

    def _v_uncertain():
        # 谎称成功但 verdicts 不确定：Policy 不得据此宣布成功
        return {"success": True, "reason": "reaudit",
                "verdicts": [{"mutation_id": "m1", "cleared": None}]}

    # H26: 预算耗尽正确停止（llm_cap=2，iter1 用满 generate+verify）
    s26 = _mk_ps()
    r26, e26, v26, c26, x26 = _p_steppers(_v_fail)

    def _cu_budget(state_dict, phase, ctx):
        ctx["llm_cap"] = 2
        return ctx

    f26 = pe.run_loop(s26, replan=r26, execute=e26, verify=v26,
                      ctx_update=_cu_budget)
    check("H26. 预算耗尽时正确停止（budget_exhausted）",
          f26["decision"] == "STOP_FAILURE"
          and f26["termination_reason"] == "budget_exhausted"
          and f26["iterations"] == 1,
          f"dec={f26['decision']}, reason={f26['termination_reason']}")

    # H27a: 相同计划重复 → 不重复执行，安全终止
    s27 = _mk_ps()
    r27, e27, v27, c27, x27 = _p_steppers(_v_fail)
    f27 = pe.run_loop(s27, replan=r27, execute=e27, verify=v27)
    check("H27a. 相同计划重复不重复执行（repeated_plan，execute=1）",
          f27["decision"] == "STOP_FAILURE"
          and f27["termination_reason"] == "repeated_plan"
          and x27["n"] == 1,
          f"dec={f27['decision']}, reason={f27['termination_reason']}, "
          f"execute={x27['n']}")

    # H27b: 计划各异但验证连续无进展 → 早停（不靠加大 max_iter）
    s27b = _mk_ps()
    r27b, e27b, v27b, c27b, x27b = _p_steppers(
        _v_fail, plan_seq=[_p_plan(goal="方案1"), _p_plan(goal="方案2"),
                           _p_plan(goal="方案3")])
    f27b = pe.run_loop(s27b, replan=r27b, execute=e27b, verify=v27b)
    check("H27b. 连续无进展按 NO_PROGRESS_LIMIT 早停（iter=2<max_iter=3）",
          f27b["decision"] == "STOP_FAILURE"
          and f27b["termination_reason"] == "no_progress"
          and f27b["iterations"] == 2,
          f"dec={f27b['decision']}, reason={f27b['termination_reason']}, "
          f"iter={f27b['iterations']}")

    # H28: 验证成功后不再调用 Planner
    s28 = _mk_ps()
    r28, e28, v28, c28, x28 = _p_steppers(_v_ok)
    f28 = pe.run_loop(s28, replan=r28, execute=e28, verify=v28)
    check("H28. 验证成功后不再调用 Planner（replan=1, iter=1）",
          f28["decision"] == "STOP_SUCCESS"
          and f28["iterations"] == 1
          and c28["n"] == 1,
          f"dec={f28['decision']}, replan={c28['n']}")

    # H29a: validate_plan 拒绝授权范围外目标（carried_over/preexisting）
    s29 = _mk_ps()
    pl29 = _p_plan(tid="c1", goal="处理前序遗留污染")
    vr29 = pe.validate_plan(s29.policy_dict(), pl29, {})
    check("H29a. carried_over 目标被授权检查拒绝",
          vr29["ok"] is False
          and any("授权恢复范围" in r for r in vr29["reasons"]),
          f"reasons={vr29['reasons']}")

    # H29b: 越权计划两次被拒 → 安全终止且从未执行
    s29b = _mk_ps()
    r29b, e29b, v29b, c29b, x29b = _p_steppers(_v_fail, plan_seq=[pl29, pl29])
    f29b = pe.run_loop(s29b, replan=r29b, execute=e29b, verify=v29b)
    check("H29b. 越权计划两次被拒 → 安全终止且不执行（execute=0）",
          f29b["decision"] == "STOP_FAILURE"
          and f29b["termination_reason"] == "plan_rejected"
          and x29b["n"] == 0,
          f"dec={f29b['decision']}, reason={f29b['termination_reason']}, "
          f"execute={x29b['n']}")

    # H30: 计划被拒后重新规划 → 有效计划 → 成功
    s30 = _mk_ps()
    pl_bad = _p_plan(tid="m999", goal="处理越权目标")
    r30, e30, v30, c30, x30 = _p_steppers(_v_ok, plan_seq=[pl_bad, _p_plan()])
    f30 = pe.run_loop(s30, replan=r30, execute=e30, verify=v30)
    check("H30. 计划被拒后可重新规划并成功（replan=2, execute=1）",
          f30["decision"] == "STOP_SUCCESS"
          and f30["iterations"] == 1
          and c30["n"] == 2
          and x30["n"] == 1,
          f"dec={f30['decision']}, replan={c30['n']}, execute={x30['n']}")

    # H31: 验证不确定不得宣布成功（即使 verify 谎称 success=True）
    s31 = _mk_ps()
    r31, e31, v31, c31, x31 = _p_steppers(_v_uncertain)
    f31 = pe.run_loop(s31, replan=r31, execute=e31, verify=v31)
    ok31 = not any(d["decision"] == "STOP_SUCCESS"
                   for d in f31["decision_log"])
    check("H31. 验证不确定不得直接宣布成功",
          f31["decision"] != "STOP_SUCCESS" and ok31,
          f"dec={f31['decision']}, log={[d['decision'] for d in f31['decision_log']]}")

    # H32: 恢复状态在失败后重建（含 accepted_plan 保留），重建后重跑安全终止
    s32 = _mk_ps()
    r32, e32, v32, c32, x32 = _p_steppers(
        _v_fail, plan_seq=[_p_plan(), _p_plan(goal="方案2"),
                           _p_plan(goal="方案3")])
    pe.run_loop(s32, replan=r32, execute=e32, verify=v32)
    st32r = rs.RecoveryState.from_dict(s32.to_dict())
    check("H32a. 失败后状态可重建（targets/attempt/iteration/budget 保留）",
          len(st32r.targets) == 1
          and len(st32r.attempt_history) == 2
          and st32r.iteration == 2
          and st32r.budget["max_iter"] == 3
          and rs.validate_state(st32r.to_dict()) == [],
          f"targets={len(st32r.targets)}, attempts={len(st32r.attempt_history)}, "
          f"iter={st32r.iteration}")
    check("H32b. 重建保留 accepted_plan（跨重建重复检测可用）",
          any(a.get("accepted_plan") for a in st32r.attempt_history),
          "accepted_plan 未随状态重建")
    r32r, e32r, v32r, c32r, x32r = _p_steppers(
        _v_fail, plan_seq=[_p_plan(), _p_plan(goal="方案4")])
    f32r = pe.run_loop(st32r, replan=r32r, execute=e32r, verify=v32r)
    check("H32c. 重建后重跑循环安全终止（不崩溃）",
          f32r["decision"].startswith("STOP_")
          and f32r["iterations"] >= 1,
          f"dec={f32r['decision']}, iter={f32r['iterations']}")

    # H33: 终止态 decide 幂等，不再发起新动作
    s33 = _mk_ps()
    s33.begin_iteration(1)
    s33.record_generate(ok=True, task_path="/t.json",
                        plan_sig={"m1": "关闭夜间模式开关"})
    s33.record_execute(ok=True,
                       rec={"traj": traj_sample, "task_dir": "iter1",
                            "final_img": "x.png"})
    s33.record_verify({"success": False, "reason": "reaudit",
                       "verdicts": [{"mutation_id": "m1", "cleared": False}]})
    s33.finish(False, False, "contaminated", failure_reason="no_progress",
               termination_reason="no_progress")
    d33 = s33.policy_dict()
    ctx33 = {"phase": pe._initial_phase(s33), "plan": _p_plan()}
    da, db = pe.decide(d33, ctx33), pe.decide(d33, ctx33)
    check("H33. 终止态 decide 幂等且输出 STOP_*",
          da["decision"] == db["decision"]
          and da["decision"].startswith("STOP_")
          and da["phase_after"] == "terminal",
          f"dec={da['decision']}, phase_after={da['phase_after']}")

    # ---- H34-H39. 阶段4：Harness 驱动的动态控制循环（不依赖 API/手机）----
    # 受控对照：相同初始条件（同一 policy_led.json, max_iter=3），
    # v1 用 _sim_v1_loop（固定 generate→execute→verify 每轮全调用）复刻，
    # v3 用 run_loop（按需调度）。比较 planner/execute/verify 调用数与终止原因。

    def _p_steppers4(verify_seq, *, plan_seq=None, actions=None, state=None):
        """阶段4 steppers：execute 时把动作契约记录写入 state（供诊断读取）。
        返回 (replan, execute, verify, calls)。"""
        calls = {"replan": 0, "execute": 0, "verify": 0}
        seq = plan_seq or [_p_plan()]

        def replan():
            calls["replan"] += 1
            idx = min(calls["replan"], len(seq)) - 1
            plan = seq[idx]
            return ("tasks.json",
                    {t["mutation_id"]: t["recovery_goal"]
                     for t in plan["tasks"]}, plan)

        def execute():
            calls["execute"] += 1
            if actions and state is not None:
                for a in actions:
                    state.record_action(dict(a))
            return {"traj": {"history_action":
                             [{"action": "click",
                               "params": {"position": [1, 2]}}]},
                    "task_dir": f"iter{calls['execute']}",
                    "final_img": f"iter{calls['execute']}.png"}

        def verify():
            calls["verify"] += 1
            idx = min(calls["verify"], len(verify_seq)) - 1
            return verify_seq[idx]

        return replan, execute, verify, calls

    # H34a: 动态调度——外部已清除（动作级 clearance=cleared 证据）→
    #       v3 跳过第 2 轮执行直接终验；v1 固定循环仍要盲执行第 2 轮。
    s34 = _mk_ps()
    act_cleared34 = [{"action_id": "d.iter1.step1", "target_id": "m1",
                      "action_type": "click", "execution_status": "executed",
                      "gui_changed": "unchanged", "clearance": "cleared",
                      "new_contamination_signal": False}]
    v_seq34 = [{"success": False, "reason": "reaudit",
                "verdicts": [{"mutation_id": "m1", "cleared": False}]},
               {"success": True, "reason": "reaudit",
                "verdicts": [{"mutation_id": "m1", "cleared": True}]}]
    r34, e34, v34, cts34 = _p_steppers4(
        v_seq34, plan_seq=[_p_plan(), _p_plan(goal="方案2")],
        actions=act_cleared34, state=s34)
    f34 = pe.run_loop(s34, replan=r34, execute=e34, verify=v34)
    v1_34 = pe._sim_v1_loop(3, lambda i: True, lambda i: True,
                            lambda i: i == 2)
    log34 = [d["decision"] for d in f34["decision_log"]]
    check("H34a. 外部清除→直接终验：v3 execute=1 < v1 execute=2（不再重复执行）",
          f34["decision"] == "STOP_SUCCESS"
          and cts34["execute"] == 1 and v1_34["execute_calls"] == 2
          and cts34["verify"] == 2,
          f"v3 execute={cts34['execute']}, v1 execute={v1_34['execute_calls']}, "
          f"log={log34}")

    # H34b: 受控对照——相同计划连续无进展：v3 重复被拒提前安全终止
    #       （repeated_plan, execute=1），v1 盲跑满 max_iter
    #       （planner/execute/verify 各 3 次）。
    s34b = _mk_ps()
    r34b, e34b, v34b, cts34b = _p_steppers4(
        [{"success": False, "reason": "reaudit",
          "verdicts": [{"mutation_id": "m1", "cleared": False}]}],
        plan_seq=[_p_plan(), _p_plan(), _p_plan()], state=s34b)
    f34b = pe.run_loop(s34b, replan=r34b, execute=e34b, verify=v34b)
    v1_34b = pe._sim_v1_loop(3, lambda i: True, lambda i: True,
                             lambda i: False)
    check("H34b. 受控对照：v3 无进展早停不重复执行，v1 盲跑满 max_iter",
          f34b["termination_reason"] == "repeated_plan"
          and cts34b["execute"] == 1
          and v1_34b["planner_calls"] == 3
          and v1_34b["execute_calls"] == 3,
          f"v3 reason={f34b['termination_reason']}, execute={cts34b['execute']}, "
          f"v1 planner/execute={v1_34b['planner_calls']}/{v1_34b['execute_calls']}")

    # H34c: 受控对照——无意外终止（max_rounds/replan_error 从未出现）
    #       且每次决策都有原因（decision_log 可完整重建决策过程）。
    unexp34 = [f34["termination_reason"], f34b["termination_reason"]]
    log34b = [d["decision"] for d in f34b["decision_log"]]
    reasons34b = [d["reason"] for d in f34b["decision_log"]]
    check("H34c. 动态调度不引入新错误终止，decision_log 完整可重建",
          not any(r in ("max_rounds", "replan_error") for r in unexp34)
          and all(r for r in reasons34b)
          and len(log34b) >= 3,
          f"v3 terminations={unexp34}, log34={log34}, log34b={log34b}")

    # H35: 动态调度——工具执行失败（execution_status=error，不猜错误字符串）
    #      → 诊断读执行结果，先 OBSERVE 重新观察。
    s35 = _mk_ps()
    act_err35 = [{"action_id": "d.iter1.step1", "target_id": "m1",
                  "action_type": "click", "execution_status": "error",
                  "error_reason": "adb timeout", "gui_changed": "unchanged",
                  "clearance": "not_cleared", "new_contamination_signal": False},
                 {"action_id": "d.iter1.step2", "target_id": "m1",
                  "action_type": "click", "execution_status": "error",
                  "error_reason": "adb timeout", "gui_changed": "unchanged",
                  "clearance": "not_cleared", "new_contamination_signal": False}]
    r35, e35, v35, cts35 = _p_steppers4(
        [{"success": False, "reason": "reaudit",
          "verdicts": [{"mutation_id": "m1", "cleared": False}]}],
        actions=act_err35, state=s35)
    obs35 = {"n": 0}

    def _observe35():
        obs35["n"] += 1
        return {"observed": True}

    f35 = pe.run_loop(s35, replan=r35, execute=e35, verify=v35,
                      observe=_observe35)
    log35 = [d["decision"] for d in f35["decision_log"]]
    check("H35. 工具执行失败→OBSERVE 重新观察（诊断只读执行结果/状态证据）",
          "OBSERVE" in log35 and obs35["n"] == 1
          and f35["decision"] == "STOP_FAILURE",
          f"log={log35}, observe_calls={obs35['n']}, "
          f"dec={f35['decision']}")

    # H36: 动态调度——新污染出现在授权目标范围 → RE_AUDIT 重新审计并评估风险，
    #      且 reaudit 计入模型调用预算（budget_from_state 含 reaudit_ok）。
    s36 = _mk_ps()
    act_new36 = [{"action_id": "d.iter1.step1", "target_id": "m1",
                  "action_type": "click", "execution_status": "executed",
                  "gui_changed": "changed", "clearance": "not_cleared",
                  "new_contamination_signal": True}]
    r36, e36, v36, cts36 = _p_steppers4(
        [{"success": False, "reason": "reaudit",
          "verdicts": [{"mutation_id": "m1", "cleared": False}]}],
        actions=act_new36, state=s36)

    def _reaudit36():
        return {"reaudited": True}

    f36 = pe.run_loop(s36, replan=r36, execute=e36, verify=v36,
                      reaudit=_reaudit36)
    log36 = [d["decision"] for d in f36["decision_log"]]
    d36 = s36.policy_dict()
    b36 = pe.budget_from_state(d36)
    reaudited36 = any(a.get("reaudit_ok") for a in d36["attempt_history"])
    check("H36. 新污染影响授权目标→RE_AUDIT 且计入 LLM 预算",
          "RE_AUDIT" in log36 and reaudited36
          and b36["llm_calls"] >= 1
          and any(it.get("reaudit") for it in d36["per_iteration"]),
          f"log={log36}, reaudit_ok={reaudited36}, "
          f"llm_calls={b36['llm_calls']}")

    # H37: Trace 重建决策过程——policy.decide 事件序列 == run_loop decision_log
    s37 = _mk_ps()
    s37.attach_trace(tr.TraceLogger(os.path.join(tmpdir, "t37.jsonl"),
                                    s37.recovery_id, "pt1", "pr1"))
    r37, e37, v37, cts37 = _p_steppers4(
        [{"success": False, "reason": "reaudit",
          "verdicts": [{"mutation_id": "m1", "cleared": False}]},
         {"success": True, "reason": "reaudit",
          "verdicts": [{"mutation_id": "m1", "cleared": True}]}],
        plan_seq=[_p_plan(), _p_plan(goal="方案2")], state=s37)
    f37 = pe.run_loop(s37, replan=r37, execute=e37, verify=v37)
    log37 = [d["decision"] for d in f37["decision_log"]]
    with open(os.path.join(tmpdir, "t37.jsonl"), encoding="utf-8") as f:
        ev37 = [json.loads(l) for l in f if l.strip()]
    dec37 = [e["payload"]["decision"] for e in ev37
             if e["type"] == "policy.decide"]
    check("H37. Trace 的 policy.decide 事件可重建完整决策过程",
          dec37 == log37 and len(dec37) >= 3,
          f"trace={dec37}, decision_log={log37}")

    # H38: 回退——v1 固定循环基线语义不变（每轮 planner→execute→verify 全调用）
    v1_38 = pe._sim_v1_loop(3, lambda i: True, lambda i: True, lambda i: False)
    with open(os.path.join(HERE, "state_recovery", "scripts",
                           "run_pipeline.py"), encoding="utf-8") as f:
        src38 = f.read()
    check("H38. v1 固定循环基线保留且可配置回退（--harness v1 语义不变）",
          v1_38["planner_calls"] == 3 and v1_38["execute_calls"] == 3
          and v1_38["verify_calls"] == 3
          and v1_38["stop"] == "max_iter_exceeded"
          and "--harness" in src38
          and "v1 始终保留为固定循环基线，可随时回退" in src38,
          f"v1={v1_38}, harness 开关={'--harness' in src38}")

    # ---- H39-H44. 阶段5：V0-V4 离线确定性对照（不依赖 API/手机）----
    import evaluate_versions as ev

    # H39a: 确定性 —— 相同输入两次运行结果一致（可复现）
    tasks39 = ev.load_tasks(limit=6)
    scn39 = ev.make_scenarios(tasks39[0]) if tasks39 else {}
    r39a = ev.run_version("V3", tasks39[0], scn39["clean_first"])
    r39b = ev.run_version("V3", tasks39[0], scn39["clean_first"])
    check("H39a. 离线对照可复现（同输入同结果）",
          r39a == r39b and len(tasks39) > 0,
          f"V3 clean_first={r39a['decision']}")

    # H39b: 统计口径 —— 无污染任务不混入恢复率分母（truth_cleared=None）
    rows39 = []
    for t in tasks39:
        scns = ev.make_scenarios(t)
        for ver in ("V0", "V4"):
            rows39.append(ev.run_version(ver, t, scns["clean_first"]))
    m39 = ev.compute_metrics(rows39)
    n_contam = sum(1 for t in tasks39 if t["has_this_task"])
    check("H39b. 统一口径：无污染任务不混入恢复率分母",
          m39["contaminated"] == n_contam * 2  # V0+V4 两条记录
          and m39["contaminated"] < len(rows39)
          and m39["final_recovery_rate"] == 1.0,
          f"contaminated={m39['contaminated']} (记录数), "
          f"污染任务={n_contam}, rows={len(rows39)}, "
          f"rate={m39['final_recovery_rate']}")

    # H40: 受控对照 —— 无进展场景 V3/V4 早停（迭代 < V0 盲跑满）
    t40 = next(t for t in ev.load_tasks(limit=30) if t["has_this_task"])
    scns40 = ev.make_scenarios(t40)
    p40 = {"persistent_fail": {}}
    for ver in ("V0", "V3", "V4"):
        p40["persistent_fail"][ver] = ev.run_version(
            ver, t40, scns40["persistent_fail"])
    v0_iter = p40["persistent_fail"]["V0"]["iterations"]
    v3_iter = p40["persistent_fail"]["V3"]["iterations"]
    v4_iter = p40["persistent_fail"]["V4"]["iterations"]
    check("H40. 无进展早停：V3/V4 迭代 < V0 盲跑满（不靠加大 max_iter）",
          v0_iter == ev.MAX_ITER and v3_iter < ev.MAX_ITER
          and v4_iter < ev.MAX_ITER
          and p40["persistent_fail"]["V3"]["replan"]
          < p40["persistent_fail"]["V0"]["replan"],
          f"V0/V3/V4 iter={v0_iter}/{v3_iter}/{v4_iter}, "
          f"planner V0/V3={p40['persistent_fail']['V0']['replan']}/"
          f"{p40['persistent_fail']['V3']['replan']}")

    # H41: 动态调度 —— 外部清除证据 → V4 直接终验跳过第 2 轮执行（V3 仍执行）
    scns41 = ev.make_scenarios(t40)
    # 手工构造 ledger_stale 注入（clearance=cleared 动作证据 + 第 2 轮 verify 成功）
    def _mk41():
        tid_targets = [x["mutation_id"] for x in t40["targets"]]
        real_plan = t40["pset"]

        def _plan(i):
            plan = dict(real_plan)
            plan["tasks"] = [x for x in (real_plan.get("tasks") or [])
                             if x.get("mutation_id") in tid_targets]
            if i >= 2:
                plan["tasks"] = [dict(t, **(
                    {"recovery_goal": t.get("recovery_goal", "")
                     + f"（第 {i} 轮方案）"})
                    if t.get("mutation_id") in tid_targets else t)
                    for t in plan["tasks"]]
            return plan

        def _exe(i, plan, contract=False):
            return {"traj": {"history_action":
                             [{"action": "click",
                               "params": {"position": [1, 2]}}],
                             "success": True},
                    "task_dir": f"iter{i}", "final_img": f"iter{i}.png",
                    "actions": [{"action_id": "f.iter1.step1",
                                 "target_id": tid_targets[0],
                                 "action_type": "click",
                                 "execution_status": "executed",
                                 "gui_changed": "unchanged",
                                 "clearance": "cleared",
                                 "new_contamination_signal": False}]}

        def _verify(i):
            return {"success": i >= 2, "reason": "reaudit",
                    "verdicts": [{"mutation_id": m, "cleared": i >= 2}
                                 for m in tid_targets]}

        return {"plan": _plan, "execute": _exe,
                "verify": _verify, "truth": lambda i: i >= 2}

    scn41 = _mk41()
    f41_v3 = ev.run_version("V3", t40, scn41)
    f41_v4 = ev.run_version("V4", t40, scn41)
    log41_v3 = f41_v3["decision_log"]
    log41_v4 = f41_v4["decision_log"]
    check("H41. 外部清除直接终验：V4 跳过第 2 轮执行（V3 执行）",
          f41_v4["decision"] == "STOP_SUCCESS" and f41_v3["decision"] == "STOP_SUCCESS"
          and f41_v4["execute"] < f41_v3["execute"]
          and "VERIFY" in log41_v4 and "EXECUTE_PLAN" not in log41_v4[-2:],
          f"V4 exec={f41_v4['execute']}, V3 exec={f41_v3['execute']}, "
          f"V4 log={log41_v4}, V3 log={log41_v3}")

    # H42: 故障注入 —— 相同动作连续失败 → V4 OBSERVE（V3 无）
    faults42 = ev.fault_injection(ev.load_tasks(limit=6))
    row42 = next(r for r in faults42
                 if r["fault"] == "same_action_repeat_fail")
    log42_v3 = row42["versions"]["V3"]["decision_log"]
    log42_v4 = row42["versions"]["V4"]["decision_log"]
    check("H42. 工具连续失败：V4 先 OBSERVE 重新观察（V3 不 OBSERVE）",
          "OBSERVE" in log42_v4 and "OBSERVE" not in log42_v3,
          f"V4 log={log42_v4}, V3 log={log42_v3}")

    # H43: 故障注入 —— 误将历史污染作为恢复目标 → V3/V4 授权拒绝不执行
    row43 = next(r for r in faults42
                 if r["fault"] == "historical_pollution_target")
    v43 = row43["versions"]
    check("H43. 越权目标授权拒绝：V3/V4 plan_rejected 且不执行",
          v43["V3"]["termination_reason"] == "plan_rejected"
          and v43["V4"]["termination_reason"] == "plan_rejected"
          and v43["V3"]["execute"] == 0 and v43["V4"]["execute"] == 0
          and v43["V0"]["execute"] == ev.MAX_ITER,
          f"V3/V4={v43['V3']['termination_reason']}/"
          f"{v43['V4']['termination_reason']}, "
          f"exec V3/V4/V0={v43['V3']['execute']}/"
          f"{v43['V4']['execute']}/{v43['V0']['execute']}")

    # H44: 动态开关消融 —— V3(dynamic=False) vs V4(dynamic=True) 行为差异存在
    #      且 V4 不引入意外终止（max_rounds/replan_error）
    unexp44 = [r["termination_reason"] for r in
               (f41_v3, f41_v4, *faults42[0]["versions"].values())
               if r["termination_reason"] in ("max_rounds", "replan_error")]
    check("H44. 动态开关可消融且 V4 无意外终止",
          not unexp44
          and f41_v3["decision_log"] != f41_v4["decision_log"],
          f"unexpected={unexp44}, V3!=V4 log: "
          f"{f41_v3['decision_log'] != f41_v4['decision_log']}")

    print()
    if FAILED:
        print(f"❌ {len(FAILED)} 项失败: {FAILED}")
        return 1
    print("✅ 全部通过（不依赖模拟器 / API key）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

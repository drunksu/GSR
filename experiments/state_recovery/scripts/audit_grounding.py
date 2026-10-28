#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_grounding.py —— 污染清单接地审计（规模化质控，不依赖金标）。

推断模型最大的风险是「看着合理但编造实体/证据」。本脚本把每条污染清单放回对应
trajectory.json 原文里做机械核验：

  G1 identifier（QQ号/群号等硬标识）必须逐字出现在轨迹文本中；
  G2 entity.name 必须出现在轨迹文本中（设置名/群名/人名——截图上看到但 Thought
     没转述的名字给 WARN，不直接判违规，阶段 B 接入截图后可消除）；
  G3 evidence_quote 与轨迹原文的二元字组覆盖率 ≥ 阈值（防杜撰引文）；
  G4 evidence_steps 步号必须在轨迹长度内；
  G5 search_terms 必须能对应到某次 type 动作的输入（防把申请答题等非搜索输入
     误记为搜索历史——但 type 文本本身出现即记 WARN，人工再判）。

用法::

    mobile\Scripts\python.exe audit_grounding.py --run q2_A_1
    mobile\Scripts\python.exe audit_grounding.py --run base_canonical --task neteasemusic_19
    mobile\Scripts\python.exe audit_grounding.py --ledger-root ..\results\ledgers \
        --results-root ..\..\..\third_party\mobilebench-ol-main\results --run s3_A_1
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]  # scripts → state_recovery → experiments → repo root
DEFAULT_LEDGER_ROOT = HERE.parent / "results" / "ledgers"
DEFAULT_RESULTS_ROOT = REPO_ROOT / "third_party" / "mobilebench-ol-main" / "results"

QUOTE_BIGRAM_COVER = 0.75   # 引文二元字组覆盖率阈值
NAME_BIGRAM_COVER = 0.80    # 名字直接子串找不到时的宽松覆盖率阈值

# 设置项常见容器/页面名——模型有时用容器名代替被切换选项的完整文案
CONTAINER_NAMES = {"设置", "通用设置", "模式选择", "我的状态", "字体大小设置",
                   "显示与亮度", "无障碍", "显示设置", "更多设置"}


def norm(s) -> str:
    return "".join(str(s).split()).lower() if s is not None else ""


def bigrams(s: str) -> set[str]:
    s = norm(s)
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}


def cover(part: str, whole_bigrams: set[str]) -> float:
    bg = bigrams(part)
    return len(bg & whole_bigrams) / len(bg) if bg else 1.0


SEARCH_CTX_RE = re.compile(
    r"搜索框|搜索栏|搜索页|在搜索(?:框|栏|中)?"
    r"|输入.{0,24}(?:搜索|查找|找到|检索|搜一下|搜下|查询|查询一下)"
    r"|(?:搜索|查找|检索|搜|查询|enter).{0,24}输入"
    r"|(?:搜|查询|查找).{0,12}(?:一下|下|进去|进入)"
)


def trajectory_text(traj: dict) -> tuple[str, list[str], list[str]]:
    """返回 (拼接全文, 全部 type 输入, 搜索语境下的 type 输入)。"""
    chunks = [str(traj.get("task_goal", ""))]
    typed: list[str] = []
    search_typed: list[str] = []
    resps = traj.get("history_response", []) or []
    for i, act in enumerate(traj.get("history_action", []) or []):
        params = act.get("params", {}) or {}
        if act.get("action") == "type" and params.get("text"):
            txt = str(params["text"])
            typed.append(txt)
            ctx = str(resps[i]) if i < len(resps) else ""
            if SEARCH_CTX_RE.search(ctx):
                search_typed.append(txt)
        chunks.append(json.dumps(params, ensure_ascii=False))
    for resp in resps:
        chunks.append(str(resp))
    return "\n".join(chunks), typed, search_typed


def grounding_checks(ledger: dict, traj: dict) -> tuple[list[str], list[str]]:
    """接地核验，返回 (硬违规, 警告)。推断修复回路与离线审计共用。"""
    raw, typed, search_typed = trajectory_text(traj)
    raw_n = norm(raw)
    raw_bg = bigrams(raw)
    typed_n = norm(" ".join(typed))
    search_typed_n = norm(" ".join(search_typed))
    typed_set = {norm(t) for t in typed}
    n_steps = len(traj.get("history_action", []) or [])
    violations, warnings = [], []

    has_carried_search = any(
        m.get("attribution") == "carried_over" and m.get("type") == "search_history"
        for m in ledger.get("mutations", []))
    for m in ledger.get("mutations", []):
        mid = m.get("id", "?")
        if m.get("attribution") == "carried_over":
            # 结转条目以**前序污染清单**为证据，不接受当前轨迹的接地核验
            continue
        ent = m.get("entity") or {}
        ident = ent.get("identifier")
        if ident and norm(ident) not in raw_n:
            violations.append(f"{mid}: identifier 未在轨迹中出现 → {ident!r}")
        name = ent.get("name")
        if m.get("type") == "settings_toggle" and isinstance(name, str) \
                and norm(name) in {norm(x) for x in CONTAINER_NAMES}:
            warnings.append(f"{mid}: settings_toggle 的 entity.name 疑似容器/页面名"
                            f"而非被切换选项 → {name!r}")
        if name and len(norm(name)) >= 2:
            if norm(name) not in raw_n:
                c = cover(name, raw_bg)
                if c >= NAME_BIGRAM_COVER:
                    warnings.append(
                        f"{mid}: entity.name 非逐字出现但字组覆盖 {c:.2f} → {name!r}")
                else:
                    violations.append(
                        f"{mid}: entity.name 在轨迹文本中找不到（可能只在截图里）"
                        f" cover={c:.2f} → {name!r}")
        quote = m.get("evidence_quote", "")
        if quote:
            c = cover(quote, raw_bg)
            if c < QUOTE_BIGRAM_COVER:
                violations.append(
                    f"{mid}: evidence_quote 与轨迹原文覆盖率仅 {c:.2f}（疑似杜撰引文）")
        for st in m.get("evidence_steps", []):
            if not isinstance(st, int) or st < 0 or st >= n_steps:
                violations.append(f"{mid}: evidence_steps 越界 → {st} (共 {n_steps} 步)")

    for term in ledger.get("search_terms", []):
        # carried_over 的搜索词证据来自前序污染清单（本任务可能零输入），豁免本轨迹核验
        if has_carried_search and norm(term) not in search_typed_n:
            continue
        nt = norm(term)
        if nt not in raw_n:
            violations.append(f"search_term 未在轨迹中出现 → {term!r}")
        elif nt not in search_typed_n and nt not in typed_set:
            # 既不在 SEARCH_CTX_RE 命中的搜索语境 type 里，也不在任何 type 动作里
            # → 真幻觉。如果它在 typed_set 里（任何 type action 都精确输入过），
            # 模型看到了 Action.params.text，就算 Thought 文本没说"搜索"，
            # 也不算硬违规——SEARCH_CTX_RE 只是启发式正则，漏判是大概率
            # （Thought 写"搜一下"、"查金价"未必包含"搜索"关键词）
            violations.append(
                f"search_term 无任何 type 输入支撑（真幻觉）→ {term!r}")
        elif nt not in search_typed_n and nt in typed_set:
            # 降级为 warning：有 type 输入但 Thought 没匹配到搜索语境关键词
            warnings.append(
                f"search_term 有 type 输入但 SEARCH_CTX_RE 未匹配 Thought "
                f"→ {term!r}（确认不是答题框即可）")

    # 反向接地：搜索框里确实 type 过的词必须登记（模型最容易漏的一类）。
    resps = traj.get("history_response", []) or []
    terms_n = {norm(t) for t in ledger.get("search_terms", [])}
    for i, act in enumerate(traj.get("history_action", []) or []):
        params = act.get("params", {}) or {}
        if act.get("action") != "type" or not params.get("text"):
            continue
        txt = str(params["text"])
        ctx = str(resps[i]) if i < len(resps) else ""
        if not SEARCH_CTX_RE.search(ctx) or norm(txt) in terms_n:
            continue
        violations.append(
            f"第 {i} 步在搜索语境下输入了 {txt!r}，但 search_terms 未登记"
            f"（Thought: {ctx[:40].strip()}…）")

    return violations, warnings


def scrub_untyped_terms(ledger: dict, traj: dict) -> list[str]:
    """确定性剔除没有任何 type 动作支撑的搜索词（幻觉/旧词误登）。

    推断阶段（结转前）的搜索残留必须由本任务输入动作产生；Thought 看到旧词、
    界面文案拼贴都不算。同步移除以该词为实体名的 search_history 条目。
    空名条目仅在它是唯一搜索条目且所有词都被剔除时才移除。
    返回被剔除词列表（用于记录）。

    判定逻辑（2026-10-28 修复，真机 V4 199 个假无污染的根因）：
      - search_typed（SEARCH_CTX_RE 命中 Thought 搜索语境的 type）→ 保留
      - typed（任何 type action，不限 Thought 语境）→ 也保留——模型看到了
        Action.params.text 里的真实输入，SEARCH_CTX_RE 只是启发式正则，
        漏判是大概率（Thought 写"搜一下"、"查金价"未必包含"搜索"关键词）
      - 只有既不在 search_typed 也不在 typed 的 term 才视为幻觉 → 剔除
        （这类 term 根本没在轨迹的任何 type action 里出现过）
    """
    _, typed, search_typed = trajectory_text(traj)
    typed_n = {norm(t) for t in typed}
    search_typed_n = {norm(t) for t in search_typed}
    dropped = []
    for t in ledger.get("search_terms", []):
        nt = norm(t)
        if nt in search_typed_n or nt in typed_n:
            continue  # 真实 type 输入支撑，保留
        dropped.append(t)  # 真幻觉：轨迹里任何 type 动作都没这个词
    if not dropped:
        return []
    dropped_n = {norm(t) for t in dropped}
    ledger["search_terms"] = [t for t in ledger.get("search_terms", [])
                              if norm(t) not in dropped_n]
    keep_muts = []
    for m in ledger.get("mutations", []):
        if m.get("type") == "search_history":
            ename = (m.get("entity") or {}).get("name")
            unnamed = not ename
            if ename and norm(ename) in dropped_n:
                continue
            if unnamed and not ledger["search_terms"]:
                continue  # 唯一空名搜索条目失去了全部词
        keep_muts.append(m)
    ledger["mutations"] = keep_muts
    return dropped


def audit_ledger(ledger: dict, traj: dict) -> dict:
    violations, warnings = grounding_checks(ledger, traj)
    return {"task": f"{ledger.get('run_id')}/{ledger.get('task_id')}",
            "n_mutations": len(ledger.get("mutations", [])),
            "violations": violations, "warnings": warnings}


# ------------------------------------------------------------ 保守降级（v0.4）
# 动机：扩样实测到三类"模型自信地错"，且错误会沿生成→执行管线放大：
#  1) rimet_6：好友申请点了发送但掉进群聊，重搜终局明说"该用户不存在"，
#     模型仍 0.95 报 done 自治 → 必须按"证据步之后的否定证据"降级门控；
#  2) pinduoduo_27：目标开关始终没找到，末尾在字体大小页点了一下、无反馈，
#     模型给空污染清单静默跳过 → 必须补录 attempted_unknown 强制挂起；
#  3) rimet_16：选项真实生效但实体名写成容器"我的状态" → 用任务目标+引文
#     中接地的选项名确定性修复。
# 规则只信轨迹文本，全部确定性、幂等；触发记录写污染清单 _warnings。

SOCIAL_TYPES = {"relationship_request", "membership_change"}

SOCIAL_NEGATION_RE = re.compile(
    r"(该|此)?用户不存在|账号不存在|对方不存在"
    r"|未找到(该)?用户|没有找到(该)?用户"
    r"|无法(继续)?(添加|发送|申请|加入)|添加失败|发送失败|申请失败|加入失败"
    r"|未成功(提交|发送|添加|加入)")

# 比否定弱一档：明确表达"提交是否成功都不确定"。只降置信到门控阈值以下。
SUBMISSION_DOUBT_RE = re.compile(
    r"可能未(成功)?(提交|发送|添加|加入)|未成功提交|未成功发送"
    r"|是否(已)?(提交|发送|发出|添加成功|加入成功)"
    r"|不确定(该)?(申请|请求|好友|群)?是否?(已)?(提交|发送|发出)")

SETTING_NEGATION_RE = re.compile(
    r"(未找到|没找到|找不到|没有找到|未发现|未见)[^。！？]{0,16}"
    r"(模式|功能|设置|开关|选项|入口)"
    r"|(?:模式|功能|设置|开关|选项|入口)[^。！？]{0,16}"
    r"(未找到|没找到|找不到|没有找到|未发现|未见)")

TOGGLE_GOAL_RE = re.compile(
    r"(开启|打开|关闭|关掉|切换|调成|设为|设置为|添加我的状态)[^，。]{0,12}"
    r"(模式|开关|状态|深色|夜间|长辈|关怀|备孕|无痕|下班)")

APP_HINTS = ("网易云音乐", "今日头条", "58同城", "哔哩哔哩", "拼多多", "百度",
             "番茄小说", "同花顺", "钉钉", "QQ", "高德", "美柚", "B站")

QUOTE_SPAN_RE = re.compile(r"[“\"「『]([^”\"」』\n]{2,10}?)[”\"」』]")
SETTING_SURFACE_RE = re.compile(r"(设置|大小|开关|状态)$")
CONTAINER_N = {norm(x) for x in CONTAINER_NAMES}

DOUBT_CONFIDENCE_CAP = 0.6   # < MIN_AUTONOMOUS_CONFIDENCE(0.7) → 进门控
NEGATION_CONFIDENCE = 0.4
INJECT_CONFIDENCE = 0.35


def _thoughts(traj: dict) -> list[str]:
    out = []
    resps = traj.get("history_response", []) or []
    for resp in resps:
        m = re.search(r"Thought:\s*(.*?)\s*Action:", str(resp), re.S)
        out.append(m.group(1).strip() if m else str(resp).strip())
    return out


def _post_evidence_window(ths: list[str], m: dict, tail_k: int = 3) -> str:
    """证据步之后的 Thought 才能否定证据步时的结论；无后续则取最后 tail_k 步。"""
    ev = m.get("evidence_steps") or [0]
    start = max(ev) + 1
    window = ths[start:] if start < len(ths) else []
    if not window:
        window = ths[-tail_k:]
    return "\n".join(window)


def _repair_container_name(m: dict, goal: str, raw_n: str) -> str | None:
    """容器名 → 从任务目标/引文中找接地的真选项名。找不到返回 None（保留 WARN）。"""
    name = (m.get("entity") or {}).get("name")
    if not isinstance(name, str) or norm(name) not in CONTAINER_N:
        return None
    candidates: list[str] = []
    g = re.search(r"为([^，。、；\s]{2,8})$", goal.strip())
    if g:
        candidates.append(g.group(1).strip("“”\"'"))
    for span in QUOTE_SPAN_RE.findall(m.get("evidence_quote", "")):
        candidates.append(span)
    for cand in candidates:
        cn = norm(cand)
        if len(cn) >= 2 and cn not in CONTAINER_N and cn in raw_n:
            return cand
    return None


def conservatism_pass(ledger: dict, traj: dict) -> list[str]:
    """确定性保守降级（就地修改污染清单），返回人类可读的处置记录。

    1. 证据步之后出现明确否定 → 社交写入/开关 done|pending 降 attempted_unknown；
       仅出现提交存疑 → 社交写入置信度压到门控阈值以下；
    2. 开关型任务目标 + 终局没找到目标 + 末尾在设置子页有点击且无反馈，
       而污染清单漏登 → 补录一条 attempted_unknown settings_toggle 强制挂起；
    3. settings_toggle 实体名是容器名 → 用目标/引文中接地的选项名替换。
    """
    notes: list[str] = []
    ths = _thoughts(traj)
    if not ths:
        return notes
    raw, _, _ = trajectory_text(traj)
    raw_n = norm(raw)
    goal = str(ledger.get("task_goal") or traj.get("task_goal") or "")

    for m in ledger.get("mutations", []):
        if m.get("attribution") != "this_task" or \
                m.get("status") not in ("done", "pending"):
            # 容器名修复与状态无关，attempted_unknown 也修
            if m.get("type") == "settings_toggle" and \
                    m.get("attribution") == "this_task":
                fixed = _repair_container_name(m, goal, raw_n)
                if fixed and fixed != (m.get("entity") or {}).get("name"):
                    old = m["entity"]["name"]
                    m["entity"]["name"] = fixed
                    notes.append(f"{m.get('id')}: 容器名 {old!r} → 选项名 {fixed!r}"
                                 f"（任务目标/引文接地，确定性修复）")
            continue
        window = _post_evidence_window(ths, m)
        mid = m.get("id")
        if m.get("type") in SOCIAL_TYPES:
            if SOCIAL_NEGATION_RE.search(window):
                m["status"] = "attempted_unknown"
                m["confidence"] = min(float(m.get("confidence", 1.0)),
                                      NEGATION_CONFIDENCE)
                notes.append(f"{mid}: 证据步后的终局否定（用户不存在/无法添加等）"
                             f"→ {m['type']} 降为 attempted_unknown 并强制门控")
            elif SUBMISSION_DOUBT_RE.search(window):
                if float(m.get("confidence", 1.0)) >= 0.7:
                    m["confidence"] = DOUBT_CONFIDENCE_CAP
                    notes.append(f"{mid}: 证据步后出现'是否提交成功'存疑表述"
                                 f"→ 置信度压至 {DOUBT_CONFIDENCE_CAP}（进门控）")
        elif m.get("type") == "settings_toggle" and SETTING_NEGATION_RE.search(window):
            m["status"] = "attempted_unknown"
            m["confidence"] = min(float(m.get("confidence", 1.0)),
                                  NEGATION_CONFIDENCE)
            notes.append(f"{mid}: 证据步后仍明确没找到目标开关/模式"
                         f" → settings_toggle 降为 attempted_unknown 并强制门控")
        if m.get("type") == "settings_toggle":
            fixed = _repair_container_name(m, goal, raw_n)
            if fixed and fixed != (m.get("entity") or {}).get("name"):
                old = m["entity"]["name"]
                m["entity"]["name"] = fixed
                notes.append(f"{mid}: 容器名 {old!r} → 选项名 {fixed!r}"
                             f"（任务目标/引文接地，确定性修复）")

    # ---- 补录：目标开关没找到 + 末尾疑似设置写操作，但污染清单漏登 --------------
    has_toggle = any(m.get("type") == "settings_toggle"
                     and m.get("attribution") == "this_task"
                     for m in ledger.get("mutations", []))
    acts = traj.get("history_action", []) or []
    tail_ths = ths[-3:]
    tail_txt = "\n".join(tail_ths)
    params_txt = ""
    if acts:
        p = acts[-1].get("params", {}) or {}
        params_txt = " ".join(str(v) for v in p.values() if isinstance(v, str))
    late_click = any(a.get("action") == "click" for a in acts[-3:])
    if (not has_toggle and TOGGLE_GOAL_RE.search(goal)
            and SETTING_NEGATION_RE.search(tail_txt + "\n" + params_txt)
            and late_click):
        # 末段 Thought 里被加引号的设置界面元素；优先真正的操作面（大小/开关/
        # 设置/状态），排除始终没找到的目标"XX模式"
        spans = [s for s in QUOTE_SPAN_RE.findall(tail_txt)
                 if norm(s) in raw_n and norm(s) not in CONTAINER_N]
        surfaces = [s for s in spans if SETTING_SURFACE_RE.search(s)]
        cand = surfaces[-1] if surfaces else None
        app = next((a for a in APP_HINTS if a in goal), None)
        if cand and app:
            off = bool(re.search(r"关闭|关掉|关了|退出|取消", goal))
            step = next((i for i in range(len(ths) - 1, -1, -1)
                         if cand in ths[i] and i < len(acts)
                         and acts[i].get("action") == "click"),
                        next((i for i in range(len(acts) - 1, -1, -1)
                              if acts[i].get("action") == "click"), len(acts) - 1))
            sentence = next((s.strip() for s in re.split(r"[。！？\n]", ths[step])
                             if cand in s and len(s.strip()) >= 4),
                            cand)
            new_id = f"m{len(ledger.get('mutations', [])) + 1}"
            ledger.setdefault("mutations", []).append({
                "id": new_id,
                "type": "settings_toggle",
                "app": app,
                "entity": {"kind": "setting", "name": cand, "identifier": None},
                "direction": "off" if off else "on",
                "persistence": "device_local",
                "status": "attempted_unknown",
                "reversible": "ui_invert",
                "evidence_steps": [step],
                "evidence_quote": sentence,
                "confidence": INJECT_CONFIDENCE,
                "attribution": "this_task",
                "carried_over_from_task": None,
            })
            notes.append(f"{new_id}: 目标开关未找到但末尾在设置子页有点击且无反馈，"
                         f"补录 attempted_unknown settings_toggle（{app}/{cand}）"
                         f"强制门控，防止静默跳过")
    return notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True, help="run_id，如 q2_A_1")
    ap.add_argument("--task", help="只审计单个任务")
    ap.add_argument("--ledger-root", type=Path, default=DEFAULT_LEDGER_ROOT)
    ap.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    ap.add_argument("--out", type=Path, help="审计报告 JSON")
    args = ap.parse_args()

    ledger_dir = args.ledger_root / args.run
    run_dir = args.results_root / args.run
    if not ledger_dir.exists():
        print(f"❌ 污染清单目录不存在: {ledger_dir}", file=sys.stderr)
        return 2

    ledger_files = ([ledger_dir / f"{args.task}_ledger.json"] if args.task
                    else sorted(ledger_dir.glob("*_ledger.json")))
    reports = []
    n_vio = n_warn = n_led = 0
    for lp in ledger_files:
        if not lp.exists():
            print(f"⚠ 缺失污染清单: {lp}")
            continue
        with open(lp, "r", encoding="utf-8") as f:
            ledger = json.load(f)
        traj_path = run_dir / ledger["task_id"] / "trajectory.json"
        if not traj_path.exists():
            print(f"⚠ 找不到轨迹: {traj_path}")
            continue
        with open(traj_path, "r", encoding="utf-8") as f:
            traj = json.load(f)
        rep = audit_ledger(ledger, traj)
        reports.append(rep)
        n_led += 1
        n_vio += len(rep["violations"])
        n_warn += len(rep["warnings"])
        tag = "✓" if not rep["violations"] else "✗"
        extra = f" ⚠{len(rep['warnings'])}" if rep["warnings"] else ""
        print(f"{tag} {rep['task']:<28} mutations={rep['n_mutations']}{extra}")
        for v in rep["violations"]:
            print(f"    VIOLATION {v}")
        for w in rep["warnings"]:
            print(f"    warn {w}")

    print("=" * 60)
    print(f"审计 {n_led} 条污染清单：违规 {n_vio}，警告 {n_warn}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"n_ledgers": n_led, "n_violations": n_vio,
                       "n_warnings": n_warn, "reports": reports},
                      f, ensure_ascii=False, indent=2)
        print(f"报告 → {args.out}")
    return 1 if n_vio else 0


if __name__ == "__main__":
    raise SystemExit(main())

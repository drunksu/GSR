#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""infer_mutations.py —— 阶段 A 离线推断原型：任务轨迹 → 污染清单（contamination list）。

输入：MobileBench-OL 的 trajectory.json（task_goal + history_action + history_response）。
输出：contamination-list/v0.1 JSON（见 ../docs/design.md §3；落盘文件名沿用 *_ledger.json）。

阶段 A 支持四种输入模态对照（--modality）：
  text            ：仅 Thought+Action 文本（默认）
  text_xml        ：文本 + 每步 UI 层级树 XML（紧凑化后拼入 prompt）
  text_image      ：文本 + 每步真机截图（base64 作为 image_url 发给 VL 模型）
  text_xml_image  ：文本 + XML + 截图

用法（Windows / venv=mobile）::

    set MBL_API_KEY=sk-...        （或让 mbl_env 从 mobile.env.ps1 自动读取）
    mobile\Scripts\python.exe infer_mutations.py \
        --run-dir third_party\mobilebench-ol-main\results\base_canonical --task qq_1 \
        --out-dir ..\results\ledgers --modality text_image
    mobile\Scripts\python.exe infer_mutations.py --run-dir ... --all --model qwen3-vl-plus --modality text_xml
    --dry-run 只打印 prompt 不调 API。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))
import mbl_env  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mutation_taxonomy as tax  # noqa: E402
import audit_grounding  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3-vl-plus"


# ----------------------------------------------------------------- 轨迹读取

def load_trajectory(traj_path: Path) -> dict:
    with open(traj_path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_episode_success(run_dir: Path, task_id: str):
    """从 episodes.jsonl 取该任务的判定成功标志；找不到返回 None（不致命）。"""
    ep_path = run_dir / "episodes.jsonl"
    if not ep_path.exists():
        return None
    with open(ep_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("task") == task_id:
                return bool(row.get("success"))
    return None


def step_lines(traj: dict) -> list[str]:
    """把轨迹压成模型好读的逐步行文；Thought 截断防 prompt 爆长。"""
    actions = traj.get("history_action", []) or []
    responses = traj.get("history_response", []) or []
    out: list[str] = []
    for i, act in enumerate(actions):
        action_type = act.get("action", "?")
        params = act.get("params", {}) or {}
        if action_type == "click":
            pos = params.get("position")
            act_repr = f"click({pos})"
        elif action_type == "type":
            act_repr = f"type(text={params.get('text', '')!r})"
        elif action_type in ("terminate", "finished"):
            act_repr = f"{action_type}({params.get('content', '')!r})"
        else:
            act_repr = f"{action_type}({json.dumps(params, ensure_ascii=False)})"
        thought = ""
        if i < len(responses):
            m = re.search(r"Thought:\s*(.*?)\s*Action:", responses[i], re.S)
            thought = (m.group(1).strip() if m else responses[i].strip())
        if len(thought) > 600:
            thought = thought[:600] + " …[截断]"
        out.append(f"Step {i}: THOUGHT: {thought}\n        ACTION: {act_repr}")
    return out


# ----------------------------------------------------------------- 多模态辅助

MODALITIES = ("text", "text_xml", "text_image", "text_xml_image")


def step_files(task_dir: Path, ext: str) -> list[Path]:
    """按 step 编号升序返回 task_dir 下的 step_N.<ext> 文件。"""
    files = list(task_dir.glob(f"step_*.{ext}"))
    def _num(p: Path) -> int:
        m = re.search(r"step_(\d+)", p.name)
        return int(m.group(1)) if m else 0
    return sorted(files, key=_num)


def compact_ui_xml(xml_text: str, max_chars: int = 5000) -> str:
    """把 Android UI 层级树 XML 压成紧凑文本，只保留有意义的节点与属性。

    原始 XML 含大量冗余属性（index/focused/scrollable/drawing-order…），
    这里只输出有 text / resource-id / content-desc 的节点或可点击节点，
    属性保留 text、id、desc、类名、clickable、bounds，层级用缩进表示。
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return "[UI XML 解析失败]"
    lines: list[str] = []

    def walk(node: ET.Element, depth: int) -> None:
        text = (node.get("text") or "").strip()
        rid = (node.get("resource-id") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        cls = (node.get("class") or "").split(".")[-1]
        clickable = node.get("clickable") == "true"
        bounds = node.get("bounds") or ""
        if text or rid or desc or clickable:
            parts = []
            if cls:
                parts.append(cls)
            if text:
                parts.append(f"text={text!r}")
            if rid:
                parts.append(f"id={rid}")
            if desc:
                parts.append(f"desc={desc!r}")
            if clickable:
                parts.append("clickable")
            if bounds:
                parts.append(f"bounds={bounds}")
            lines.append("  " * depth + " ".join(parts))
        for child in node:
            walk(child, depth + 1)

    walk(root, 0)
    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars] + "\n…[截断]"
    return out


def encode_image_data_url(path: Path) -> str:
    """把 PNG 读成 data:image/png;base64,... 供 VL API 的 image_url 使用。"""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def ui_xml_block(task_dir: Path) -> list[str]:
    """把 task_dir 下所有 step_N.xml 紧凑化后拼成 prompt 文本块。"""
    xmls = step_files(task_dir, "xml")
    if not xmls:
        return []
    out = ["", "## 各步 UI 层级树（紧凑）"]
    for xf in xmls:
        m = re.search(r"step_(\d+)", xf.name)
        idx = m.group(1) if m else "?"
        try:
            xml_text = xf.read_text(encoding="utf-8")
        except OSError:
            continue
        out.append(f"--- step_{idx} UI ---")
        out.append(compact_ui_xml(xml_text))
    return out


# ----------------------------------------------------------------- prompt

SYS_PROMPT = f"""你是移动 GUI 任务轨迹的「状态变更审计员」。给你一个任务描述和一条
完整执行轨迹（含执行 agent 每步的中文 Thought 与结构化 Action），你要判断：**这次
执行在手机 App / 账号 / 服务端留下了哪些任务结束后仍然存在的状态变更**。

背景：这些轨迹来自顺序批量评测，设备不会在任务间重置。后续任务会被前序任务残留的
状态影响（例如夜间模式没关、好友申请还挂着、搜索历史有残留）。我们要据此做恢复。

============================================================
## 三大铁律（违反即错，务必逐条核对）
============================================================

【铁律一：实体名必须逐字来自轨迹，绝不编造】
  设置项名字、好友 QQ 号、群名、搜索词、消息正文……所有 entity.name / identifier
  都必须是轨迹里**逐字出现的原文**。找不到就填 null 或标 status=attempted_unknown。
  evidence_quote 也必须是 Thought/Action 文本的**连续原文摘录**，不得改写。

【铁律二：settings_toggle 只有"点了开关"才算，进设置页不算】
  · 必须在 Action 里出现对 Switch/开关控件的 click，且该控件 bounds 与开关位置吻合，
    才允许登记 settings_toggle 且 status=done。
  · 只进入"设置"页面、浏览设置项列表、读取当前开关状态 → **不登记任何 settings_toggle**。
  · name 填**开关名**（如"关怀模式""夜间模式"），不要填值（如"女""黑色"）
    也不要填菜单名（如"通用设置"）。

【铁律三：搜索框输入的词必须登记 search_history，且 name 逐字照抄】
  · 只要在搜索框（不是问答框、不是聊天框）里输入过内容，就必须登记
    type=search_history, direction=created，且 entity.name = 输入词原文（逐字）。
  · 同时在顶层 search_terms 数组里逐字列出所有输入过的搜索词。
  · 问答框（入群验证、身份验证）里输入的答案**不是**搜索词。

============================================================
## 你必须遵守的规则
1. 只依据轨迹证据下结论。实体（设置项名字、好友 QQ 号、群名、输入的搜索词）必须是
   轨迹里逐字出现的；证据不足就标 status=attempted_unknown 或降低 confidence，
   **禁止编造**任何标识符。evidence_quote 必须是从 Thought 或 Action 文本里**连续
   摘录的原文**（允许用省略号跳过中间片段，但每个分句都要逐字照抄），不得改写、
   翻译或把不相邻的句子拼在一起。
2. success 字段只表示官方评测器判定任务是否成功，**不代表有无持久化变更**：任务
   判失败但开关可能已被切上，任务成功也可能只浏览没改东西。独立判断。
3. 纯导航/浏览/查询（打开页面看一眼、播放、翻页）不产生持久化变更，不要登记。
4. 空结果是合法且重要的输出：没有持久化变更时 mutations 给 []。
5. 搜索框里输入过的搜索词会留下搜索历史，统一登记 type=search_history、
   direction=created、persistence 多为 account（云同步搜索）或 device_local，
   并在顶层 search_terms 里逐字列出输入词。**搜索历史是真实的持久化残留
   （会影响后续任务的搜索界面），只要由本任务产生就必须登记**。注意：只有在**搜索框**里输入
   的词才算搜索历史；在申请表问答题框里输入的答案（如入群验证问题）不是搜索词。
6. type/direction/kind 区分：
   - 加**好友**申请 → relationship_request；加**群/退群** → membership_change；
   - **收藏**文章/商品/视频 → type=social_reaction, direction=collected；**点赞**
     → direction=liked（收藏/点赞不是 content_lifecycle，绝不要写 created）；
     关注作者/歌手/店铺 → direction=followed；
   - 发布/新建笔记、帖子、日程、地址 → content_lifecycle+created；
   - entity.kind：IM 联系人才用 friend/group；歌手/作者/店铺/公众号等公开主体用
     account；文章/商品/视频/帖子/动态用 content；设置项用 setting；
   - entity.name 统一填**被改动的对象本身**，各 type 口径如下：
     · message_send：name 填**消息正文内容**（逐字，恢复时要重发的那句话），
       收件人昵称/QQ号填 identifier；不要把收件人当 name；照片/表情等多媒体
       消息没有文字正文时，name 用轨迹里对该内容的称呼原文（如“照片”“微笑”）。
     · settings_toggle：name 填**设置项/开关的名字**（如“关怀模式”“夜间模式”
       “性别”“翻页方式”），不要填选中的值（如“女”“上下”“黑色”），
       也不要写容器菜单名（如“字体大小设置”“通用设置”）；
     · social_reaction：name 填**被互动的内容对象**（书名/帖子标题/商品名），
       不要填动作名（“收藏”“加书架”“订阅”是 direction，不是 name）；
     · relationship_request / membership_change：name 填对方昵称/群名，
       identifier 填 QQ号/群号；
     · search_history：name 填搜索词原文（逐字）。
7. status=done 必须有**动作确实生效**的证据（开关被选中、“保存成功”“已收藏”等
   反馈）；只进入设置页、没点到开关、或停在“用户不存在/未找到该功能”→ not_done
   或 attempted_unknown。反过来，界面上某状态“已开启/
   已存在”但本任务没有执行开启/创建动作 → 这不是本任务造成的变更：无痕浏览等
   session-only 状态一律 persistence=session 且不登记为持久化变更；其余老状态
   最多标 attribution=preexisting。搜索到“用户不存在”时禁止登记 relationship_request。
8. 可逆性分级：开关/关注/收藏/点赞可拨回 → ui_invert；待审批的申请可取消 →
   cancel_pending；已通过的好友/已加入的群 → counterparty；**本任务新建**的帖子/
   笔记/日程 → delete_created；**删除任务开始前就存在的内容**（旧笔记、聊天记录）
   无法还原 → irreversible；发出的消息、支付/下单 → irreversible；说不清 → unknown。
9. persistence：存在对方/云端服务器 → server；本账号云端配置 → account；
   只在本机 App 设置 → device_local；只在当前前台会话（Home 即清）→ session。
10. 归因 attribution（每条必填）：本任务自己新造成的 → this_task；分不清先后
    （任务开始前就存在）→ preexisting。如果输入中给了「前序任务污染清单」：你**不要**
    手工抄录 carried_over 条目——系统会自动把前序清单里仍开放的残留结转到本清单。
    你只需：(a) 判断本任务自己新造成的变更；(b) 若本任务的动作确实清除或反转了
    某条前序残留，照常登记一条 this_task 变更描述该清除动作。本任务没有新的 type
    输入动作时，绝不要把前序搜索词改标为 this_task。

============================================================
## 易错示例（务必对照，避免重蹈覆辙）
============================================================

【示例 A：进入设置页 ≠ 切换开关】
  轨迹：Thought="先打开设置看看" → Action=click("设置") → Thought="看到夜间模式是关的"
  → 没有后续点击开关的 Action。
  ✗ 错误：登记 settings_toggle(name="夜间模式", direction=created, status=done)
  ✓ 正确：mutations=[]（只是浏览，没点开关，没有变更）

【示例 B：浏览内容 ≠ 发布/收藏】
  轨迹：Thought="找到这篇帖子看看" → Action=click(帖子) → Thought="帖子内容是…"
  → 没有点击"收藏"或"发布"按钮的 Action。
  ✗ 错误：登记 content_lifecycle(direction=created) 或 social_reaction(collected)
  ✓ 正确：mutations=[]（只是阅读浏览）

【示例 C：搜索词必须逐字登记】
  轨迹：Action=set_text("今天天气怎么样", target="搜索框") → Action=click("搜索")
  ✗ 错误：search_terms=[] 或 name="天气"（改写了）
  ✓ 正确：登记 search_history(name="今天天气怎么样", direction=created)，
          search_terms=["今天天气怎么样"]

============================================================
## 输出前自检（逐条过一遍再输出）
============================================================
□ 每条 mutation 的 entity.name 都能在轨迹里找到逐字原文吗？找不到的填 null 了吗？
□ settings_toggle 是否都有"点击开关"的 Action 证据？没有就删掉。
□ 所有搜索框输入是否都登记了 search_history，且 name 逐字正确？
□ 浏览/导航/查询类动作有没有被误登记为变更？
□ evidence_quote 是否是轨迹原文连续摘录？

## 输出格式（严格输出一个 JSON 对象，不要 markdown 围栏，不要多余解释）
{{
  "schema": "{tax.LEDGER_SCHEMA}",
  "task_id": "<原样回填>",
  "run_id": "<原样回填>",
  "task_goal": "<任务描述>",
  "judged_success": <true|false>,
  "mutations": [
    {{
      "id": "m1",
      "type": "<{ '|'.join(tax.MUTATION_TYPES) }>",
      "app": "<App 名>",
      "entity": {{"kind": "<{'|'.join(tax.ENTITY_KINDS)}>",
                 "name": "<界面上看到的名字，没有填 null>",
                 "identifier": "<QQ号/群号等硬标识，没有填 null>"}},
      "direction": "<{'|'.join(tax.DIRECTIONS)}>",
      "persistence": "<{'|'.join(tax.PERSISTENCE_LEVELS)}>",
      "status": "<{'|'.join(tax.STATUSES)}>",
      "reversible": "<{'|'.join(tax.REVERSIBILITY)}>",
      "evidence_steps": [0],
      "evidence_quote": "<轨迹中支撑判断的原文摘录（Thought 或输入文本）>",
      "confidence": 0.0,
      "attribution": "<{'|'.join(tax.ATTRIBUTIONS)}>",
      "carried_over_from_task": "<attribution=carried_over 时填前序 task_id，否则 null>"
    }}
  ],
  "search_terms": ["<逐字输入过的搜索词，没有就 []>"]
}}
"""


def predecessor_block(prev: dict | None) -> list[str]:
    """把前一条污染清单压成紧凑上下文（同一台设备、紧邻的上一个任务）。"""
    if not prev:
        return []
    digest = {
        "task_id": prev.get("task_id"),
        "task_goal": prev.get("task_goal"),
        "mutations": [
            {"type": m.get("type"), "app": m.get("app"),
             "entity": m.get("entity"), "direction": m.get("direction"),
             "status": m.get("status"), "attribution": m.get("attribution"),
             "carried_over_from_task": m.get("carried_over_from_task")}
            for m in prev.get("mutations", [])
        ],
        "search_terms": prev.get("search_terms", []),
    }
    return [
        "## 前序污染清单：截至上一个任务，设备上仍开放的全部残留（含更早任务结转来的）",
        "```json",
        json.dumps(digest, ensure_ascii=False),
        "```",
        "这些状态**都不是本任务造成的**，不要在本清单登记它们（系统会自动结转）。"
        "仅当本任务动作确实清除/反转了其中某项时，登记一条描述该清除动作的 "
        "this_task 变更。",
        "",
    ]


def build_user_prompt(traj: dict, run_id: str, judged_success,
                      prev_ledger: dict | None = None,
                      modality: str = "text",
                      task_dir: Path | None = None) -> str:
    succ_txt = "true" if judged_success is True else (
        "false" if judged_success is False else "未知")
    lines = [
        f"task_id: {traj.get('task_id', '?')}",
        f"run_id: {run_id}",
        f"task_goal: {traj.get('task_goal', '?')}",
        f"judged_success(仅供参考，不可作为变更依据): {succ_txt}",
    ]
    lines.extend(predecessor_block(prev_ledger))
    lines.append(f"共 {len(traj.get('history_action', []) or [])} 步轨迹：")
    lines.append("")
    lines.extend(step_lines(traj))
    if modality in ("text_xml", "text_xml_image") and task_dir is not None:
        lines.extend(ui_xml_block(task_dir))
    return "\n".join(lines)


# ----------------------------------------------------------------- API 调用

def chat_complete(base_url: str, key: str, model: str, messages: list,
                  timeout: int = 180, response_format: dict | None = None) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
    }
    if response_format:
        payload["response_format"] = response_format
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"]


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def parse_ledger_json(text: str) -> dict:
    """容忍模型加围栏/前后缀：取第一个平衡的 {...}。解析失败直接抛错。"""
    text = text.strip()
    m = _JSON_FENCE_RE.search(text)
    if m:
        obj = json.loads(m.group(1))
    else:
        start = text.find("{")
        if start < 0:
            raise ValueError("模型输出里没有 JSON 对象")
        depth = 0
        obj = None
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    obj = json.loads(text[start:i + 1])
                    break
        if obj is None:
            raise ValueError("模型输出的 JSON 括号不平衡")
    # needs_recovery 已废弃（恢复需求等价于 mutations 非空），丢弃模型残留输出
    obj.pop("needs_recovery", None)
    return obj


# ----------------------------------------------------------------- 确定性结转

def canonicalize_search(ledger: dict) -> dict:
    """搜索历史规范化：一个搜索词一条 mutation，空实体名用搜索词回填。

    模型常把多个搜索词塞进一条空名 search_history（或留空 name），这会让去重键
    塌缩、门控无法逐条处置。规范化后每条 mutation 自带实体名，与词表一一对应。
    """
    muts = ledger.get("mutations", [])
    search_idx = [i for i, m in enumerate(muts) if m.get("type") == "search_history"]
    if not search_idx:
        return ledger
    terms = list(ledger.get("search_terms", []))
    named = {audit_grounding.norm(m.get("entity", {}).get("name"))
             for m in (muts[i] for i in search_idx)
             if (m.get("entity") or {}).get("name")}
    unnamed_idx = [i for i in search_idx
                   if not (muts[i].get("entity") or {}).get("name")]
    if not unnamed_idx:
        return ledger
    template = dict(muts[unnamed_idx[0]])  # 证据/置信度等字段沿用首条
    leftover = [t for t in terms if audit_grounding.norm(t) not in named]
    keep = [m for i, m in enumerate(muts) if i not in unnamed_idx]
    for t in leftover:
        nm = dict(template)
        nm["id"] = None
        nm["entity"] = {"kind": "search", "name": t,
                        "identifier": (template.get("entity") or {}).get("identifier")}
        keep.append(nm)
    for i, m in enumerate(keep, start=1):  # 统一重排 id，避免克隆条目撞 id
        m["id"] = f"m{i}"
    ledger["mutations"] = keep
    return ledger


def _mut_key(m: dict) -> tuple:
    """残留实体去重键：同 app/type/方向/实体标识 视为同一条开放残留。"""
    e = m.get("entity") or {}
    ident = e.get("identifier") or e.get("name") or ""
    return (m.get("type"), m.get("app"), m.get("direction"),
            "".join(str(ident).split()).lower())


def merge_carried(prev: dict, cur: dict, typed_n: str = "") -> dict:
    """把前序污染清单中仍开放的残留确定性地结转到当前清单。

    - 当前清单已出现同键条目（模型登记的 this_task/preexisting）视为该残留已被
      本任务接管/处理，不重复结转；
    - 若模型把**前序已存在且本任务没有重新 type 输入**的搜索词误标为
      this_task，确定性改判 carried_over（Thought 里看到旧词不算新输入）；
    - carried 条目的源头任务沿用最早登记方（传递闭包的起点）；
    - search_terms 取并集；门控在合并后重算。
    纯代码、无模型参与，保证链上残留集合只增不丢。
    """
    prev_terms = {audit_grounding.norm(t) for t in prev.get("search_terms", [])}
    prev_by_key = {_mut_key(m): m for m in prev.get("mutations", [])}

    def _relabel_old_search(m: dict) -> bool:
        if m.get("type") != "search_history" or m.get("attribution") != "this_task":
            return False
        name = (m.get("entity") or {}).get("name")
        term = name if name else (
            cur.get("search_terms", [""])[0] if len(cur.get("search_terms", [])) == 1
            else "")
        tn = audit_grounding.norm(term)
        if tn and tn in prev_terms and tn not in typed_n:
            pm = prev_by_key.get(_mut_key(m))
            m["attribution"] = "carried_over"
            m["carried_over_from_task"] = (
                (pm or {}).get("carried_over_from_task") or prev.get("task_id"))
            cur.setdefault("_warnings", []).append(
                f"旧搜索词 {term!r} 本任务无 type 输入，已由 this_task 改判 "
                f"carried_over（源头 {m['carried_over_from_task']}）")
            return True
        return False

    relabeled = [m for m in cur.get("mutations", []) if _relabel_old_search(m)]

    cur_keys = {_mut_key(m) for m in cur.get("mutations", [])}
    n_added = 0
    carried_search = False
    next_id = 1 + len(cur.get("mutations", []))
    for pm in prev.get("mutations", []):
        if _mut_key(pm) in cur_keys:
            continue
        nm = dict(pm)
        nm.pop("id", None)
        nm["id"] = f"c{next_id}"
        next_id += 1
        nm["attribution"] = "carried_over"
        nm["carried_over_from_task"] = (
            pm.get("carried_over_from_task") or prev.get("task_id"))
        cur["mutations"].append(nm)
        cur_keys.add(_mut_key(pm))
        n_added += 1
        carried_search = carried_search or pm.get("type") == "search_history"
    terms = list(cur.get("search_terms", []))
    have = {"".join(str(t).split()).lower() for t in terms}
    # 搜索词条目的实体名可能为空（接地物在顶层词表里）；只要结转了搜索残留，
    # 就把前序词表整体并入（都是仍开放的搜索残留）
    extra_term_sources = list(prev.get("search_terms", [])) if carried_search else []
    for t in extra_term_sources:
        if t and "".join(str(t).split()).lower() not in have:
            terms.append(t)
            have.add("".join(str(t).split()).lower())
    cur["search_terms"] = terms
    cur["_gate"] = tax.gate_decision(cur)
    if n_added:
        cur.setdefault("_warnings", []).append(
            f"确定性结转补录 {n_added} 条 carried_over（前序仍开放的残留）")
    return cur


# ----------------------------------------------------------------- 恢复复核（重新审计）

VERIFY_SYS_PROMPT = """你是移动 GUI 恢复效果的复核员。给你：
  1. 一份「待清理污染清单」（每项含 mutation_id、type、app、实体名、硬标识），
     这是恢复任务要清除的目标；
  2. 一条「恢复任务的完整执行轨迹」（agent 每步 Thought + Action 文本）以及各步截图。

任务：逐项判断污染清单里的每一处污染，是否被这条恢复轨迹**真正清除 / 反转**。

判定口径（务必逐条核对）：
  - cleared=true 仅当轨迹里有明确证据表明该污染已被撤销 / 删除 / 关闭 / 取消，例如：
    搜索历史里该词已被删除、开关已关闭、申请已取消、消息已撤回、内容已删除，
    并且界面或轨迹反馈能够确认完成；
  - 仅"进入相关页面"却没有后续清除动作，或 agent 只是口头声称完成但轨迹里看不到
    清除动作或清除后的证据 → cleared=false；
  - evidence_quote 必须是从 Thought/Action 文本里**逐字摘录的连续原文**；
  - 清单里有几项就要输出几项，不得漏项，也不得编造清单里不存在的 mutation_id。

严格只输出一个 JSON 对象，不要 markdown 围栏，不要多余解释：
{{"verdicts":[{{"mutation_id":"m1","cleared":true,"evidence_quote":"..."}}]}}
"""


def verify_cleared(ledger: dict, recovery_traj: dict, task_dir: Path,
                   model: str, base_url: str, key: str) -> list[dict]:
    """复核恢复效果：逐项判断 this_task 污染是否被恢复轨迹真正清除。

    返回 verdicts 列表（每项含 mutation_id / cleared / evidence_quote）；
    清单里没有 this_task 污染时返回 []（无需复核）。
    """
    this_muts = [m for m in ledger.get("mutations", [])
                 if m.get("attribution") == "this_task"]
    if not this_muts:
        return []

    items = []
    for m in this_muts:
        e = m.get("entity") or {}
        items.append({
            "mutation_id": m.get("id"),
            "type": m.get("type"),
            "app": m.get("app"),
            "entity_name": e.get("name"),
            "entity_identifier": e.get("identifier"),
            "direction": m.get("direction"),
        })

    lines = [
        "## 待清理污染清单",
        "```json",
        json.dumps(items, ensure_ascii=False, indent=1),
        "```",
        "",
        "## 恢复任务完整轨迹",
        "",
    ]
    lines.extend(step_lines(recovery_traj))
    prompt = "\n".join(lines)

    imgs = step_files(task_dir, "png")
    content: list = [{"type": "text", "text": prompt}]
    for imgf in imgs:
        content.append({
            "type": "image_url",
            "image_url": {"url": encode_image_data_url(imgf)},
        })

    messages = [
        {"role": "system", "content": VERIFY_SYS_PROMPT},
        {"role": "user", "content": content},
    ]

    raw = chat_complete(base_url, key, model, messages)
    obj = parse_ledger_json(raw)
    verdicts = obj.get("verdicts")
    if not isinstance(verdicts, list) or not verdicts:
        raise ValueError("复核模型未返回 verdicts 列表")
    return verdicts


# ----------------------------------------------------------------- 主流程

def run_order(run_dir: Path) -> list[str]:
    """按 episodes.jsonl 的 position 给出任务执行顺序；无 episodes 时返回 []。"""
    ep = run_dir / "episodes.jsonl"
    if not ep.exists():
        return []
    rows = []
    with open(ep, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    rows.sort(key=lambda r: r.get("position", 0))
    seen, order = set(), []
    for r in rows:
        t = r.get("task")
        if t and t not in seen and (run_dir / t / "trajectory.json").exists():
            seen.add(t)
            order.append(t)
    return order


def infer_one(traj_path: Path, run_dir: Path, run_id: str, model: str,
              base_url: str, key: str, dry_run: bool,
              prev_ledger: dict | None = None,
              modality: str = "text") -> dict:
    traj = load_trajectory(traj_path)
    task_id = traj.get("task_id") or traj_path.parent.name
    judged = find_episode_success(run_dir, task_id) if run_dir else None
    task_dir = traj_path.parent
    prompt = build_user_prompt(traj, run_id, judged, prev_ledger,
                               modality, task_dir)
    if dry_run:
        print("=" * 70)
        print(f"[dry-run] task={task_id} run={run_id} modality={modality} "
              f"prompt_chars={len(prompt)}")
        if modality in ("text_image", "text_xml_image"):
            imgs = step_files(task_dir, "png")
            print(f"[dry-run] would attach {len(imgs)} screenshot(s)")
        print(prompt[:3000])
        return {}

    if modality in ("text_image", "text_xml_image"):
        imgs = step_files(task_dir, "png")
        content: list | str = [{"type": "text", "text": prompt}]
        for imgf in imgs:
            content.append({
                "type": "image_url",
                "image_url": {"url": encode_image_data_url(imgf)},
            })
    else:
        content = prompt

    messages = [
        {"role": "system", "content": SYS_PROMPT},
        {"role": "user", "content": content},
    ]

    def call() -> str:
        last_err = None
        for attempt in range(2):  # 网络/限流最多重试 1 次；坏 JSON 不走这里
            try:
                return chat_complete(base_url, key, model, messages)
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"API 调用失败: {last_err}")

    raw = call()
    repair_used = False
    # 校验失败时把具体错误回灌一次（确定性修复，不猜内容）；再失败才大声报错
    for _ in range(2):
        ledger = parse_ledger_json(raw)
        # null 字符串清洗（模型偶尔把 JSON null 写成 "null"）
        for _m in ledger.get("mutations", []):
            _e = _m.get("entity")
            if isinstance(_e, dict):
                for _k in ("name", "identifier"):
                    if isinstance(_e.get(_k), str) and _e[_k].strip().lower() in tax.NULL_LIKE:
                        _e[_k] = None
        # 搜索历史规范化（一词一条、空名回填），防止去重键塌缩
        ledger = canonicalize_search(ledger)
        # 保守降级（v0.4）：终局否定/提交存疑/容器名确定性修复/漏登补录。
        # 必须在 schema 校验与门控之前，降级结果接受同一套接地核验。
        conservatism_notes = audit_grounding.conservatism_pass(ledger, traj)
        # 以轨迹事实回填身份字段，防止模型写错 id 污染下游
        ledger["schema"] = tax.LEDGER_SCHEMA
        ledger["task_id"] = task_id
        ledger["run_id"] = run_id
        ledger.setdefault("task_goal", traj.get("task_goal", ""))
        ledger["judged_success"] = bool(judged) if judged is not None else bool(
            traj.get("success"))
        errs = tax.validate_ledger(ledger)
        warnings: list[str] = []
        if not errs:
            # 静态 schema 通过后，先做**确定性 scrub**（不依赖 grounding_checks 报错），
            # 剔除真幻觉搜索词。scrub 已放宽判定：只要 type action 里有该词就保留，
            # 不再依赖 SEARCH_CTX_RE 在 Thought 文本里命中。
            scrub_untyped = audit_grounding.scrub_untyped_terms(ledger, traj)
            if scrub_untyped:
                warnings.append(
                    f"确定性剔除真幻觉搜索词 {scrub_untyped}")
            # scrub 后再做接地核验——此时 violations 只剩真幻觉，
            # 不会再出现 199 个假无污染那种 grounding 过度保守的误伤
            errs, g_warnings = audit_grounding.grounding_checks(ledger, traj)
            warnings.extend(g_warnings)
        if not errs:
            ledger["_gate"] = tax.gate_decision(ledger)
            ledger["_model"] = model
            ledger["_modality"] = modality
            ledger["_repair_used"] = repair_used
            ledger["_warnings"] = warnings + conservatism_notes
            return ledger
        if repair_used:
            break
        repair_used = True
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content":
            "你上一条输出未通过校验，问题：\n- "
            + "\n- ".join(errs)
            + "\n请对照轨迹原文输出修正后的完整 JSON（仍然只输出 JSON 本身）。"})
        raw = call()
    raise ValueError("污染清单校验失败（schema 或接地，已给 1 次修复机会）:\n  - "
                     + "\n  - ".join(errs) + f"\n--- 模型原始输出 ---\n{raw[:1500]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--traj", type=Path, help="单个 trajectory.json")
    ap.add_argument("--run-dir", type=Path,
                    help="一轮实验目录（如 results/s3_A_1），配合 --task/--all")
    ap.add_argument("--task", help="run-dir 下的任务目录名，如 qq_1")
    ap.add_argument("--all", action="store_true", help="跑 run-dir 下全部任务")
    ap.add_argument("--out-dir", type=Path,
                    default=REPO_ROOT / "experiments" / "state_recovery"
                    / "results" / "ledgers",
                    help="污染清单输出根目录（按 run_id 分子目录）")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--base-url",
                    default=os.environ.get("MBL_BASE_URL", DEFAULT_BASE_URL))
    ap.add_argument("--prev-ledger", type=Path,
                    help="单条模式：把指定污染清单作为前序上下文传入")
    ap.add_argument("--modality", choices=MODALITIES, default="text",
                    help="输入模态对照：text（默认）/text_xml/text_image/text_xml_image")
    ap.add_argument("--dry-run", action="store_true", help="只打印 prompt")
    ap.add_argument("--skip-existing", action="store_true",
                    help="批量模式：若目标 ledger 已存在则跳过（用于断点续跑）")
    args = ap.parse_args()

    # jobs: (traj_path, run_dir, run_id, chained)；chained=True 时按序继承上一条清单
    jobs: list[tuple[Path, Path, str, bool]] = []
    explicit_prev = None
    if args.traj:
        run_dir = args.run_dir or args.traj.parents[1]
        jobs.append((args.traj, run_dir,
                     args.run_dir.name if args.run_dir else "unknown", False))
    elif args.run_dir and (args.task or args.all):
        run_dir = args.run_dir
        if args.all:
            order = run_order(run_dir)
            if order:
                for t in order:
                    jobs.append((run_dir / t / "trajectory.json", run_dir,
                                 run_dir.name, True))
            else:
                # 没有 episodes 就不做链式归因（执行顺序不可信）
                for tdir in sorted(p for p in run_dir.iterdir() if p.is_dir()):
                    if (tdir / "trajectory.json").exists():
                        jobs.append((tdir / "trajectory.json", run_dir,
                                     run_dir.name, False))
        else:
            tj = run_dir / args.task / "trajectory.json"
            if tj.exists():
                jobs.append((tj, run_dir, run_dir.name, False))
    else:
        ap.error("需要指定 --traj，或 --run-dir 配 --task/--all")

    if args.prev_ledger:
        with open(args.prev_ledger, "r", encoding="utf-8") as f:
            explicit_prev = json.load(f)

    key = mbl_env.api_key()
    if not args.dry_run and not key:
        print("❌ 未找到 MBL_API_KEY（环境变量或 mobile.env.ps1）", file=sys.stderr)
        return 2

    n_ok = n_fail = 0
    chained_prev = None  # 链式模式下的运行时前序污染清单
    for traj_path, run_dir, run_id, chained in jobs:
        prev = chained_prev if chained else explicit_prev
        # 断点续跑：已存在的 ledger 直接加载（链式模式下仍作为前序上下文）
        if args.skip_existing and not args.dry_run:
            task_id = traj_path.parent.name
            exist_path = args.out_dir / run_id / f"{task_id}_ledger.json"
            if exist_path.exists():
                try:
                    with open(exist_path, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                    chained_prev = existing if chained else None
                    print(f"⊘ {run_id}/{task_id}: 已存在，跳过 → {exist_path}")
                    n_ok += 1
                    continue
                except Exception as e:
                    print(f"✗ {run_id}/{task_id}: 已有 ledger 读取失败，重跑: {e}",
                          file=sys.stderr)
        try:
            ledger = infer_one(traj_path, run_dir, run_id, args.model,
                               args.base_url, key or "", args.dry_run, prev,
                               modality=args.modality)
            if args.dry_run:
                continue
            if prev is not None:
                # 链式归因：模型只判本任务，跨任务残留由代码确定性结转
                _t = load_trajectory(traj_path)
                _, _, _search_typed = audit_grounding.trajectory_text(_t)
                _typed_n = audit_grounding.norm(" ".join(_search_typed))
                ledger = merge_carried(prev, ledger, _typed_n)
                verr = tax.validate_ledger(ledger)
                if verr:
                    raise ValueError("结转后清单校验失败: " + "; ".join(verr))
            out_dir = args.out_dir / run_id
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{ledger['task_id']}_ledger.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(ledger, f, ensure_ascii=False, indent=2)
            g = ledger["_gate"]
            n_co = sum(1 for m in ledger["mutations"]
                       if m.get("attribution") == "carried_over")
            chain_tag = f"，继承 {n_co} 条" if chained and prev else ""
            if ledger.get("_warnings"):
                chain_tag += f"，⚠{len(ledger['_warnings'])}"
            print(f"✓ {run_id}/{ledger['task_id']}: {len(ledger['mutations'])} 条变更 "
                  f"(自主 {len(g['autonomous'])}, 门控 {len(g['halt'])}, "
                  f"noop={g['noop']}{chain_tag}) → {out_path}")
            n_ok += 1
            chained_prev = ledger if chained else None
        except Exception as e:  # 单条失败不拖垮整批，但必须显式报错
            print(f"✗ {run_id}/{traj_path.parent.name}: {e}", file=sys.stderr)
            n_fail += 1
            chained_prev = None  # 链断了就不再向后续任务传递（不能假装知道前序状态）
    print(f"\n完成：成功 {n_ok}，失败 {n_fail}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())

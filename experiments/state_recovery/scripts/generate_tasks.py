#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""generate_tasks.py —— 模块②离线版：污染清单 → 恢复任务集。

四层约束生成策略（2026-10-22 重构）：
  1. 骨架预填：所有确定性字段（schema/id/App名/实体名/risk_level/idempotent/
     max_steps/gate_reason）由代码从污染清单直接写入，LLM 不可触碰；
  2. 逐 mutation 生成：每个 this_task 变更单独一次 LLM 调用，只填该变更对应
     task / human_gate 的自然语言字段，避免多 mutation 时漏生成或 id 错位；
  3. 提示词 + 示例：系统提示词只约束自然语言字段写法，每字段给正例；
  4. 结构化输出 + 校验兜底：response_format=json_object 强制 JSON，回填后
     跑 validate_task_set，确定性错误由代码直接覆盖，自然语言字段问题给
     1 次修复机会。

逐任务触发口径不变：
  - 只为 attribution=this_task 的变更产出处置；
  - gate.autonomous → 自动恢复任务；gate.halt → 人工挂起条目；
  - carried_over / preexisting 不出现。

用法（Windows / venv=mobile）::

    mobile\\Scripts\\python.exe generate_tasks.py --run base_canonical
    mobile\\Scripts\\python.exe generate_tasks.py --run q2_A_1 --all
    mobile\\Scripts\\python.exe generate_tasks.py --ledger ..\\results\\ledgers\\base_canonical\\qq_10_ledger.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))
import mbl_env  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recovery_task as rt  # noqa: E402
import infer_mutations as infer  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LEDGER_ROOT = Path(__file__).resolve().parent.parent / "results" / "ledgers"
DEFAULT_OUT_ROOT = Path(__file__).resolve().parent.parent / "results" / "recovery_tasks"
DEFAULT_MODEL = infer.DEFAULT_MODEL

# 按 mutation 类型取 max_steps 默认值（代码写死，不让 LLM 决定）
MAX_STEPS_BY_TYPE = {
    "search_history": 8,
    "settings_toggle": 8,
    "social_reaction": 8,
    "session_state": 5,
    "relationship_request": 15,
    "membership_change": 15,
    "content_lifecycle": 15,
    "login_session": 15,
    "message_send": 12,
    "other": 12,
}


# ----------------------------------------------------------------- 骨架预填

def _entity_display(mutation: dict) -> str:
    """拼接实体展示名：名称 + 硬标识（有则带括号），供恢复指令接地。"""
    ent = mutation.get("entity") or {}
    name = ent.get("name") or ""
    ident = ent.get("identifier") or ""
    if name and ident:
        return f"{name}（{ident}）"
    return name or ident


def _risk_of(mutation: dict) -> str:
    """由可逆性类别映射风险等级（代码写死）。"""
    return rt.REVERSIBILITY_RISK.get(mutation.get("reversible"), "medium")


def _max_steps_of(mutation: dict) -> int:
    """由 mutation 类型取默认步数（代码写死）。"""
    return MAX_STEPS_BY_TYPE.get(mutation.get("type"), 12)


def build_skeleton(ledger: dict) -> dict:
    """由污染清单构造恢复任务集骨架：所有确定性字段已填好，自然语言字段留空。"""
    auto_ids = sorted(rt.expected_autonomous_ids(ledger))
    halt_ids = sorted(rt.expected_halt_ids(ledger))
    midx = rt._mutation_index(ledger)
    gate = ledger.get("_gate", {})
    reason_by_id = {h["id"]: h.get("reason", "")
                    for h in gate.get("halt", []) if isinstance(h, dict)}

    tasks = []
    for mid in auto_ids:
        m = midx[mid]
        ent = m.get("entity") or {}
        tasks.append({
            "schema": rt.TASK_SCHEMA,
            "mutation_id": mid,
            "recovery_goal": "",          # LLM 填
            "precondition": {
                "target": "",             # LLM 填
                "check_instruction": "",  # LLM 填
                "clean_if_state": "",     # LLM 填
            },
            "expected_end_state": {
                "kind": "vlm_judge",
                "question": "",           # LLM 填
                "expected": "yes",
            },
            "idempotent": True,
            "risk_level": _risk_of(m),
            "max_steps": _max_steps_of(m),
        })

    human_gate = []
    for mid in halt_ids:
        m = midx[mid]
        human_gate.append({
            "mutation_id": mid,
            "title": "",                    # LLM 填
            "gate_reason": reason_by_id.get(mid, ""),  # 代码照抄门控
            "reason": "",                   # LLM 填
            "suggested_manual_action": "",  # LLM 填
        })

    return {
        "schema": rt.TASK_SET_SCHEMA,
        "task_id": ledger["task_id"],
        "run_id": ledger["run_id"],
        "tasks": tasks,
        "human_gate": human_gate,
    }


# ----------------------------------------------------------------- 提示词

TASK_SYS_PROMPT = """你是移动 GUI 自动恢复系统的「恢复计划员」。系统已经为你准备好了
恢复任务的骨架（App名、实体名、风险等级等都已填好），你只需要填写 5 个中文自然语言
字段。严格只输出一个 JSON 对象，不要 markdown 围栏，不要多余解释。

待填写字段与要求：
1. recovery_goal：给 GUI agent 的中文操作指令，必须包含系统给出的 App 名、实体名
   （有硬标识时一并写上），说明要把状态恢复成什么样；不要写"检查一下"这类不确定措辞。
2. precondition.target：一句话说清检查什么状态。
3. precondition.check_instruction：进入哪个页面、看哪个元素来判断当前状态，必须提到
   系统给出的实体名。
4. precondition.clean_if_state：用中文描述"当前已经是什么样就算已恢复"（此时执行器
   将零动作直接成功）。
5. expected_end_state.question：一个独立检查者（不看执行过程）能凭截图回答 yes/no 的
   完整中文问句（句末带问号），必须提到系统给出的实体名，问的是"状态是否已回到目标"。

输出格式：
{"recovery_goal":"...","precondition":{"target":"...","check_instruction":"...","clean_if_state":"..."},"expected_end_state":{"question":"..."}}
"""

HUMAN_GATE_SYS_PROMPT = """你是移动 GUI 自动恢复系统的「恢复计划员」。系统判定这条变更
不能自动恢复，需要人工处理。系统已经填好了 mutation_id 和 gate_reason（照抄门控理由），
你只需要填写 3 个中文自然语言字段。严格只输出一个 JSON 对象，不要 markdown 围栏。

待填写字段与要求：
1. title：一句话说清是什么 App 的什么残留（必须提到实体名）。
2. reason：用中文解释为什么不能自动处理。
3. suggested_manual_action：给出具体的人工操作建议（进入哪个页面、点什么），必须提到
   系统给出的实体名。禁止写成"可以自动试试"。

输出格式：
{"title":"...","reason":"...","suggested_manual_action":"..."}
"""


def build_task_prompt(ledger: dict, mutation: dict) -> str:
    """为单个自动恢复任务构造用户 prompt，给出上下文与接地锚点。"""
    ent = mutation.get("entity") or {}
    display = _entity_display(mutation)
    ctx = {
        "task_goal": ledger.get("task_goal"),
        "mutation": {
            "id": mutation.get("id"),
            "type": mutation.get("type"),
            "app": mutation.get("app"),
            "entity_name": ent.get("name"),
            "entity_identifier": ent.get("identifier"),
            "direction": mutation.get("direction"),
            "persistence": mutation.get("persistence"),
            "evidence_quote": mutation.get("evidence_quote"),
        },
        "grounding": {
            "app": mutation.get("app"),
            "entity_display": display,
            "must_include": [mutation.get("app"), ent.get("name"),
                             ent.get("identifier")] if (ent.get("name") or
                             ent.get("identifier")) else [mutation.get("app")],
        },
    }
    lines = [
        "## 本变更上下文",
        "```json",
        json.dumps(ctx, ensure_ascii=False, indent=1),
        "```",
        f"恢复目标里必须逐字包含：{display or mutation.get('app')}",
        "严格只输出 JSON 对象。",
    ]
    return "\n".join(lines)


def build_human_gate_prompt(ledger: dict, mutation: dict,
                            gate_reason: str) -> str:
    """为单个人工挂起条目构造用户 prompt。"""
    ent = mutation.get("entity") or {}
    display = _entity_display(mutation)
    ctx = {
        "task_goal": ledger.get("task_goal"),
        "mutation": {
            "id": mutation.get("id"),
            "type": mutation.get("type"),
            "app": mutation.get("app"),
            "entity_name": ent.get("name"),
            "entity_identifier": ent.get("identifier"),
            "direction": mutation.get("direction"),
            "evidence_quote": mutation.get("evidence_quote"),
        },
        "gate_reason": gate_reason,
    }
    lines = [
        "## 本变更上下文",
        "```json",
        json.dumps(ctx, ensure_ascii=False, indent=1),
        "```",
        f"挂起条目里必须提到实体：{display or mutation.get('app')}",
        "严格只输出 JSON 对象。",
    ]
    return "\n".join(lines)


# ----------------------------------------------------------------- 单条生成

def _call_llm(sys_prompt: str, user_prompt: str, model: str,
              base_url: str, key: str) -> str:
    """调用 LLM，带 1 次重试，强制 JSON 输出。"""
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]
    last_err = None
    for attempt in range(2):
        try:
            return infer.chat_complete(
                base_url, key, model, messages,
                response_format={"type": "json_object"})
        except Exception as e:  # noqa: BLE001 网络/限流重试 1 次
            last_err = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"API 调用失败: {last_err}")


def _parse_json(text: str) -> dict:
    """解析模型输出的 JSON，容忍围栏。"""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def generate_task_fields(ledger: dict, mutation: dict, model: str,
                         base_url: str, key: str) -> dict:
    """为单个自动恢复任务生成自然语言字段，返回填充后的 task dict。"""
    sys_prompt = TASK_SYS_PROMPT
    user_prompt = build_task_prompt(ledger, mutation)
    raw = _call_llm(sys_prompt, user_prompt, model, base_url, key)
    fields = _parse_json(raw)

    ent = mutation.get("entity") or {}
    app = mutation.get("app")
    name = ent.get("name")
    ident = ent.get("identifier")
    display = _entity_display(mutation)

    def _ground(text: str, must_app: bool = False) -> str:
        """确保自然语言字段包含必要的接地锚点（App 名 + 实体名）。"""
        if not isinstance(text, str) or not text.strip():
            return text
        if must_app and app and app not in text:
            text = f"在{app}中，{text}"
        if display and display not in text:
            if name and name not in text and (not ident or ident not in text):
                text = f"{text}（{name}）"
            elif ident and ident not in text:
                text = f"{text}（{ident}）"
        return text

    goal = _ground(fields.get("recovery_goal", ""), must_app=True)
    if not isinstance(goal, str) or len(goal.strip()) < 8:
        anchor = display or app or "该实体"
        goal = f"在{app}中，将{anchor}的状态恢复到目标状态"
    pre = fields.get("precondition", {}) or {}
    target = pre.get("target", "")
    if not isinstance(target, str) or len(target.strip()) < 4:
        target = f"{display or '该实体'}的当前状态"
    ci = _ground(pre.get("check_instruction", ""))
    if not isinstance(ci, str) or len(ci.strip()) < 4:
        ci = f"进入{app}相关页面，查看{display or '该实体'}的当前状态"
    clean = pre.get("clean_if_state", "")
    if not isinstance(clean, str) or len(clean.strip()) < 4:
        clean = f"{display or '该实体'}已恢复到目标状态，无需操作"
    ass = fields.get("expected_end_state", {}) or {}
    q = _ground(ass.get("question", ""))
    # 兜底：LLM 偶尔返回空/过短问句，用实体名构造默认问句
    if not isinstance(q, str) or len(q.strip()) < 8:
        anchor = display or app or "该实体"
        q = f"{anchor}的状态是否已恢复到目标状态？"
    elif not q.endswith(("？", "?")):
        q = q.rstrip("。.") + "？"

    return {
        "recovery_goal": goal,
        "precondition": {
            "target": target,
            "check_instruction": ci,
            "clean_if_state": clean,
        },
        "expected_end_state": {
            "kind": "vlm_judge",
            "question": q,
            "expected": "yes",
        },
    }


def generate_human_gate_fields(ledger: dict, mutation: dict, gate_reason: str,
                               model: str, base_url: str, key: str) -> dict:
    """为单个人工挂起条目生成自然语言字段。"""
    sys_prompt = HUMAN_GATE_SYS_PROMPT
    user_prompt = build_human_gate_prompt(ledger, mutation, gate_reason)
    raw = _call_llm(sys_prompt, user_prompt, model, base_url, key)
    fields = _parse_json(raw)

    ent = mutation.get("entity") or {}
    name = ent.get("name")
    ident = ent.get("identifier")
    display = _entity_display(mutation)
    app = mutation.get("app")

    def _ground(text: str) -> str:
        if not isinstance(text, str) or not text.strip():
            return text
        if display and display not in text:
            if name and name not in text and (not ident or ident not in text):
                text = f"{text}（{name}）"
            elif ident and ident not in text:
                text = f"{text}（{ident}）"
        return text

    title = _ground(fields.get("title", ""))
    if not isinstance(title, str) or len(title.strip()) < 4:
        title = f"{app}中{display or '该实体'}的残留需人工处理"
    reason = fields.get("reason", "")
    if not isinstance(reason, str) or len(reason.strip()) < 4:
        reason = "该变更无法通过 GUI 自动化自动恢复，需人工介入处理"
    sug = _ground(fields.get("suggested_manual_action", ""))
    if not isinstance(sug, str) or len(sug.strip()) < 4:
        sug = f"请手动进入{app}，处理{display or '该实体'}相关的残留操作"

    return {
        "title": title,
        "gate_reason": gate_reason,  # 代码照抄，不用模型输出
        "reason": reason,
        "suggested_manual_action": sug,
    }


# ----------------------------------------------------------------- 整任务生成

def generate_one(ledger: dict, model: str, base_url: str, key: str,
                 dry_run: bool = False) -> dict:
    """为单个污染清单生成恢复任务集：骨架预填 + 逐 mutation 生成 + 校验。"""
    skeleton = build_skeleton(ledger)
    midx = rt._mutation_index(ledger)
    gate = ledger.get("_gate", {})
    reason_by_id = {h["id"]: h.get("reason", "")
                    for h in gate.get("halt", []) if isinstance(h, dict)}

    if dry_run:
        print("=" * 70)
        print(f"[dry-run] task={ledger.get('task_id')} run={ledger.get('run_id')}")
        print(f"  自动恢复任务 {len(skeleton['tasks'])} 个，"
              f"人工挂起 {len(skeleton['human_gate'])} 条")
        for t in skeleton["tasks"]:
            m = midx[t["mutation_id"]]
            print(f"  [task {t['mutation_id']}] type={m.get('type')} "
                  f"risk={t['risk_level']} steps={t['max_steps']}")
            print(f"    prompt:\n{build_task_prompt(ledger, m)}")
        for h in skeleton["human_gate"]:
            m = midx[h["mutation_id"]]
            print(f"  [halt {h['mutation_id']}] reason={h['gate_reason']}")
            print(f"    prompt:\n{build_human_gate_prompt(ledger, m, h['gate_reason'])}")
        return skeleton

    # 逐 mutation 生成自然语言字段
    n_call = 0
    for t in skeleton["tasks"]:
        m = midx[t["mutation_id"]]
        fields = generate_task_fields(ledger, m, model, base_url, key)
        t["recovery_goal"] = fields["recovery_goal"]
        t["precondition"] = fields["precondition"]
        t["expected_end_state"] = fields["expected_end_state"]
        n_call += 1

    for h in skeleton["human_gate"]:
        m = midx[h["mutation_id"]]
        fields = generate_human_gate_fields(
            ledger, m, h["gate_reason"], model, base_url, key)
        h["title"] = fields["title"]
        h["reason"] = fields["reason"]
        h["suggested_manual_action"] = fields["suggested_manual_action"]
        n_call += 1

    # 校验
    errs = rt.validate_task_set(skeleton, ledger)
    if not errs:
        skeleton["_model"] = model
        skeleton["_llm_calls"] = n_call
        return skeleton

    # 仅对自然语言字段问题给 1 次修复；确定性错误（接地/risk等）已由代码消除
    for t in skeleton["tasks"]:
        m = midx[t["mutation_id"]]
        task_errs = [e for e in errs
                     if e.startswith(f"tasks[{t['mutation_id']}]")]
        if task_errs:
            fields = generate_task_fields(ledger, m, model, base_url, key)
            t["recovery_goal"] = fields["recovery_goal"]
            t["precondition"] = fields["precondition"]
            t["expected_end_state"] = fields["expected_end_state"]
            n_call += 1

    for h in skeleton["human_gate"]:
        m = midx[h["mutation_id"]]
        gate_errs = [e for e in errs
                     if e.startswith(f"human_gate[{h['mutation_id']}]")]
        if gate_errs:
            fields = generate_human_gate_fields(
                ledger, m, h["gate_reason"], model, base_url, key)
            h["title"] = fields["title"]
            h["reason"] = fields["reason"]
            h["suggested_manual_action"] = fields["suggested_manual_action"]
            n_call += 1

    errs = rt.validate_task_set(skeleton, ledger)
    if errs:
        raise ValueError("恢复任务集校验失败（已给 1 次修复机会）:\n  - "
                         + "\n  - ".join(errs))

    skeleton["_model"] = model
    skeleton["_llm_calls"] = n_call
    return skeleton


# ----------------------------------------------------------------- CLI

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", type=Path, help="单个 *_ledger.json（污染清单落盘文件）")
    ap.add_argument("--ledger-root", type=Path, default=DEFAULT_LEDGER_ROOT)
    ap.add_argument("--run", help="ledger-root 下的 run 目录名，如 base_canonical")
    ap.add_argument("--task", help="只处理某个任务（文件名前缀，如 qq_10）")
    ap.add_argument("--all", action="store_true", help="处理 run 目录下全部污染清单")
    ap.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--base-url",
                    default=__import__("os").environ.get(
                        "MBL_BASE_URL", infer.DEFAULT_BASE_URL))
    ap.add_argument("--dry-run", action="store_true", help="只打印 prompt")
    ap.add_argument("--skip-existing", action="store_true",
                    help="跳过已存在 *_tasks.json 的任务")
    args = ap.parse_args()

    jobs: list[Path] = []
    if args.ledger:
        jobs.append(args.ledger)
    elif args.run and (args.task or args.all):
        run_dir = args.ledger_root / args.run
        if args.all:
            jobs = sorted(run_dir.glob("*_ledger.json"))
        else:
            p = run_dir / f"{args.task}_ledger.json"
            if not p.exists():
                ap.error(f"找不到 {p}")
            jobs.append(p)
    else:
        ap.error("需要指定 --ledger，或 --run 配 --task/--all")

    key = mbl_env.api_key()
    if not args.dry_run and not key:
        print("❌ 未找到 MBL_API_KEY（环境变量或 mobile.env.ps1）", file=sys.stderr)
        return 2

    n_ok = n_fail = n_skip = 0
    for lp in jobs:
        try:
            with open(lp, "r", encoding="utf-8") as f:
                ledger = json.load(f)

            out_dir = args.out_root / ledger["run_id"]
            out_path = out_dir / f"{ledger['task_id']}_tasks.json"
            if args.skip_existing and out_path.exists() and not args.dry_run:
                print(f"⊘ {ledger['run_id']}/{ledger['task_id']}: 已存在，跳过")
                n_skip += 1
                continue

            pset = generate_one(ledger, args.model, args.base_url,
                                key or "", args.dry_run)
            if args.dry_run:
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(pset, f, ensure_ascii=False, indent=2)
            print(f"✓ {ledger['run_id']}/{ledger['task_id']}: "
                  f"{len(pset['tasks'])} 个自动恢复任务，"
                  f"{len(pset['human_gate'])} 条人工挂起 "
                  f"（LLM 调用 {pset.get('_llm_calls', 0)} 次）→ {out_path}")
            n_ok += 1
        except Exception as e:  # noqa: BLE001 单条失败不拖垮整批，但显式报错
            print(f"✗ {lp.name}: {e}", file=sys.stderr)
            n_fail += 1
    if not args.dry_run:
        print(f"\n完成：成功 {n_ok}，跳过 {n_skip}，失败 {n_fail}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())

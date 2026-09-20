#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mbl_find_actions.py —— 在跑过的轨迹里做"取证"：哪个任务干了某件事？

典型用途：
  * 手机上莫名多了一个好友 / 进了一个群 → 查是哪个任务的哪一步干的
  * 某个 App 的设置被改了 → 查是谁改的
  * 想统计"任务声称完成但实际做了别的事"

它会扫描每个任务目录的 trajectory.json，在 **goal / 模型每步原始输出 / 执行的动作** 里
搜关键字，并给出任务、步号、命中关键字和上下文片段。

用法：
    # QQ 加好友/加群
    python mbl_find_actions.py --run-dir results/base_canonical ^
        --keywords 加好友,添加好友,加群,群聊,加入群,申请加,同意,好友申请

    # 顺带把另一个顺序也扫了
    python mbl_find_actions.py --run-dir results/base_canonical --run-dir results/base_shuffle --keywords 好友,群

    # 只看目标里就带关键字的任务（不扫轨迹）
    python mbl_find_actions.py --run-dir results/base_canonical --goals-only --keywords 群,好友

输出：控制台表格 + 可选 --json 落盘。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

DEFAULT_KEYWORDS = "加好友,添加好友,加群,群聊,加入群,申请加,同意,好友申请,发送好友"

# 动作里能看出"写了状态"的类型（用于给命中排序时提权）
WRITE_ACTIONS = {"click", "type", "swipe"}


def load_result_list(run_dir: str) -> dict[str, bool]:
    p = os.path.join(run_dir, "result_list.txt")
    if not os.path.exists(p):
        return {}
    out = {}
    for item in open(p, encoding="utf-8").read().strip().split(" "):
        if "," in item:
            k, v = item.rsplit(",", 1)
            out[k.strip()] = v.strip().lower() == "true"
    return out


def ctx(text: str, kw: str, width: int = 90) -> str:
    """截取关键字周围的上下文，去掉换行。"""
    if not text:
        return ""
    i = text.find(kw)
    if i < 0:
        return ""
    s = max(0, i - width // 2)
    snippet = text[s:s + width].replace("\n", " ").replace("\r", " ")
    return ("…" if s > 0 else "") + snippet.strip() + "…"


def scan_task(tdir: str, keywords: list[str], goals_only: bool) -> list[dict]:
    fp = os.path.join(tdir, "trajectory.json")
    if not os.path.exists(fp):
        return []
    try:
        t = json.load(open(fp, encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return []
    task = t.get("task_id") or os.path.basename(tdir)
    goal = t.get("task_goal") or ""
    hits = []

    for kw in keywords:
        if kw in goal:
            hits.append({"source": "goal", "step": None, "keyword": kw, "snippet": goal})
    if goals_only:
        return hits

    responses = t.get("history_response") or []
    actions = t.get("history_action") or []
    for idx, resp in enumerate(responses, 1):
        text = resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False)
        for kw in keywords:
            if kw in text:
                hits.append({"source": "model_response", "step": idx, "keyword": kw,
                             "snippet": ctx(text, kw)})
    for idx, act in enumerate(actions, 1):
        text = json.dumps(act, ensure_ascii=False)
        # 只有文本类动作才可能"打字加好友/群号"
        if act.get("action") == "type":
            for kw in keywords:
                if kw in text:
                    hits.append({"source": "action(type)", "step": idx, "keyword": kw,
                                 "snippet": ctx(text, kw)})
    # 最终自述
    summary = " | ".join(t.get("summary") or [])
    for kw in keywords:
        if kw in summary:
            hits.append({"source": "summary", "step": None, "keyword": kw,
                         "snippet": ctx(summary, kw)})
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", action="append", required=True,
                    help="可多次指定（如 --run-dir results/base_canonical --run-dir results/base_shuffle）")
    ap.add_argument("--keywords", default=DEFAULT_KEYWORDS)
    ap.add_argument("--goals-only", action="store_true", help="只在任务目标里搜（不扫轨迹）")
    ap.add_argument("--json", default=None, help="把结果写到该 JSON 文件")
    args = ap.parse_args()

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    print(f"关键字 {len(keywords)} 个: {keywords}\n")

    all_rows = []
    for rd in args.run_dir:
        run_dir = os.path.abspath(rd)
        if not os.path.isdir(run_dir):
            print(f"⚠️  跳过不存在的目录 {run_dir}")
            continue
        results = load_result_list(run_dir)
        tdirs = sorted(d for d in glob.glob(os.path.join(run_dir, "*"))
                       if os.path.isdir(d) and not os.path.basename(d).startswith("."))
        print(f"### {os.path.basename(run_dir)}  ({len(tdirs)} 个任务目录)")
        for tdir in tdirs:
            hits = scan_task(tdir, keywords, args.goals_only)
            if not hits:
                continue
            task = os.path.basename(tdir)
            succ = results.get(task)
            flag = "成功" if succ else ("失败" if succ is False else "未记录")
            steps = sorted({h["step"] for h in hits if h["step"]})
            kws = sorted({h["keyword"] for h in hits})
            print(f"  ★ {task:20s} 判定={flag:6s} 命中步={steps or '-'} 关键字={kws}")
            for h in hits[:6]:
                print(f"      [{h['source']:<14s} step={h['step']}] {h['snippet'][:130]}")
            all_rows.append({"run": os.path.basename(run_dir), "task": task,
                             "success": succ, "steps": steps, "keywords": kws, "hits": hits})
        print()

    if not all_rows:
        print("没有命中。可以换关键字再试（比如只搜单个字「群」或「好友」）。")
    else:
        # 按"命中步数多少 + 是否成功"排个粗序，方便找最可疑的
        all_rows.sort(key=lambda r: (-len(r["hits"]), r["task"]))
        print("=== 可疑度排序（命中越多越可疑）===")
        for r in all_rows:
            print(f"  {r['task']:20s} run={r['run']:18s} 命中 {len(r['hits']):3d} 处  "
                  f"判定={'成功' if r['success'] else '失败'}  关键字={r['keywords']}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(all_rows, fh, ensure_ascii=False, indent=2)
        print(f"\nJSON -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

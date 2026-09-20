#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mbl_make_task_csv.py —— 从官方任务集里切出一个子集并**按指定顺序**写出新 CSV。

为什么需要它
------------
`run.py` 的执行顺序 = **CSV 行序**（`load_tasks()` 用 csv.DictReader 顺序读，无排序无打乱），
而任务文件只能通过 `get_task_file(subset)` 拿到 —— 所以：

  * 想只跑 3 个任务做冒烟测试  → 需要自己切 CSV
  * 想跑"顺序执行 vs 乱序执行" → 需要**同一批任务、不同行序**的多份 CSV

本脚本就是这两件事的工具：先按 ID 选任务，再按 canonical / reverse / shuffle 排列，
写出与官方格式完全一致（utf-8-sig、同表头）的 CSV。

用法
----
    # 冒烟：只要 2 个任务
    python mbl_make_task_csv.py --repo <repo> --tasks bili_0,bili_4 \\
        --out smoke_2task.csv

    # 同一批任务，三种顺序（顺序实验的基础）
    python mbl_make_task_csv.py --repo <repo> --limit 30 --order canonical --out base_canonical.csv
    python mbl_make_task_csv.py --repo <repo> --limit 30 --order shuffle --seed 0 --out base_shuffle0.csv
    python mbl_make_task_csv.py --repo <repo> --limit 30 --order reverse --out base_reverse.csv

跑的时候用环境变量把文件喂给 run.py（需先打 `--task-file-env` 补丁）：
    set MBL_TASK_FILE=data/smoke_2task.csv
    python run.py --mode interact --config config/interact_API_qwen3vl_base.conf --subset base --output results/smoke
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import sys

CANONICAL_COL_NOTE = "顺序 = CSV 行序；本工具只改行序、不改内容"


def load(source: str) -> tuple[list[str], list[dict]]:
    with open(source, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--source", default=None,
                    help="源任务集（默认 base 用的 'MobileBench-OL - top12.csv'）")
    ap.add_argument("--tasks", default=None, help="逗号分隔的 task_identifier，按此顺序输出")
    ap.add_argument("--limit", type=int, default=None, help="不指定 --tasks 时取前 N 个")
    ap.add_argument("--order", choices=("as-is", "canonical", "reverse", "shuffle"),
                    default="as-is")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True, help="输出 CSV（相对仓库 data/ 或绝对路径）")
    ap.add_argument("--require-reset-label", action="store_true",
                    help="只保留 Reset 列非空（作者标注'会产生残留'）的任务")
    ap.add_argument("--drop-reset-label", action="store_true",
                    help="只保留 Reset 列为空的任务（读取型，victim 候选）")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    src = args.source or os.path.join(repo, "data", "MobileBench-OL - top12.csv")
    if not os.path.isabs(src):
        src = os.path.join(repo, "data", src)
    if not os.path.exists(src):
        print(f"❌ 找不到源任务集: {src}")
        return 2

    fieldnames, rows = load(src)
    print(f"源: {os.path.basename(src)}  共 {len(rows)} 行，{len(fieldnames)} 列")

    if args.require_reset_label:
        rows = [r for r in rows if (r.get("Reset") or "").strip()]
        print(f"  只保留 Reset 标注非空 → {len(rows)} 行")
    if args.drop_reset_label:
        rows = [r for r in rows if not (r.get("Reset") or "").strip()]
        print(f"  只保留 Reset 标注为空 → {len(rows)} 行")

    # 选任务
    if args.tasks:
        want = [t.strip() for t in args.tasks.split(",") if t.strip()]
        by_id = {(r.get("task_identifier") or "").strip(): r for r in rows}
        missing = [t for t in want if t not in by_id]
        if missing:
            print(f"❌ 源文件里没有这些任务: {missing}")
            avail = sorted(by_id)[:12]
            print(f"   （可用的前 12 个: {avail}）")
            return 2
        rows = [by_id[t] for t in want]
    elif args.limit:
        rows = rows[: args.limit]

    # 排列
    if args.order == "canonical":
        rows = sorted(rows, key=lambda r: (r.get("task_identifier") or ""))
    elif args.order == "reverse":
        rows = sorted(rows, key=lambda r: (r.get("task_identifier") or ""), reverse=True)
    elif args.order == "shuffle":
        random.Random(args.seed).shuffle(rows)

    out = args.out if os.path.isabs(args.out) else os.path.join(repo, "data", args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"\n写出 {len(rows)} 个任务 -> {out}   （order={args.order}"
          + (f", seed={args.seed}" if args.order == "shuffle" else "") + "）")
    print(f"  {CANONICAL_COL_NOTE}")
    # 任务多时只列前 15 个，避免刷屏
    show = rows if len(rows) <= 20 else rows[:15]
    for i, r in enumerate(show, 1):
        print(f"  {i:3d}. {(r.get('task_identifier') or ''):20s} "
              f"[{(r.get('task_app') or '?'):13s}] steps={r.get('golden_steps','?'):>3s} "
              f"reset={(r.get('Reset') or '-') or '-':7s} {r.get('goal','')[:34]}")
    if len(rows) > len(show):
        print(f"  … 其余 {len(rows) - len(show)} 个已省略（完整顺序见生成的 CSV）")
    print(f"\n用法: set MBL_TASK_FILE={os.path.relpath(out, repo).replace(os.sep, '/')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

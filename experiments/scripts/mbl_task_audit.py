#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mbl_task_audit.py —— 审计 MobileBench-OL 的任务集 CSV。

回答三个问题：
  1. 任务集在哪、每个文件多少任务、覆盖哪些 App？
  2. 每个 CSV 有哪些列？`load_tasks()` 需要的列是否齐全、有没有空值？
  3. 有没有坏行（列数错位 / key_nodes 解析不了）—— CSV 是手改过的，必须查。

用法：
    python mbl_task_audit.py --repo <path-to-mobilebench-ol>
    python mbl_task_audit.py --repo <path> --out ../../results/mbl_audit

输出：控制台摘要 + audit.json + 任务集清单.md（含每台手机要装的 APK 清单）
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import Counter, defaultdict

# get_task_file() 里的真实映射（run.py）
SUBSET_MAP = {
    "base": "MobileBench-OL - top12.csv",
    "long-tail": "longtail.csv",
    "long-horizon": "MobileBench-OL - Long-Horizon.csv",
    "gui-reasoning": "MobileBench-OL - Explo_already.csv",
    "noise-robust": "MobileBench-OL - top12.csv  (再被改写成 '... - {repeat,unexecuted,delay,popup}.csv'，仓库里不存在)",
}

# task_executor.load_tasks() 真正读取的列
REQUIRED = ["task_identifier", "goal", "adb_home_page", "golden_steps", "key_nodes"]
OPTIONAL = ["reset_xpath", "reset_query"]


def read_raw(path: str) -> tuple[list[str], list[list[str]], str, bool]:
    """返回 (表头, 数据行, 实际编码, 仓库 loader 能否直接读)。

    仓库里 `load_tasks()` 写死了 `encoding="utf-8-sig"`，
    所以任何非 UTF-8 的 CSV 都会让原版 loader 直接 UnicodeDecodeError。
    """
    with open(path, "rb") as fh:
        raw = fh.read()
    loader_ok = True
    enc_used = "utf-8-sig"
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        loader_ok = False
        for cand in ("gb18030", "gbk", "big5", "utf-16"):
            try:
                text = raw.decode(cand)
                enc_used = cand
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8-sig", errors="replace")
            enc_used = "utf-8-sig(replace)"
    rows = list(csv.reader(text.splitlines()))
    if not rows:
        return [], [], enc_used, loader_ok
    return rows[0], rows[1:], enc_used, loader_ok


def audit_file(path: str) -> dict:
    header, rows, enc_used, loader_ok = read_raw(path)
    ncol = len(header)
    bad_width = [i + 2 for i, r in enumerate(rows) if len(r) != ncol]  # 行号从 2 起（含表头）

    recs = []
    for r in rows:
        if not r or not any(c.strip() for c in r):
            continue
        d = dict(zip(header, r + [""] * (ncol - len(r))))
        recs.append(d)

    missing = {c: 0 for c in REQUIRED + OPTIONAL if c not in header}
    empty = Counter()
    bad_nodes = []
    for i, d in enumerate(recs, start=2):
        for c in REQUIRED:
            if c in header and not (d.get(c) or "").strip():
                empty[c] += 1
        kn = (d.get("key_nodes") or "").strip()
        if kn and not (kn.startswith("{") and "xpath" in kn):
            bad_nodes.append({"row": i, "task": d.get("task_identifier", ""), "head": kn[:60]})

    apps = {}
    for d in recs:
        app = (d.get("task_app") or "").strip()
        if not app:
            continue
        apps.setdefault(
            app,
            {
                "app": app,
                "app_chn": (d.get("task_app_CHN") or "").strip(),
                "home": (d.get("adb_home_page") or "").strip(),
                "n_tasks": 0,
            },
        )["n_tasks"] += 1

    diff = Counter((d.get("difficulty_level") or "?").strip() for d in recs)
    reset_flag = Counter((d.get("Reset") or "?").strip() for d in recs)
    n_need_reset = sum(
        1 for d in recs if (d.get("reset_query") or "").strip() and (d.get("reset_xpath") or "").strip()
    )

    return {
        "file": os.path.basename(path),
        "size_bytes": os.path.getsize(path),
        "encoding": enc_used,
        "loader_compatible": loader_ok,
        "n_rows": len(rows),
        "n_tasks_parsed": len(recs),
        "n_tasks_kept_by_loader": sum(1 for d in recs if (d.get("key_nodes") or "").strip()),
        "columns": header,
        "missing_columns": missing,
        "empty_required": dict(empty),
        "rows_with_wrong_field_count": bad_width,
        "rows_with_unparseable_key_nodes": bad_nodes,
        "difficulty": dict(diff),
        "reset_column_values": dict(reset_flag),
        "n_tasks_with_reset_query_and_xpath": n_need_reset,
        "apps": sorted(apps.values(), key=lambda x: -x["n_tasks"]),
    }


def _load(repo: str, name: str, enc: str = "utf-8-sig") -> list[dict]:
    with open(os.path.join(repo, "data", name), encoding=enc, newline="") as fh:
        return list(csv.DictReader(fh))


def reset_overlap(repo: str) -> None:
    """任务集与 reset 标注集的关系 —— 这是挑"污染源任务"的直接依据。"""
    print("\n## 主任务集 vs reset 标注集")
    for main, reset in (("MobileBench-OL - top12.csv", "top12-reset.csv"),
                        ("longtail.csv", "longtail-reset.csv")):
        m = {r["task_identifier"].strip() for r in _load(repo, main)}
        r = {x["task_identifier"].strip() for x in _load(repo, reset)}
        print(f"- `{main}` {len(m)} 个 vs `{reset}` {len(r)} 个 → 交集 {len(m & r)}，"
              f"**reset 独有 {len(r - m)}**")

    base = _load(repo, "MobileBench-OL - top12.csv")
    print("\n## base 子集每个 App 的任务数")
    for app, n in Counter((r.get("task_app") or "?").strip() for r in base).most_common():
        print(f"- {app}: {n}")

    need = [r for r in base if (r.get("Reset") or "").strip()]
    print(f"\n## base 里被作者标注为「会产生残留」的任务：{len(need)} / {len(base)}")
    print(f"- Reset 列取值分布: {dict(Counter((r.get('Reset') or '').strip() for r in need))}")
    print("\n## base 前 8 个任务示例")
    for r in base[:8]:
        print(f"- [{r.get('task_app','?'):12s}] {r['task_identifier']:20s} "
              f"steps={str(r.get('golden_steps','')):>3s} reset={r.get('Reset','') or '-':8s} "
              f"goal={r['goal'][:38]}")


def apk_column_info(repo: str) -> None:
    """longtail.csv 多一个 `apk` 列，可能记录了 App 包信息（对复现 xpath 很关键）。"""
    rows = _load(repo, "longtail.csv")
    vals = Counter((r.get("apk") or "").strip() for r in rows)
    print(f"\n## longtail.csv 的 `apk` 列（{len(vals)} 个不同取值，前 15 个）")
    for v, n in vals.most_common(15):
        print(f"- {v!r}: {n} 个任务")
    print("\n（其它 CSV 没有这一列；若这里只是包名而非版本号，说明作者未固定 App 版本）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="mobilebench-ol 仓库根目录")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    data_dir = os.path.join(args.repo, "data")
    files = sorted(f for f in os.listdir(data_dir) if f.lower().endswith(".csv"))
    audits = [audit_file(os.path.join(data_dir, f)) for f in files]

    print(f"# MobileBench-OL 任务集审计  (data/ 下 {len(files)} 个 CSV)\n")
    print("| 文件 | 大小 | 编码 | loader 可读 | 数据行 | loader 保留 | 唯一 App | 难度分布 | Reset 列 | 有 reset_query+xpath | 坏行 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for a in audits:
        print(
            f"| {a['file']} | {a['size_bytes']//1024} KB | {a['encoding']} | "
            f"{'✅' if a['loader_compatible'] else '❌'} | {a['n_rows']} | {a['n_tasks_kept_by_loader']} | "
            f"{len(a['apps'])} | {a['difficulty']} | {a['reset_column_values']} | "
            f"{a['n_tasks_with_reset_query_and_xpath']} | {len(a['rows_with_wrong_field_count'])} |"
        )

    print("\n## subset → 文件映射（run.py::get_task_file）")
    for k, v in SUBSET_MAP.items():
        print(f"- `--subset {k}` → `data/{v}`")

    referenced = {v.split()[0] for v in SUBSET_MAP.values()}
    unreachable = [a["file"] for a in audits if a["file"] not in referenced]
    print(f"\n**get_task_file() 无法到达的文件**（含 reset 通道要用的）：{unreachable}")

    print("\n## 每份任务集需要的 App")
    for a in audits:
        print(f"\n### {a['file']}  （{len(a['apps'])} 个 App）")
        print("| App | 中文名 | 入口 Activity | 任务数 |")
        print("|---|---|---|---|")
        for app in a["apps"]:
            print(f"| `{app['app']}` | {app['app_chn']} | `{app['home']}` | {app['n_tasks']} |")

    print("\n## 列结构")
    for a in audits:
        flag = "⚠️ 缺 " + ",".join(a["missing_columns"]) if a["missing_columns"] else "✅ 必需列齐全"
        print(f"- **{a['file']}**: {flag}")
        print(f"  - 列: {a['columns']}")
        if a["empty_required"]:
            print(f"  - 必需列空值: {a['empty_required']}")
        if a["rows_with_wrong_field_count"]:
            print(f"  - ⚠️ 列数异常的行号: {a['rows_with_wrong_field_count']}")
        if a["rows_with_unparseable_key_nodes"]:
            print(f"  - ⚠️ key_nodes 可疑行: {a['rows_with_unparseable_key_nodes'][:5]}")

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "audit.json"), "w", encoding="utf-8") as fh:
            json.dump({"audits": audits, "subset_map": SUBSET_MAP, "unreachable": unreachable},
                      fh, ensure_ascii=False, indent=2)
        print(f"\nJSON -> {os.path.join(args.out, 'audit.json')}")

    reset_overlap(args.repo)
    if os.path.exists(os.path.join(args.repo, "data", "longtail.csv")):
        apk_column_info(args.repo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

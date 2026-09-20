#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mbl_app_checklist.py —— 生成"要装哪些 App"的清单（可直接当待办清单用）。

从任务集 CSV 里聚合出每个 App：中文名、包名、入口 Activity、任务数、
其中有多少个被作者标注"会产生残留"（Reset 非空），并可顺手用 adb 查已装情况。

用法：
    python mbl_app_checklist.py --repo <repo>
    python mbl_app_checklist.py --repo <repo> --subset long-tail --adb <adb.exe> --device <serial>
    python mbl_app_checklist.py --repo <repo> --out ../results/app_checklist.md
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
from collections import defaultdict

SUBSETS = {
    "base": "MobileBench-OL - top12.csv",
    "long-tail": "longtail.csv",
    "long-horizon": "MobileBench-OL - Long-Horizon.csv",
    "gui-reasoning": "MobileBench-OL - Explo_already.csv",
    "base-reset": "top12-reset.csv",
    "long-tail-reset": "longtail-reset.csv",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--subset", default="base", choices=sorted(SUBSETS))
    ap.add_argument("--adb", default=None, help="adb.exe 路径（给了就查已装情况）")
    ap.add_argument("--device", default=None, help="设备序列号")
    ap.add_argument("--out", default=None, help="输出 markdown 路径")
    args = ap.parse_args()

    src = os.path.join(os.path.abspath(args.repo), "data", SUBSETS[args.subset])
    if not os.path.exists(src):
        print(f"❌ 找不到 {src}")
        return 2
    with open(src, encoding="utf-8-sig", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if (r.get("key_nodes") or "").strip()]

    agg: dict[str, dict] = defaultdict(lambda: {"n": 0, "n_reset": 0, "apk": ""})
    for r in rows:
        app = (r.get("task_app") or "?").strip()
        a = agg[app]
        a["n"] += 1
        a["app_chn"] = (r.get("task_app_CHN") or "").strip()
        a["home"] = (r.get("adb_home_page") or "").strip()
        if (r.get("Reset") or "").strip():
            a["n_reset"] += 1
        if (r.get("apk") or "").strip():
            a["apk"] = (r.get("apk") or "").strip()

    installed: set[str] = set()
    if args.adb and os.path.exists(args.adb):
        cmd = [args.adb] + (["-s", args.device] if args.device else []) + ["shell", "pm", "list", "packages"]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
            installed = {ln.strip().replace("package:", "") for ln in out.splitlines() if ln.strip()}
        except Exception as exc:  # noqa: BLE001
            print(f"（查询设备失败: {exc}）")

    order = sorted(agg.items(), key=lambda kv: -kv[1]["n"])
    missing = [k for k, v in order if installed and v["home"].split("/")[0] not in installed]

    lines = [f"# 需要安装的 App 清单（子集: {args.subset}）", ""]
    lines.append(f"来源: `data/{SUBSETS[args.subset]}`，共 {len(rows)} 个任务 / {len(agg)} 个 App")
    if installed:
        lines.append(f"\n设备已装 {len(agg) - len(missing)} 个，**还需要装 {len(missing)} 个**。")
    lines += ["", "| 装好了 | App | 中文名 | 包名 | 入口 Activity | 任务数 | 其中需重置 | 版本线索 |",
              "|---|---|---|---|---|---|---|---|"]
    for app, a in order:
        pkg = a["home"].split("/")[0]
        # ☑ = 已装；☐ = 待装（未用 adb 查询时一律 ☐）
        mark = "☑" if (installed and pkg in installed) else "☐"
        lines.append(f"| {mark} | `{app}` | {a.get('app_chn','')} | `{pkg}` | `{a['home']}` | "
                     f"{a['n']} | {a['n_reset']} | {a['apk'] or '—'} |")
    lines += ["", "## 说明", "",
              "- **版本线索**列只有 `longtail.csv` 有（形如 `keep_8.5.30.apk`）；`base` 任务集**没有任何版本约束**，",
              "  所以任意较新的商店版本先试，xpath 匹配不上再换版本。",
              "- APK 需要你自己获取（仓库不提供）：各 App 官网 / 应用宝 / 华为·小米应用商店 / APKMirror / APKPure 均可，",
              "  注意遵守各平台的许可与使用条款。",
              "- 装完后用 `mbl_app_checklist.py --adb <adb> --device <serial>` 复查一遍打勾情况。",
              "- 只用 base 的话，**B站独占 30 个任务**（最大单 App 任务块），所以哪怕只装 B站也能先做第一轮实验。"]
    text = "\n".join(lines)
    print(text)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        open(args.out, "w", encoding="utf-8").write(text + "\n")
        print(f"\n已写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

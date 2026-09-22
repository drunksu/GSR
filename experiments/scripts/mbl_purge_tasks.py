#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mbl_purge_tasks.py —— 从 result_list.txt 里摘掉某些任务，让下次运行重跑它们。

为什么长跑必须要有它
--------------------
`run.py` 的续跑机制是：只要任务出现在 `result_list.txt` 里就跳过。
所以一次 16 小时的长跑里，任何**与实验无关的失败**（手机熄屏导致的黑屏、
ADB 抖动、接口偶发错误）都会被永久记成"任务失败"，无法重试 —— 直接污染 ΔSR。

用法：
    # 先看看这一轮有哪些任务需要重跑（不修改任何东西）
    python mbl_purge_tasks.py --run-dir results/base_canonical --blank-only --dry-run
    python mbl_purge_tasks.py --run-dir results/base_canonical --failed-only --dry-run

    # 真删（删完重跑同一条 run 命令即可自动续跑这些任务）
    python mbl_purge_tasks.py --run-dir results/base_canonical --blank-only
    python mbl_purge_tasks.py --run-dir results/base_canonical --tasks bili_0,bili_4

注意：删掉后重跑时，框架会先清空该任务目录里的旧文件再跑（见 try_execute_task_with_retry），
所以旧截图不会残留。若要保留旧证据，先自己复制一份目录。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import sys


def read_result_list(path: str) -> list[tuple[str, str]]:
    if not os.path.exists(path):
        return []
    content = open(path, encoding="utf-8").read().strip()
    pairs = []
    for item in content.split(" "):
        if "," in item:
            k, v = item.rsplit(",", 1)
            pairs.append((k.strip(), v.strip()))
    return pairs


def write_result_list(path: str, pairs: list[tuple[str, str]]) -> None:
    shutil.copy2(path, path + ".bak")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(" ".join(f"{k},{v}" for k, v in pairs))


def blank_tasks(run_dir: str, thresh: float = 25.0, std_thresh: float = 3.0) -> list[str]:
    """找出末帧黑屏/纯色的任务（与顺序污染无关的设备问题）。"""
    try:
        from PIL import Image  # noqa: PLC0415
        import numpy as _np  # noqa: PLC0415
    except ImportError:
        print("需要 pillow/numpy：pip install pillow numpy")
        return []
    out = []
    for d in sorted(os.listdir(run_dir)):
        tdir = os.path.join(run_dir, d)
        if not os.path.isdir(tdir) or d.startswith("."):
            continue
        pngs = sorted(glob.glob(os.path.join(tdir, "step_*.png")),
                      key=lambda p: int(re.findall(r"step_(\d+)", p)[0] or 0))
        if not pngs:
            continue
        try:
            arr = _np.asarray(Image.open(pngs[-1]).convert("L"), dtype=_np.float32)
            if float(arr.mean()) < thresh or float(arr.std()) < std_thresh:
                out.append(d)
        except Exception:  # noqa: BLE001
            pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--tasks", default=None, help="逗号分隔的任务 id")
    ap.add_argument("--failed-only", action="store_true", help="删掉所有判为失败的任务")
    ap.add_argument("--blank-only", action="store_true",
                    help="删掉末帧黑屏的任务（⚠️ 会连成功的也删，见下）")
    ap.add_argument("--blank-failed-only", action="store_true",
                    help="只删「末帧黑屏 **且** 失败」的任务 —— 这才是与顺序无关的设备问题，推荐用这个")
    ap.add_argument("--thresh", type=float, default=25.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    run_dir = os.path.abspath(args.run_dir)
    rl = os.path.join(run_dir, "result_list.txt")
    pairs = read_result_list(rl)
    if not pairs:
        print(f"❌ 读不到 {rl}（或为空）")
        return 2
    print(f"当前 {len(pairs)} 条记录，其中失败 {sum(1 for _, v in pairs if v.lower() != 'true')} 条")

    targets: set[str] = set()
    if args.tasks:
        targets |= {t.strip() for t in args.tasks.split(",") if t.strip()}
    if args.failed_only:
        targets |= {k for k, v in pairs if v.lower() != "true"}
    if args.blank_only:
        bl = blank_tasks(run_dir, args.thresh)
        # ⚠️ 实测（base_canonical 310）：「末帧暗」并不等于「失败」—— 21 个被标记的任务里
        #    有 13 个其实**成功**了。原因很合理：音乐/播放类任务成功之后屏幕就熄了，
        #    即时通讯类成功之后也常常息屏。把成功的结果一起删掉会让 SR 失真。
        #    只想摘掉"设备问题"造成的假失败，请用 --blank-failed-only。
        succ = {k for k, v in pairs if v.lower() == "true"}
        overlap = sorted(set(bl) & succ)
        print(f"检测到末帧黑屏的任务 {len(bl)} 个: {bl}")
        if overlap:
            print(f"  ⚠️ 其中 {len(overlap)} 个其实**是成功的**: {overlap}")
            print("     末帧变暗 ≠ 失败（播放类任务成功后就会息屏）。"
                  "只摘设备问题请改用 --blank-failed-only。")
        targets |= set(bl)
    if args.blank_failed_only:
        bl = set(blank_tasks(run_dir, args.thresh))
        fails = {k for k, v in pairs if v.lower() != "true"}
        both = bl & fails
        print(f"末帧黑屏 {len(bl)} 个 ∩ 失败 {len(fails)} 个 → 认定设备问题 {len(both)} 个: {sorted(both)}")
        targets |= both

    # 只保留确实存在的 key
    known = {k for k, _ in pairs}
    unknown = sorted(targets - known)
    targets &= known
    if unknown:
        print(f"（忽略不在 result_list.txt 里的 {len(unknown)} 个: {unknown[:8]}）")

    if not targets:
        print("没有需要摘掉的任务。")
        return 0

    print(f"\n将摘掉 {len(targets)} 个任务，使下次运行重跑它们：")
    for k, v in pairs:
        if k in targets:
            print(f"  - {k:22s} 原结果={v}")
    if args.dry_run:
        print("\n（--dry-run：未修改任何文件）")
        return 0

    kept = [(k, v) for k, v in pairs if k not in targets]
    write_result_list(rl, kept)
    # 顺手把它们从 episodes.jsonl 里剔除，避免旧数据混进分析
    ep = os.path.join(run_dir, "episodes.jsonl")
    if os.path.exists(ep):
        rows = [json.loads(l) for l in open(ep, encoding="utf-8") if l.strip()]
        rows = [r for r in rows if r.get("task") not in targets]
        with open(ep, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"  已同步更新 episodes.jsonl（剩 {len(rows)} 条）")
    print(f"\n✅ 已写入 {rl}（原文件备份为 result_list.txt.bak）")
    print(f"   剩余 {len(kept)} 条；重跑同一条 run 命令即可自动补跑这 {len(targets)} 个任务。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

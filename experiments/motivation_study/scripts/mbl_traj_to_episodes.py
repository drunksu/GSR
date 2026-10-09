#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mbl_traj_to_episodes.py —— 把 MobileBench-OL 真机跑出来的结果转成 episodes.jsonl。

目的：让 `analyze_order_effects.py`（ΔSR / OD-flaky 率 / CTCI / PASR / polluter lift / DiD）
**直接吃真机数据**，不用改分析代码。

输入：一次运行的输出目录（`run.py --output <dir>`），里面有
    result_list.txt            "task_id,True task_id2,False"
    <task_id>/trajectory.json   {task_id, task_goal, history_action[], history_response[], summary, success}
    <task_id>/step_*.png/.xml   每步截图 + 元素树
    <task_id>/api_metrics.jsonl （可选，--metrics 补丁产出：延迟/token）
    <task_id>/step_timing.jsonl （可选，--metrics 补丁产出：每步起始时间）
    run_manifest.json           （可选，run_mbl.ps1 产出：顺序模式/重置条件/任务顺序）

输出：episodes.jsonl，字段与 AndroidWorld 那条链路完全一致，额外多几个成本字段。

    {"run_id","agent","condition","order_mode","order_seed","repeat","position",
     "predecessor","task","goal","success","exception","episode_length","run_time_s",
     "ts","api_calls","api_latency_s","prompt_tokens","completion_tokens","api_errors",
     "timing_source"}

condition 的取值沿用分析脚本的约定：
    "official" = reset=true（跑了 cleaner）
    "none"     = reset=false（只重启 App，没有 cleaner）

用法：
    python mbl_traj_to_episodes.py --run-dir <results/o1> --out <results/o1/episodes.jsonl>
    python mbl_traj_to_episodes.py --run-dir <results/o1> \
        --order-mode shuffle --condition none --agent qwen3-vl-plus \
        --tasks data/order_shuffle0.csv --out <results/o1/episodes.jsonl>
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
from datetime import datetime


def read_task_order(csv_path: str) -> list[str]:
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        return [(r.get("task_identifier") or "").strip()
                for r in csv.DictReader(fh) if (r.get("task_identifier") or "").strip()]


def read_metrics(task_dir: str) -> dict:
    """汇总 --metrics 补丁产出的 api_metrics.jsonl。"""
    fp = os.path.join(task_dir, "api_metrics.jsonl")
    out = {"api_calls": 0, "api_latency_s": 0.0, "prompt_tokens": 0,
           "completion_tokens": 0, "api_errors": 0}
    if not os.path.exists(fp):
        return out
    with open(fp, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            out["api_calls"] += 1
            out["api_latency_s"] += float(rec.get("latency_s") or 0.0)
            out["prompt_tokens"] += int(rec.get("prompt_tokens") or 0)
            out["completion_tokens"] += int(rec.get("completion_tokens") or 0)
            if rec.get("error"):
                out["api_errors"] += 1
    out["api_latency_s"] = round(out["api_latency_s"], 1)
    return out


def episode_duration(task_dir: str, metrics: dict) -> tuple[float, str]:
    """优先用 step_timing.jsonl；否则退回 PNG 文件时间；都不行给 0。"""
    fp = os.path.join(task_dir, "step_timing.jsonl")
    if os.path.exists(fp):
        ts = []
        with open(fp, encoding="utf-8") as fh:
            for line in fh:
                try:
                    ts.append(json.loads(line).get("start_ts"))
                except Exception:  # noqa: BLE001
                    pass
        ts = [t for t in ts if isinstance(t, (int, float))]
        if len(ts) >= 2:
            return round(max(ts) - min(ts), 1), "step_timing"
        if len(ts) == 1:
            return 0.0, "step_timing(单步)"
    pngs = sorted(glob.glob(os.path.join(task_dir, "step_*.png")),
                  key=lambda p: os.path.getmtime(p))
    if len(pngs) >= 2:
        return round(os.path.getmtime(pngs[-1]) - os.path.getmtime(pngs[0]), 1), "png_mtime"
    return 0.0, "none"


def screen_quality(task_dir: str) -> dict:
    """最后一张截图的平均亮度 —— 用来识别"黑屏/锁屏"这类设备问题。

    实测案例：同一任务重复跑时出现 `Premature` 失败，agent 自述"屏幕持续黑屏"，
    这类失败**与顺序污染无关**，若不标记出来会被误算成 OD 效应。
    """
    out = {"last_step_brightness": None, "screen_blank": False}
    try:
        from PIL import Image  # noqa: PLC0415
        import glob as _g  # noqa: PLC0415
        import numpy as _np  # noqa: PLC0415
    except ImportError:
        return out
    pngs = sorted(_g.glob(os.path.join(task_dir, "step_*.png")))
    if not pngs:
        return out
    try:
        arr = _np.asarray(Image.open(pngs[-1]).convert("L"), dtype=_np.float32)
        mean = float(arr.mean())
        out["last_step_brightness"] = round(mean, 1)
        # 黑屏或纯色（方差极小）都判为异常画面
        out["screen_blank"] = bool(mean < 25 or float(arr.std()) < 3.0)
    except Exception:  # noqa: BLE001
        pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out", default=None, help="默认写到 <run-dir>/episodes.jsonl")
    ap.add_argument("--manifest", default=None, help="默认读 <run-dir>/run_manifest.json")
    ap.add_argument("--tasks", default=None, help="任务顺序 CSV（给出则以此确定 position/predecessor）")
    ap.add_argument("--order-mode", default=None, help="canonical / reverse / shuffle / adversarial")
    ap.add_argument("--order-seed", type=int, default=0)
    ap.add_argument("--condition", default=None, help="official(=reset) / none(=no reset)")
    ap.add_argument("--agent", default=None)
    ap.add_argument("--repeat", type=int, default=0)
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()

    run_dir = os.path.abspath(args.run_dir)
    if not os.path.isdir(run_dir):
        print(f"❌ 目录不存在: {run_dir}")
        return 2

    manifest = {}
    mfp = args.manifest or os.path.join(run_dir, "run_manifest.json")
    if os.path.exists(mfp):
        # PS 5.1 的 Set-Content -Encoding UTF8 会写 BOM，必须用 utf-8-sig 读
        with open(mfp, encoding="utf-8-sig") as fh:
            manifest = json.load(fh)
        print(f"读到 manifest: {mfp}")

    order_mode = args.order_mode or manifest.get("order_mode") or "unknown"
    condition = args.condition or manifest.get("condition") or "unknown"
    agent = args.agent or manifest.get("agent") or manifest.get("model") or "unknown"
    repeat = args.repeat if args.repeat else int(manifest.get("repeat", 0))
    order_seed = args.order_seed if args.order_seed else int(manifest.get("order_seed", 0))
    run_id = args.run_id or manifest.get("run_id") or os.path.basename(run_dir.rstrip("/\\"))

    # 任务顺序 → position / predecessor
    order: list[str] = []
    if manifest.get("tasks"):
        order = list(manifest["tasks"])
    elif args.tasks:
        tf = args.tasks
        if not os.path.isabs(tf):
            tf = os.path.join(manifest.get("repo", "."), tf)
        if os.path.exists(tf):
            order = read_task_order(tf)
    if not order:
        print("⚠️  没有任务顺序信息（manifest 里无 tasks，也没给 --tasks）"
              " → position 按任务目录名字典序，predecessor 可能不准")

    # result_list.txt 是权威成败来源；trajectory.json 补细节
    results: dict[str, bool] = {}
    rl = os.path.join(run_dir, "result_list.txt")
    if os.path.exists(rl):
        content = open(rl, encoding="utf-8").read().strip()
        for pair in content.split(" "):
            if "," in pair:
                k, v = pair.rsplit(",", 1)
                results[k.strip()] = v.strip().lower() == "true"
    else:
        print("⚠️  没有 result_list.txt，只能靠 trajectory.json 的 success 字段")

    task_dirs = sorted(d for d in os.listdir(run_dir)
                       if os.path.isdir(os.path.join(run_dir, d)) and not d.startswith("."))
    if order:
        task_dirs = [t for t in order if t in task_dirs] + \
                    [t for t in task_dirs if t not in order]
    pos_of = {t: i for i, t in enumerate(order)} if order else {}

    rows = []
    now_iso = datetime.now().isoformat(timespec="seconds")
    for i, tid in enumerate(task_dirs):
        tdir = os.path.join(run_dir, tid)
        traj_fp = os.path.join(tdir, "trajectory.json")
        traj = {}
        if os.path.exists(traj_fp):
            try:
                traj = json.load(open(traj_fp, encoding="utf-8-sig"))
            except json.JSONDecodeError:
                print(f"⚠️  {tid}/trajectory.json 解析失败")
        metrics = read_metrics(tdir)
        dur, timing_src = episode_duration(tdir, metrics)
        screen = screen_quality(tdir)
        n_actions = len(traj.get("history_action") or [])
        pos = pos_of.get(tid, i)
        rows.append({
            "run_id": run_id,
            "agent": agent,
            "condition": condition,
            "order_mode": order_mode,
            "order_seed": order_seed,
            "repeat": repeat,
            "position": pos,
            "predecessor": order[pos - 1] if (order and pos > 0) else None,
            "task": tid,
            "goal": traj.get("task_goal", ""),
            "success": 1.0 if results.get(tid, bool(traj.get("success", False))) else 0.0,
            # 框架把"agent 抛异常/未产出轨迹"也算失败，但我们可以从缺失 trajectory 看出来
            "exception": not os.path.exists(traj_fp),
            "episode_length": n_actions,
            "run_time_s": dur,
            "ts": now_iso,
            **metrics,
            **screen,
            "timing_source": timing_src,
        })

    out = args.out or os.path.join(run_dir, "episodes.jsonl")
    with open(out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    ok = sum(int(r["success"]) for r in rows)
    lat = sum(r["api_latency_s"] for r in rows)
    tok = sum(r["prompt_tokens"] + r["completion_tokens"] for r in rows)
    err = sum(r["api_errors"] for r in rows)
    blank = [r["task"] for r in rows if r.get("screen_blank")]
    print(f"\n写出 {len(rows)} 个 episode -> {out}")
    print(f"  agent={agent}  condition={condition}  order_mode={order_mode}(seed={order_seed})")
    print(f"  成功 {ok}/{len(rows)} = {ok/len(rows)*100:.1f}%" if rows else "  (无数据)")
    print(f"  累计 API 延迟 {lat:.0f}s，token {tok}，接口错误 {err}")
    if blank:
        print(f"  ⚠️  检测到疑似黑屏/锁屏的 episode: {blank} —— 这类失败与顺序污染无关，分析时应剔除")
    print(f"  每任务平均: {sum(r['run_time_s'] for r in rows)/len(rows):.0f}s，"
          f"{sum(r['episode_length'] for r in rows)/len(rows):.1f} 步" if rows else "")
    for r in rows:
        print(f"    {r['position']:3d}. {r['task']:14s} success={bool(r['success'])!s:5s} "
              f"steps={r['episode_length']:2d} {r['run_time_s']:6.0f}s "
              f"api={r['api_latency_s']:6.1f}s tok={r['prompt_tokens']+r['completion_tokens']:6d} "
              f"亮度={r.get('last_step_brightness')} pred={r['predecessor'] or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest.py —— 一条命令跑完所有不依赖模拟器的验证。

    python selftest.py

覆盖：
  A. 顺序构造的不变式（5 种模式 × 5 个 seed 都必须是原任务集的排列）
  B. 对抗序确实构造出 writer→reader 紧邻；且不丢任务（已知 bug 回归测试）
  C. 计划算术（episodes = runs × 任务数）
  D. 统计函数正确性（Fisher 已知值、BH 单调性、bootstrap CI 覆盖真值）
  E. 端到端分析管道（合成数据 → 分析 → 与 ground truth 对比，precision ≥ 0.9）
  F. 样本量计算单调性（ΔSR 越大所需样本越少）

全部通过则退出码 0，任一失败退出码 1。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------------------
# 让本脚本在中文 Windows 的默认 cmd（控制台代码页 GBK/cp936）里也能正常输出。
#
# ⚠️ 实测踩过：不加这段，`%PY% %S%\selftest.py` 在**新开的 cmd 窗口**里会直接崩：
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
sys.path.insert(0, HERE)

import analyze_order_effects as ana  # noqa: E402
import order_runner as o  # noqa: E402
import power_analysis as pw  # noqa: E402
import task_catalog as tc  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def main() -> int:
    tasks = [t.name for t in tc.CATALOG]

    # ---- A. 顺序不变式 -------------------------------------------------
    ok = True
    for mode in o.ORDER_MODES:
        for seed in range(5):
            try:
                s = o.build_order(mode, tasks, seed)
                if sorted(s) != sorted(tasks):
                    ok = False
            except Exception:  # noqa: BLE001
                ok = False
    check("A. 所有顺序模式 × seed 都保持任务集合完整", ok, f"{len(o.ORDER_MODES)} 模式 × 5 seed × {len(tasks)} 任务")

    # ---- B. 对抗序确实制造 writer→reader 紧邻 ---------------------------------
    adv = o.order_adversarial(tasks, 0)
    pairs = [
        (adv[i - 1], adv[i])
        for i in range(1, len(adv))
        if tc.BY_NAME[adv[i]].is_reader
        and tc.BY_NAME[adv[i - 1]].is_writer
        and tc.BY_NAME[adv[i]].cluster == tc.BY_NAME[adv[i - 1]].cluster
    ]
    check("B1. 对抗序构造出同簇 writer→reader 紧邻", len(pairs) >= 3, f"{len(pairs)} 对")

    pilot = ["SimpleCalendarAnyEventsOnDate", "SimpleCalendarNextEvent",
             "SimpleCalendarAddOneEventTomorrow", "MarkorCreateNote",
             "MarkorDeleteNewestNote", "SystemCopyToClipboard"]
    padv = o.order_adversarial(pilot, 0)
    check("B2. reader 多于 writer 时不丢任务（bug 回归）",
          sorted(padv) == sorted(pilot), f"{len(padv)} vs {len(pilot)}")

    # ---- C. 计划算术 ---------------------------------------------------
    plan = o.build_plan(pilot, ["t3a_gpt4"], ["canonical", "adversarial"],
                        ["official", "none"], 10, [0, 1])
    # canonical 1 seed + adversarial 2 seeds = 3 顺序 × 2 重置 × 10 重复 = 60 runs
    episodes = sum(len(p.tasks) for p in plan)
    check("C. 计划算术正确", len(plan) == 60 and episodes == 60 * len(pilot),
          f"runs={len(plan)}, episodes={episodes}")

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

    # ---- E. 端到端管道 --------------------------------------------------
    tmp = tempfile.mkdtemp(prefix="odflaky_selftest_")
    # 子进程用 UTF-8 输出（否则中文 Windows 上它们按 GBK 打印，
    # 父进程按 utf-8 解码会在 reader 线程里抛 UnicodeDecodeError、拿不到输出）。
    child_env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    try:
        r1 = subprocess.run([sys.executable, os.path.join(HERE, "make_sim_data.py"),
                             "--out", tmp, "--repeats", "12"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=child_env)
        r2 = subprocess.run([sys.executable, os.path.join(HERE, "analyze_order_effects.py"),
                             "--input", os.path.join(tmp, "episodes.jsonl"),
                             "--out", os.path.join(tmp, "analysis"),
                             "--check-against", os.path.join(tmp, "ground_truth.json")],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=child_env)
        check("E1. 合成数据 + 分析命令成功退出", r1.returncode == 0 and r2.returncode == 0,
              (r1.stderr or r2.stderr or "")[-200:])

        rows = ana.load_episodes([os.path.join(tmp, "episodes.jsonl")])
        report = ana.analyze(rows)
        truth = ana.check_against_ground_truth(report, os.path.join(tmp, "ground_truth.json"))
        prec = truth["overall"]["precision"]
        rec = truth["overall"]["recall"]
        # ground truth 的判据是"被污染暴露 >= min_events 次"（机制层面），
        # 检出判据是"|ΔSR| >= δ 且 q < α"（观测层面），两者边界不重合，
        # 因此允许极少数"暴露次数略少但观测上仍显著"的任务被判为 FP。
        check("E2. victim 检出 precision ≥ 0.9（几乎无假阳性）", (prec or 0) >= 0.9, f"precision={prec}")
        check("E3. victim 检出 recall ≥ 0.5", (rec or 0) >= 0.5, f"recall={rec}")

        c2 = [g for k, g in report["contrasts"].items() if k.endswith("C2_order_main")]
        check("E4. H2 形态：官方重置下顺序主效应 ≈ 0",
              all(abs(g["delta_sr"]) < 0.05 for g in c2),
              f"ΔSR={[round(g['delta_sr'], 3) for g in c2]}")

        adv_poll = [g for k, g in report["order_contrasts"].items() if k.endswith("polluted_order:adversarial")]
        check("E5. H1 形态：污染 + 对抗序造成显著下降",
              all(g["delta_sr"] < -0.15 for g in adv_poll),
              f"ΔSR={[round(g['delta_sr'], 3) for g in adv_poll]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- G. 仓库自身的坑（回归守卫）------------------------------------
    # G1: PowerShell 5.1 会用本地代码页（中文 Windows = GBK）读**无 BOM** 的 .ps1，
    #     含中文的脚本会被读成乱码，轻则输出乱码、重则解析失败。
    #     .cmd/.bat 反过来必须纯 ASCII（同样是本地代码页）。
    root = os.path.abspath(os.path.join(HERE, "..", ".."))
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

    # ---- F. 样本量 -----------------------------------------------------
    ns = [pw.n_two_proportion(0.6, 0.6 - d) for d in (0.1, 0.2, 0.3, 0.45)]
    check("F. 样本量随 ΔSR 增大而单调下降", all(ns[i] > ns[i + 1] for i in range(len(ns) - 1)), f"n={ns}")

    print()
    if FAILED:
        print(f"❌ {len(FAILED)} 项失败: {FAILED}")
        return 1
    print("✅ 全部通过（不依赖模拟器 / API key）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

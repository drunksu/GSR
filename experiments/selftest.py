#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest.py —— 一条命令跑完所有不依赖模拟器 / API key 的验证。

    python experiments\selftest.py

覆盖：
  D. 统计函数正确性（Fisher 已知值、BH 单调性、bootstrap CI 覆盖真值）
     —— motivation_study 的 analyze_order_effects.py 是全部实验报告的口径，
        这些函数错了，所有 ΔSR / CI / victim 结论都不可信。
  G. 仓库自身的坑（回归守卫）：含中文的 .ps1 必须带 UTF-8 BOM；
     .cmd/.bat 必须是纯 ASCII。

（顺序构造 / 对抗序 / 样本量 / 合成数据端到端管道的 A/B/C/E/F 检查属于
AndroidWorld 支线，随其脚本一起移到了 backup/androidworld/。）

全部通过则退出码 0，任一失败退出码 1。
"""

from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# 让本脚本在中文 Windows 的默认 cmd（控制台代码页 GBK/cp936）里也能正常输出。
#
# ⚠️ 实测踩过：不加这段，`%PY% experiments\selftest.py` 在**新开的 cmd 窗口**里会直接崩：
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
sys.path.insert(0, os.path.join(HERE, "motivation_study", "scripts"))

import analyze_order_effects as ana  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILED.append(name)


def main() -> int:
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

    # ---- G. 仓库自身的坑（回归守卫）------------------------------------
    # G1: PowerShell 5.1 会用本地代码页（中文 Windows = GBK）读**无 BOM** 的 .ps1，
    #     含中文的脚本会被读成乱码，轻则输出乱码、重则解析失败。
    #     .cmd/.bat 反过来必须纯 ASCII（同样是本地代码页）。
    root = os.path.abspath(os.path.join(HERE, ".."))
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

    print()
    if FAILED:
        print(f"❌ {len(FAILED)} 项失败: {FAILED}")
        return 1
    print("✅ 全部通过（不依赖模拟器 / API key）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

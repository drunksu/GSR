#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""power_analysis.py —— 给"顺序 vs 乱序"实验算样本量。

两个模型：

1. **非配对（two-proportion）**：把"规范序的一批 episode"和"乱序的一批 episode"
   当成两组独立样本（最保守，几乎不依赖配对假设）。
       n_per_group = ( z_{1-α/2}·√(2·p̄·(1-p̄)) + z_{1-β}·√(p1(1-p1)+p2(1-p2)) )² / Δ²

2. **配对（McNemar）**：同一个任务反复跑，同一 repeat 下标下比较"规范序成功/失败"
   与"乱序成功/失败"。设 discordant 比例 π_d，其中 p_fail→success = q，
   则所需 discordant 对数 n_d ≈ ( z_{1-α/2}√π_d + z_{1-β}√(π_d - Δ²) )² / Δ²（近似）。

用途：论证"每个 cell 要跑多少遍"。AndroidWorld 一个 episode 约 1–3 分钟，
所以这个数字直接决定实验预算。

用法：
    python power_analysis.py --p 0.6 --deltas 0.1,0.15,0.2,0.3,0.4
"""

from __future__ import annotations

import argparse
from statistics import NormalDist

Z = NormalDist()


def n_two_proportion(p1: float, p2: float, alpha: float = 0.05, power: float = 0.8) -> int:
    za = Z.inv_cdf(1 - alpha / 2)
    zb = Z.inv_cdf(power)
    pbar = (p1 + p2) / 2
    num = (za * (2 * pbar * (1 - pbar)) ** 0.5 + zb * (p1 * (1 - p1) + p2 * (1 - p2)) ** 0.5) ** 2
    delta = abs(p1 - p2)
    return int(-(-num / delta**2 // 1)) if delta else 10**9


def n_mcnemar(p1: float, p2: float, pi_d: float = 0.4, alpha: float = 0.05, power: float = 0.8) -> int:
    """近似：n = ( z_a·√π_d + z_b·√(π_d − Δ²) )² / Δ²，返回所需**配对对数**。"""
    za = Z.inv_cdf(1 - alpha / 2)
    zb = Z.inv_cdf(power)
    delta = abs(p1 - p2)
    if delta == 0:
        return 10**9
    inner = pi_d - delta**2
    if inner <= 0:
        inner = 1e-6
    return int(-(-((za * pi_d**0.5 + zb * inner**0.5) ** 2 / delta**2) // 1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--p", type=float, default=0.6, help="干净条件下的基线成功率")
    ap.add_argument("--deltas", default="0.05,0.1,0.15,0.2,0.3,0.4")
    ap.add_argument("--pi-d", type=float, default=0.4, help="McNemar 的 discordant 比例")
    ap.add_argument("--power", type=float, default=0.8)
    args = ap.parse_args()

    print(f"基线成功率 p={args.p}，alpha=0.05，power={args.power}")
    print()
    print("| 目标 ΔSR | 每组 episode 数（非配对） | 配对数（McNemar, π_d=%.2f） | 单任务 4 条件下总 episode |" % args.pi_d)
    print("|---|---|---|---|")
    for d in [float(x) for x in args.deltas.split(",")]:
        n1 = n_two_proportion(args.p, args.p - d, power=args.power)
        n2 = n_mcnemar(args.p, args.p - d, args.pi_d, power=args.power)
        # 4 条件（2 顺序 × 2 重置）下把 n1 摊到 4 个 cell
        print(f"| {d:.2f} | {n1} | {n2} | {n1 * 4} |")
    print()
    print("解读：AndroidWorld 单 episode 约 1–3 分钟（视任务与模型而定）。")
    print("若目标是检出 ΔSR=0.20（p=0.6→0.40），非配对每组约需上表第一列对应行；")
    print('论文里的「30 次重复」应理解为**每条件每任务**的重复次数。')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analyze_order_effects.py —— 从 episodes.jsonl 量化「顺序 × 状态重置」的效应。

输入：order_runner.py 产出的 JSONL，每行一个 episode：
    run_id, agent, condition, order_mode, order_seed, repeat, position,
    predecessor, task, success, exception, episode_length, run_time_s

核心设计：**2×2 析因分解**。把实验条件拆成两个因子——
    因子 O（顺序）  : 规范序 canonical  vs  乱序（shuffle/adversarial/reverse）
    因子 R（重置）  : 官方重置 official vs  削弱重置（none/no_reset/no_teardown）
并在同一 agent 内计算三个对比 + 一个交互项：

    C1 污染主效应  = E[SR | R=弱, O=规范] − E[SR | R=官方, O=规范]
    C2 顺序主效应  = E[SR | R=官方, O=乱序] − E[SR | R=官方, O=规范]
    C3 叠加效应    = E[SR | R=弱,   O=乱序] − E[SR | R=官方, O=规范]
    DiD 交互项     = C3 − C1 − C2      （顺序效应是否**只在**污染条件下被放大）

这样能直接回答你要的两个问题：
* "OD flaky 是否影响成功率？"        → C2 / C3 的 ΔSR 与 OD-flaky 率
* "某个任务因为执行顺序变化而失败"  → victim 名单 + polluter 归因
* "多个 Agent"                      → 每个 agent 一组，并给出跨 agent 的一致性

指标定义（可直接写进论文 Methods）
----------------------------------
* SR(t, o, r)  任务 t 在顺序 o、重置 r 下的成功率。
* ΔSR(t)       处理组与参照组的成功率差（配对到任务）。
* OD-flaky 率  被判为 victim 的任务占比：|ΔSR| ≥ δ 且 BH-FDR 校正后 q < α。
* CTCI         跨任务污染指数 = E_t[ max_o SR(t) − min_o SR(t) ]（顺序不确定性的全幅）。
* PASR         污染感知成功率 = E_t[ min_o SR(t) ]（最坏顺序下的可信下界）。
* polluter lift = P(fail | 紧邻前序任务 = P) / P(fail)，用于给污染源排序。

统计实现：纯标准库（Fisher 精确检验双边 p + Benjamini–Hochberg FDR +
对**任务**做配对 bootstrap 的 95% CI），不依赖 scipy / pandas。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
from collections import defaultdict
from typing import Any, Callable, Sequence

OFFICIAL = "official"
CANONICAL = "canonical"


# ==========================================================================
# 统计工具（纯标准库）
# ==========================================================================
def _log_comb(n: int, k: int) -> float:
    """log(C(n,k))，用 lgamma 计算，避免大整数组合数带来的性能灾难。"""
    if k < 0 or k > n:
        return float("-inf")
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def _hypergeom_pmf(a: int, b: int, c: int, d: int) -> float:
    """超几何概率（对数域计算，返回浮点）。"""
    n = a + b + c + d
    return math.exp(_log_comb(a + b, a) + _log_comb(c + d, c) - _log_comb(n, a + c))


def fisher_exact_2x2(a: int, b: int, c: int, d: int) -> float:
    """双边 Fisher 精确检验，表 [[a, b], [c, d]] = [[成功,失败]_处理, [成功,失败]_参照]。"""
    if min(a, b, c, d) < 0 or (a + b) == 0 or (c + d) == 0:
        return float("nan")
    obs = _hypergeom_pmf(a, b, c, d)
    total = 0.0
    r1, r2 = a + b, c + d
    c1 = a + c
    for x in range(0, min(r1, c1) + 1):
        y, z = r1 - x, c1 - x
        w = r2 - z
        if y < 0 or z < 0 or w < 0:
            continue
        p = _hypergeom_pmf(x, y, z, w)
        if p <= obs + 1e-12:
            total += p
    return min(1.0, total)


def benjamini_hochberg(pvals: Sequence[float]) -> list[float]:
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    prev = 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        prev = min(prev, pvals[i] * m / (rank + 1))
        q[i] = min(1.0, prev)
    return q


def mean(xs: Sequence[float]) -> float:
    vals = [x for x in xs if not math.isnan(x)]
    return sum(vals) / len(vals) if vals else float("nan")


def bootstrap_ci(values: Sequence[float], n_boot: int = 2000, alpha: float = 0.05, seed: int = 0):
    vals = [v for v in values if not math.isnan(v)]
    if not vals:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(vals)
    # random.choices 比 randrange 逐次采样快一个数量级
    stats = sorted(sum(rng.choices(vals, k=n)) / n for _ in range(n_boot))
    return (stats[int(alpha / 2 * n_boot)], stats[int((1 - alpha / 2) * n_boot) - 1])


def _sr(rows: Sequence[dict[str, Any]], filt: Callable[[dict[str, Any]], bool]) -> tuple[float, int]:
    sub = [r for r in rows if filt(r)]
    if not sub:
        return (float("nan"), 0)
    return (sum(float(r.get("success") or 0.0) for r in sub) / len(sub), len(sub))


# ==========================================================================
# 载入
# ==========================================================================
def load_episodes(paths: Sequence[str]) -> list[dict[str, Any]]:
    files: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                files += [os.path.join(root, n) for n in names if n.endswith(".jsonl")]
        else:
            files.append(p)
    rows: list[dict[str, Any]] = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    print(f"[warn] 跳过无法解析的行 ({f})", file=sys.stderr)
    return rows


# ==========================================================================
# 逐任务对比
# ==========================================================================
def per_task_compare(
    rows: Sequence[dict[str, Any]],
    ref_filter: Callable[[dict[str, Any]], bool],
    treat_filter: Callable[[dict[str, Any]], bool],
) -> list[dict[str, Any]]:
    # 先按任务分桶（一次 O(rows)），避免"每个任务都遍历全部行"的 O(rows×tasks)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        buckets[r["task"]].append(r)

    out = []
    pvals = []
    for t in sorted(buckets):
        rs = buckets[t]
        ref = [r for r in rs if ref_filter(r)]
        tr = [r for r in rs if treat_filter(r)]
        if not ref or not tr:
            continue
        s_ref = sum(float(r.get("success") or 0.0) for r in ref)
        s_tr = sum(float(r.get("success") or 0.0) for r in tr)
        n_ref, n_tr = len(ref), len(tr)
        sr_ref, sr_tr = s_ref / n_ref, s_tr / n_tr
        # Fisher 精确检验需要二元结果：复合任务可能返回 0~1 的分数，
        # 这里以 0.5 为阈值二值化（均值仍用原始分数，不丢信息）。
        b_ref = sum(1 for r in ref if float(r.get("success") or 0.0) > 0.5)
        b_tr = sum(1 for r in tr if float(r.get("success") or 0.0) > 0.5)
        # 按任务内的顺序模式明细，用于 CTCI/PASR。
        # ⚠️ 必须用该任务的**全部 episode**（不只是处理组）：否则同格内只剩一种
        # 顺序模式，CTCI 会算成 nan、PASR 也退化成处理组的最小值，两者都失真。
        by_order: dict[str, list[float]] = defaultdict(list)
        for r in rs:
            by_order[r["order_mode"]].append(float(r.get("success") or 0.0))
        order_sr = {o: sum(v) / len(v) for o, v in by_order.items()}
        p = fisher_exact_2x2(b_tr, n_tr - b_tr, b_ref, n_ref - b_ref)
        pvals.append(p if not math.isnan(p) else 1.0)
        out.append(
            {
                "task": t,
                "sr_ref": sr_ref,
                "sr_treat": sr_tr,
                "delta_sr": sr_tr - sr_ref,
                "n_ref": n_ref,
                "n_treat": n_tr,
                "p_value": p,
                "per_order_sr": order_sr,
            }
        )
    qs = benjamini_hochberg(pvals)
    for rec, q in zip(out, qs):
        rec["q_value"] = q
    return out


def summarize_compare(
    records: Sequence[dict[str, Any]], delta: float, alpha: float, seed: int = 0
) -> dict[str, Any]:
    for r in records:
        r["victim"] = abs(r["delta_sr"]) >= delta and r["q_value"] < alpha
        r["victim_direction"] = (
            "degraded" if r["victim"] and r["delta_sr"] < 0 else "improved" if r["victim"] else "stable"
        )
    deltas = [r["delta_sr"] for r in records]
    lo, hi = bootstrap_ci(deltas, seed=seed)
    ranges, worst = [], []
    for r in records:
        vals = list(r["per_order_sr"].values())
        if len(vals) >= 2:
            ranges.append(max(vals) - min(vals))
        if vals:
            worst.append(min(vals))
    victims = [r for r in records if r["victim"]]
    return {
        "n_tasks": len(records),
        "suite_sr_ref": mean([r["sr_ref"] for r in records]),
        "suite_sr_treat": mean([r["sr_treat"] for r in records]),
        "delta_sr": mean(deltas),
        "delta_sr_ci95": [lo, hi],
        "ctci": mean(ranges),
        "pasr": mean(worst),
        "od_flaky_rate": len(victims) / len(records) if records else float("nan"),
        "victims": sorted(v["task"] for v in victims),
        "victims_direction": {v["task"]: v["victim_direction"] for v in victims},
    }# ==========================================================================
# 主分析：2×2 析因
# ==========================================================================
def analyze(
    rows: Sequence[dict[str, Any]],
    baseline_order: str = CANONICAL,
    official_condition: str = OFFICIAL,
    delta: float = 0.2,
    alpha: float = 0.05,
) -> dict[str, Any]:
    agents = sorted({r["agent"] for r in rows})
    conditions = sorted({r.get("condition", "?") for r in rows})
    order_modes = sorted({r["order_mode"] for r in rows})
    weak = [c for c in conditions if c != official_condition]
    off = [(o) for o in order_modes if o != baseline_order]

    report: dict[str, Any] = {
        "baseline_order": baseline_order,
        "official_condition": official_condition,
        "delta": delta,
        "alpha": alpha,
        "conditions": conditions,
        "order_modes": order_modes,
        "contrasts": {},
        "order_contrasts": {},
        "od_flaky_tasks": {},
        "groups": {},
        "warnings": [],
    }
    if not weak:
        report["warnings"].append("只有 official 条件，无法估计污染主效应（C1/C3）。")
    if not off:
        report["warnings"].append("只有规范顺序，无法估计顺序主效应（C2/C3）。")

    is_off = lambda r: r.get("condition", "?") == official_condition  # noqa: E731
    ref_f = lambda r: is_off(r) and r["order_mode"] == baseline_order  # noqa: E731

    for agent in agents:
        ar = [r for r in rows if r["agent"] == agent]
        contrasts: dict[str, str] = {
            "C1_pollution_main": f"R=弱/规范序({','.join(weak)}) vs R=官方/规范序",
            "C2_order_main": f"R=官方/乱序({','.join(off)}) vs R=官方/规范序",
            "C3_combined": f"R=弱/乱序 vs R=官方/规范序",
        }
        defs: dict[str, Callable[[dict[str, Any]], bool]] = {
            "C1_pollution_main": lambda r: r.get("condition") in weak and r["order_mode"] == baseline_order,
            "C2_order_main": lambda r: r.get("condition") == official_condition and r["order_mode"] != baseline_order,
            "C3_combined": lambda r: r.get("condition") in weak and r["order_mode"] != baseline_order,
        }
        for name, treat_f in defs.items():
            recs = per_task_compare(ar, ref_f, treat_f)
            if not recs:
                continue
            summary = summarize_compare(recs, delta, alpha)
            summary["definition"] = contrasts[name]
            summary["_recs"] = recs
            report["contrasts"][f"{agent}|{name}"] = summary

        # 逐顺序模式对比：参照恒定 = 官方重置 + 规范顺序（"干净基线"）。
        # 这样"某个任务因为执行顺序变化而失败"就能按顺序模式分别归因，
        # 也避免了把 shuffle 与 adversarial 混在一起被稀释。
        for mode in off:
            recs_off = per_task_compare(
                ar,
                ref_f,
                lambda r, m=mode: r.get("condition") == official_condition and r["order_mode"] == m,
            )
            if recs_off:
                s = summarize_compare(recs_off, delta, alpha)
                s["definition"] = f"R=官方/顺序={mode} vs R=官方/规范序（纯顺序效应）"
                s["_recs"] = recs_off
                report["order_contrasts"][f"{agent}|order:{mode}"] = s

            recs_comb = per_task_compare(
                ar,
                ref_f,
                lambda r, m=mode: r.get("condition") in weak and r["order_mode"] == m,
            )
            if recs_comb:
                s = summarize_compare(recs_comb, delta, alpha)
                s["definition"] = f"R=弱/顺序={mode} vs R=官方/规范序（污染+顺序叠加）"
                s["_recs"] = recs_comb
                report["order_contrasts"][f"{agent}|polluted_order:{mode}"] = s

        # OD-flaky 任务集合 = 在任一顺序对比下被判为 victim 的任务（与顺序模式无关的并集）
        flaky: set[str] = set()
        for key, s in report["order_contrasts"].items():
            if key.startswith(f"{agent}|"):
                flaky |= set(s["victims"])
        report["od_flaky_tasks"][agent] = sorted(flaky)

        # DiD 交互项：C3 − C1 − C2（逐任务）
        c1 = {r["task"]: r["delta_sr"] for r in report["contrasts"].get(f"{agent}|C1_pollution_main", {}).get("_recs", [])}
        c2 = {r["task"]: r["delta_sr"] for r in report["contrasts"].get(f"{agent}|C2_order_main", {}).get("_recs", [])}
        c3 = {r["task"]: r["delta_sr"] for r in report["contrasts"].get(f"{agent}|C3_combined", {}).get("_recs", [])}
        did = {t: c3[t] - c1.get(t, 0.0) - c2.get(t, 0.0) for t in c3}
        if did:
            lo, hi = bootstrap_ci(list(did.values()), seed=1)
            report["contrasts"][f"{agent}|DiD_interaction"] = {
                "definition": "C3 − C1 − C2（顺序效应是否只在重置被削弱时被放大）",
                "n_tasks": len(did),
                "delta_sr": mean(list(did.values())),
                "delta_sr_ci95": [lo, hi],
                "per_task_did": did,
            }

        # 分组明细：agent × condition 内的"规范序 vs 乱序"
        for cond in conditions:
            cr = [r for r in ar if r.get("condition") == cond]
            recs = per_task_compare(
                cr,
                lambda r: r["order_mode"] == baseline_order,
                lambda r: r["order_mode"] != baseline_order,
            )
            if not recs:
                continue
            s = summarize_compare(recs, delta, alpha)
            s["agent"] = agent
            s["condition"] = cond
            # 逐顺序模式成功率：**只统计两侧都可比的公共任务**。
            # 否则样本不对称时会误导（实例：规范序跑了 310 个、乱序只跑了 25 个，
            # 直接平均会显示 0.57 vs 0.46 的假差异，而公共任务是 0.462 vs 0.462）。
            comparable = {r["task"] for r in recs}
            cr_cmp = [r for r in cr if r["task"] in comparable]
            orders = sorted({r["order_mode"] for r in cr_cmp})
            s["suite_sr_by_order"] = {
                o: _sr(cr_cmp, lambda r, oo=o: r["order_mode"] == oo)[0] for o in orders
            }
            s["n_by_order"] = {
                o: _sr(cr_cmp, lambda r, oo=o: r["order_mode"] == oo)[1] for o in orders
            }
            s["n_comparable_tasks"] = len(comparable)
            s["_recs"] = recs
            report["groups"][f"{agent}|{cond}"] = s

    report["polluters"] = polluter_lift(rows)
    return report


def polluter_lift(rows: Sequence[dict[str, Any]], min_support: int = 3) -> list[dict[str, Any]]:
    """P(fail | 前序任务 = P) / P(fail)：污染源排序 + Fisher 检验。"""
    out: list[dict[str, Any]] = []
    by_group: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("position", 0) > 0 and r.get("predecessor"):
            by_group[(r["agent"], r.get("condition", "?"))].append(r)

    for (agent, cond), rs in sorted(by_group.items()):
        base_fail = sum(1 for r in rs if not float(r.get("success") or 0.0))
        base_rate = base_fail / len(rs)
        for p in sorted({r["predecessor"] for r in rs}):
            sub = [r for r in rs if r["predecessor"] == p]
            if len(sub) < min_support:
                continue
            fail = sum(1 for r in sub if not float(r.get("success") or 0.0))
            other_fail, other_tot = base_fail - fail, len(rs) - len(sub)
            rate = fail / len(sub)
            out.append(
                {
                    "agent": agent,
                    "condition": cond,
                    "polluter": p,
                    "n": len(sub),
                    "fail_rate": rate,
                    "baseline_fail_rate": base_rate,
                    "lift": (rate / base_rate) if base_rate else float("inf"),
                    "p_value": fisher_exact_2x2(fail, len(sub) - fail, other_fail, other_tot - other_fail),
                }
            )
    for agent, cond in {(r["agent"], r["condition"]) for r in out}:
        idx = [i for i, r in enumerate(out) if r["agent"] == agent and r["condition"] == cond]
        for i, q in zip(idx, benjamini_hochberg([out[i]["p_value"] for i in idx])):
            out[i]["q_value"] = q
    out.sort(key=lambda r: (-(r["lift"] if r["lift"] != float("inf") else 1e9), r["polluter"]))
    return out


# ==========================================================================
# 与合成数据 ground truth 自检
# ==========================================================================
def check_against_ground_truth(report: dict[str, Any], gt_path: str) -> dict[str, Any]:
    with open(gt_path, encoding="utf-8") as fh:
        gt = json.load(fh)
    gt_victims = set(gt.get("victims", []))
    gt_polluters = set(gt.get("polluters", []))

    all_detected: set[str] = set()
    per_agent: dict[str, dict[str, Any]] = {}
    for bucket in ("contrasts", "order_contrasts"):
        for key, g in report[bucket].items():
            if key.endswith("DiD_interaction"):
                continue
            agent = key.split("|")[0]
            det = set(g.get("victims", []))
            all_detected |= det
            per_agent.setdefault(agent, {"detected": set()})["detected"] |= det

    def pr(det: set[str]) -> dict[str, Any]:
        tp, fp, fn = len(det & gt_victims), len(det - gt_victims), len(gt_victims - det)
        return {
            "detected": sorted(det),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": tp / (tp + fp) if (tp + fp) else None,
            "recall": tp / (tp + fn) if (tp + fn) else None,
        }

    topk = [p["polluter"] for p in report["polluters"][: len(gt_polluters)]] if gt_polluters else []
    return {
        "gt_n_victims": len(gt_victims),
        "gt_victims": sorted(gt_victims),
        "overall": pr(all_detected),
        "per_agent": {a: pr(v["detected"]) for a, v in sorted(per_agent.items())},
        "polluter_topk": topk,
        "polluter_topk_overlap": sorted(set(topk) & gt_polluters),
        "polluter_topk_precision": (len(set(topk) & gt_polluters) / len(topk)) if topk else None,
    }


# ==========================================================================
# 报告
# ==========================================================================
def _fmt(x: Any) -> str:
    """报告用的数值格式化：None / NaN 渲染为 '—'（例如单顺序模式下 CTCI 无定义）。"""
    if x is None:
        return "—"
    if isinstance(x, float) and math.isnan(x):
        return "—"
    return f"{x:.3f}"


def _sanitize(obj: Any) -> Any:
    """递归把 NaN/Inf 换成 None，保证 analysis.json 是严格合法 JSON。"""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def write_report(report: dict[str, Any], out_dir: str, truth: dict[str, Any] | None) -> str:
    os.makedirs(out_dir, exist_ok=True)
    md: list[str] = ["# 顺序效应（OD flaky）分析报告", ""]
    md.append(f"- 规范顺序: `{report['baseline_order']}`；官方重置条件: `{report['official_condition']}`")
    md.append(f"- victim 判定: |ΔSR| ≥ {report['delta']} 且 BH-FDR q < {report['alpha']}")
    md.append(f"- 条件: {report['conditions']}；顺序模式: {report['order_modes']}")
    for w in report["warnings"]:
        md.append(f"- ⚠️ {w}")
    md.append("")

    md.append("## 1. 主结果：2×2 析因（顺序 × 重置）")
    md.append("")
    md.append("| agent | 对比 | 定义 | SR(参照) | SR(处理) | ΔSR | ΔSR 95%CI | OD-flaky 率 |")
    md.append("|---|---|---|---|---|---|---|---|")
    for key, g in report["contrasts"].items():
        agent, name = key.split("|", 1)
        if name == "DiD_interaction":
            md.append(
                f"| {agent} | DiD 交互 | {g['definition']} | — | — | {g['delta_sr']:+.3f} | "
                f"[{g['delta_sr_ci95'][0]:+.3f}, {g['delta_sr_ci95'][1]:+.3f}] | — |"
            )
            continue
        md.append(
            f"| {agent} | {name} | {g['definition']} | {g['suite_sr_ref']:.3f} | {g['suite_sr_treat']:.3f} | "
            f"{g['delta_sr']:+.3f} | [{g['delta_sr_ci95'][0]:+.3f}, {g['delta_sr_ci95'][1]:+.3f}] | "
            f"{g['od_flaky_rate']:.1%} |"
        )
    md.append("")

    md.append("## 2. 分组明细：同一重置条件下「规范序 vs 乱序」")
    md.append("")
    md.append("| agent | condition | 各顺序 SR（仅公共任务） | 公共任务数 | SR(规范) | SR(乱序) | ΔSR | ΔSR 95%CI | CTCI | PASR | OD-flaky 率 | victims |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for key, g in report["groups"].items():
        n_by = g.get("n_by_order", {})
        by_order = ", ".join(
            f"{o}={v:.2f}(n={n_by.get(o, '?')})" for o, v in g.get("suite_sr_by_order", {}).items())
        md.append(
            f"| {g['agent']} | {g['condition']} | {by_order} | {g.get('n_comparable_tasks', '?')} | "
            f"{g['suite_sr_ref']:.3f} | {g['suite_sr_treat']:.3f} | "
            f"{g['delta_sr']:+.3f} | [{g['delta_sr_ci95'][0]:+.3f}, {g['delta_sr_ci95'][1]:+.3f}] | "
            f"{g['ctci']:.3f} | {g['pasr']:.3f} | {g['od_flaky_rate']:.1%} | {len(g['victims'])} |"
        )
    md.append("")
    md.append("> 若各顺序的 `n` 与「公共任务数」不一致，说明两侧样本不对称（例如某一轮没跑完）。"
              "ΔSR/CTCI/PASR 只在**两侧都跑过的公共任务**上计算，但 polluter 一节用的是全部 episode，"
              "样本不对称时该节仅供参考。")
    md.append("")

    md.append("## 2b. 逐顺序模式对比（参照 = 官方重置 + 规范顺序）")
    md.append("")
    md.append("| agent | 对比 | SR(参照) | SR(处理) | ΔSR | ΔSR 95%CI | CTCI | PASR | OD-flaky 率 | victims |")
    md.append("|---|---|---|---|---|---|---|---|---|---|")
    for key, g in report["order_contrasts"].items():
        agent, name = key.split("|", 1)
        md.append(
            f"| {agent} | {name} | {g['suite_sr_ref']:.3f} | {g['suite_sr_treat']:.3f} | {g['delta_sr']:+.3f} | "
            f"[{g['delta_sr_ci95'][0]:+.3f}, {g['delta_sr_ci95'][1]:+.3f}] | {_fmt(g['ctci'])} | "
            f"{_fmt(g['pasr'])} | {g['od_flaky_rate']:.1%} | {len(g['victims'])} |"
        )
    md.append("")
    md.append("> CTCI / PASR 需要同一格内存在 ≥2 种顺序才有定义；单顺序模式的对比里显示为「—」。"
              "（见 §2 的分组明细表，那里才是 CTCI/PASR 的正式取值处。）")
    md.append("")
    md.append("### 每个 agent 的 OD-flaky 任务集合（任一顺序模式下的并集）")
    md.append("")
    for agent, tasks in report["od_flaky_tasks"].items():
        md.append(f"- **{agent}** ({len(tasks)}): {', '.join(tasks) if tasks else '（无）'}")
    md.append("")

    md.append("## 3. Victim 任务（顺序一变就掉）")
    md.append("")
    md.append("| agent | 对比 | task | SR(参照) | SR(处理) | ΔSR | p | q | 方向 |")
    md.append("|---|---|---|---|---|---|---|---|---|")
    for bucket in ("contrasts", "order_contrasts"):
        for key, g in report[bucket].items():
            agent, name = key.split("|", 1)
            if name == "DiD_interaction":
                continue
            for r in sorted(g.get("_recs", []), key=lambda x: x["delta_sr"]):
                if not r.get("victim"):
                    continue
                md.append(
                    f"| {agent} | {name} | {r['task']} | {r['sr_ref']:.3f} | {r['sr_treat']:.3f} | "
                    f"{r['delta_sr']:+.3f} | {r['p_value']:.4f} | {r['q_value']:.4f} | {r['victim_direction']} |"
                )
    md.append("")

    md.append("## 4. Polluter 排名（前序任务抬升后续失败率）")
    md.append("")
    md.append("| agent | condition | 前序任务 | n | 条件失败率 | 基线失败率 | lift | q |")
    md.append("|---|---|---|---|---|---|---|---|")
    for r in report["polluters"][:30]:
        lift = "∞" if r["lift"] == float("inf") else f"{r['lift']:.2f}"
        q = r.get("q_value", float("nan"))
        md.append(
            f"| {r['agent']} | {r['condition']} | {r['polluter']} | {r['n']} | {r['fail_rate']:.3f} | "
            f"{r['baseline_fail_rate']:.3f} | {lift} | {q:.4f} |"
        )
    md.append("")

    if truth:
        md.append("## 5. 管道自检（合成数据）")
        md.append("")
        ov = truth["overall"]
        md.append(
            f"- 总体 victim 检出: TP={ov['tp']} FP={ov['fp']} FN={ov['fn']} "
            f"precision={ov['precision']} recall={ov['recall']}"
        )
        md.append(f"- polluter top-k 命中: {truth['polluter_topk_overlap']} "
                  f"(precision={truth['polluter_topk_precision']})")
        md.append("")
        md.append("| agent | TP | FP | FN | precision | recall |")
        md.append("|---|---|---|---|---|---|")
        for a, v in truth["per_agent"].items():
            md.append(f"| {a} | {v['tp']} | {v['fp']} | {v['fn']} | {v['precision']} | {v['recall']} |")
        md.append("")

    md.append("## 6. 阅读提示")
    md.append("")
    md.append("- **预期形态**：C2（官方重置下的顺序主效应）≈ 0 → app 快照恢复确实挡住了同 app 污染；"
              "C1/C3（重置被削弱）显著为负 → 污染与顺序叠加才致命。若 C2 也显著，说明快照本身不可靠，"
              "这是更强的结论。")
    md.append("- **DiD > 0（更负）** 表示顺序效应只在重置不彻底时才被放大——这正是论文要讲的故事。")
    md.append("- victim 名单 = 需要 cleaner 的任务清单，也是恢复模块的评测集来源。")
    md.append("- CTCI 越大 = 评测越不可信；PASR 是评测公平性的可信下界。")
    md.append("")

    path = os.path.join(out_dir, "report.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))

    clean = _sanitize(json.loads(json.dumps(report, default=str)))
    for bucket in (clean.get("contrasts", {}), clean.get("groups", {}), clean.get("order_contrasts", {})):
        for v in bucket.values():
            v.pop("_recs", None)
    with open(os.path.join(out_dir, "analysis.json"), "w", encoding="utf-8") as fh:
        json.dump(clean, fh, ensure_ascii=False, indent=2)

    with open(os.path.join(out_dir, "victims.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["agent", "contrast", "task", "sr_ref", "sr_treat", "delta_sr", "p_value", "q_value", "victim"])
        for bucket_name in ("contrasts", "order_contrasts"):
            for key, g in report[bucket_name].items():
                agent, name = key.split("|", 1)
                for r in g.get("_recs", []):
                    w.writerow([agent, name, r["task"], f"{r['sr_ref']:.4f}", f"{r['sr_treat']:.4f}",
                                f"{r['delta_sr']:+.4f}", f"{r['p_value']:.6f}", f"{r['q_value']:.6f}",
                                int(r.get("victim", False))])
        for key, g in report["groups"].items():
            for r in g.get("_recs", []):
                w.writerow([g["agent"], f"group:{g['condition']}", r["task"], f"{r['sr_ref']:.4f}",
                            f"{r['sr_treat']:.4f}", f"{r['delta_sr']:+.4f}", f"{r['p_value']:.6f}",
                            f"{r['q_value']:.6f}", int(r.get("victim", False))])
    return path


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="顺序效应 / OD flaky 分析（2×2 析因）")
    ap.add_argument("--input", nargs="+", required=True, help="episodes.jsonl 或包含它的目录")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "results", "analysis"))
    ap.add_argument("--baseline-order", default=CANONICAL)
    ap.add_argument("--official-condition", default=OFFICIAL)
    ap.add_argument("--delta", type=float, default=0.2)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--check-against", default=None, help="ground_truth.json（合成数据自检）")
    args = ap.parse_args(argv)

    rows = load_episodes(args.input)
    if not rows:
        print("没有读到任何 episode。", file=sys.stderr)
        return 2
    report = analyze(
        rows,
        baseline_order=args.baseline_order,
        official_condition=args.official_condition,
        delta=args.delta,
        alpha=args.alpha,
    )
    truth = check_against_ground_truth(report, args.check_against) if args.check_against else None
    path = write_report(report, args.out, truth)
    print(f"{len(rows)} episodes -> {path}")
    for key, g in report["contrasts"].items():
        if key.endswith("DiD_interaction"):
            print(f"  {key}: {g['delta_sr']:+.3f} CI={[round(x, 3) for x in g['delta_sr_ci95']]}")
            continue
        print(
            f"  {key}: ΔSR={g['delta_sr']:+.3f} CI=[{g['delta_sr_ci95'][0]:+.3f},{g['delta_sr_ci95'][1]:+.3f}] "
            f"OD-flaky={g['od_flaky_rate']:.1%} victims={len(g['victims'])}"
        )
    for key, g in report["groups"].items():
        print(f"  {key}: ΔSR={g['delta_sr']:+.3f} CTCI={g['ctci']:.3f} PASR={g['pasr']:.3f} "
              f"OD-flaky={g['od_flaky_rate']:.1%}")
    for key, g in report["order_contrasts"].items():
        print(f"  {key}: ΔSR={g['delta_sr']:+.3f} OD-flaky={g['od_flaky_rate']:.1%} victims={len(g['victims'])}")
    for agent, tasks in report["od_flaky_tasks"].items():
        print(f"  OD-flaky[{agent}] ({len(tasks)}): {', '.join(tasks) if tasks else '无'}")
    if truth:
        print(f"  自检 overall: {truth['overall']}")
        print(f"  polluter top-k: {truth['polluter_topk_overlap']} (precision={truth['polluter_topk_precision']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

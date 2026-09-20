#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_sim_data.py —— 生成带**已知顺序效应**的合成 episodes，用于自测分析管道。

为什么需要它
------------
真跑 AndroidWorld 需要模拟器 + API key + 几十小时。在拿到这些之前，
必须先证明"分析管道能正确地把顺序效应检出来"，否则等真数据到手再发现
指标算错，代价很大。本脚本按一个明确的机制生成数据：

    污染机制（写进 ground truth）
    -----------------------------
    1. condition == official           → 快照恢复挡住一切，无顺序效应（H2 的零假设）
    2. condition != official 且
       前序任务与当前 reader 同 cluster 且是 writer
                                      → reader 成功率按 pollute_strength 下降（H1）
    3. system_write / fs_write 前序任务 → 对"后续任意任务"造成较小的全局抬升（H3）
    4. 不存在于 ground truth 的随机噪声   → 用于检验 FDR 是否会把假阳性压住

输出与 order_runner.py 完全一致的行格式 + ground_truth.json，
因此可以：

    python make_sim_data.py --out ../results/sim
    python analyze_order_effects.py --input ../results/sim/episodes.jsonl \
        --out ../results/sim/analysis --check-against ../results/sim/ground_truth.json

并检查 report 里的 precision/recall 是否为 1.0。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import random
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import task_catalog  # noqa: E402
from order_runner import build_plan  # noqa: E402


def agent_skill(agent: str) -> float:
    """不同 agent 的基础能力（体现"多个 Agent"维度）。"""
    table = {
        "t3a_gpt4": 0.62,       # 中等能力：信号带内，最利于观测 OD 效应
        "m3a_gpt4v": 0.55,
        "seeact": 0.34,         # 弱 agent：失败多，OD 效应会被淹没
        "uitars_1_5_7b": 0.68,
        "minitap_multi": 0.92,  # 强 agent：接近饱和，OD 效应无从体现（H4 的边界条件）
    }
    return table.get(agent, 0.5)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "results", "sim"))
    ap.add_argument("--agents", default="t3a_gpt4,m3a_gpt4v,seeact,minitap_multi")
    ap.add_argument("--order-modes", default="canonical,shuffle,adversarial")
    ap.add_argument("--clean-modes", default="official,none")
    ap.add_argument("--order-seeds", default="0,1,2")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--pollute-strength", type=float, default=0.45, help="同簇 writer->reader 的失败抬升")
    ap.add_argument("--global-pollute", type=float, default=0.12, help="系统/文件系统前序任务的全局抬升")
    ap.add_argument("--noise", type=float, default=0.03, help="与顺序无关的随机抖动")
    ap.add_argument("--min-events", type=int, default=5,
                    help="ground truth victim 至少要被污染暴露这么多次（过滤偶发噪声）")
    ap.add_argument("--seed", type=int, default=20270108)
    args = ap.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    rng = random.Random(args.seed)

    agents = [a.strip() for a in args.agents.split(",") if a.strip()]
    plan = build_plan(
        tasks=[t.name for t in task_catalog.CATALOG],
        agents=agents,
        order_modes=[m.strip() for m in args.order_modes.split(",")],
        clean_modes=[m.strip() for m in args.clean_modes.split(",")],
        repeats=args.repeats,
        order_seeds=[int(s) for s in args.order_seeds.split(",") if s.strip()],
    )

    pollute_events: dict[str, int] = {}
    polluters: set[str] = set()
    n_lines = 0
    jsonl = os.path.join(args.out, "episodes.jsonl")
    with open(jsonl, "w", encoding="utf-8") as fh:
        for run in plan:
            for pos, tname in enumerate(run.tasks):
                spec = task_catalog.BY_NAME[tname]
                p = agent_skill(run.agent)

                # 任务本身"可被污染"的程度：reader 最脆弱，写任务反而更稳
                if spec.is_reader:
                    p -= 0.05

                polluted = False
                if run.clean_mode != "official" and pos > 0:
                    pred = task_catalog.BY_NAME.get(run.tasks[pos - 1])
                    if pred is not None:
                        if pred.is_writer and pred.cluster == spec.cluster:
                            p -= args.pollute_strength
                            polluted = True
                            polluters.add(pred.name)
                        elif pred.snapshot_scope == "out" and pred.is_writer:
                            p -= args.global_pollute
                            polluted = True
                            polluters.add(pred.name)

                # 与顺序无关的噪声（模拟 LLM 采样抖动），用于检验 FDR
                p += rng.uniform(-args.noise, args.noise)
                p = min(0.99, max(0.01, p))

                success = 1.0 if rng.random() < p else 0.0
                if polluted and run.clean_mode != "official":
                    # 记录"被污染暴露"的次数（与本次是否侥幸成功无关），
                    # 这样 ground truth 描述的是机制而非某次抽样结果。
                    pollute_events[tname] = pollute_events.get(tname, 0) + 1

                fh.write(
                    json.dumps(
                        {
                            "run_id": run.run_id,
                            "agent": run.agent,
                            "condition": run.clean_mode,
                            "order_mode": run.order_mode,
                            "order_seed": run.order_seed,
                            "repeat": run.repeat,
                            "position": pos,
                            "predecessor": run.tasks[pos - 1] if pos > 0 else None,
                            "task": tname,
                            "success": success,
                            "exception": False,
                            "episode_length": rng.randint(2, 30),
                            "run_time_s": round(rng.uniform(20, 180), 1),
                            "seed": args.seed,
                            "ts": _dt.datetime.now().isoformat(timespec="seconds"),
                            "_injected_polluted": polluted,
                            "_injected_p": round(p, 4),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                n_lines += 1

    # ground truth：暴露次数达标的任务才算"系统性受害者"，避免把偶发噪声算进去
    victims = sorted(t for t, c in pollute_events.items() if c >= args.min_events)
    gt = {
        "generator": "make_sim_data.py",
        "params": {k: v for k, v in vars(args).items()},
        "victims": victims,
        "polluters": sorted(polluters),
        "pollute_events": dict(sorted(pollute_events.items(), key=lambda kv: -kv[1])),
        "n_episodes": n_lines,
        "note": ("victims = 在非 official 条件下被前序 writer 污染暴露 >= min_events 次的任务；"
                 "polluters = 作为污染前序出现过的任务"),
    }
    with open(os.path.join(args.out, "ground_truth.json"), "w", encoding="utf-8") as fh:
        json.dump(gt, fh, ensure_ascii=False, indent=2)

    print(f"写出 {n_lines} 条 episode -> {jsonl}")
    print(f"ground truth: victims={len(victims)} (>= {args.min_events} 次暴露) polluters={len(polluters)}")
    print(f"  victims: {sorted(victims)}")
    print(f"  polluters: {sorted(polluters)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

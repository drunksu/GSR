#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""score_tasks.py —— 模块②离线评测：对生成的恢复任务集做批量校验与统计。

不调 API、不依赖手机：把 results/recovery_tasks/ 下每份恢复任务集与对应污染清单
重新核对（recovery_task.validate_task_set），统计：
  - 恢复任务/挂起条目的生成覆盖率（清单要求的是否都生成、有无多余）；
  - 校验合格率与错误类型分布；
  - 空处置任务（本任务无 this_task 变更）是否真的零输出；
  - 自动恢复任务与人工挂起的数量分布（供真机阶段估算人工干预率）。

用法::

    mobile\\Scripts\\python.exe score_tasks.py --out ..\\results\\recovery_task_report_v0.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recovery_task as rt  # noqa: E402

HERE = Path(__file__).resolve().parent
DEFAULT_TASK_ROOT = HERE.parent / "results" / "recovery_tasks"
DEFAULT_LEDGER_ROOT = HERE.parent / "results" / "ledgers"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task-root", type=Path, default=DEFAULT_TASK_ROOT)
    ap.add_argument("--ledger-root", type=Path, default=DEFAULT_LEDGER_ROOT)
    ap.add_argument("--out", type=Path, help="报告 JSON 输出路径")
    args = ap.parse_args()

    task_files = sorted(args.task_root.glob("*/*_tasks.json"))
    if not task_files:
        print(f"✗ {args.task_root} 下没有恢复任务文件", file=sys.stderr)
        return 2

    per_case, per_run = [], {}
    totals = {"lists_with_tasks": 0, "expected_tasks": 0, "got_tasks": 0,
              "expected_halt": 0, "got_halt": 0, "valid_sets": 0, "invalid_sets": 0,
              "empty_tasks": 0, "empty_ok": 0}
    err_kinds: dict[str, int] = {}

    for tf in task_files:
        run_id, fname = tf.parent.name, tf.name
        lp = args.ledger_root / run_id / fname.replace("_tasks.json", "_ledger.json")
        if not lp.exists():
            print(f"✗ 缺污染清单: {lp}", file=sys.stderr)
            continue
        pset = json.loads(tf.read_text(encoding="utf-8"))
        ledger = json.loads(lp.read_text(encoding="utf-8"))
        errs = rt.validate_task_set(pset, ledger)
        want_a, want_h = rt.expected_autonomous_ids(ledger), rt.expected_halt_ids(ledger)
        got_a = {p.get("mutation_id") for p in pset.get("tasks", [])}
        got_h = {h.get("mutation_id") for h in pset.get("human_gate", [])}
        is_empty = not want_a and not want_h
        totals["lists_with_tasks"] += 1
        totals["expected_tasks"] += len(want_a)
        totals["got_tasks"] += len(got_a)
        totals["expected_halt"] += len(want_h)
        totals["got_halt"] += len(got_h)
        if is_empty:
            totals["empty_tasks"] += 1
            if not got_a and not got_h:
                totals["empty_ok"] += 1
        if errs:
            totals["invalid_sets"] += 1
            for e in errs:
                # 错误归类：取字段名前缀
                kind = e.split(":")[0].split("[")[0].strip().split(".")[0]
                err_kinds[kind] = err_kinds.get(kind, 0) + 1
        else:
            totals["valid_sets"] += 1

        r = per_run.setdefault(run_id, {"cases": 0, "tasks": 0, "human_gate": 0,
                                        "invalid": 0})
        r["cases"] += 1
        r["tasks"] += len(got_a)
        r["human_gate"] += len(got_h)
        r["invalid"] += 1 if errs else 0

        per_case.append({"case": f"{run_id}/{ledger.get('task_id')}",
                         "expected_tasks": len(want_a), "got_tasks": len(got_a),
                         "expected_halt": len(want_h), "got_halt": len(got_h),
                         "empty_task": is_empty, "valid": not errs,
                         "errors": errs})

    n = totals["lists_with_tasks"]
    report = {
        "n_task_sets": n,
        "valid_rate": round(totals["valid_sets"] / n, 3) if n else 0.0,
        "task_coverage": round(
            min(totals["got_tasks"], totals["expected_tasks"])
            / totals["expected_tasks"], 3) if totals["expected_tasks"] else 1.0,
        "halt_coverage": round(
            min(totals["got_halt"], totals["expected_halt"])
            / totals["expected_halt"], 3) if totals["expected_halt"] else 1.0,
        "empty_task_specificity": (
            round(totals["empty_ok"] / totals["empty_tasks"], 3)
            if totals["empty_tasks"] else 1.0),
        "totals": totals,
        "error_kinds": dict(sorted(err_kinds.items(), key=lambda kv: -kv[1])),
        "per_run": per_run,
        "per_case": per_case,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(f"恢复任务集 {n} 份：合格率 {report['valid_rate']}，"
          f"任务覆盖 {report['task_coverage']}，挂起覆盖 {report['halt_coverage']}，"
          f"空任务零输出 {totals['empty_ok']}/{totals['empty_tasks']}")
    if err_kinds:
        print("错误类型分布：", report["error_kinds"])
    if args.out:
        print(f"报告 → {args.out}")
    return 0 if totals["invalid_sets"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

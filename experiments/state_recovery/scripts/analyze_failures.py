#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析 pipeline 失败案例，打印每轮详情。"""
import json
import glob
from pathlib import Path

base = Path(__file__).resolve().parent.parent / "results" / "pipeline" / "base_canonical"
files = glob.glob(str(base / "*_pipeline.json"))

fails = []
for f in files:
    d = json.load(open(f, encoding="utf-8"))
    if not d.get("success") and d.get("has_contamination"):
        fails.append(d)

print(f"失败任务数: {len(fails)}")
print()

# 统计失败模式
exec_fail = 0
verify_fail = 0
for d in fails:
    for it in d.get("per_iteration", []):
        if not it.get("execute_ok"):
            exec_fail += 1
        else:
            v = it.get("verify", {})
            if not v.get("success"):
                verify_fail += 1

print(f"执行失败次数: {exec_fail}")
print(f"重新审计未清除次数: {verify_fail}")
print()

def verdict_summary(v):
    verdicts = v.get("verdicts", [])
    if not verdicts:
        return f"reason={v.get('reason', '?')}"
    cleared = [x for x in verdicts if x.get("cleared")]
    leftover = [x.get("mutation_id") for x in verdicts if not x.get("cleared")]
    s = f"cleared={len(cleared)}/{len(verdicts)}"
    if leftover:
        s += f" 残留={leftover}"
    return s


for d in fails[:8]:
    print(f"=== {d['task_id']} ===")
    print(f"  iterations: {d['iterations']}, failure: {d['failure_reason']}")
    for it in d.get("per_iteration", []):
        v = it.get("verify", {})
        print(f"  iter {it['iter']}: exec_ok={it.get('execute_ok')}, "
              f"verify={v.get('success')}, {verdict_summary(v)}")
    print()

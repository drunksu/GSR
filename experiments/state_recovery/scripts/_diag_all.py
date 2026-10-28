#!/usr/bin/env python3
"""一条命令查真实现场：ledger vs pipeline 是不是同一版本同一任务。"""
import json, sys
from pathlib import Path

ROOT = Path(r"D:\GSR")

# 1. 找所有 run 目录下的 articlenews_0 ledger
print("=== 1. 所有 articlenews_0 ledger 文件（看哪个是最新的）===")
for p in sorted(ROOT.glob("experiments/state_recovery/results/ledgers/*/articlenews_0_ledger.json")):
    data = json.loads(p.read_text(encoding="utf-8"))
    gate = data.get("_gate", {})
    muts = data.get("mutations", [])
    w = data.get("_warnings", [])
    print(f"  [{p.parent.name}] {len(muts)} muts  gate.auto={gate.get('autonomous')}  gate.halt={[h['id'] if isinstance(h,dict) else h for h in gate.get('halt',[])]}")
    if any("canonicalize" in str(warn) for warn in w):
        print(f"    ↳ 含 canonicalize_reversibility 回填警告（commit 05be824+）")
    else:
        print(f"    ↳ 无 canonicalize 警告（旧代码！）")

# 2. 找所有 articlenews_0 pipeline  
print("\n=== 2. 所有 articlenews_0 pipeline 文件（看哪个是最新的）===")
for p in sorted(ROOT.glob("experiments/state_recovery/results/pipeline/*/articlenews_0_pipeline.json")):
    data = json.loads(p.read_text(encoding="utf-8"))
    print(f"  [{p.parent.name}] term={data.get('termination_reason')} fail={data.get('failure_reason','')[:60]} iter={data.get('iterations')} targets={[t['recovery_status']+':'+t['mutation_id'] for t in data.get('targets',[])]}")

# 3. 看 base_canonical_v3 目录里有没有 10 个 needs_human 的 pipeline
print("\n=== 3. base_canonical_v3 pipeline 终止原因分布 ===")
from collections import Counter
c = Counter()
for p in sorted((ROOT / "experiments/state_recovery/results/pipeline/base_canonical_v3").glob("*_pipeline.json")):
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        tr = data.get("termination_reason", "?")
        fr = data.get("failure_reason", "") or ""
        if tr == "needs_human":
            print(f"  NEEDS_HUMAN: {p.name} fail={fr[:80]}")
        c[tr] += 1
    except Exception as e:
        print(f"  ERROR reading {p.name}: {e}")
print(f"  汇总: {dict(c)}")

# 4. 看有没有 310 条的 pipeline_summary
print("\n=== 4. pipeline_summary.json（看是不是旧的）===")
for p in sorted((ROOT / "experiments/state_recovery/results/pipeline").glob("*/pipeline_summary.json")):
    data = json.loads(p.read_text(encoding="utf-8"))
    s = data.get("summary", {})
    print(f"  [{p.parent.name}] total={s.get('total_tasks')} with_contam={s.get('tasks_with_contamination')} without={s.get('tasks_without_contamination')} errors={s.get('errors')} suc={s.get('recovery_success')}")
    print(f"         failure_reasons={s.get('failure_reasons')}")

# 5. git log 真机仓库
print("\n=== 5. 真机 git log（确认 commit）===")
import subprocess
r = subprocess.run(["git", "log", "--oneline", "-5"], capture_output=True, text=True, cwd=str(ROOT))
print(r.stdout if r.stdout else "(git error)")

print("\n=== Done — 把以上完整输出贴回来 ===")

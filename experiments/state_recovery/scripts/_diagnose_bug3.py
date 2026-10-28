#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机 Bug 3 诊断：ledger._gate 正确但 pipeline 还是 STOP_NEEDS_HUMAN。

直接打印所有中间值，定位矛盾在哪一层。
"""
import json
import sys
from pathlib import Path

ROOT = Path(r"D:\GSR")
LEDGER = ROOT / "experiments" / "state_recovery" / "results" / "ledgers" / "base_canonical_v3" / "articlenews_0_ledger.json"
PIPELINE = ROOT / "experiments" / "state_recovery" / "results" / "pipeline" / "base_canonical_v3" / "articlenews_0_pipeline.json"
TASKS_ROOT = ROOT / "experiments" / "state_recovery" / "results" / "recovery_tasks"

# ---- 1. Ledger ----
print("=" * 60)
print("1. Ledger 原始")
print("=" * 60)
led = json.loads(LEDGER.read_text(encoding="utf-8"))
print(f"  mutations: {len(led['mutations'])}")
for m in led["mutations"]:
    print(f"    {m['id']}: attr={m['attribution']} rev={m['reversible']} conf={m['confidence']}")
print(f"  _gate.autonomous: {led['_gate']['autonomous']}")
print(f"  _gate.halt: {led['_gate']['halt']}")
print(f"  _warnings: {led.get('_warnings', [])}")

# ---- 2. RecoveryState.load_ledger 后 targets ----
print("\n" + "=" * 60)
print("2. RecoveryState.load_ledger() 后 targets")
print("=" * 60)
sys.path.insert(0, str(ROOT / "experiments" / "state_recovery" / "scripts"))
import recovery_state as rs
import mutation_taxonomy as tax
import recovery_task as rt

st = rs.RecoveryState("articlenews_0", "base_canonical_v3", 3)
st.load_ledger(LEDGER)
print(f"  has_contamination: {st.has_contamination}")
print(f"  targets: {len(st.targets)}")
for t in st.targets:
    print(f"    {t['mutation_id']}: recovery_status={t['recovery_status']}  contam={t['contamination_status']}")

# ---- 3. Planner skeleton ----
print("\n" + "=" * 60)
print("3. Planner build_skeleton() 输出")
print("=" * 60)
auto = tax.gate_decision(led)
skeleton = {"autonomous": auto["autonomous"], "halt": [h["id"] for h in auto["halt"]]}
print(f"  skeleton.autonomous: {skeleton['autonomous']}")
print(f"  skeleton.halt:       {skeleton['halt']}")
print(f"  expected_autonomous_ids: {sorted(rt.expected_autonomous_ids(led))}")
print(f"  expected_halt_ids:       {sorted(rt.expected_halt_ids(led))}")

# ---- 4. Pipeline ----
print("\n" + "=" * 60)
print("4. Pipeline JSON")
print("=" * 60)
p = json.loads(PIPELINE.read_text(encoding="utf-8"))
print(f"  termination_reason: {p.get('termination_reason')}")
print(f"  failure_reason:     {p.get('failure_reason')}")
print(f"  iterations:         {p.get('iterations')}")
print(f"  targets 数:         {len(p.get('targets', []))}")
for t in p.get("targets", []):
    print(f"    {t['mutation_id']}: recovery_status={t['recovery_status']}  contam={t['contamination_status']}")
print(f"  decision_log 数:    {len(p.get('decision_log', []))}")
for i, d in enumerate(p.get("decision_log", [])):
    print(f"    [{i}] dec={d.get('decision')} phase={d.get('phase_after')} reason={d.get('reason','')[:80]}")

# ---- 5. 跑一遍 policy_engine 的 decide，手动给 ctx ----
print("\n" + "=" * 60)
print("5. 手动跑 decide（targets 用 pipeline 里的值）")
print("=" * 60)
import policy_engine as pe

# 用 pipeline 里的 targets（真实 run_loop 用的值）
targets_from_pipeline = p.get("targets", [])
st_dict = {
    "phase": p.get("phase", "init"),
    "success": p.get("success", False),
    "termination_reason": p.get("termination_reason"),
    "budget": {
        "max_iter": 3, "remaining": p.get("budget", {}).get("remaining", 3),
        "iter_remaining": p.get("budget", {}).get("remaining", 3),
        "llm_calls": 2, "llm_cap": 50,
        "actions_total": 0, "actions_cap": 100,
    },
    "targets": targets_from_pipeline,
    "context": [],
    "attempt_history": [],
    "per_iteration": [],
}
halted_ids = {t["mutation_id"] for t in targets_from_pipeline if t.get("recovery_status") == "halted"}
active = [t for t in targets_from_pipeline if t.get("recovery_status") != "halted"]
print(f"  halted_ids (pipeline targets): {halted_ids}")
print(f"  active targets:                {[t['mutation_id'] for t in active]}")

# 如果 halted_ids 非空，就找到了矛盾点
if halted_ids:
    print(f"\n  ⚠ 矛盾点！pipeline.targets 里有 halted 状态的 this_task 目标")
    print(f"    但 ledger._gate.halt = {led['_gate']['halt']}")
    print(f"    说明：**某个代码环节在 load_ledger 之后、run_loop 之前把 recovery_status 改成了 halted**")
else:
    print(f"\n  targets 全非 halted，那 decision_log[0] 应该不是 L327")
    print(f"  看 decision_log[0] 的 reason 就能知道是哪条路径触发的 STOP_NEEDS_HUMAN")

print("\n" + "=" * 60)
print("Done — 把以上完整输出贴回来")
print("=" * 60)

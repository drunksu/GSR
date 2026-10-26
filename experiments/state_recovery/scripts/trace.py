#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""trace.py —— 恢复闭环的结构化事件日志（Trace，阶段1）。

每条事件 = JSON 行（JSONL），包含统一信封字段：
  recovery_id / task_id / run_id / iteration / ts(UTC ISO) / type / payload

约定：
  - 大型工件（截图、完整轨迹、任务集 JSON）一律作为外部文件保留，
    事件 payload 只写稳定引用（路径 / 摘要 / 计数），不内联大对象；
  - 敏感信息：不记录 API key / 完整 prompt 原文；实体名称与项目既有
    evidence（ledger / trajectory）一致，不引入新标识；
  - 写入失败：fail loudly（立即抛错），不允许静默吞掉日志错误。

可用命令：
  python trace.py --demo --out <path>   生成一个代表性生命周期示例 Trace
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TraceLogger:
    """JSONL 事件日志。open 失败立即抛错；写失败立即抛错。"""

    def __init__(self, path, recovery_id: str, task_id: str, run_id: str):
        self.path = Path(path)
        self.recovery_id = recovery_id
        self.task_id = task_id
        self.run_id = run_id
        try:
            self.fh = open(self.path, "a", encoding="utf-8")
        except OSError as e:
            raise RuntimeError(f"Trace 日志无法打开: {self.path} ({e})")
        self.emit("trace.open", 0, {})

    def emit(self, etype: str, iteration: int, payload: dict) -> None:
        record = {
            "recovery_id": self.recovery_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "iteration": iteration,
            "ts": utc_iso(),
            "type": etype,
            "payload": payload,
        }
        line = json.dumps(record, ensure_ascii=False)
        try:
            self.fh.write(line + "\n")
            self.fh.flush()
        except OSError as e:
            raise RuntimeError(f"Trace 日志写入失败: {self.path} ({e})")

    def close(self) -> None:
        try:
            self.fh.close()
        except OSError:
            pass


# ------------------------------------------------------------------ 示例

def _demo_trace(out: str) -> None:
    """生成一个代表性的恢复生命周期 Trace（纯本地，不调用手机/API）。"""
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tl = TraceLogger(out_path, "qq_10.base_canonical.1700000000",
                     "qq_10", "base_canonical")
    tl.emit("state.init", 0, {"recovery_id": tl.recovery_id, "max_iter": 3})
    tl.emit("state.ledger_loaded", 0, {
        "ledger": "results/ledgers/base_canonical/qq_10_ledger.json",
        "target_count": 1,
        "context_count": 12,
        "target_ids": ["m1"],
        "context_ids": ["c1", "c2"],
    })
    tl.emit("audit.output", 0, {
        "ledger": "results/ledgers/base_canonical/qq_10_ledger.json",
        "this_task_count": 1,
        "mutation_ids": ["m1"],
    })
    tl.emit("planner.input", 1, {
        "ledger": "results/ledgers/base_canonical/qq_10_ledger.json",
        "target_ids": ["m1"],
    })
    tl.emit("planner.output", 1, {
        "task_set": "results/recovery_tasks/base_canonical/qq_10_tasks.json",
        "task_count": 1,
        "human_gate_count": 0,
        "accepted": True,
        "reason": "validate_task_set passed",
    })
    tl.emit("execute.intent", 1, {
        "task_ref": "results/recovery_tasks/base_canonical/qq_10_tasks.json",
        "goal": "打开 QQ 搜索框，输入并搜索 qq_10_ledger 中的搜索词……",
        "artifact": "pipeline/base_canonical/qq_10/recovery_iter1/trajectory.json",
    })
    tl.emit("execute.result", 1, {
        "execute_ok": True,
        "task_dir": "pipeline/base_canonical/qq_10/recovery_iter1",
        "final_screenshot": "pipeline/base_canonical/qq_10/recovery_iter1/step_3.png",
        "steps": 3,
        "error": None,
    })
    tl.emit("verify.result", 1, {
        "success": False,
        "reason": "reaudit",
        "verdicts": [{"mutation_id": "m1", "cleared": False,
                      "evidence_quote": "搜索历史仍包含该词条"}],
    })
    tl.emit("state.updated", 1, {
        "phase": "verify", "iteration": 1, "budget_remaining": 2,
        "targets": [{"mutation_id": "m1", "recovery_status": "failed",
                     "contamination_status": "present", "attempts": 1}],
    })
    tl.emit("state.terminated", 2, {
        "success": True, "final_state": "clean",
        "termination_reason": "recovered",
        "failure_reason": None, "iterations": 2,
    })
    tl.close()
    print(f"示例 Trace 已写入: {out_path}")
    print(out_path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="恢复闭环 Trace 工具")
    ap.add_argument("--demo", action="store_true", help="生成示例 Trace")
    ap.add_argument("--out", default="trace_demo.jsonl", help="输出路径")
    args = ap.parse_args()
    if args.demo:
        _demo_trace(args.out)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_pipeline.py —— 端到端闭环 pipeline 脚本。

完整流程：
  Step 1: 跑原任务制造污染态（MobileBench 执行原 goal）
  Step 2: Audit 初始推断污染清单
  Step 3: 判断是否有 this_task 污染；无污染 → 直接成功
  闭环循环（最多 max_iter 次）：
    a. Planner 生成恢复任务
    b. Execute 执行恢复（轨迹+截图落盘到独立目录）
    c. Verify 重新审计恢复轨迹（逐项判断 this_task 污染是否被真正清除）
       全部清除 → 成功并退出；仍有残留 → 下一轮
  达到 max_iter 仍有残留 → 失败

单任务用法：
  mobile\\Scripts\\python.exe run_pipeline.py --task qq_10

全量用法（带断点续传）：
  mobile\\Scripts\\python.exe run_pipeline.py --all --skip-infer --skip-generate --skip-existing

跳过已有结果的步骤：
  mobile\\Scripts\\python.exe run_pipeline.py --task qq_10 --skip-infer --skip-generate

手机已处于污染态时，跳过原任务：
  mobile\\Scripts\\python.exe run_pipeline.py --task qq_10 --skip-original --skip-infer --skip-generate
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

# MobileBench 路径
REPO_ROOT = Path(__file__).resolve().parents[3]
MBL_ROOT = REPO_ROOT / "third_party" / "mobilebench-ol-main"
sys.path.insert(0, str(MBL_ROOT))
sys.path.insert(0, str(MBL_ROOT / "mobilebench"))

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))
import mbl_env  # noqa: E402

# 自动注入环境变量：MobileBench 只读 os.environ，不读 mobile.env.ps1 文件
_key = mbl_env.api_key()
if _key and not os.environ.get("MBL_API_KEY"):
    os.environ["MBL_API_KEY"] = _key
if not os.environ.get("MBL_MODEL"):
    os.environ["MBL_MODEL"] = "qwen3-vl-plus"
if not os.environ.get("MBL_COORD"):
    os.environ["MBL_COORD"] = "norm"
if not os.environ.get("MBL_API_LOG"):
    os.environ["MBL_API_LOG"] = "results/api_errors.jsonl"
if not os.environ.get("MBL_API_RETRIES"):
    os.environ["MBL_API_RETRIES"] = "2"
# ADB 路径
_adb = str(REPO_ROOT / "third_party" / "platform-tools")
if _adb not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _adb + os.pathsep + os.environ.get("PATH", "")
if not os.environ.get("ADBUTILS_ADB_PATH"):
    os.environ["ADBUTILS_ADB_PATH"] = str(Path(_adb) / "adb.exe")
# 编码：强制 UTF-8 输出，避免 Windows GBK 无法编码 emoji
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
import infer_mutations as infer  # noqa: E402
import generate_tasks as gen  # noqa: E402
import recovery_task as rt  # noqa: E402
import recovery_state as rs  # noqa: E402
import trace as tr  # noqa: E402
import action_contract as ac  # noqa: E402
import policy_engine as pe  # noqa: E402

DEFAULT_RUN = "base_canonical"
DEFAULT_CSV = MBL_ROOT / "data" / "base_canonical.csv"
DEFAULT_CONFIG = MBL_ROOT / "config" / "interact_API_qwen3vl_base.conf"
LEDGER_ROOT = Path(__file__).resolve().parent.parent / "results" / "ledgers"
TASK_ROOT = Path(__file__).resolve().parent.parent / "results" / "recovery_tasks"
PIPELINE_OUT = Path(__file__).resolve().parent.parent / "results" / "pipeline"
DEFAULT_MAX_ITER = 3


# ----------------------------------------------------------------- 工具

def _log(msg: str):
    print(f"\n{'='*60}\n{msg}\n{'='*60}")


def _load_task_row(task_id: str, csv_path: Path) -> dict:
    """从 CSV 中提取单个任务行。"""
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["task_identifier"] == task_id:
                return row
    raise ValueError(f"CSV 中找不到任务 {task_id}: {csv_path}")


def _make_single_task_csv(task_id: str, csv_path: Path, out_dir: Path) -> Path:
    """生成只含一个任务的 CSV，供 MobileBench 执行。"""
    row = _load_task_row(task_id, csv_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / f"{task_id}.csv"
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)
    return out_csv


def _count_this_task_mutations(ledger_path: Path) -> int:
    """统计 ledger 中 this_task 类别的 mutation 数量。"""
    if not ledger_path.exists():
        return 0
    with open(ledger_path, encoding="utf-8") as f:
        ledger = json.load(f)
    return sum(1 for m in ledger.get("mutations", [])
               if m.get("attribution") == "this_task")


# ----------------------------------------------------------------- Step 1: 跑原任务

def run_original_task(task_id: str, csv_path: Path, config_path: Path,
                      out_dir: Path) -> Path:
    """跑原任务，返回 trajectory.json 路径。"""
    from mobilebench.utils.task_executor import (
        DeviceManager, AgentFactory, TaskExecutor, load_tasks,
    )
    from configparser import ConfigParser

    _log(f"[Step 1] 跑原任务 {task_id} 制造污染态")

    single_csv = _make_single_task_csv(task_id, csv_path, out_dir)
    tasks = load_tasks(single_csv)
    if not tasks:
        raise RuntimeError(f"无法加载任务 {task_id}")
    task = tasks[0]

    config = ConfigParser()
    config.read(str(config_path), encoding="UTF-8")
    serial = config.get("device", "id")
    model_name = config.get("model", "name")
    model_url = config.get("model", "url")
    max_steps = int(config.get("operation", "max_steps"))
    time_sleep = int(config.get("operation", "sleep_seconds_per_act"))

    dev_mgr = DeviceManager(serial)
    agent = AgentFactory.create(model_name, model_url, dev_mgr.d)
    executor = TaskExecutor(dev_mgr, agent, time_sleep, max_steps)

    task_out = out_dir / task_id
    task_out.mkdir(parents=True, exist_ok=True)
    traj = executor.run(task, task_out, reset=False)

    traj_path = task_out / "trajectory.json"
    with open(traj_path, "w", encoding="utf-8") as f:
        json.dump(traj.__dict__, f, ensure_ascii=False, indent=2)
    print(f"  原任务完成: success={traj.success}, steps={len(traj.history_action)}")
    print(f"  轨迹保存: {traj_path}")
    return traj_path


# ----------------------------------------------------------------- Step 2: 推断污染

def run_infer(task_id: str, run: str, traj_path: Path,
              out_dir: Path, skip_existing: bool = True) -> Path:
    """推断污染清单，返回 ledger.json 路径。"""
    _log(f"[Step 2] Audit 推断污染清单 {task_id}")

    ledger_dir = LEDGER_ROOT / run
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / f"{task_id}_ledger.json"

    if skip_existing and ledger_path.exists():
        print(f"  已有 ledger，跳过: {ledger_path}")
        return ledger_path

    key = mbl_env.api_key()
    try:
        ledger = infer.infer_one(
            traj_path=traj_path,
            run_dir=traj_path.parent.parent,
            run_id=run,
            model=infer.DEFAULT_MODEL,
            base_url=infer.DEFAULT_BASE_URL,
            key=key,
            dry_run=False,
        )
    except Exception as e:
        # 推断失败（额度/网络/解析）必须显式报错，绝不能静默当作
        # "无污染"直接成功 —— 否则额度耗尽时会产出大量假成功。
        raise RuntimeError(
            f"infer 失败（未写入 ledger，避免误判无污染）: {e}") from e
    if not isinstance(ledger, dict) or "mutations" not in ledger:
        raise RuntimeError(
            "infer 返回非法格式（未写入 ledger，避免误判无污染）")
    with open(ledger_path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)
    n_mut = len(ledger.get("mutations", []))
    print(f"  推断完成: {n_mut} 条 mutation → {ledger_path}")
    return ledger_path


def _build_harness_ctx(st, pset: dict) -> dict:
    """构造阶段2 Harness 上下文（授权范围 / 目标 / 预算 / 记录回调）。

    从 pset 的第一个恢复任务与 RecoveryState 确定性推导：
      - target_ids：本轮授权的污染目标（仅 this_task targets 中未清除者）
      - target_id / mutation：恢复任务对应的目标（找不到则取首个目标）
      - budget：轮次剩余预算（循环/Policy 控制）
      - max_actions：本轮 GUI 动作上限
      - record：动作记录写回 RecoveryState（trace 事件）
    """
    tasks = pset.get("tasks") or []
    rec_task = tasks[0] if tasks else {}
    # 本轮授权范围：尚未 verified_cleared 的 this_task 目标
    target_ids = [t["mutation_id"] for t in st.targets
                  if t.get("recovery_status") != "verified_cleared"]
    target_id = rec_task.get("mutation_id")
    mutation = None
    for t in st.targets:
        if t["mutation_id"] == target_id:
            mutation = t["mutation_ref"]
            break
    if mutation is None and st.targets:
        mutation = st.targets[0]["mutation_ref"]
    max_actions = rec_task.get("max_steps", 20)
    return {
        "enabled": True,
        "recovery_id": st.recovery_id,
        "target_ids": target_ids,
        "target_id": target_id,
        "mutation": mutation,
        "budget": dict(st.budget),
        "max_actions": max_actions,
        "action_log": [],
        "record": st.record_action,
    }


# ----------------------------------------------------------------- Step 3: 生成恢复任务

def run_generate(task_id: str, run: str, ledger_path: Path,
                 skip_existing: bool = True) -> Path:
    """生成恢复任务，返回 tasks.json 路径。"""
    _log(f"[Step 3] Planner 生成恢复任务 {task_id}")

    task_dir = TASK_ROOT / run
    task_dir.mkdir(parents=True, exist_ok=True)
    task_path = task_dir / f"{task_id}_tasks.json"

    if skip_existing and task_path.exists():
        print(f"  已有 task，跳过: {task_path}")
        return task_path

    with open(ledger_path, encoding="utf-8") as f:
        ledger = json.load(f)

    key = mbl_env.api_key()
    pset = gen.generate_one(
        ledger, infer.DEFAULT_MODEL, infer.DEFAULT_BASE_URL, key or "")
    with open(task_path, "w", encoding="utf-8") as f:
        json.dump(pset, f, ensure_ascii=False, indent=2)
    print(f"  生成完成: {len(pset['tasks'])} 个任务, "
          f"{len(pset['human_gate'])} 条挂起 → {task_path}")
    return task_path


# ----------------------------------------------------------------- Step 4: 执行恢复

def run_recovery(task_id: str, run: str, task_path: Path,
                 csv_path: Path, config_path: Path,
                 out_dir: Path, iter_idx: int,
                 harness: dict | None = None) -> dict:
    """执行恢复任务，返回恢复轨迹 dict 与目录信息，供重新审计用。

    harness（阶段2）：非 None 且 enabled 时，把 Executor 改造成受 Harness
    管理的组件 —— 每步挂动作契约钩子（执行前检查 / 执行后三分离验证），
    并在关键动作后通过 step 回调返回控制权。默认 None = 旧行为（v1）。
    """
    from mobilebench.utils.task_executor import (
        DeviceManager, AgentFactory, TaskExecutor, load_tasks,
    )
    from configparser import ConfigParser

    _log(f"[Step 4] Execute 执行恢复任务 {task_id} (第 {iter_idx} 轮)")

    with open(task_path, encoding="utf-8") as f:
        pset = json.load(f)

    tasks = pset.get("tasks", [])
    if not tasks:
        print(f"  无自动恢复任务（可能全是人工挂起或空任务），跳过执行")
        return {"traj": {}, "task_dir": None, "final_img": None}

    # 取第一个自动恢复任务
    rec_task = tasks[0]
    goal = rec_task["recovery_goal"]
    max_steps = rec_task.get("max_steps", 20)
    print(f"  恢复目标: {goal}")
    print(f"  最大步数: {max_steps}")

    # 用原任务的 home_activity
    row = _load_task_row(task_id, csv_path)
    home_activity = row["adb_home_page"]
    golden_steps = int(row["golden_steps"])

    config = ConfigParser()
    config.read(str(config_path), encoding="UTF-8")
    serial = config.get("device", "id")
    model_name = config.get("model", "name")
    model_url = config.get("model", "url")
    time_sleep = int(config.get("operation", "sleep_seconds_per_act"))

    dev_mgr = DeviceManager(serial)
    agent = AgentFactory.create(model_name, model_url, dev_mgr.d)
    executor = TaskExecutor(dev_mgr, agent, time_sleep, maximum_steps=max_steps)

    # ---- 阶段2 Harness：受管 Executor（动作契约 + 三分离验证 + 暂停）----
    if harness is not None and harness.get("enabled"):
        harness["recovery_task"] = rec_task

        def _action_id() -> str:
            return (f"{harness['recovery_id']}.iter{iter_idx}."
                    f"step{len(harness['action_log']) + 1}")

        def _harness_pre(act, xml_before, img_before):
            pre = ac.precheck_action(act, xml_before or "", harness)
            harness["last_pre"] = pre
            if not pre["allow"]:
                # 前置不成立：不盲目执行，记录 blocked 并返回 Harness
                rec = ac.compose_record(
                    action_id=_action_id(), target_id=harness["target_id"],
                    action=act, precheck=pre,
                    tool_result={"adb_ok": None, "error": pre["reason"]},
                    postcheck=None,
                    expected_effect=rec_task.get("expected_end_state"))
                harness["action_log"].append(rec)
                harness["record"](rec)
            return {"allow": pre["allow"], "reason": pre["reason"]}

        def _harness_post(act, tool_result, xml_before, img_before, env):
            # 重新观察：动作后的界面层级与截图（拿不到 → uncertain，不崩执行）
            xml_after = ""
            img_after_path = None
            try:
                xml_after = env.dump_hierarchy() or ""
            except Exception:
                xml_after = ""
            try:
                after_img = env.screenshot()
                img_after_path = str(Path(img_before).with_name(
                    Path(img_before).stem + "_after.png"))
                after_img.save(img_after_path)
            except Exception:
                img_after_path = None
            post = ac.postcheck_action(act, tool_result,
                                       xml_before or "", xml_after, harness)
            pre = harness.get("last_pre") or ac.precheck_action(
                act, xml_before or "", harness)
            rec = ac.compose_record(
                action_id=_action_id(), target_id=harness["target_id"],
                action=act, precheck=pre, tool_result=tool_result,
                postcheck=post,
                expected_effect=rec_task.get("expected_end_state"),
                observation_ref={
                    "img_before": img_before,
                    "img_after": img_after_path,
                    "xml_before_sig": ac.xml_signature(xml_before or ""),
                    "xml_after_sig": ac.xml_signature(xml_after),
                })
            harness["action_log"].append(rec)
            harness["record"](rec)

        def _harness_step_cb(step_count, ok, stepdata):
            """关键动作后返回控制权：blocked / 达动作上限 / 目标已清 / 新污染。"""
            recs = harness["action_log"]
            if not recs:
                return False
            last = recs[-1]
            if last.get("execution_status") == "blocked":
                return True
            if step_count >= harness.get("max_actions", 999):
                return True
            if last.get("clearance") == "cleared":
                return True
            if last.get("new_contamination_signal"):
                return True
            return False

        agent.set_action_hooks(pre_action=_harness_pre,
                               post_action=_harness_post)
        executor.set_step_callback(_harness_step_cb)

    # 构造恢复 Task
    from mobilebench.utils.task_executor import Task
    task = Task(
        identifier=f"{task_id}_recovery_iter{iter_idx}",
        goal=goal,
        home_activity=home_activity,
        golden_steps=golden_steps,
        key_nodes="",  # 不用 xpath 验证，用 VLM
        reset_xpath="",
        reset_query="",
    )

    # 独立目录保存本轮轨迹与截图，避免覆盖原任务 / 上一轮的文件
    rec_out = out_dir / task_id / f"recovery_iter{iter_idx}"
    rec_out.mkdir(parents=True, exist_ok=True)
    traj = executor.run(task, rec_out, reset=False)

    # 取最后一张截图
    imgs = traj.history_image_path
    final_img = Path(imgs[-1]) if imgs else None
    print(f"  恢复执行完成: steps={len(traj.history_action)}")
    if final_img:
        print(f"  最终截图: {final_img}")
    return {
        "traj": traj.__dict__,
        "task_dir": str(rec_out),
        "final_img": str(final_img) if final_img else None,
    }


# ----------------------------------------------------------------- Step 5: 验证（重新检测当前状态）

def run_verify(task_id: str, run: str, ledger_path: Path,
               recovery_traj: dict, task_dir: str, iter_idx: int) -> dict:
    """重新审计恢复轨迹：逐项判断 this_task 污染是否被真正清除。

    对照原始污染清单（ledger），让 VLM 复核整条恢复轨迹（含各步截图），
    逐项判断每一处 this_task 污染是否已被撤销/删除/关闭/取消。全部清除才算成功。
    """
    _log(f"[Step 5] Verify 重新审计恢复轨迹 {task_id} (第 {iter_idx} 轮)")

    with open(ledger_path, encoding="utf-8") as f:
        ledger = json.load(f)
    this_task_muts = [m for m in ledger.get("mutations", [])
                      if m.get("attribution") == "this_task"]
    if not this_task_muts:
        return {"success": True, "reason": "no_contamination", "verdicts": []}

    if not task_dir:
        return {"success": False, "reason": "no_recovery_traj", "verdicts": []}

    key = mbl_env.api_key()
    if not key:
        return {"success": False, "reason": "no_api_key", "verdicts": []}

    verdicts = infer.verify_cleared(
        ledger, recovery_traj, Path(task_dir),
        infer.DEFAULT_MODEL, infer.DEFAULT_BASE_URL, key)

    ids = {m.get("id") for m in this_task_muts}
    got = {v.get("mutation_id") for v in verdicts}
    cleared_ids = {v.get("mutation_id") for v in verdicts
                   if v.get("cleared") is True}
    all_cleared = bool(ids) and ids.issubset(got) and ids.issubset(cleared_ids)

    print(f"  复核 verdicts: {verdicts}")
    print(f"  污染状态: {'已全部清除' if all_cleared else '仍有残留'}")
    return {"success": all_cleared, "reason": "reaudit", "verdicts": verdicts}


# ----------------------------------------------------------------- 主流程

def run_pipeline_one(task_id: str, run: str, csv_path: Path,
                     config_path: Path, skip_infer: bool,
                     skip_generate: bool, skip_original: bool,
                     max_iter: int, trace: bool = False,
                     harness_mode: str = "v1") -> dict:
    """跑单个任务的完整闭环 pipeline。

    trace=True 时：开启显式 RecoveryState（targets / attempt_history /
    termination_reason）与 JSONL Trace 日志；循环策略本身不变（阶段1
    不引入动态策略、不改 Planner Prompt、不改执行器动作策略、不加 LLM 调用）。

    harness_mode="v2" 时（阶段2）：启用动作契约与独立验证 —— 每步执行前
    检查（授权/前置/明确性/动作集合/预算）、执行后三分离验证
    （execution_status / gui_changed / clearance），Executor 受 Harness
    管理（关键动作后返回控制权，不允许自宣成功）。动作结果与最终恢复结果
    分开表示：恢复成功仍只由 Verify（VLM 复核）判定。v2 隐含启用显式
    RecoveryState（targets/budget/actions 记录）。
    """
    out_dir = PIPELINE_OUT / run
    out_dir.mkdir(parents=True, exist_ok=True)

    # 显式恢复状态（阶段1）：闭环循环由确定性状态对象驱动，最终序列化与旧 *_pipeline.json 兼容
    st = rs.RecoveryState(task_id, run, max_iter)

    # Trace 日志（可选）：--trace 开启时输出 <task>_trace.jsonl
    trace_logger = None
    if trace:
        trace_logger = tr.TraceLogger(out_dir / f"{task_id}_trace.jsonl",
                                      st.recovery_id, task_id, run)
        st.attach_trace(trace_logger)

    # ---- Step 1: 原任务（只跑一次，制造污染态）----
    if skip_original:
        # 按优先级查找现有轨迹（2026-10-28 修复：run_original_task 写到
        # pipeline 输出目录，skip_original 之前只查 MBL_ROOT/results 目录）：
        #   1) pipeline 输出目录同 run 下（run_pipeline 自己写的）
        #   2) MobileBench 默认 results/run 目录（旧 harness v1）
        #   3) MobileBench 默认 results/base_canonical 目录（跨 harness 复用）
        candidates = [
            PIPELINE_OUT / run / task_id / "trajectory.json",
            MBL_ROOT / "results" / run / task_id / "trajectory.json",
            MBL_ROOT / "results" / DEFAULT_RUN / task_id / "trajectory.json",
        ]
        traj_path = None
        for cand in candidates:
            if cand.exists():
                traj_path = cand
                break
        if traj_path is None:
            raise RuntimeError(
                f"skip-original 找不到 trajectory.json，检查过：\n"
                + "\n".join(f"  {c}" for c in candidates))
        print(f"\n[Step 1] 跳过原任务，使用已有轨迹: {traj_path}")
    else:
        traj_path = run_original_task(task_id, csv_path, config_path, out_dir)
    st.trajectory_path = str(traj_path)

    # ---- Step 2: 初始推断污染清单 ----
    st.emit_event("audit.input", 0, {"trajectory": str(traj_path)})
    ledger_path = run_infer(task_id, run, traj_path, out_dir,
                            skip_existing=skip_infer)
    st.ledger_path = str(ledger_path)

    # 检查是否有 this_task 污染（trace / v2 / v3 时走严格只读校验并构造 targets）
    if trace or harness_mode in ("v2", "v3"):
        st.load_ledger(ledger_path)          # 严格校验 + targets/context 构造
        has_contamination = st.has_contamination
        n_this_task = len(st.targets)
    else:
        n_this_task = _count_this_task_mutations(ledger_path)
        has_contamination = n_this_task > 0
    st.emit_event("audit.output", 0, {"ledger": str(ledger_path),
                                      "this_task_count": n_this_task})
    print(f"\n  初始检测: this_task 污染 {n_this_task} 条")

    extended = trace or harness_mode in ("v2", "v3")

    # 无 this_task 污染 → 无需恢复，直接成功
    if not has_contamination:
        st.finish(success=True, first_try=True, final_state="clean",
                  termination_reason="no_contamination")
        result_path = out_dir / f"{task_id}_pipeline.json"
        st.save(result_path, extended=extended)
        print(f"\n  无 this_task 污染，无需恢复 → 成功")
        print(f"  Pipeline 结果保存: {result_path}")
        if trace_logger is not None:
            trace_logger.close()
        return st.to_dict(extended=extended)

    # ---- 闭环循环：生成 → 执行 → 检测 ----
    success = False
    first_try_success = False
    final_state = "contaminated"
    failure_reason = None

    # ---- 阶段3：Policy Engine 驱动的闭环（v3，确定性管理，不再让循环盲跑）----
    if harness_mode == "v3":
        holder = {"task_path": None, "last_rec": None}

        def _replan():
            task_path = run_generate(task_id, run, ledger_path,
                                     skip_existing=False)
            with open(task_path, encoding="utf-8") as f:
                pset = json.load(f)
            plan_sig = {}
            for _t in pset.get("tasks") or []:
                plan_sig[_t.get("mutation_id")] = _t.get("recovery_goal")
            holder["task_path"] = task_path
            return task_path, plan_sig, pset

        def _execute():
            task_path = holder.get("task_path")
            if task_path is None:
                raise RuntimeError("v3: 无计划可执行（replan 未先行）")
            with open(task_path, encoding="utf-8") as f:
                pset = json.load(f)
            harness_ctx = _build_harness_ctx(st, pset)
            rec = run_recovery(task_id, run, task_path, csv_path,
                               config_path, out_dir, st.iteration,
                               harness=harness_ctx)
            holder["last_rec"] = rec
            return rec

        def _verify():
            rec = holder.get("last_rec")
            if rec is None or rec.get("task_dir") is None:
                return {"success": False, "reason": "no_recovery_traj",
                        "verdicts": []}
            return run_verify(task_id, run, ledger_path, rec["traj"],
                              rec["task_dir"], st.iteration)

        def _reaudit():
            """重新审计（阶段4）：基于最新恢复轨迹重推断污染并调整 targets。

            由 Policy 在「新污染出现在授权目标范围」时按需调用；失败时
            保持原判断（返回 None = 无变化），绝不让审计失败阻断循环。
            """
            rec = holder.get("last_rec")
            if rec is None or not rec.get("traj"):
                return None
            try:
                re_dir = out_dir / task_id / f"reaudit_{st.iteration}"
                re_dir.mkdir(parents=True, exist_ok=True)
                traj_path = re_dir / "trajectory.json"
                with open(traj_path, "w", encoding="utf-8") as f:
                    json.dump(rec["traj"], f, ensure_ascii=False, indent=2)
                key = mbl_env.api_key()
                new_ledger = infer.infer_one(
                    traj_path=traj_path, run_dir=re_dir, run_id=run,
                    model=infer.DEFAULT_MODEL, base_url=infer.DEFAULT_BASE_URL,
                    key=key, dry_run=False)
                tmp = re_dir / "ledger.json"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(new_ledger, f, ensure_ascii=False, indent=2)
                st.load_ledger(tmp)   # 严格校验 + 重建 targets/context
                print(f"  重审计完成: this_task {len(st.targets)} 条 → {tmp}")
                return {"reaudited": True, "target_count": len(st.targets),
                        "ledger": str(tmp)}
            except Exception as e:
                print(f"  重审计失败（保持原判断）: {e}")
                return None

        ledger_ro = rs.load_ledger_immutable(ledger_path)
        final = pe.run_loop(
            st,
            replan=_replan, execute=_execute, verify=_verify,
            observe=_verify, reaudit=_reaudit,
            plan_validator=rt.validate_task_set, ledger=ledger_ro)
        st.finish(
            success=final["decision"] == "STOP_SUCCESS",
            first_try=(final["decision"] == "STOP_SUCCESS"
                       and final["iterations"] == 1),
            final_state=("clean" if final["decision"] == "STOP_SUCCESS"
                         else "pending" if final["decision"] == "STOP_NEEDS_HUMAN"
                         else "contaminated"),
            failure_reason=(None if final["decision"] == "STOP_SUCCESS"
                            else final["reason"]),
            termination_reason=final["termination_reason"])
        result_path = out_dir / f"{task_id}_pipeline.json"
        st.save(result_path, extended=extended)
        print(f"\n  Policy Engine 终止: {final['decision']} "
              f"({final['termination_reason']}) 共 {final['iterations']} 轮 "
              f"{final['llm_calls']} 次模型调用 {final['actions_total']} 个动作")
        print(f"  Pipeline 结果保存: {result_path}")
        if trace_logger is not None:
            trace_logger.close()
        return st.to_dict(extended=extended)

    for i in range(1, max_iter + 1):
        st.begin_iteration(i)

        # Step 3: 生成恢复任务（每轮重新生成，LLM 可能给出不同方案）
        st.emit_event("planner.input", i, {
            "ledger": str(ledger_path),
            "target_ids": [t["mutation_id"] for t in st.targets] if extended else [],
        })
        try:
            task_path = run_generate(task_id, run, ledger_path,
                                     skip_existing=skip_generate and i == 1)
            st.record_generate(ok=True, task_path=task_path)
        except Exception as e:
            st.record_generate(ok=False, error=e)
            failure_reason = f"generate_error: {e}"
            print(f"  ✗ 第 {i} 轮生成失败: {e}")
            break

        # ---- 阶段2：构造 Harness 上下文（授权范围 / 目标 / 预算 / 记录回调）----
        harness_ctx = None
        if harness_mode == "v2":
            with open(task_path, encoding="utf-8") as f:
                _pset = json.load(f)
            harness_ctx = _build_harness_ctx(st, _pset)

        # Step 4: 执行恢复
        st.emit_event("execute.intent", i, {
            "task_ref": str(task_path),
            "artifact_dir": str(out_dir / task_id / f"recovery_iter{i}"),
        })
        try:
            rec = run_recovery(task_id, run, task_path, csv_path,
                               config_path, out_dir, i, harness=harness_ctx)
            st.record_execute(ok=rec["final_img"] is not None, rec=rec,
                              intent={"task_ref": str(task_path)})
        except Exception as e:
            st.record_execute(ok=False, error=e)
            failure_reason = f"execute_error: {e}"
            print(f"  ✗ 第 {i} 轮执行失败: {e}")
            break

        # Step 5: 重新审计恢复轨迹，判断污染是否清除
        # （阶段2：恢复成功只由这里判定，Executor 的 success 标志不参与）
        try:
            verify = run_verify(task_id, run, ledger_path, rec["traj"],
                                rec["task_dir"], i)
            st.record_verify(verify)
            if verify["success"]:
                success = True
                final_state = "clean"
                if i == 1:
                    first_try_success = True
                print(f"\n  ✓ 第 {i} 轮恢复成功！")
                break
        except Exception as e:
            st.record_verify({"success": False, "reason": str(e), "answer": ""})
            failure_reason = f"verify_error: {e}"
            print(f"  ✗ 第 {i} 轮验证出错: {e}")
            break

        print(f"\n  第 {i} 轮恢复未成功，进入下一轮...")

    if not success and failure_reason is None:
        failure_reason = f"max_iter_exceeded ({max_iter})"
        final_state = "contaminated"

    st.finish(success, first_try_success, final_state, failure_reason)
    result_path = out_dir / f"{task_id}_pipeline.json"
    st.save(result_path, extended=extended)
    print(f"\n  Pipeline 结果保存: {result_path}")
    if trace_logger is not None:
        trace_logger.close()
    return st.to_dict(extended=extended)


def _compute_summary(results: list) -> dict:
    """从结果列表计算汇总指标。"""
    total = len(results)
    with_contam = [r for r in results if r.get("has_contamination")]
    success = [r for r in with_contam if r.get("success")]
    first_try = [r for r in with_contam if r.get("first_try_success")]
    errors = [r for r in results if "error" in r]

    # 失败原因分布
    failure_reasons = {}
    for r in with_contam:
        if not r.get("success"):
            reason = r.get("failure_reason", "unknown")
            # 归类
            if reason.startswith("generate_error"):
                cat = "generate_error"
            elif reason.startswith("execute_error"):
                cat = "execute_error"
            elif reason.startswith("verify_error"):
                cat = "verify_error"
            elif reason.startswith("max_iter"):
                cat = "max_iter_exceeded"
            else:
                cat = reason
            failure_reasons[cat] = failure_reasons.get(cat, 0) + 1

    # 平均迭代次数（只算有污染且成功的）
    iters = [r.get("iterations", 0) for r in success]
    avg_iter = sum(iters) / len(iters) if iters else 0

    return {
        "total_tasks": total,
        "tasks_with_contamination": len(with_contam),
        "tasks_without_contamination": total - len(with_contam) - len(errors),
        "errors": len(errors),
        "recovery_success": len(success),
        "recovery_rate": round(len(success) / len(with_contam), 4) if with_contam else 0,
        "first_try_success": len(first_try),
        "first_try_rate": round(len(first_try) / len(with_contam), 4) if with_contam else 0,
        "avg_iterations": round(avg_iter, 2),
        "failure_reasons": failure_reasons,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", help="单个任务 ID，如 qq_10")
    ap.add_argument("--all", action="store_true", help="跑全部 base_canonical 任务")
    ap.add_argument("--run", default=None,
                    help="结果目录 run 名（默认 base_canonical；harness v2/v3 时"
                         "自动用 base_canonical_{v2,v3}，避免覆盖旧基线）")
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--skip-infer", action="store_true",
                    help="跳过推断，使用已有 ledger")
    ap.add_argument("--skip-generate", action="store_true",
                    help="跳过生成（仅第一轮），使用已有 recovery task")
    ap.add_argument("--skip-original", action="store_true",
                    help="跳过原任务执行（手机已处于污染态时用）")
    ap.add_argument("--skip-existing", action="store_true",
                    help="断点续传：跳过已成功完成的任务")
    ap.add_argument("--max-iter", type=int, default=DEFAULT_MAX_ITER,
                    help=f"最大闭环迭代次数（默认 {DEFAULT_MAX_ITER}）")
    ap.add_argument("--trace", action="store_true",
                    help="开启显式 RecoveryState（targets/attempt_history）与 JSONL Trace 日志")
    ap.add_argument("--harness", choices=("v1", "v2", "v3"), default="v1",
                    help="v2=启用动作契约与独立验证（阶段2）；v3=v2 + Policy Engine"
                         "（阶段3/4：确定性动态控制循环 + 证据驱动诊断/按需调度）。"
                         "v1 始终保留为固定循环基线，可随时回退")
    args = ap.parse_args()

    # ---- run 目录隔离（避免不同 harness 模式互相覆盖 / 混叠歧义）----
    # 显式 --run 尊重用户；未指定时按 harness 模式自动分流：
    #   v1（旧基线）→ base_canonical；v2 → base_canonical_v2；
    #   v3（V4 动态控制）→ base_canonical_v3
    # 这样 ledger / recovery_tasks / pipeline 三处输出都落在各自独立
    # 目录，V4 结果不会覆盖 V0 基线，统计口径清晰。
    if args.run is None:
        args.run = DEFAULT_RUN if args.harness == "v1" \
            else f"{DEFAULT_RUN}_{args.harness}"
    print(f"结果目录 run = {args.run}（harness={args.harness}）")

    if not args.task and not args.all:
        ap.error("需要指定 --task 或 --all")

    # 收集任务列表
    if args.all:
        with open(args.csv, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            task_ids = [row["task_identifier"] for row in reader
                        if row.get("key_nodes")]
    else:
        task_ids = [args.task]

    print(f"将执行 {len(task_ids)} 个任务的 pipeline（max_iter={args.max_iter}）")
    results = []
    skipped = 0
    for idx, tid in enumerate(task_ids, 1):
        result_path = PIPELINE_OUT / args.run / f"{tid}_pipeline.json"

        # 断点续传：已成功的任务跳过
        if args.skip_existing and result_path.exists():
            try:
                with open(result_path, encoding="utf-8") as f:
                    existing = json.load(f)
                if existing.get("success"):
                    print(f"[{idx}/{len(task_ids)}] {tid} 已成功，跳过")
                    results.append(existing)
                    skipped += 1
                    continue
            except Exception:
                pass

        print(f"\n[{idx}/{len(task_ids)}] 处理任务: {tid}")
        try:
            r = run_pipeline_one(
                tid, args.run, args.csv, args.config,
                args.skip_infer, args.skip_generate, args.skip_original,
                args.max_iter, trace=args.trace, harness_mode=args.harness)
            results.append(r)
        except Exception as e:  # noqa: BLE001
            print(f"\n✗ {tid} pipeline 失败: {e}")
            results.append({"task_id": tid, "error": str(e)})

    # 汇总
    summary = _compute_summary(results)
    print(f"\n{'='*60}")
    print(f"Pipeline 汇总")
    print(f"{'='*60}")
    print(f"  总任务数:           {summary['total_tasks']}")
    print(f"  有污染任务数:       {summary['tasks_with_contamination']}")
    print(f"  无污染任务数:       {summary['tasks_without_contamination']}")
    print(f"  出错任务数:         {summary['errors']}")
    print(f"  恢复成功数:         {summary['recovery_success']}")
    print(f"  恢复成功率:         {summary['recovery_rate']:.2%}")
    print(f"  一次成功数:         {summary['first_try_success']}")
    print(f"  一次成功率:         {summary['first_try_rate']:.2%}")
    print(f"  平均迭代次数:       {summary['avg_iterations']}")
    print(f"  失败原因分布:       {summary['failure_reasons']}")
    if skipped:
        print(f"  断点续传跳过:       {skipped}")

    summary_path = PIPELINE_OUT / args.run / "pipeline_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": results},
                  f, ensure_ascii=False, indent=2)
    print(f"\n汇总保存: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

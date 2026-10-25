#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_pipeline.py —— 端到端闭环 pipeline 脚本。

完整流程：
  Step 1: 跑原任务制造污染态（MobileBench 执行原 goal）
  Step 2: Audit 初始推断污染清单
  Step 3: 如果无 this_task 污染 → 直接成功
  循环（最多 max_iter 次）：
    Step 4: Planner 生成恢复任务
    Step 5: Execute 执行恢复
    Step 6: Verify 重新检测当前状态（VLM 看图回答 expected_end_state.question）
            → 回答 yes（污染已清除）→ 成功，退出循环
            → 回答 no（污染仍存在）→ 继续下一轮（重新生成+执行）
  达到 max_iter 仍未清除 → 失败

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
    ledger = infer.infer_one(
        traj_path=traj_path,
        model=infer.DEFAULT_MODEL,
        base_url=infer.DEFAULT_BASE_URL,
        api_key=key,
        run_id=run,
    )
    with open(ledger_path, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)
    n_mut = len(ledger.get("mutations", []))
    print(f"  推断完成: {n_mut} 条 mutation → {ledger_path}")
    return ledger_path


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
                 out_dir: Path, iter_idx: int) -> Path:
    """执行恢复任务，返回最终截图路径。"""
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
        return None

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

    rec_out = out_dir / task_id
    rec_out.mkdir(parents=True, exist_ok=True)
    traj = executor.run(task, rec_out, reset=False)

    # 取最后一张截图
    imgs = traj.history_image_path
    final_img = imgs[-1] if imgs else None
    print(f"  恢复执行完成: steps={len(traj.history_action)}")
    if final_img:
        print(f"  最终截图: {final_img}")
    return Path(final_img) if final_img else None


# ----------------------------------------------------------------- Step 5: 验证（重新检测当前状态）

def run_verify(task_id: str, run: str, task_path: Path,
               final_img: Path, iter_idx: int) -> dict:
    """用 VLM 重新检测当前状态，判断污染是否已清除。"""
    _log(f"[Step 5] Verify 重新检测状态 {task_id} (第 {iter_idx} 轮)")

    if final_img is None or not final_img.exists():
        print("  无最终截图，验证失败")
        return {"success": False, "reason": "no_screenshot", "answer": ""}

    with open(task_path, encoding="utf-8") as f:
        pset = json.load(f)
    tasks = pset.get("tasks", [])
    if not tasks:
        return {"success": False, "reason": "no_task", "answer": ""}

    question = tasks[0]["expected_end_state"]["question"]
    print(f"  检测问题: {question}")

    key = mbl_env.api_key()
    if not key:
        return {"success": False, "reason": "no_api_key", "answer": ""}

    # 用 qwen3-vl-plus 看图回答 yes/no
    import base64
    with open(final_img, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    sys_prompt = (
        "你是 GUI 状态检测器。根据截图回答用户的 yes/no 问题。"
        "只能回答 yes 或 no，不要解释。"
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            ],
        },
    ]
    answer = infer.chat_complete(
        infer.DEFAULT_BASE_URL, key, infer.DEFAULT_MODEL, messages)
    answer = answer.strip().lower()
    clean = "yes" in answer
    print(f"  VLM 回答: {answer}")
    print(f"  污染状态: {'已清除' if clean else '仍存在'}")
    return {"success": clean, "answer": answer, "question": question}


# ----------------------------------------------------------------- 主流程

def run_pipeline_one(task_id: str, run: str, csv_path: Path,
                     config_path: Path, skip_infer: bool,
                     skip_generate: bool, skip_original: bool,
                     max_iter: int) -> dict:
    """跑单个任务的完整闭环 pipeline。"""
    out_dir = PIPELINE_OUT / run
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- Step 1: 原任务（只跑一次，制造污染态）----
    if skip_original:
        traj_path = MBL_ROOT / "results" / run / task_id / "trajectory.json"
        print(f"\n[Step 1] 跳过原任务，使用已有轨迹: {traj_path}")
    else:
        traj_path = run_original_task(task_id, csv_path, config_path, out_dir)

    # ---- Step 2: 初始推断污染清单 ----
    ledger_path = run_infer(task_id, run, traj_path, out_dir,
                            skip_existing=skip_infer)

    # 检查是否有 this_task 污染
    n_this_task = _count_this_task_mutations(ledger_path)
    has_contamination = n_this_task > 0
    print(f"\n  初始检测: this_task 污染 {n_this_task} 条")

    # 无 this_task 污染 → 无需恢复，直接成功
    if not has_contamination:
        pipeline_result = {
            "task_id": task_id,
            "run": run,
            "trajectory": str(traj_path),
            "ledger": str(ledger_path),
            "recovery_task": None,
            "has_contamination": False,
            "iterations": 0,
            "success": True,
            "first_try_success": True,
            "final_state": "clean",
            "failure_reason": None,
            "per_iteration": [],
        }
        result_path = out_dir / f"{task_id}_pipeline.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(pipeline_result, f, ensure_ascii=False, indent=2)
        print(f"\n  无 this_task 污染，无需恢复 → 成功")
        print(f"  Pipeline 结果保存: {result_path}")
        return pipeline_result

    # ---- 闭环循环：生成 → 执行 → 检测 ----
    per_iteration = []
    success = False
    first_try_success = False
    final_state = "contaminated"
    failure_reason = None
    task_path = None

    for i in range(1, max_iter + 1):
        iter_info = {"iter": i}

        # Step 3: 生成恢复任务（每轮重新生成，LLM 可能给出不同方案）
        try:
            task_path = run_generate(task_id, run, ledger_path,
                                     skip_existing=skip_generate and i == 1)
            iter_info["generate_ok"] = True
            iter_info["recovery_task"] = str(task_path)
        except Exception as e:
            iter_info["generate_ok"] = False
            iter_info["error"] = str(e)
            per_iteration.append(iter_info)
            failure_reason = f"generate_error: {e}"
            print(f"  ✗ 第 {i} 轮生成失败: {e}")
            break

        # Step 4: 执行恢复
        try:
            final_img = run_recovery(task_id, run, task_path, csv_path,
                                     config_path, out_dir, i)
            iter_info["execute_ok"] = final_img is not None
            iter_info["final_screenshot"] = str(final_img) if final_img else None
        except Exception as e:
            iter_info["execute_ok"] = False
            iter_info["error"] = str(e)
            per_iteration.append(iter_info)
            failure_reason = f"execute_error: {e}"
            print(f"  ✗ 第 {i} 轮执行失败: {e}")
            break

        # Step 5: 重新检测当前状态
        try:
            verify = run_verify(task_id, run, task_path, final_img, i)
            iter_info["verify"] = verify
            if verify["success"]:
                success = True
                final_state = "clean"
                if i == 1:
                    first_try_success = True
                per_iteration.append(iter_info)
                print(f"\n  ✓ 第 {i} 轮恢复成功！")
                break
        except Exception as e:
            iter_info["verify"] = {"success": False, "reason": str(e), "answer": ""}
            per_iteration.append(iter_info)
            failure_reason = f"verify_error: {e}"
            print(f"  ✗ 第 {i} 轮验证出错: {e}")
            break

        per_iteration.append(iter_info)
        print(f"\n  第 {i} 轮恢复未成功，进入下一轮...")

    if not success and failure_reason is None:
        failure_reason = f"max_iter_exceeded ({max_iter})"
        final_state = "contaminated"

    iterations = len(per_iteration)
    pipeline_result = {
        "task_id": task_id,
        "run": run,
        "trajectory": str(traj_path),
        "ledger": str(ledger_path),
        "recovery_task": str(task_path) if task_path else None,
        "has_contamination": True,
        "iterations": iterations,
        "success": success,
        "first_try_success": first_try_success,
        "final_state": final_state,
        "failure_reason": failure_reason,
        "per_iteration": per_iteration,
    }
    result_path = out_dir / f"{task_id}_pipeline.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(pipeline_result, f, ensure_ascii=False, indent=2)
    print(f"\n  Pipeline 结果保存: {result_path}")
    return pipeline_result


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
    ap.add_argument("--run", default=DEFAULT_RUN)
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
    args = ap.parse_args()

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
                args.max_iter)
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

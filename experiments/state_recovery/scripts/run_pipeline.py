#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_pipeline.py —— 端到端 pipeline 演示脚本。

完整流程：
  1. 跑原任务制造污染态（MobileBench 执行原 goal）
  2. Audit 推断污染清单（infer_mutations.py）
  3. Planner 生成恢复任务（generate_tasks.py）
  4. Execute 执行恢复（复用 MobileBench executor，goal=recovery_goal）
  5. Verify 验证恢复效果（VLM 回答 expected_end_state.question）

单任务用法：
  mobile\\Scripts\\python.exe run_pipeline.py --task qq_10

全量用法：
  mobile\\Scripts\\python.exe run_pipeline.py --all

跳过已有结果的步骤（如已有 ledger/task，只跑执行+验证）：
  mobile\\Scripts\\python.exe run_pipeline.py --task qq_10 --skip-infer --skip-generate
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
# 编码
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

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
              out_dir: Path) -> Path:
    """推断污染清单，返回 ledger.json 路径。"""
    _log(f"[Step 2] Audit 推断污染清单 {task_id}")

    ledger_dir = LEDGER_ROOT / run
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / f"{task_id}_ledger.json"

    if ledger_path.exists():
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

def run_generate(task_id: str, run: str, ledger_path: Path) -> Path:
    """生成恢复任务，返回 tasks.json 路径。"""
    _log(f"[Step 3] Planner 生成恢复任务 {task_id}")

    task_dir = TASK_ROOT / run
    task_dir.mkdir(parents=True, exist_ok=True)
    task_path = task_dir / f"{task_id}_tasks.json"

    if task_path.exists():
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
                 out_dir: Path) -> Path:
    """执行恢复任务，返回最终截图路径。"""
    from mobilebench.utils.task_executor import (
        DeviceManager, AgentFactory, TaskExecutor, load_tasks,
    )
    from configparser import ConfigParser

    _log(f"[Step 4] Execute 执行恢复任务 {task_id}")

    with open(task_path, encoding="utf-8") as f:
        pset = json.load(f)

    tasks = pset.get("tasks", [])
    if not tasks:
        print(f"  无自动恢复任务（可能全是人工挂起或空任务），跳过执行")
        return None

    # 取第一个自动恢复任务演示
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
    executor = TaskExecutor(dev_mgr, agent, time_sleep, max_steps=max_steps)

    # 构造恢复 Task
    from mobilebench.utils.task_executor import Task
    task = Task(
        identifier=f"{task_id}_recovery",
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


# ----------------------------------------------------------------- Step 5: 验证恢复

def run_verify(task_id: str, run: str, task_path: Path,
               final_img: Path) -> dict:
    """用 VLM 验证恢复效果。"""
    _log(f"[Step 5] Verify 验证恢复效果 {task_id}")

    if final_img is None or not final_img.exists():
        print("  无最终截图，跳过验证")
        return {"success": False, "reason": "no_screenshot"}

    with open(task_path, encoding="utf-8") as f:
        pset = json.load(f)
    tasks = pset.get("tasks", [])
    if not tasks:
        return {"success": False, "reason": "no_task"}

    question = tasks[0]["expected_end_state"]["question"]
    print(f"  验证问题: {question}")

    key = mbl_env.api_key()
    if not key:
        return {"success": False, "reason": "no_api_key"}

    # 用 qwen3-vl-plus 看图回答 yes/no
    import base64
    with open(final_img, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    sys_prompt = (
        "你是 GUI 恢复效果验证器。根据截图回答用户的 yes/no 问题。"
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
    success = "yes" in answer
    print(f"  VLM 回答: {answer}")
    print(f"  恢复结果: {'成功' if success else '失败'}")
    return {"success": success, "answer": answer, "question": question}


# ----------------------------------------------------------------- 主流程

def run_pipeline_one(task_id: str, run: str, csv_path: Path,
                     config_path: Path, skip_infer: bool,
                     skip_generate: bool) -> dict:
    """跑单个任务的完整 pipeline。"""
    out_dir = PIPELINE_OUT / run
    out_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: 原任务
    traj_path = run_original_task(task_id, csv_path, config_path, out_dir)

    # Step 2: 推断
    if skip_infer:
        ledger_path = LEDGER_ROOT / run / f"{task_id}_ledger.json"
        print(f"\n[Step 2] 跳过推断，使用已有 ledger: {ledger_path}")
    else:
        ledger_path = run_infer(task_id, run, traj_path, out_dir)

    # Step 3: 生成
    if skip_generate:
        task_path = TASK_ROOT / run / f"{task_id}_tasks.json"
        print(f"\n[Step 3] 跳过生成，使用已有 task: {task_path}")
    else:
        task_path = run_generate(task_id, run, ledger_path)

    # Step 4: 执行恢复
    final_img = run_recovery(task_id, run, task_path, csv_path,
                             config_path, out_dir)

    # Step 5: 验证
    result = run_verify(task_id, run, task_path, final_img)

    # 保存 pipeline 结果
    pipeline_result = {
        "task_id": task_id,
        "run": run,
        "trajectory": str(traj_path),
        "ledger": str(ledger_path),
        "recovery_task": str(task_path),
        "final_screenshot": str(final_img) if final_img else None,
        "verification": result,
    }
    result_path = out_dir / f"{task_id}_pipeline.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(pipeline_result, f, ensure_ascii=False, indent=2)
    print(f"\n  Pipeline 结果保存: {result_path}")
    return pipeline_result


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
                    help="跳过生成，使用已有 recovery task")
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

    print(f"将执行 {len(task_ids)} 个任务的 pipeline")
    results = []
    for tid in task_ids:
        try:
            r = run_pipeline_one(
                tid, args.run, args.csv, args.config,
                args.skip_infer, args.skip_generate)
            results.append(r)
        except Exception as e:  # noqa: BLE001
            print(f"\n✗ {tid} pipeline 失败: {e}")
            results.append({"task_id": tid, "error": str(e)})

    # 汇总
    success = sum(1 for r in results
                  if r.get("verification", {}).get("success"))
    total = len(results)
    print(f"\n{'='*60}")
    print(f"Pipeline 汇总: {success}/{total} 恢复成功")
    print(f"{'='*60}")

    summary_path = PIPELINE_OUT / args.run / "pipeline_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({"total": total, "success": success,
                   "results": results}, f, ensure_ascii=False, indent=2)
    print(f"汇总保存: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

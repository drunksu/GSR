#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""order_runner.py —— 顺序 / 重置条件可控的评测调度器。

它解决三件事：

1. **顺序可控**：AndroidWorld 的 ``suite_utils.create_suite()`` 结尾有一行
   ``Suite(sorted(suite.items()))``，即执行顺序**永远是任务名字典序**。
   想跑"乱序"就必须绕开它。本模块在 Suite(dict) 上重排 key，得到
   canonical / reverse / shuffle(seed) / adversarial(writer->reader) 四种顺序。
2. **重置强度可控**：AndroidWorld 每任务的清理来自
   ``TaskEval.initialize_task() -> _initialize_apps() -> app_snapshot.restore_snapshot()``
   以及 ``tear_down()``。本模块把这两处做成可开关的"clean mode"，
   用来模拟"没有 cleaner / cleaner 不彻底"的真实在线 benchmark。
3. **可复现记录**：每个 episode 落一行 JSONL（含 run_id / order / position /
   predecessor），供 analyze_order_effects.py 做配对统计。

三种 clean mode（对应论文里的三条路线）
---------------------------------------
* ``official``      —— 原样：每任务前后恢复 app 快照（≈快照/程序化重置路线）。
* ``no_reset``      —— 屏蔽 initialize 阶段的快照恢复（≈"只重启 App"/手工 cleaner 缺失）。
* ``no_teardown``   —— 屏蔽 tear_down（≈teardown 脚本不彻底）。
* ``none``          —— 两者都屏蔽（≈Mobile-Agent/Mobile-Eval 的人工恢复缺失场景）。

重要：AndroidWorld 的 ``_run_task`` 在任务抛异常时**直接 return，不调用 tear_down**
（suite_utils.py）。这本身就是一个真实的污染入口，``official`` 模式并不免疫。

用法
----
    # 1) 只看计划，不需要模拟器
    python order_runner.py --backend dryrun --out-dir ../results/plan

    # 2) 真跑（需要 android_world 已安装 + 模拟器已按官方文档启动）
    python order_runner.py --backend androidworld \
        --agents t3a_gpt4 --order-modes canonical,shuffle --order-seeds 0,1,2 \
        --clean-modes official,none --repeats 3 \
        --out-dir ../results/aw_pilot

    # 3) 校验本仓库任务目录里的 app 归属（需要 android_world）
    python order_runner.py --verify-catalog

设计约束：**不修改被测系统的任何文件**。对 android_world 的改动全部通过
运行时 monkey-patch（app_snapshot.restore_snapshot / TaskEval.tear_down）完成，
因此对纸面结果里"官方设置"的可信度没有影响。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import random
import sys
import time
from dataclasses import dataclass, asdict
from typing import Any, Iterable, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import task_catalog  # noqa: E402

ORDER_MODES = ("canonical", "reverse", "shuffle", "adversarial", "seeded_random_global")
CLEAN_MODES = ("official", "no_reset", "no_teardown", "none", "no_teardown_on_error_only")


# ==========================================================================
# 1. 顺序构造
# ==========================================================================
def order_canonical(tasks: Sequence[str]) -> list[str]:
    """AndroidWorld 的默认顺序：任务名字典序。"""
    return sorted(tasks)


def order_reverse(tasks: Sequence[str]) -> list[str]:
    return sorted(tasks, reverse=True)


def order_shuffle(tasks: Sequence[str], seed: int) -> list[str]:
    rng = random.Random(seed)
    out = list(sorted(tasks))
    rng.shuffle(out)
    return out


def order_adversarial(tasks: Sequence[str], seed: int = 0) -> list[str]:
    """对抗顺序：把"写同一状态域"的任务紧排在"读该状态域"的任务之前。

    这是把 OD 失败概率**最大化**的顺序，用来给出效应的上界，
    也用来给 polluter 归因提供强信号（pred == writer，victim == reader）。

    不变式：返回的列表**恰好是 tasks 的一个排列**（不丢任务、不重复）。
    注意：一个状态域的 writer 数量可能少于 reader 数量，此时配不上对的
    reader 会原样保留在尾部——绝不能把它们丢掉（早先版本有此 bug）。
    """
    specs = [task_catalog.select(t) for t in tasks]
    writers: dict[str, list[str]] = {}
    for s in specs:
        if s.is_writer:
            writers.setdefault(s.cluster, []).append(s.name)
    rng = random.Random(seed)
    for v in writers.values():
        rng.shuffle(v)

    out: list[str] = []
    paired: set[str] = set()
    for s in specs:
        pool = writers.get(s.cluster)
        if s.is_reader and pool:
            w = pool.pop(0)
            out.append(w)
            out.append(s.name)
            paired.add(w)
            paired.add(s.name)

    # 未被配对的（包括配不上对的 reader、没用完的 writer、以及所有非 reader）
    out.extend(sorted(s.name for s in specs if s.name not in paired))

    assert len(out) == len(tasks) and set(out) == set(tasks), (
        "order_adversarial 必须返回原任务集的一个排列"
    )
    return out


def build_order(mode: str, tasks: Sequence[str], seed: int = 0) -> list[str]:
    if mode == "canonical":
        order = order_canonical(tasks)
    elif mode == "reverse":
        order = order_reverse(tasks)
    elif mode == "shuffle":
        order = order_shuffle(tasks, seed)
    elif mode == "adversarial":
        order = order_adversarial(tasks, seed)
    elif mode == "seeded_random_global":
        # 跨 agent 的"全局随机顺序"：同一个 seed 下所有 agent 共用一种顺序，
        # 用于验证"顺序效应是否 agent 无关"（H4）。
        order = order_shuffle(tasks, 20270108)
    else:
        raise ValueError(f"未知 order mode: {mode}")
    # 全局不变式：任何顺序都必须是原任务集的一个排列
    assert len(order) == len(tasks) and set(order) == set(tasks), (
        f"order mode {mode} 破坏了任务集合（多/少任务）"
    )
    return order


# ==========================================================================
# 2. 运行计划
# ==========================================================================
@dataclass
class RunPlan:
    run_id: str
    agent: str
    order_mode: str
    order_seed: int
    clean_mode: str
    repeat: int
    tasks: list[str]
    started_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_plan(
    tasks: Sequence[str],
    agents: Sequence[str],
    order_modes: Sequence[str],
    clean_modes: Sequence[str],
    repeats: int,
    order_seeds: Sequence[int],
) -> list[RunPlan]:
    plan: list[RunPlan] = []
    for agent in agents:
        for clean_mode in clean_modes:
            for order_mode in order_modes:
                seeds = order_seeds if order_mode in ("shuffle", "adversarial") else [0]
                for seed in seeds:
                    for repeat in range(repeats):
                        rid = f"{agent}|{clean_mode}|{order_mode}|s{seed}|r{repeat}"
                        plan.append(
                            RunPlan(
                                run_id=rid,
                                agent=agent,
                                order_mode=order_mode,
                                order_seed=int(seed),
                                clean_mode=clean_mode,
                                repeat=repeat,
                                tasks=build_order(order_mode, tasks, int(seed)),
                            )
                        )
    return plan


def write_plan(plan: Sequence[RunPlan], out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "plan.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([p.to_dict() for p in plan], fh, ensure_ascii=False, indent=2)

    # 人类可读 + 可 diff 的调度表
    csv_path = os.path.join(out_dir, "schedule.csv")
    with open(csv_path, "w", encoding="utf-8") as fh:
        fh.write("run_id,agent,clean_mode,order_mode,order_seed,repeat,position,task,cluster,role,snapshot_scope\n")
        for p in plan:
            for pos, t in enumerate(p.tasks):
                spec = task_catalog.BY_NAME.get(t)
                fh.write(
                    f"{p.run_id},{p.agent},{p.clean_mode},{p.order_mode},{p.order_seed},{p.repeat},"
                    f"{pos},{t},{spec.cluster if spec else '?'},{spec.role if spec else '?'},"
                    f"{spec.snapshot_scope if spec else '?'}\n"
                )
    return path


def summarize_plan(plan: Sequence[RunPlan]) -> dict[str, Any]:
    return {
        "n_runs": len(plan),
        "n_episodes": sum(len(p.tasks) for p in plan),
        "agents": sorted({p.agent for p in plan}),
        "clean_modes": sorted({p.clean_mode for p in plan}),
        "order_modes": sorted({p.order_mode for p in plan}),
        "repeats": sorted({p.repeat for p in plan}),
        "order_seeds": sorted({p.order_seed for p in plan}),
    }


# ==========================================================================
# 3. AndroidWorld 后端
# ==========================================================================
def _apply_clean_mode(clean_mode: str):
    """返回 (undo_fn, 描述)。通过 monkey-patch 改变重置强度。"""
    import android_world.utils.app_snapshot as app_snapshot  # noqa: PLC0415
    from android_world.task_evals import task_eval as task_eval_mod  # noqa: PLC0415

    undo: list[Any] = []

    if clean_mode in ("no_reset", "none"):
        orig_restore = app_snapshot.restore_snapshot

        def _noop_restore(app_name, env, *a, **kw):
            return None

        app_snapshot.restore_snapshot = _noop_restore
        undo.append(lambda: setattr(app_snapshot, "restore_snapshot", orig_restore))

    if clean_mode in ("no_teardown", "none"):
        orig_teardown = task_eval_mod.TaskEval.tear_down

        def _noop_teardown(self, env):
            self.initialized = False
            return None

        task_eval_mod.TaskEval.tear_down = _noop_teardown
        undo.append(lambda: setattr(task_eval_mod.TaskEval, "tear_down", orig_teardown))

    if clean_mode == "no_teardown_on_error_only":
        # 只屏蔽"异常路径下的 teardown 缺失"这一真实入口：把 _run_task 的
        # except 分支补上 tear_down，观察它是否消除了顺序效应。
        import android_world.suite_utils as suite_utils  # noqa: PLC0415

        orig_run_task = suite_utils._run_task

        def _patched_run_task(task, run_episode, env, demo_mode):
            try:
                return orig_run_task(task, run_episode, env, demo_mode)
            finally:
                try:
                    if getattr(task, "initialized", False):
                        task.tear_down(env)
                except Exception:  # noqa: BLE001
                    pass

        suite_utils._run_task = _patched_run_task
        undo.append(lambda: setattr(suite_utils, "_run_task", orig_run_task))

    def undo_all():
        for fn in reversed(undo):
            fn()

    return undo_all, f"clean_mode={clean_mode}"


def _make_agent(name: str, env, model_override: str | None):
    """构造 agent。名字沿用 run.py 的约定，前后可用 '-' 追加模型名覆盖。"""
    from android_world.agents import infer, m3a, random_agent, seeact, t3a  # noqa: PLC0415

    base, _, model = name.partition(":")
    model = model or model_override
    if base == "random_agent":
        return random_agent.RandomAgent(env)
    if base == "t3a_gpt4":
        return t3a.T3A(env, infer.Gpt4Wrapper(model or "gpt-4o"))
    if base == "m3a_gpt4v":
        return m3a.M3A(env, infer.Gpt4Wrapper(model or "gpt-4o"))
    if base == "t3a_gemini_gcp":
        return t3a.T3A(env, infer.GeminiGcpWrapper(model_name=model or "gemini-2.5-pro"))
    if base == "m3a_gemini_gcp":
        return m3a.M3A(env, infer.GeminiGcpWrapper(model_name=model or "gemini-2.5-pro"))
    if base == "seeact":
        return seeact.SeeAct(env)
    raise ValueError(
        f"未知 agent {base!r}。内置：random_agent/t3a_gpt4/m3a_gpt4v/t3a_gemini_gcp/"
        "m3a_gemini_gcp/seeact；自定义 agent 请继承 EnvironmentInteractingAgent 并在此注册。"
    )


def run_androidworld(plan: Sequence[RunPlan], args) -> str:
    """在已启动的模拟器上按 plan 执行，写出 episodes.jsonl。"""
    try:
        from android_world import registry, suite_utils  # noqa: PLC0415
        from android_world.env import env_launcher  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            "无法 import android_world："
            f"{exc}\n请先 git clone https://github.com/google-research/android_world 并 pip install，"
            "或用 --backend dryrun 只生成计划。"
        )

    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    jsonl_path = os.path.join(out_dir, "episodes.jsonl")

    env = env_launcher.load_and_setup_env(
        console_port=args.console_port,
        emulator_setup=False,
        adb_path=args.adb_path,
    )

    task_registry = registry.TaskRegistry().get_registry(
        family=registry.TaskRegistry.ANDROID_WORLD_FAMILY
    )

    with open(jsonl_path, "a", encoding="utf-8") as fh:
        for run in plan:
            undo, desc = _apply_clean_mode(run.clean_mode)
            try:
                suite = suite_utils.create_suite(
                    task_registry,
                    n_task_combinations=1,
                    seed=args.task_random_seed,
                    tasks=list(run.tasks),
                    env=env,
                )
                # ---- 关键：绕开 create_suite 的 sorted()，按 plan 的顺序重排 ----
                ordered = suite_utils.Suite()
                for name in run.tasks:
                    if name in suite:
                        ordered[name] = suite[name]
                ordered.suite_family = "android_world"

                agent = _make_agent(run.agent, env, args.model_override)
                agent.name = run.agent

                print(f"[order_runner] run={run.run_id} {desc}")
                print("[order_runner] order: " + " -> ".join(run.tasks))

                results = suite_utils.run(
                    ordered,
                    agent,
                    checkpointer=suite_utils.checkpointer_lib.NullCheckpointer(),  # type: ignore[attr-defined]
                    demo_mode=False,
                    return_full_episode_data=True,
                )
            finally:
                undo()

            for pos, ep in enumerate(results):
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
                            "task": ep.get("task_template"),
                            "goal": ep.get("goal"),
                            "success": float(ep.get("is_successful") or 0.0),
                            "exception": ep.get("exception_info") is not None,
                            "episode_length": ep.get("episode_length"),
                            "run_time_s": ep.get("run_time"),
                            "seed": ep.get("seed"),
                            "ts": _dt.datetime.now().isoformat(timespec="seconds"),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            fh.flush()

    env.close()
    return jsonl_path


# ==========================================================================
# 4. dry-run 后端（无模拟器也能验证调度逻辑）
# ==========================================================================
def run_dryrun(plan: Sequence[RunPlan], args) -> str:
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "dryrun_commands.ps1")
    with open(path, "w", encoding="utf-8") as fh:
        for run in plan:
            fh.write(
                "# run_id=" f"{run.run_id} clean_mode={run.clean_mode} "
                f"order={run.order_mode}(seed={run.order_seed}) repeat={run.repeat}\n"
            )
            fh.write(
                "python order_runner.py --backend androidworld "
                f"--agents {run.agent} --tasks {','.join(run.tasks)} "
                f"--order-modes {run.order_mode} --order-seeds {run.order_seed} "
                f"--clean-modes {run.clean_mode} --repeats 1 "
                f"--out-dir ../results/{run.agent}\n"
            )
    return path


def verify_catalog(args) -> int:
    try:
        from android_world import registry  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        print(f"跳过校验（无 android_world）：{exc}")
        return 2
    reg = registry.TaskRegistry().get_registry(family=registry.TaskRegistry.ANDROID_WORLD_FAMILY)
    bad = 0
    for spec in task_catalog.CATALOG:
        if spec.name not in reg:
            print(f"[MISSING] {spec.name} 不在 registry 中")
            bad += 1
            continue
        cls = reg[spec.name]
        try:
            apps = tuple(cls.app_names.fget(cls))  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            apps = getattr(cls, "app_names", ())
        if tuple(sorted(apps)) != tuple(sorted(spec.apps)):
            print(f"[APP-DIFF] {spec.name}: 目录={spec.apps} registry={tuple(apps)}")
            bad += 1
    print(f"校验结束：{len(task_catalog.CATALOG)} 个任务，{bad} 处不一致。")
    return 1 if bad else 0


# ==========================================================================
# CLI
# ==========================================================================
def _load_tasks(args) -> list[str]:
    if args.tasks_file:
        if args.tasks_file.endswith(".json"):
            with open(args.tasks_file, encoding="utf-8") as fh:
                return list(json.load(fh))
        with open(args.tasks_file, encoding="utf-8") as fh:
            return [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    if args.tasks:
        return [t.strip() for t in args.tasks.split(",") if t.strip()]
    return [t.name for t in task_catalog.CATALOG]


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="顺序/重置条件可控的 GUI agent 评测调度器")
    ap.add_argument("--backend", choices=("dryrun", "androidworld"), default="dryrun")
    ap.add_argument("--out-dir", default=os.path.join(os.path.dirname(__file__), "..", "results", "plan"))
    ap.add_argument("--tasks", default=None, help="逗号分隔的任务名；默认用 task_catalog 全部")
    ap.add_argument("--tasks-file", default=None, help="任务清单文件（txt 一行一个 / json 数组）")
    ap.add_argument("--agents", default="t3a_gpt4", help="逗号分隔；支持 name:model 覆盖模型")
    ap.add_argument("--model-override", default=None)
    ap.add_argument("--order-modes", default="canonical,shuffle,adversarial")
    ap.add_argument("--clean-modes", default="official,none")
    ap.add_argument("--order-seeds", default="0,1,2")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--task-random-seed", type=int, default=30)
    ap.add_argument("--console-port", type=int, default=5554)
    ap.add_argument("--adb-path", default=None)
    ap.add_argument("--verify-catalog", action="store_true")
    args = ap.parse_args(argv)

    if args.verify_catalog:
        return verify_catalog(args)

    tasks = _load_tasks(args)
    unknown = [t for t in tasks if t not in task_catalog.BY_NAME]
    if unknown:
        print(f"[warn] 以下任务不在本仓库目录中，将按 'unknown' 处理：{unknown}")

    plan = build_plan(
        tasks=tasks,
        agents=[a.strip() for a in args.agents.split(",") if a.strip()],
        order_modes=[m.strip() for m in args.order_modes.split(",") if m.strip()],
        clean_modes=[m.strip() for m in args.clean_modes.split(",") if m.strip()],
        repeats=args.repeats,
        order_seeds=[int(s) for s in args.order_seeds.split(",") if s.strip()],
    )

    t0 = time.time()
    plan_path = write_plan(plan, args.out_dir)
    summary = summarize_plan(plan)
    with open(os.path.join(args.out_dir, "plan_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"plan -> {plan_path}")

    if args.backend == "dryrun":
        print(f"commands -> {run_dryrun(plan, args)}")
        print(f"耗时 {time.time() - t0:.2f}s（dry-run，未接触设备）")
        return 0

    jsonl = run_androidworld(plan, args)
    print(f"episodes -> {jsonl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mbl_apply_api_patch.py —— 让 MobileBench-OL 能安全地走"托管 API"路线。

背景（都是读源码确认过的）
--------------------------
`mobilebench/models/execute.py` 和 `mobilebench/models/llm_core_qwen2_5vl.py`
里各有一份 OpenAI 客户端封装，都有三个"只适合自建 vLLM"的硬编码：

  ① ``api_key="123456"``                      → 托管 API 会 401
  ② ``self.model = models.list().data[0].id`` → 托管 API 会**选错模型**
                                                （而且百炼兼容模式未必有 /v1/models）
  ③ ``except Exception: print(e)``            → 接口失败被静默吞掉，
                                                最终表现成"任务失败"，
                                                会被误判成**顺序效应**

本脚本做 4 件事（幂等、带备份、可回滚）：
  1. 写入 ``mobilebench/utils/mbl_api_shim.py``（错误日志 + 可选重试）
  2. ``api_key`` 从环境变量 ``MBL_API_KEY`` 读（缺省回落到原值）
  3. 模型名从环境变量 ``MBL_MODEL`` 读；**设了就不再调用 /v1/models**（短路）
  4. ``except`` 里记录失败到 ``MBL_API_LOG`` 指定的 JSONL
  5. （`--with-retry`）把 wrapper 的调用点换成 `call_with_retry(...)`，
     因为原代码里 ``max_retry`` 存了但**从未使用**，一次网络抖动就丢一步

用法
----
    python mbl_apply_api_patch.py --repo <repo> --check      # 只看会改什么
    python mbl_apply_api_patch.py --repo <repo>              # 应用
    python mbl_apply_api_patch.py --repo <repo> --with-retry # 应用并加重试
    python mbl_apply_api_patch.py --repo <repo> --revert     # 回滚
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

MARK = "MBL API patch"

SHIM = '''# -*- coding: utf-8 -*-
"""MBL API patch 的共享工具：错误日志 + 重试。

为什么需要错误日志：原代码在 OpenAI 调用失败时只 print 一下就返回 None，
上层会把这次 step 变成 'invalid' action 静默跳过 —— 于是**接口抖动会被
误判成顺序效应**，直接污染 OD flaky 实验的观测量。这里把每次失败记到
环境变量 MBL_API_LOG 指定的 JSONL，事后可按 episode 对齐、剔除或分层。
"""

from __future__ import annotations

import json
import os
import threading
import time

_LOCK = threading.Lock()


def log_api_error(model, err, extra=None):
    path = os.environ.get("MBL_API_LOG", "").strip()
    if not path:
        return
    rec = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model,
        "error": str(err)[:800],
    }
    if extra:
        rec.update(extra)
    try:
        with _LOCK:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\\n")
    except Exception:  # noqa: BLE001  日志失败绝不能影响评测
        pass


def call_with_retry(client, messages, retries=None, backoff=2.0, **kwargs):
    """重试封装：原代码的 max_retry 从未被使用。"""
    if retries is None:
        retries = int(os.environ.get("MBL_API_RETRIES", "2"))
    last = None
    for attempt in range(retries + 1):
        out = client.call(messages, **kwargs)
        if out:
            return out
        last = attempt
        if attempt < retries:
            time.sleep(backoff * (attempt + 1))
    log_api_error(getattr(client, "model", "?"), f"all {retries + 1} attempts returned empty",
                  {"stage": "call_with_retry"})
    return None


def to_pixels(x, y, width, height):
    """坐标约定换算。

    ``MBL_COORD`` 取值：
      ``pixel``（默认）—— 模型输出绝对像素，原样返回（UI-TARS-1.5 的原生约定）
      ``norm``        —— 模型输出 0-1000 归一化，按真实宽高换算成像素
                          （qwen3-vl-plus 实测就是这个约定）

    实测依据：给模型一张 1080x2400 的图、右下角像素 (920,2110) 处放蓝色按钮，
    qwen3-vl-plus 回答 ``851 879`` —— 与归一化中心 (852,879) 只差 1 像素，
    与像素中心差 1233 像素。若不做换算，所有点击都会落进左上角。
    """
    mode = os.environ.get("MBL_COORD", "pixel").strip().lower()
    if mode == "norm":
        return int(round(x / 1000.0 * width)), int(round(y / 1000.0 * height))
    return int(x), int(y)


# ---------------------------------------------------------------------------
# 日志增强：每步时间戳 / API 延迟 / token 用量
# 原版 trajectory.json 里没有时间和成本信息，导致"超时失败"与"污染失败"无法区分。
# ---------------------------------------------------------------------------

_CTX = {"dir": None, "step": None}


def set_step_context(task_dir, step):
    """在 agent.step() 开头调用，记录当前任务目录与步号。"""
    _CTX["dir"] = task_dir
    _CTX["step"] = step
    if task_dir:
        try:
            with open(os.path.join(task_dir, "step_timing.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"step": step, "start_ts": time.time()}) + "\\n")
        except Exception:  # noqa: BLE001
            pass


def now():
    return time.time()


def record_call(model, t0, usage=None, error=None):
    """记录一次 API 调用的延迟与 token 用量，写到当前任务的 api_metrics.jsonl。"""
    rec = {"ts": time.time(), "step": _CTX.get("step"), "model": model,
           "latency_s": round(time.time() - t0, 2)}
    if usage is not None:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            val = getattr(usage, key, None)
            if val is None and isinstance(usage, dict):
                val = usage.get(key)
            if val is not None:
                rec[key] = val
    if error:
        rec["error"] = str(error)[:400]
    task_dir = _CTX.get("dir")
    if not task_dir:
        return
    try:
        with open(os.path.join(task_dir, "api_metrics.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\\n")
    except Exception:  # noqa: BLE001
        pass
'''

# (相对路径, 说明, [(old, new), ...], 是否属于 --with-retry)
SPECS: list[tuple[str, str, list[tuple[str, str]], bool]] = [
    (
        "mobilebench/models/execute.py",
        "uitars_1_5 / uitars 用的 OpenAI 客户端",
        [
            (
                "from openai import OpenAI\n",
                "from openai import OpenAI\nimport os as _mbl_os  "
                f"# {MARK}: 读 MBL_API_KEY / MBL_MODEL\n",
            ),
            (
                '        openai_api_key = api_key\n',
                f'        openai_api_key = _mbl_os.environ.get("MBL_API_KEY", api_key) or api_key  # {MARK}\n',
            ),
            (
                "        models = self.client.models.list()\n        self.model = models.data[0].id\n",
                f'        # {MARK}: 显式模型名优先；设了就不调 /v1/models（托管 API 未必有该接口）\n'
                '        _mbl_model = _mbl_os.environ.get("MBL_MODEL", "").strip()\n'
                "        if _mbl_model:\n"
                "            self.model = _mbl_model\n"
                "        else:\n"
                "            self.model = self.client.models.list().data[0].id\n",
            ),
            (
                "            return result.choices[0].message.content\n"
                "        except Exception as e:\n"
                "            print(e)\n",
                "            return result.choices[0].message.content\n"
                "        except Exception as e:\n"
                "            print(e)\n"
                f"            from mobilebench.utils.mbl_api_shim import log_api_error as _mbl_log  # {MARK}\n"
                '            _mbl_log(getattr(self, "model", "?"), e)\n',
            ),
        ],
        False,
    ),
    (
        "mobilebench/models/llm_core_qwen2_5vl.py",
        "qwen2_5vl 用的 OpenAI 客户端（自带一份实现）",
        [
            (
                "from openai import OpenAI\n",
                "from openai import OpenAI\nimport os as _mbl_os  "
                f"# {MARK}: 读 MBL_API_KEY / MBL_MODEL\n",
            ),
            (
                "            api_key=api_key,\n            base_url=url,\n",
                f'            api_key=_mbl_os.environ.get("MBL_API_KEY", api_key) or api_key,  # {MARK}\n'
                "            base_url=url,\n",
            ),
            (
                "        models = self.client.models.list()\n        self.model = models.data[0].id\n",
                f'        # {MARK}: 显式模型名优先；设了就不调 /v1/models（托管 API 未必有该接口）\n'
                '        _mbl_model = _mbl_os.environ.get("MBL_MODEL", "").strip()\n'
                "        if _mbl_model:\n"
                "            self.model = _mbl_model\n"
                "        else:\n"
                "            self.model = self.client.models.list().data[0].id\n",
            ),
            (
                "            return result.choices[0].message.content\n"
                "        except Exception as e:\n"
                "            print(e)\n",
                "            return result.choices[0].message.content\n"
                "        except Exception as e:\n"
                "            print(e)\n"
                f"            from mobilebench.utils.mbl_api_shim import log_api_error as _mbl_log  # {MARK}\n"
                '            _mbl_log(getattr(self, "model", "?"), e)\n',
            ),
        ],
        False,
    ),
]

# --with-retry：wrapper 的调用点（原代码 max_retry 形同虚设）
RETRY_SPECS: list[tuple[str, str, list[tuple[str, str]], bool]] = [
    (
        "mobilebench/models/llm_core_uitars_1_5.py",
        "UI-TARS-1.5 wrapper 调用点",
        [
            (
                "        response = self.client.call(req_messages, temparature=0, max_tokens=512, top_p=0.9)\n",
                f"        from mobilebench.utils.mbl_api_shim import call_with_retry as _mbl_retry  # {MARK}\n"
                "        response = _mbl_retry(self.client, req_messages, "
                f"temparature=0, max_tokens=512, top_p=0.9)  # {MARK}\n",
            )
        ],
        True,
    ),
    (
        "mobilebench/models/llm_core_qwen2_5vl.py",
        "Qwen2.5-VL wrapper 调用点",
        [
            (
                "        response = self.client.call(req_messages, temparature=0, max_tokens=512, top_p=0.9)\n",
                f"        from mobilebench.utils.mbl_api_shim import call_with_retry as _mbl_retry  # {MARK}\n"
                "        response = _mbl_retry(self.client, req_messages, "
                f"temparature=0, max_tokens=512, top_p=0.9)  # {MARK}\n",
            )
        ],
        True,
    ),
]


# --coord-norm：qwen3-vl-plus 实测输出 0-1000 归一化坐标，而仓库代码当像素用。
# 不修的话所有点击都会落进左上角，实验"全部失败"且看不出原因。
COORD_SPECS: list[tuple[str, str, list[tuple[str, str]], bool]] = [
    (
        "mobilebench/models/llm_core_qwen2_5vl.py",
        "坐标约定换算 + 用真实分辨率",
        [
            (
                f"import os as _mbl_os  # {MARK}: 读 MBL_API_KEY / MBL_MODEL\n",
                f"import os as _mbl_os  # {MARK}: 读 MBL_API_KEY / MBL_MODEL\n"
                f"from mobilebench.utils.mbl_api_shim import to_pixels as _mbl_to_pixels  # {MARK}\n",
            ),
            (
                "                x, y = action_parser_tool.extract_xy_from_point(extracted_action)\n",
                "                x, y = action_parser_tool.extract_xy_from_point(extracted_action)\n"
                f"                x, y = _mbl_to_pixels(x, y, width, height)  # {MARK}: 坐标约定换算\n",
            ),
            (
                "                x, y, dir = action_parser_tool.extract_swipe_point_direction(extracted_action)\n",
                "                x, y, dir = action_parser_tool.extract_swipe_point_direction(extracted_action)\n"
                f"                x, y = _mbl_to_pixels(x, y, width, height)  # {MARK}: 坐标约定换算\n",
            ),
            (
                "        output = self.message_handler.process_response(response, 1080, 2400)\n",
                f"        # {MARK}: 原代码把屏幕尺寸写死 1080x2400，换成真实截图尺寸\n"
                "        _mbl_w, _mbl_h = Image.open(current_image_path).size\n"
                "        output = self.message_handler.process_response(response, _mbl_w, _mbl_h)\n",
            ),
        ],
        True,
    ),
]


# --task-file-env：让 run.py 能通过环境变量指定任务集。
# 这是"顺序实验"的前提：run.py 只认 get_task_file(subset) 的 5 个内置值，
# 没有任何 subset 指向 *-reset.csv 或自定义 CSV。
TASKFILE_SPECS: list[tuple[str, str, list[tuple[str, str]], bool]] = [
    (
        "run.py",
        "允许用 MBL_TASK_FILE 指定任务集（从而控制执行顺序）",
        [
            (
                'def get_task_file(subset):\n    if subset == "base":\n',
                f"def get_task_file(subset):\n"
                f'    import os as _mbl_os  # {MARK}\n'
                f'    _mbl_tf = _mbl_os.environ.get("MBL_TASK_FILE", "").strip()  # {MARK}\n'
                f"    if _mbl_tf:\n"
                f"        return _mbl_tf\n"
                f'    if subset == "base":\n',
            )
        ],
        True,
    ),
]


# 屏幕尺寸也要修：adb_executor 的滑动分支写死 1080x2400。
# 实测设备是 1220x2712，写死会导致滑动起点/距离按错误尺寸计算。
SCREEN_SPECS: list[tuple[str, str, list[tuple[str, str]], bool]] = [
    (
        "mobilebench/utils/adb_executor.py",
        "滑动用真实屏幕尺寸（原代码写死 1080x2400）",
        [
            (
                '            params = action.get("params", {})\n'
                '            direction = params.get("direction")\n'
                "            screen_height = 2400\n"
                "            screen_width = 1080\n",
                '            params = action.get("params", {})\n'
                '            direction = params.get("direction")\n'
                f"            try:  # {MARK}: 原代码写死 1080x2400，实测设备是 1220x2712\n"
                "                screen_width, screen_height = env.window_size()\n"
                "            except Exception:\n"
                "                screen_height, screen_width = 2400, 1080\n",
            )
        ],
        True,
    ),
]


# --metrics：记录每步时间戳 / API 延迟 / token 用量。
# 原版 trajectory.json 完全没有时间与成本信息，无法区分"超时失败"与"污染失败"。
METRICS_SPECS: list[tuple[str, str, list[tuple[str, str]], bool]] = [
    (
        "mobilebench/models/execute.py",
        "记录 API 延迟与 token（uitars）",
        [
            (
                f"import os as _mbl_os  # {MARK}: 读 MBL_API_KEY / MBL_MODEL\n",
                f"import os as _mbl_os  # {MARK}: 读 MBL_API_KEY / MBL_MODEL\n"
                f"from mobilebench.utils.mbl_api_shim import now as _mbl_now, record_call as _mbl_rec  # {MARK}\n",
            ),
            (
                "        try:\n            if top_p is not None:\n",
                f"        _mbl_t0 = _mbl_now()  # {MARK}: 计时开始\n"
                "        try:\n            if top_p is not None:\n",
            ),
            (
                "            return result.choices[0].message.content\n",
                f"            _mbl_rec(self.model, _mbl_t0, getattr(result, 'usage', None))  # {MARK}\n"
                "            return result.choices[0].message.content\n",
            ),
            (
                '            _mbl_log(getattr(self, "model", "?"), e)\n',
                '            _mbl_log(getattr(self, "model", "?"), e)\n'
                f"            _mbl_rec(getattr(self, \"model\", \"?\"), _mbl_t0, None, error=str(e))  # {MARK}\n",
            ),
        ],
        True,
    ),
    (
        "mobilebench/models/llm_core_qwen2_5vl.py",
        "记录 API 延迟与 token（qwen）",
        [
            (
                f"import os as _mbl_os  # {MARK}: 读 MBL_API_KEY / MBL_MODEL\n",
                f"import os as _mbl_os  # {MARK}: 读 MBL_API_KEY / MBL_MODEL\n"
                f"from mobilebench.utils.mbl_api_shim import now as _mbl_now, record_call as _mbl_rec  # {MARK}\n",
            ),
            (
                "        try:\n            if top_p is not None:\n",
                f"        _mbl_t0 = _mbl_now()  # {MARK}: 计时开始\n"
                "        try:\n            if top_p is not None:\n",
            ),
            (
                "            return result.choices[0].message.content\n",
                f"            _mbl_rec(self.model, _mbl_t0, getattr(result, 'usage', None))  # {MARK}\n"
                "            return result.choices[0].message.content\n",
            ),
            (
                '            _mbl_log(getattr(self, "model", "?"), e)\n',
                '            _mbl_log(getattr(self, "model", "?"), e)\n'
                f"            _mbl_rec(getattr(self, \"model\", \"?\"), _mbl_t0, None, error=str(e))  # {MARK}\n",
            ),
        ],
        True,
    ),
    (
        "mobilebench/utils/agent.py",
        "每步开头写入时间戳（供适配器算每步耗时）",
        [
            (
                '    def step(self, goal: str, path="screenshot/"):\n',
                '    def step(self, goal: str, path="screenshot/"):\n'
                f"        from mobilebench.utils.mbl_api_shim import set_step_context as _mbl_ctx  # {MARK}\n"
                f"        _mbl_ctx(path, len(self.history_image_path) + 1)  # {MARK}\n",
            )
        ],
        True,
    ),
]


# --resilient：让"一次接口/ADB 抖动"不再杀死整个长跑。
# 实测事故：2026-09-20 04:03 接口断连 → 重试耗尽 → 异常一路抛出 →
# run_with_reconnect 的重连是死代码、try_execute_task_with_retry 的 try 被注释掉
# → 整个 run.py 进程死亡，310 个任务跑到第 25 个就停了。
# 补法：把两处调用点包上 try/except；失败则不算完成（不写入 result_list.txt），
# 下次用同一条命令续跑时会自动重试该任务。
RESILIENT_SPECS: list[tuple[str, str, list[tuple[str, str]], bool]] = [
    (
        "run.py",
        "抗抖动：任务抛异常时跳过而不是整轮崩溃（正常分支）",
        [
            (
                "                    traj = try_execute_task_with_retry(task, BASE_DIR, executor, dev_mgr, CONNECT_RETRY, FAIL_RETRY, reset)\n"
                "                    if traj is not None:\n",
                f"                    try:  # {MARK}: 抗抖动\n"
                "                        traj = try_execute_task_with_retry(task, BASE_DIR, executor, dev_mgr, CONNECT_RETRY, FAIL_RETRY, reset)\n"
                "                    except Exception as _mbl_e:\n"
                f'                        print(f"[MBL] {{task.identifier}} 抛异常，跳过以便续跑重试: {{_mbl_e}}")  # {MARK}\n'
                "                        traj = None\n"
                "                    if traj is not None:\n",
            )
        ],
        True,
    ),
    (
        "run.py",
        "抗抖动：任务抛异常时跳过而不是整轮崩溃（噪声分支）",
        [
            (
                "                        traj = try_execute_task_with_retry(task, BASE_DIR, executor, dev_mgr, CONNECT_RETRY, FAIL_RETRY, reset)\n"
                "                        # 下面是存traj.json\n",
                f"                        try:  # {MARK}: 抗抖动\n"
                "                            traj = try_execute_task_with_retry(task, BASE_DIR, executor, dev_mgr, CONNECT_RETRY, FAIL_RETRY, reset)\n"
                "                        except Exception as _mbl_e:\n"
                f'                            print(f"[MBL] {{task.identifier}} 抛异常，跳过以便续跑重试: {{_mbl_e}}")  # {MARK}\n'
                "                            traj = None\n"
                "                        # 下面是存traj.json\n",
            )
        ],
        True,
    ),
]


def apply_spec(path: str, label: str, repls, check_only: bool) -> tuple[int, list[str]]:
    if not os.path.exists(path):
        return 0, [f"跳过（文件不存在）: {path}"]
    src = open(path, encoding="utf-8").read()

    out = src
    notes: list[str] = []
    changed = 0
    skipped = 0
    for old, new in repls:
        # 幂等性必须**逐处**判断：同一个文件可能被两组 spec 命中
        # （例如 llm_core_qwen2_5vl.py 既在 SPECS 又在 RETRY_SPECS）。
        # 另：当 new 以 old 开头（纯插入）时，只比较"本次新增的片段"——
        # 否则两条 spec 锚在同一行导入上时，会互相把对方的新增当成"未应用"而重复插入。
        probe = new[len(old):] if new.startswith(old) else new
        if probe.strip() and probe in out:
            skipped += 1
            continue
        n = out.count(old)
        if n != 1:
            notes.append(f"⚠️  锚点命中 {n} 次（期望 1），已跳过该处: {old.splitlines()[0][:60]!r}")
            continue
        out = out.replace(old, new, 1)
        changed += 1

    if skipped and not changed:
        return 0, [f"已全部打过补丁，无需改动（{label}）"]
    if check_only:
        notes.append(f"将修改 {changed}/{len(repls)} 处（{label}）")
        return changed, notes

    shutil.copy2(path, path + ".bak")
    open(path, "w", encoding="utf-8").write(out)
    suffix = f"，另 {skipped} 处此前已打过" if skipped else ""
    notes.append(f"已写入 {changed}/{len(repls)} 处{suffix}，备份 {os.path.basename(path)}.bak（{label}）")
    return changed, notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--with-retry", action="store_true")
    ap.add_argument("--coord-norm", action="store_true",
                    help="坐标归一化->像素换算 + 分辨率修正（qwen3-vl-plus + 非 1080x2400 实测需要）")
    ap.add_argument("--task-file-env", action="store_true",
                    help="让 run.py 支持用 MBL_TASK_FILE 指定任务集（顺序实验的前提）")
    ap.add_argument("--metrics", action="store_true",
                    help="记录每步时间戳 / API 延迟 / token 用量")
    ap.add_argument("--resilient", action="store_true",
                    help="抗抖动：任务抛异常时跳过而不是让整轮崩溃（长跑必开）")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(os.path.join(repo, "mobilebench")):
        print(f"❌ {repo} 看起来不是 mobilebench-ol 仓库根目录")
        return 2

    if args.revert:
        n = 0
        for rel, *_ in (SPECS + RETRY_SPECS + COORD_SPECS + TASKFILE_SPECS
                        + SCREEN_SPECS + METRICS_SPECS + RESILIENT_SPECS):
            bak = os.path.join(repo, rel) + ".bak"
            if os.path.exists(bak):
                shutil.move(bak, os.path.join(repo, rel))
                print(f"已回滚 {rel}")
                n += 1
        print(f"回滚 {n} 个文件。")
        return 0

    specs = list(SPECS)
    if args.with_retry:
        specs += RETRY_SPECS
    if args.coord_norm:
        specs += COORD_SPECS + SCREEN_SPECS
    if args.task_file_env:
        specs += TASKFILE_SPECS
    if args.metrics:
        specs += METRICS_SPECS
    if args.resilient:
        specs += RESILIENT_SPECS
    total = 0
    print(f"{'[检查模式] ' if args.check else ''}仓库: {repo}\n")
    for rel, label, repls, _ in specs:
        changed, notes = apply_spec(os.path.join(repo, rel), label, repls, args.check)
        total += changed
        print(f"- {rel}")
        for note in notes:
            print(f"    {note}")

    # shim 模块：内容不一致就更新（否则新加的函数不会生效）
    shim_path = os.path.join(repo, "mobilebench", "utils", "mbl_api_shim.py")
    if not args.check:
        import re as _re
        # 从 SHIM 源码里自动推导需要存在的函数，避免以后加函数又忘了改检查表
        required = _re.findall(r"^def (\w+)", SHIM, _re.M)
        cur = open(shim_path, encoding="utf-8").read() if os.path.exists(shim_path) else None
        missing = [fn for fn in required if cur is None or f"def {fn}" not in cur]
        if cur is None:
            os.makedirs(os.path.dirname(shim_path), exist_ok=True)
            open(shim_path, "w", encoding="utf-8").write(SHIM)
            print(f"- mobilebench/utils/mbl_api_shim.py 已创建（{', '.join(required)}）")
        elif missing:
            shutil.copy2(shim_path, shim_path + ".bak")
            open(shim_path, "w", encoding="utf-8").write(SHIM)
            print(f"- mobilebench/utils/mbl_api_shim.py 已更新（补上 {', '.join(missing)}），"
                  f"旧文件备份为 mbl_api_shim.py.bak")
        else:
            print(f"- mobilebench/utils/mbl_api_shim.py 已是最新（{len(required)} 个函数齐备），跳过")
    else:
        print(f"- mobilebench/utils/mbl_api_shim.py {'已存在' if os.path.exists(shim_path) else '将创建'}")

    print(f"\n合计修改 {total} 处。")
    if not args.check:
        print("\n使用方式：")
        print('  set MBL_API_KEY=sk-xxxx')
        print('  set MBL_MODEL=qwen3-vl-plus')
        print('  set MBL_API_LOG=results/api_errors.jsonl')
        if args.coord_norm:
            print('  set MBL_COORD=norm      # qwen3-vl-plus 输出 0-1000 归一化坐标，必须设')
        else:
            print('  # 若模型输出 0-1000 归一化坐标（qwen3-vl-plus 实测如此），'
                  '需用 --coord-norm 重跑本脚本')
        if args.with_retry:
            print('  set MBL_API_RETRIES=2')
        print('  python run.py --mode interact --config config/interact_qwen2_5vl_base.conf \\')
        print('      --subset base --output results/api_smoke')
    else:
        print("（检查模式未改动任何文件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

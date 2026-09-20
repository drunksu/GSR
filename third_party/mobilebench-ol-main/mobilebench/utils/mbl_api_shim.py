# -*- coding: utf-8 -*-
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
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
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
                fh.write(json.dumps({"step": step, "start_ts": time.time()}) + "\n")
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
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass

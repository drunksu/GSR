#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mbl_api_probe.py —— 只用 Python 标准库探测 OpenAI 兼容端点。

为什么单独写一个：`mbl_api_smoketest.py` 需要 openai / pillow / numpy / 仓库模块，
而你手上可能还没装。这个脚本 **零依赖**，能在装任何东西之前回答三个问题：

  1. key 有效吗？端点通吗？           → --models / --chat
  2. 到底有哪些模型可用？             → --models（若支持）或 --scan（逐个试探）
  3. 这个端点能不能吃下"1 张图 / 10 张图 + 长 prompt"？ → --image N

用法
----
    set MBL_API_KEY=sk-xxxx
    python mbl_api_probe.py --models
    python mbl_api_probe.py --chat qwen2.5-vl-7b-instruct
    python mbl_api_probe.py --image qwen2.5-vl-7b-instruct --n 1
    python mbl_api_probe.py --image qwen2.5-vl-7b-instruct --n 10
    python mbl_api_probe.py --scan qwen2.5-vl-7b-instruct,qwen3-vl-plus,qwen-vl-max
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import struct
import time
import urllib.error
import urllib.request
import zlib


def make_flat_png(width: int, height: int, rgb=(235, 238, 242)) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


# 尽量贴近 MobileBench-OL 真实请求：system + 长指令 + 图 + 动作格式要求
SYS_PROMPT = (
    "You are a GUI agent. You are given a task and your action history, with screenshots. "
    "You need to perform the next action to complete the task.\n"
    "## Output Format\n```\nThought: ...\nAction: ...\n```\n"
    "## Action Space\n\n"
    "click(point='<point>x1 y1</point>')\n"
    "type(content='')\n"
    "scroll(point='<point>x1 y1</point>', direction='down or up or right or left')\n"
    "press_home()\npress_back()\nwait()\nfinished(content='xxx')\n\n"
    "## Note\n- Use Chinese in `Thought` part.\n"
    "- Write a small plan and finally summarize your next action "
    "(with its target element) in one sentence in `Thought` part.\n\n"
    "## User Instruction\n"
)


def build_messages(task: str, uri: str, n_history: int):
    msgs = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": SYS_PROMPT + task},
    ]
    for _ in range(n_history):
        msgs.append({"role": "user", "content": [{"type": "image_url", "image_url": {"url": uri}}]})
        msgs.append({"role": "assistant", "content": "Thought: 上一步\nAction: wait()"})
    msgs.append({"role": "user", "content": [{"type": "image_url", "image_url": {"url": uri}}]})
    return msgs


def post(url: str, key: str, payload: dict | None, method: str = "POST", timeout: int = 180):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {key}")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), time.time() - t0
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}", time.time() - t0


def show(status: int, body: str, dt: float, head: int = 700) -> None:
    flag = "✅" if status == 200 else "❌"
    print(f"  {flag} HTTP {status}  ({dt:.1f}s)")
    print(f"  {body[:head]}" + (" …" if len(body) > head else ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get(
        "MBL_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
    ap.add_argument("--models", action="store_true", help="GET /v1/models")
    ap.add_argument("--filter", default=None, help="只显示 id 含该子串的模型（配合 --models）")
    ap.add_argument("--dump-models", default=None, help="把全部模型 id 写到该文件（便于本地筛选）")
    ap.add_argument("--chat", metavar="MODEL", help="纯文本请求")
    ap.add_argument("--image", metavar="MODEL", help="带图请求")
    ap.add_argument("--n", type=int, default=1, help="图片数量（含当前帧）")
    ap.add_argument("--scan", help="逗号分隔的候选模型名，逐个试探可用性")
    ap.add_argument("--size", default="1080x2400", help="测试图尺寸，如 540x1200（省 token）")
    args = ap.parse_args()

    # key 来源：环境变量 → 仓库根的 mobile.env.ps1（见 mbl_env.py 的说明）
    import mbl_env  # noqa: PLC0415

    key = mbl_env.require_api_key()
    base = args.base_url.rstrip("/")
    print(f"endpoint: {base}")
    print(f"key: {key[:8]}…{key[-4:]}  (len={len(key)})\n")

    if args.models or args.dump_models:
        print("[GET /models]")
        st, body, dt = post(f"{base}/models", key, None, method="GET")
        ids: list[str] = []
        try:
            ids = sorted(m["id"] for m in json.loads(body)["data"])
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ 解析失败: {exc} | HTTP {st} | {body[:200]}")
        if ids:
            print(f"  ✅ 共 {len(ids)} 个模型（HTTP {st}, {dt:.1f}s）")
        if args.dump_models and ids:
            with open(args.dump_models, "w", encoding="utf-8") as fh:
                json.dump(ids, fh, ensure_ascii=False, indent=1)
            print(f"  已写入 {args.dump_models}")
        if args.filter and ids:
            hits = [i for i in ids if args.filter.lower() in i.lower()]
            print(f"  匹配 '{args.filter}': {len(hits)} 个")
            for h in hits:
                print("   ", h)
        elif args.models and not ids:
            show(st, body, dt)

    if args.scan:
        print("\n[逐个试探模型是否可用]")
        for m in [x.strip() for x in args.scan.split(",") if x.strip()]:
            st, body, dt = post(f"{base}/chat/completions", key, {
                "model": m, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 4})
            note = ""
            if st != 200:
                try:
                    note = json.loads(body)["error"]["message"][:110]
                except Exception:  # noqa: BLE001
                    note = body[:110]
            print(f"  {'✅' if st == 200 else '❌'} {m:34s} HTTP {st} {dt:5.1f}s {note}")

    if args.chat:
        print(f"\n[纯文本 {args.chat}]")
        show(*post(f"{base}/chat/completions", key, {
            "model": args.chat, "max_tokens": 64, "temperature": 0,
            "messages": [{"role": "user", "content": "回复两个字：收到"}]}))

    if args.image:
        w, h = (int(x) for x in args.size.lower().split("x"))
        png = make_flat_png(w, h)
        uri = data_uri(png)
        n_hist = max(0, args.n - 1)
        msgs = build_messages("打开B站搜索喜羊羊与灰太狼", uri, n_hist)
        n_img = sum(1 for m in msgs if isinstance(m.get("content"), list) for c in m["content"]
                    if isinstance(c, dict) and c.get("type") == "image_url")
        payload = {"model": args.image, "messages": msgs, "max_tokens": 300,
                   "temperature": 0, "top_p": 0.9}
        body_len = len(json.dumps(payload))
        print(f"\n[带图 {args.image}]  图片数={n_img}  测试图={w}x{h}  "
              f"请求体={body_len/1e6:.2f} MB")
        st, body, dt = post(f"{base}/chat/completions", key, payload)
        show(st, body, dt, head=900)
        if st == 200:
            try:
                text = json.loads(body)["choices"][0]["message"]["content"]
                print("\n  --- 模型输出 ---")
                print("  " + text.replace("\n", "\n  ")[:600])
                low = text.lower()
                print("\n  --- 格式自检 ---")
                print(f"  含 'action' 关键字: {'action' in low}")
                print(f"  含坐标式点击 click(point=: {'click(point=' in low or 'start_point' in low}")
                print(f"  含 finished(): {'finished(' in low}")
                usage = json.loads(body).get("usage")
                if usage:
                    print(f"  token 用量: {usage}")
            except Exception as e:  # noqa: BLE001
                print(f"  （解析输出失败: {e}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

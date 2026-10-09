#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mbl_api_smoketest.py —— 在跑 benchmark 之前，先验证"这个 API 端点能不能吃下 MobileBench-OL 的请求"。

为什么需要它
------------
MobileBench-OL 的 qwen2_5vl / uitars_1_5 两个 wrapper 有两个容易致命的假设
（见 mobilebench/models/execute.py 与 llm_core_qwen2_5vl.py）：

  1. 构造时会调 ``client.models.list()``，并用 ``data[0].id`` 当模型名
     —— 自建 vLLM 只有一个模型所以没事；托管 API 上会**选错模型**，
     而百炼的兼容模式文档里并没有列出 Models 接口，可能直接报错。
  2. 每个 step 会把**当前截图 + 最近 9 张历史截图**一起发出去（10 张图），
     且用 **无损 PNG + base64**（``do_resize`` 默认 False）。
     托管 API 常有单请求图片数 / 请求体大小限制，**可能直接 400**。

本脚本按"由简到难"发 4 个探测请求，把这两个假设逐个验证：

  P0  列出模型（可选，预期在托管 API 上失败 —— 失败也没关系）
  P1  纯文本请求           → 验证 endpoint / key / 模型名是否可用
  P2  1 张图 + **仓库真实 prompt** → 验证图片输入 + 输出格式能否被 action parser 解析
  P3  10 张图（1 当前 + 9 历史）→ 验证托管 API 的多图 / 请求体限制  ← 最容易挂在这里

用法
----
    # 1) 不联网，只生成测试图并报告体积（先看看流量有多大）
    python mbl_api_smoketest.py --repo <repo> --build-only

    # 2) 真跑（先设好环境变量）
    set MBL_API_KEY=sk-xxxx
    set MBL_MODEL=qwen2.5-vl-7b-instruct
    python mbl_api_smoketest.py --repo <repo> --base-url https://dashscope.aliyuncs.com/compatible-mode/v1

可选环境变量：
    MBL_API_KEY   API Key（必填；脚本会喂给 openai SDK）
    MBL_MODEL     模型名（强烈建议显式指定，见上面第 1 条）
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import struct
import sys
import time
import zlib

# ---------------------------------------------------------------- 造图（不依赖 PIL）


def make_png(width: int, height: int, rgb: tuple[int, int, int] = (235, 238, 242),
             noisy: bool = False) -> bytes:
    """生成一张 PNG。noisy=True 时用伪随机像素，模拟"真实截图压缩不掉"的最坏情况。"""
    if noisy:
        # 用固定种子的线性同余生成器，避免引入 random 依赖差异
        seed = 12345
        rows = []
        for _y in range(height):
            row = bytearray(b"\x00")
            for _x in range(width):
                seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
                row += bytes(((seed >> 16) & 0xFF, (seed >> 8) & 0xFF, seed & 0xFF))
            rows.append(bytes(row))
        raw = b"".join(rows)
    else:
        raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def b64_len(nbytes: int) -> int:
    """base64 后的长度（含 data URI 前缀的粗略值）。"""
    return (nbytes + 2) // 3 * 4


# ---------------------------------------------------------------- 探测


def probe(models_ok, name, fn):
    print(f"\n{'=' * 70}\n[{name}]\n{'=' * 70}")
    t0 = time.time()
    try:
        ok, detail = fn()
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    dt = time.time() - t0
    print(f"结果: {'✅ 通过' if ok else '❌ 失败'}  ({dt:.1f}s)")
    print(f"详情: {detail}")
    return ok, dt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="mobilebench-ol 仓库根目录")
    ap.add_argument("--base-url", default=os.environ.get(
        "MBL_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
    ap.add_argument("--build-only", action="store_true", help="只造图并报告体积，不联网")
    ap.add_argument("--real-image", default=None,
                    help="用一张真实截图来量体积（强烈建议：合成图的偏差极大）")
    ap.add_argument("--skip-multi-image", action="store_true")
    ap.add_argument("--tmp", default=None, help="测试图输出目录（默认仓库下 /tmp_smoke）")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    tmp = args.tmp or os.path.join(repo, "tmp_smoke")
    os.makedirs(tmp, exist_ok=True)

    # ---------------- 造图并报告体积（这一步永远执行） ----------------
    print("#" * 70)
    print("# 测试图体积（决定跨公网跑 benchmark 的带宽成本）")
    print("#" * 70)
    flat = make_png(1080, 2400, noisy=False)
    noise = make_png(1080, 2400, noisy=True)
    f_p, n_p = os.path.join(tmp, "step_flat.png"), os.path.join(tmp, "step_noise.png")
    open(f_p, "wb").write(flat)
    open(n_p, "wb").write(noise)
    for label, blob in (("纯色 1080x2400", flat), ("噪声 1080x2400（真实截图下界估计）", noise)):
        print(f"  {label:36s} PNG {len(blob)/1e6:6.2f} MB → base64 {b64_len(len(blob))/1e6:6.2f} MB")

    per_img_lo = b64_len(len(flat)) / 1e6
    per_img_hi = b64_len(len(noise)) / 1e6

    probe_img = f_p
    if args.real_image and os.path.exists(args.real_image):
        blob = open(args.real_image, "rb").read()
        dim = ""
        if blob[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", blob[16:24])
            dim = f" {w}x{h}"
        print(f"  ★ 真实截图 {os.path.basename(args.real_image)}{dim}: "
              f"PNG {len(blob)/1e6:6.2f} MB → base64 {b64_len(len(blob))/1e6:6.2f} MB")
        per_img_lo = per_img_hi = b64_len(len(blob)) / 1e6
        probe_img = args.real_image
        print("  （已用它替代合成图作为下面探测请求的输入）")

    print(f"\n  每个 step 发 10 张图 → 单步请求体约 {10*per_img_lo:.1f} ~ {10*per_img_hi:.1f} MB")
    print("  （真实截图介于两者之间；信息流/视频封面多时接近上限）")
    print(f"\n  测试图已写入: {tmp}")

    if args.build_only:
        print("\n--build-only：未联网。")
        return 0

    # ---------------- 联网探测 ----------------
    sys.path.insert(0, repo)
    try:
        from openai import OpenAI
    except ImportError:
        print("\n❌ 缺少 openai 依赖：pip install openai pillow opencv-python numpy uiautomator2")
        return 2

    api_key = os.environ.get("MBL_API_KEY", "")
    model = os.environ.get("MBL_MODEL", "").strip()
    if not api_key:
        print("\n❌ 未设置 MBL_API_KEY")
        return 2
    if not model:
        print("\n⚠️  未设置 MBL_MODEL：将尝试 /v1/models 推断。"
              "托管 API 上这几乎一定会选错模型，强烈建议显式指定。")

    client = OpenAI(api_key=api_key, base_url=args.base_url)

    results: dict[str, object] = {}

    # P0: 列模型（可选）
    def p0():
        ms = client.models.list()
        ids = [m.id for m in ms.data]
        return True, f"共 {len(ids)} 个模型，前 5 个: {ids[:5]}"

    ok0, _ = probe(None, "P0  GET /v1/models（托管 API 上失败属正常）", p0)
    results["P0_models_list"] = ok0

    used_model = model or None
    if not used_model and ok0:
        used_model = client.models.list().data[0].id
    if not used_model:
        print("\n❌ 没有可用模型名（MBL_MODEL 未设且 /v1/models 不可用）→ 必须显式设置 MBL_MODEL")
        return 2
    print(f"\n>>> 本次探测使用的模型: {used_model}")

    # P1: 纯文本
    def p1():
        r = client.chat.completions.create(
            model=used_model,
            messages=[{"role": "user", "content": "回复两个字：收到"}],
            max_tokens=32,
            temperature=0,
        )
        return True, repr(r.choices[0].message.content)[:200]

    ok1, _ = probe(None, "P1  纯文本请求（验证 endpoint / key / 模型名）", p1)
    results["P1_text"] = ok1

    # P2 / P3: 用仓库**真实的** prompt 与解析器
    ok2 = ok3 = False
    try:
        from mobilebench.models import llm_core_qwen2_5vl as core
        from mobilebench.utils import action_parser_tool

        handler = core.qwen2_5vl_message_handler()

        def build_messages(n_history: int):
            history = None
            if n_history:
                history = {
                    "history_response": ["Thought: 上一步\nAction: wait()"] * n_history,
                    "history_image_path": [probe_img] * n_history,
                }
            msgs = handler.process_message("打开B站搜索喜羊羊与灰太狼", probe_img, history)
            return msgs

        def p2():
            msgs = build_messages(0)
            r = client.chat.completions.create(
                model=used_model, messages=msgs, max_tokens=512, temperature=0, top_p=0.9)
            text = r.choices[0].message.content
            parsed = action_parser_tool.parse_agent_output(text)
            act = parsed.get("action")
            good = act not in (None, "", "invalid")
            tail = ("✅ 格式合规" if good
                    else "❌ 输出不符合 click(point=...) 动作格式，这个模型不能直接当 GUI agent 用")
            return good, (f"模型输出前 200 字: {text[:200]!r}\n"
                          f"      解析到的 action = {act!r}\n"
                          f"      {tail}")

        ok2, _ = probe(None, "P2  1 张图 + 仓库真实 prompt（验证图片输入 + 动作格式）", p2)

        if not args.skip_multi_image:
            def p3():
                msgs = build_messages(9)
                n_img = sum(
                    1 for m in msgs if isinstance(m.get("content"), list)
                    for c in m["content"] if isinstance(c, dict) and c.get("type") == "image_url"
                )
                r = client.chat.completions.create(
                    model=used_model, messages=msgs, max_tokens=512, temperature=0, top_p=0.9)
                text = r.choices[0].message.content
                act = action_parser_tool.parse_agent_output(text).get("action")
                return act not in (None, "", "invalid"), \
                    f"本次共发送 {n_img} 张图；解析到的 action = {act!r}"

            ok3, _ = probe(None, "P3  10 张图（1 当前 + 9 历史，框架的真实形态）", p3)
    except ImportError as exc:
        print(f"\n⚠️  无法 import 仓库模块（{exc}）→ 跳过 P2/P3。"
              "请在装好依赖的环境里跑，且 --repo 要指向仓库根目录。")

    results.update({"P2_single_image": ok2, "P3_multi_image": ok3})

    # ---------------- 结论 ----------------
    print("\n" + "#" * 70)
    print("# 结论")
    print("#" * 70)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if ok1 and ok2 and (ok3 or args.skip_multi_image):
        print("\n✅ 端点可用。下一步：打补丁（mbl_apply_api_patch.py）后跑 1 个任务。")
    elif ok1 and not ok2:
        print("\n⚠️  端点通了，但模型输出不符合动作格式 → 换个更强的 VL 模型"
              "（如 qwen3-vl-plus / qwen-vl-max）再试。")
    elif ok1 and ok2 and not ok3:
        print("\n❌ 单图可以，多图不行 → 托管 API 挡在了'10 张历史图'这一关。"
              "对策：把 wrapper 改成只发当前图（会改变观测，需在论文声明），或改走自建 vLLM。")
    else:
        print("\n❌ 连文本请求都不通 → 检查 base_url / key / 模型名。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

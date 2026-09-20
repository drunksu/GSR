#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mbl_coord_convention_check.py —— 判定模型输出的坐标是"像素"还是"0-1000 归一化"。

为什么必须查
------------
`mobilebench/models/llm_core_qwen2_5vl.py` 里：

    def process_response(self, content, width, height):
        x, y = extract_xy_from_point(...)
        params = {"position": [x, y]}          # ← 直接当像素用，不做任何换算
    ...
    response = self.client.call(...)
    output = self.message_handler.process_response(response, 1080, 2400)

而 UI-TARS 的原生约定是**绝对像素**，Qwen-VL 系列的原生 grounding 约定是
**0-1000 归一化**。若模型给的是归一化值而被当成像素，1080 宽屏上所有点击
都会挤到左上角 —— 实验会"全部失败"且看不出原因。

判定方法
--------
画一张 1080x2400 的图，在**右下角**放一个蓝色方块（像素中心约 (920, 2110)，
对应归一化约 (852, 879)），然后让模型点它：

    回答 ≈ (920, 2110) → 像素约定 ✅ 与仓库代码一致
    回答 ≈ (852,  879) → 归一化约定 ❌ 必须给 wrapper 加换算

用法
----
    set MBL_API_KEY=sk-xxxx
    python mbl_coord_convention_check.py --model qwen3-vl-plus
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from io import BytesIO

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("需要 pillow: pip install pillow")
    raise SystemExit(2)

W, H = 1080, 2400
# 右下角蓝色按钮（像素），以及它对应的归一化坐标（0-1000）
BOX = (820, 2040, 1020, 2180)
PX_CENTER = ((BOX[0] + BOX[2]) / 2, (BOX[1] + BOX[3]) / 2)          # (920, 2110)
NORM_CENTER = (PX_CENTER[0] / W * 1000, PX_CENTER[1] / H * 1000)     # (852, 879)

TASK = "点击屏幕右下角的蓝色按钮。"


def make_screen() -> bytes:
    img = Image.new("RGB", (W, H), (250, 250, 250))
    d = ImageDraw.Draw(img)
    # 干扰项：左上角红色按钮
    d.rectangle([60, 180, 260, 320], fill=(220, 60, 60))
    # 目标：右下角蓝色按钮
    d.rectangle(list(BOX), fill=(40, 90, 220))
    try:
        font = ImageFont.load_default()
    except Exception:  # noqa: BLE001
        font = None
    d.text((80, 230), "RED", fill=(255, 255, 255), font=font)
    d.text((860, 2090), "BLUE", fill=(255, 255, 255), font=font)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url", default=os.environ.get(
        "MBL_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
    ap.add_argument("--repo", default=None, help="可选：用仓库真实 prompt 与解析器")
    args = ap.parse_args()

    key = os.environ.get("MBL_API_KEY", "")
    if not key:
        print("❌ 未设置 MBL_API_KEY")
        return 2

    png = make_screen()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coord_probe.png")
    open(out, "wb").write(png)
    uri = "data:image/png;base64," + base64.b64encode(png).decode()
    print(f"合成图已保存: {out}")
    print(f"目标像素中心 = {PX_CENTER}，对应归一化中心 = "
          f"({NORM_CENTER[0]:.0f}, {NORM_CENTER[1]:.0f})\n")

    # 优先用仓库真实 prompt / 解析器
    sys_prompt = None
    if args.repo and os.path.isdir(args.repo):
        sys.path.insert(0, args.repo)
        try:
            from mobilebench.models import llm_core_qwen2_5vl as core  # noqa: PLC0415
            sys_prompt = core.sys_prompt
            print("使用仓库真实 sys_prompt")
        except Exception as exc:  # noqa: BLE001
            print(f"（未能加载仓库 prompt: {exc}）")
    if sys_prompt is None:
        sys_prompt = ("You are a GUI agent. You are given a task and your action history, with screenshots.\n"
                      "## Output Format\n```\nThought: ...\nAction: ...\n```\n"
                      "## Action Space\n"
                      "click(point='<point>x1 y1</point>')\n"
                      "finished(content='xxx')\n\n## User Instruction\n")

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": sys_prompt + TASK},
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": uri}}]},
    ]
    payload = {"model": args.model, "messages": messages, "max_tokens": 300,
               "temperature": 0, "top_p": 0.9}

    req = urllib.request.Request(f"{args.base_url.rstrip('/')}/chat/completions",
                                data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {key}")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            body = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP {e.code}: {e.read().decode()[:400]}")
        return 1
    dt = time.time() - t0
    text = body["choices"][0]["message"]["content"]
    print(f"模型输出（{dt:.1f}s）:\n{text}\n")

    # 取坐标
    coords = None
    if args.repo and os.path.isdir(args.repo):
        try:
            from mobilebench.utils import action_parser_tool as apt  # noqa: PLC0415
            parsed = apt.parse_agent_output(text)
            act = str(parsed.get("action", ""))
            if "point" in act:
                coords = apt.extract_xy_from_point(act)
            print(f"仓库解析器 → action={act!r}  coords={coords}")
        except Exception as exc:  # noqa: BLE001
            print(f"（仓库解析器不可用: {exc}）")
    if coords is None:
        import re
        nums = re.findall(r"(\d+)\s+(\d+)", text)
        coords = tuple(int(v) for v in nums[0]) if nums else None
        print(f"正则兜底 → coords={coords}")

    if not coords:
        print("\n❌ 没能从输出里取到坐标，无法判定。")
        return 1

    d_px = ((coords[0] - PX_CENTER[0]) ** 2 + (coords[1] - PX_CENTER[1]) ** 2) ** 0.5
    d_nm = ((coords[0] - NORM_CENTER[0]) ** 2 + (coords[1] - NORM_CENTER[1]) ** 2) ** 0.5
    print(f"\n与'像素中心'的欧氏距离 = {d_px:.0f}")
    print(f"与'归一化中心'的欧氏距离 = {d_nm:.0f}")

    # 逻辑判据（比距离更硬）：0-1000 归一化坐标**不可能超过 1000**。
    # 只要出现 >1000 的分量，就必然是像素或别的绝对坐标系。
    if coords[0] > 1000 or coords[1] > 1000:
        print(f"\n✅ 判定：**像素约定** —— 出现 {coords}，分量 >1000，归一化不可能超过 1000。")
        if min(d_px, d_nm) > 260:
            print("   ⚠️  但该坐标距真实目标较远 → 这个模型**定位精度**在这张合成图上较差"
                  "（像素约定 + 定位差 = 点击会偏，建议真机复验一次）。")
        return 0

    if d_px < d_nm and d_px < 260:
        print("\n✅ 判定：**像素约定**，与仓库代码一致，可以直接跑。")
        return 0
    if d_nm < d_px and d_nm < 260:
        print("\n❌ 判定：**0-1000 归一化约定** —— 仓库代码把它当像素用，会让所有点击挤到左上角。")
        print("   修法：在 process_response 里把 x,y 按 (x/1000*width, y/1000*height) 换算。")
        return 3
    print("\n⚠️  两种都不接近：模型可能没看准位置，或输出的是别的约定。"
          "建议换更靠边的目标再测一次（本脚本可改 BOX 常量）。")
    return 4


if __name__ == "__main__":
    raise SystemExit(main())

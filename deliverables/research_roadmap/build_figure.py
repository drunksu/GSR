"""build_figure.py — 生成《研究思路框架图》SVG（独立科研插图，可嵌入 PPT）。

课题：面向移动GUI智能体评测的应用状态污染检测和恢复方法研究
用途：中期答辩 PPT 第 5 页「研究思路」内容区（960×540pt 版面，可用区约 900×420pt）

设计稿的唯一来源是本脚本；改文字 / 改配色 / 改布局后重跑即可重新出图：
    mobile\\Scripts\\python.exe deliverables\\research_roadmap\\build_figure.py

脚本只使用标准库，输出 deliverables\\research_roadmap\\research_figure.svg。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------- palette ---
NAVY = "#1a365d"      # 主结构色
BLUE = "#2c5282"      # 次级结构色
ACCENT = "#3182ce"    # 流程色
LIGHT = "#ebf8ff"
SOFT = "#f7fafc"
WHITE = "#ffffff"
ORANGE = "#dd6b20"    # 唯一强调色：矛盾 / 污染 / 门控
ORANGE_BG = "#fffaf0"
MUTED = "#718096"
SLATE = "#4a5568"
BORDER = "#cbd5e0"
GRID = "#e2e8f0"

FONT = "Microsoft YaHei, PingFang SC, Noto Sans CJK SC, Segoe UI, sans-serif"

W, H = 1920, 720


def esc(s: str) -> str:
    a = chr(38)
    return s.replace(a, a + "amp;").replace("<", a + "lt;").replace(">", a + "gt;")


def char_w(ch: str, size: float) -> float:
    o = ord(ch)
    if o < 128:
        if ch == " ":
            return size * 0.32
        if ch.isdigit() or ch.isupper():
            return size * 0.60
        if ch.islower():
            return size * 0.53
        return size * 0.42
    if 0x2000 <= o <= 0x206F:
        return size * 0.55
    return size * 1.0


def text_w(s: str, size: float) -> float:
    return sum(char_w(c, size) for c in s)


class Canvas:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def open_group(self, gid: str, label: str) -> None:
        self.parts.append(f'<g id="{gid}"><title>{esc(label)}</title>')

    def close_group(self) -> None:
        self.parts.append("</g>")

    def rect(self, x, y, w, h, fill=WHITE, stroke=None, rx=0, sw=1.5, dash=None):
        a = [f'x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}"', f'fill="{fill}"']
        if stroke:
            a.append(f'stroke="{stroke}" stroke-width="{sw:g}"')
            if dash:
                a.append(f'stroke-dasharray="{dash}"')
        else:
            a.append('stroke="none"')
        if rx:
            a.append(f'rx="{rx:g}"')
        self.parts.append(f'<rect {" ".join(a)}/>')

    def line(self, x1, y1, x2, y2, stroke=GRID, sw=1.5, dash=None, marker=None, cap=None):
        a = [f'x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}"',
             f'stroke="{stroke}" stroke-width="{sw:g}"']
        if dash:
            a.append(f'stroke-dasharray="{dash}"')
        if cap:
            a.append(f'stroke-linecap="{cap}"')
        if marker:
            a.append(f'marker-end="url(#{marker})"')
        self.parts.append(f'<line {" ".join(a)}/>')

    def path(self, d, stroke=SLATE, sw=2, fill="none", dash=None, marker=None, cap=None):
        a = [f'd="{d}"', f'stroke="{stroke}" stroke-width="{sw:g}"', f'fill="{fill}"']
        if dash:
            a.append(f'stroke-dasharray="{dash}"')
        if cap:
            a.append(f'stroke-linecap="{cap}"')
        if marker:
            a.append(f'marker-end="url(#{marker})"')
        self.parts.append(f'<path {" ".join(a)}/>')

    def text(self, x, y, s, size=15, fill=SLATE, weight="normal", anchor="start"):
        a = [f'x="{x:g}" y="{y:g}"', f'font-size="{size:g}"', f'fill="{fill}"']
        if weight != "normal":
            a.append(f'font-weight="{weight}"')
        if anchor != "start":
            a.append(f'text-anchor="{anchor}"')
        self.parts.append(f'<text {" ".join(a)}>{esc(s)}</text>')

    def circle(self, cx, cy, r, fill=ACCENT, stroke=None, sw=1.5):
        a = [f'cx="{cx:g}" cy="{cy:g}" r="{r:g}"', f'fill="{fill}"']
        if stroke:
            a.append(f'stroke="{stroke}" stroke-width="{sw:g}"')
        self.parts.append(f'<circle {" ".join(a)}/>')

    def poly(self, pts, fill=ACCENT, stroke=None, sw=1.5):
        p = " ".join(f"{x:g},{y:g}" for x, y in pts)
        a = [f'points="{p}"', f'fill="{fill}"']
        if stroke:
            a.append(f'stroke="{stroke}" stroke-width="{sw:g}"')
        self.parts.append(f'<polygon {" ".join(a)}/>')


# ------------------------------------------------------------- 图元符号 ----
def icon_phone(c: Canvas, x, y, w=96, h=150, accent=ORANGE):
    """手机轮廓（真机 App 状态残留示意）。"""
    c.rect(x, y, w, h, fill=WHITE, stroke=BORDER, rx=12, sw=2)
    c.rect(x + 8, y + 16, w - 16, h - 30, fill=SOFT, rx=4, sw=1)
    c.circle(x + w / 2, y + h - 9, 3.5, fill=BORDER)
    # 开关图形：被改动的持久化设置
    c.rect(x + 22, y + 44, 44, 20, fill=WHITE, stroke=accent, rx=10, sw=2)
    c.circle(x + 22 + 44 - 12, y + 54, 8, fill=accent)
    c.text(x + w / 2, y + 88, "状态被改", 12.5, accent, "bold", "middle")


def icon_phone_dirty(c: Canvas, x, y, w=96, h=150):
    """起始条件失真的手机。"""
    c.rect(x, y, w, h, fill=WHITE, stroke=BORDER, rx=12, sw=2)
    c.rect(x + 8, y + 16, w - 16, h - 30, fill=SOFT, rx=4, sw=1)
    c.circle(x + w / 2, y + h - 9, 3.5, fill=BORDER)
    c.circle(x + w / 2, y + 52, 13, fill=ORANGE)
    c.poly([(x + w / 2 - 6, y + 52), (x + w / 2 + 8, y + 52), (x + w / 2 - 2, y + 64)], WHITE)
    c.text(x + w / 2, y + 88, "起始条件失真", 12.5, ORANGE, "bold", "middle")


def icon_clipboard(c: Canvas, x, y, s=42, color=NAVY):
    """污染清单图标。"""
    c.rect(x + 4, y + 6, s - 8, s - 6, fill=WHITE, stroke=color, rx=4, sw=2)
    c.rect(x + s / 2 - 8, y, 16, 8, fill=color, rx=3, sw=2)
    for i, wdt in enumerate((s - 20, s - 24, s - 16)):
        c.line(x + 11, y + 20 + i * 9, x + 11 + wdt, y + 20 + i * 9, color, 2, cap="round")


def icon_undo(c: Canvas, x, y, s=42, color=BLUE):
    """恢复任务图标：逆向操作箭头。"""
    c.path(f"M {x + s - 6} {y + s / 2} A {s / 2 - 3} {s / 2 - 3} 0 1 0 {x + 6} {y + s / 2}",
           color, 2.6, cap="round")
    c.poly([(x + 2, y + s / 2 - 7), (x + 12, y + s / 2 - 5), (x + 5, y + s / 2 + 3)], color)


def icon_gate(c: Canvas, x, y, s=42, color=ORANGE):
    """硬门控图标：向下的执行箭头被栏杆拦下。"""
    c.line(x + s / 2, y + 2, x + s / 2, y + 11, color, 2.4, cap="round")
    c.poly([(x + s / 2 - 5, y + 10), (x + s / 2 + 5, y + 10), (x + s / 2, y + 18)], color)
    c.rect(x + 3, y + 19, s - 6, 8, fill=color, rx=3)
    c.line(x + 10, y + 27, x + 10, y + s - 2, color, 2.4, cap="round")
    c.line(x + s - 10, y + 27, x + s - 10, y + s - 2, color, 2.4, cap="round")


def icon_check(c: Canvas, cx, cy, r=15, color=ACCENT):
    c.circle(cx, cy, r, fill=color)
    c.path(f"M {cx - r * 0.45} {cy} L {cx - r * 0.08} {cy + r * 0.38} L {cx + r * 0.5} {cy - r * 0.38}",
           WHITE, 2.8, cap="round")


def build(bg: bool = True) -> str:
    c = Canvas()
    c.parts.append(
        '<defs>'
        '<marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" '
        'markerHeight="8" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#2c5282"/></marker>'
        '<marker id="ar_o" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" '
        'markerHeight="8" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#dd6b20"/></marker>'
        '<marker id="ar_g" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" '
        'markerHeight="8" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#718096"/></marker>'
        '</defs>'
    )
    if bg:
        c.rect(0, 0, W, H, fill=WHITE)

    # ==================================================== 左：研究问题与矛盾
    c.open_group("problem", "研究问题与核心矛盾")
    c.text(40, 70, "研究问题", 21, NAVY, "bold")
    c.rect(40, 82, 54, 4, fill=ORANGE, rx=2)

    # 现象示意：任务 A 留下状态 → 任务 B 起始条件失真
    icon_phone(c, 52, 142)
    icon_phone_dirty(c, 292, 142)
    c.line(160, 216, 282, 216, BLUE, 2.2, marker="ar")
    c.path("M 166 206 C 200 178, 244 178, 276 206", ORANGE, 2, dash="6 5",
           marker="ar_o", cap="round")
    c.text(221, 170, "状态残留", 13.5, ORANGE, "bold", "middle")
    c.text(100, 322, "任务 A", 14, SLATE, "bold", "middle")
    c.text(340, 322, "任务 B", 14, SLATE, "bold", "middle")

    # 核心矛盾
    c.rect(40, 358, 400, 150, fill=ORANGE_BG, stroke=ORANGE, rx=10, sw=1.5)
    c.rect(40, 370, 5, 126, fill=ORANGE, rx=2)
    c.text(62, 396, "恢复动作本身也是设备操作，", 17, SLATE)
    c.text(62, 424, "执行错误 = 制造新的污染", 17, ORANGE, "bold")
    c.text(62, 466, "→ 生成可以自由，执行必须受控", 16, NAVY, "bold")

    # 由矛盾推出的两条设计约束
    c.circle(47, 562, 3.4, fill=ACCENT)
    c.text(60, 568, "检测只依据轨迹证据，不依赖 success 判定", 15, SLATE)
    c.circle(47, 600, 3.4, fill=ACCENT)
    c.text(60, 606, "前序残留由代码结转，不靠模型记忆", 15, SLATE)
    c.close_group()

    # ================================================== 中：状态恢复闭环主体
    c.open_group("loop", "状态恢复闭环")
    c.rect(500, 40, 910, 640, fill=SOFT, stroke=GRID, rx=14, sw=1.5)
    c.text(528, 76, "状态恢复闭环", 21, NAVY, "bold")
    c.text(528, 100, "语义级检测 · 门控式执行 · 恢复者自审计", 13.5, MUTED)

    mods = [
        (545, 130, "①", "推断", "Audit Agent · 离线", NAVY, icon_clipboard,
         ["读轨迹 → 结构化污染清单", "污染只依据轨迹证据"],
         "链式结转：代码管归因"),
        (1045, 130, "②", "生成", "Planner Agent · 离线", BLUE, icon_undo,
         ["污染清单 → 恢复任务", "目标自由撰写，限证据实体"],
         "前置检查保证幂等"),
        (795, 430, "③", "执行", "Execute Agent · 真机", ORANGE, icon_gate,
         ["硬门控状态机", "PRECHECK → EXECUTE → VERIFY"],
         "不可逆 / 不确定 → 人工挂起"),
    ]
    for mx, my, num, name, role, color, icon, lines, accent in mods:
        c.rect(mx, my, 320, 200, fill=WHITE, stroke=BORDER, rx=12, sw=1.6)
        c.rect(mx, my, 320, 5, fill=color, rx=2)
        c.circle(mx + 30, my + 38, 16, fill=color)
        c.text(mx + 30, my + 44, num, 16, WHITE, "bold", "middle")
        c.text(mx + 58, my + 36, name, 20, NAVY, "bold")
        c.text(mx + 58, my + 58, role, 13, MUTED)
        icon(c, mx + 262, my + 22, 42, color)
        c.line(mx + 18, my + 78, mx + 302, my + 78, GRID, 1.2)
        c.text(mx + 18, my + 108, lines[0], 15.5, SLATE)
        c.text(mx + 18, my + 136, lines[1], 15.5, SLATE)
        c.text(mx + 18, my + 174, accent, 14.5, color, "bold")

    # 模块之间的数据流
    c.line(865, 230, 1035, 230, BLUE, 2.4, marker="ar")
    c.text(950, 218, "污染清单", 13.5, MUTED, "normal", "middle")
    c.line(1075, 330, 1075, 420, BLUE, 2.4, marker="ar")
    c.text(1090, 378, "恢复任务", 13.5, MUTED)

    # 反馈回路：恢复轨迹再检测
    c.path("M 870 630 L 870 645 L 700 645 L 700 340", MUTED, 2, dash="7 6",
           marker="ar_g", cap="round")
    c.text(785, 668, "反馈：恢复轨迹再检测（自审计）", 14, MUTED, "normal", "middle")

    # 输入
    c.line(470, 230, 537, 230, BLUE, 2.4, marker="ar")
    c.text(503, 218, "任务轨迹", 13.5, MUTED, "normal", "middle")
    c.close_group()

    # ==================================================== 右：验证目标
    c.open_group("goal", "验证目标")
    c.rect(1456, 40, 432, 606, fill=WHITE, stroke=GRID, rx=14, sw=1.5)
    c.text(1478, 76, "验证目标", 21, NAVY, "bold")
    c.rect(1478, 88, 54, 4, fill=ORANGE, rx=2)

    rows = [
        ("独立执行", 1830, BLUE, 132, "任务成功率基准"),
        ("有前置污染", 1700, ORANGE, 196, "状态污染后"),
        ("本方法恢复后", 1830, ACCENT, 260, "恢复到基准口径"),
    ]
    for label, x_end, color, ry, note in rows:
        c.text(1478, ry + 12, label, 13.5, SLATE, "bold")
        c.text(1478, ry + 30, note, 12, MUTED)
        c.rect(1590, ry, x_end - 1590, 24, fill=color, rx=3)
    c.text(1846, 214, "≈", 26, BLUE, "bold", "middle")
    c.line(1830, 156, 1830, 260, GRID, 1.2, dash="4 4")

    chips = ["ΔSR 污染前后成功率差", "CTCI 任务跨顺序波动", "PASR 最差顺序成功率"]
    for i, t in enumerate(chips):
        y = 336 + i * 46
        c.rect(1478, y, 388, 34, fill=SOFT, stroke=GRID, rx=17, sw=1.2)
        c.text(1672, y + 22, t, 14, SLATE, "normal", "middle")

    c.text(1478, 512, "对照条件：none / ours / official", 14, MUTED)
    c.text(1478, 550, "人工干预率（人工挂起占比）", 14, MUTED)
    c.close_group()

    # 闭环 → 验证目标
    c.line(1115, 470, 1448, 470, BLUE, 2.4, marker="ar")
    c.text(1281, 458, "恢复后的状态", 13.5, MUTED, "normal", "middle")

    head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}" font-family="{FONT}">')
    desc = ("<desc>研究思路框架图：左侧为研究问题与核心矛盾（恢复错误等于新污染，"
            "因此生成可自由、执行必受控）；中部为检测—生成—执行三阶段状态恢复闭环，"
            "并含恢复轨迹再检测的反馈回路；右侧为验证目标——恢复后任务成功率回到独立执行口径，"
            "以 ΔSR、CTCI、PASR 评价。</desc>")
    return head + "\n" + desc + "\n" + "\n".join(c.parts) + "\n</svg>\n"


def main() -> None:
    here = Path(__file__).parent
    out = here / "research_figure.svg"
    out.write_text(build(bg=True), encoding="utf-8")
    print(f"[OK] wrote {out} ({out.stat().st_size} bytes)")
    out_t = here / "research_figure_transparent.svg"
    out_t.write_text(build(bg=False), encoding="utf-8")
    print(f"[OK] wrote {out_t} ({out_t.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

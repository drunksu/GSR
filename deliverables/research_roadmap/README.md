# 研究思路框架图 · 交付说明

课题：**面向移动 GUI 智能体评测的应用状态污染检测和恢复方法研究**
用途：**插入中期答辩 PPT 第 5 页「研究思路」内容区的独立科研插图**

---

## 1. 文件清单

| 文件 | 用途 |
|---|---|
| `research_figure_3840x1440_transparent.png` | **推荐插入**：2× 高清，透明底，可直接叠在版面的浅色底纹上 |
| `research_figure_3840x1440.png` | 2× 高清，白底（需要纯白背景时用） |
| `research_figure_1920x720.png` | 1×，白底 |
| `research_figure.svg` | **可编辑矢量源**，文本为真实文本层、图形为矢量，Figma / AI / Inkscape 可直接导入 |
| `research_figure_transparent.svg` | 同上，去掉白底矩形 |
| `preview_slide5_transparent.png` | 插进 PPT 第 5 页后的实际效果预览（透明底版） |
| `preview_slide5_opaque.png` | 插进 PPT 第 5 页后的实际效果预览（白底版） |
| `build_figure.py` | 出图脚本（唯一图源），含手机/清单/环形箭头/栏杆等复用图元 |
| `render_figure.ps1` | 用无头 Chrome 把 SVG 渲染成上述 PNG |
| `preview.html` | 渲染包装页（Chrome 截图用） |
| `design_notes.md` | 设计说明：抽象层级、构图方案、视觉编码、PPT 插入参数、待确认表述 |

---

## 2. 插入 PPT 第 5 页

版心 960 × 540 pt。第 5 页已有左上标题「研究思路」与右上校徽，底部左侧为页脚格言，
内容区约 x 25–935 pt、y 85–430 pt。

| 参数 | 建议值 |
|---|---|
| 图片 | `research_figure_3840x1440_transparent.png` |
| 位置 | 左 25 pt，上 88 pt |
| 尺寸 | 宽 910 pt × 高 341 pt（**保持 2.67:1，不要单独拉伸**） |
| 备选 | `research_figure_3840x1440.png`（白底） |

若需要更大字号，可把图宽放到 920 pt、高 345 pt，或裁掉图中左右两段留白后放大——
图内文字按 12.5 pt 正文设计，放到 910 pt 宽时约为 6–8 pt，投影可读；再放大会更清晰。

---

## 3. 改图

```powershell
# 1. 编辑 build_figure.py（文案集中在各模块的列表与 build() 中）
# 2. 重新生成 SVG 与全部 PNG
mobile\Scripts\python.exe deliverables\research_roadmap\build_figure.py
powershell -ExecutionPolicy Bypass -File deliverables\research_roadmap\render_figure.ps1
```

脚本只依赖 Python 标准库，不需要手机、API Key 或网络。

---

## 4. 内容边界与口径

- 本图只表达**研究逻辑**（问题 → 矛盾 → 方法闭环 → 验证目标），**不含**实验数值、
  阶段进度、预期成果与投稿计划——这些由 PPT 的"研究背景""关键成果""总结与展望"页承担。
- 图中"本方法恢复后"的成功率条与"独立执行"基准条等长，表达的是**验证目标（目标态）**，
  不是已取得的结果；讲稿中建议点明这一点。
- 其余口径与数据出处（真机实证、阶段 A 评测、恢复任务覆盖、接地审计）见
  `design_notes.md` 与 `README` 备注；本图未引用具体实验数值，故不存在 F1 口径冲突。

> **备注（与本图无关，但影响关键成果页）**：`docs/开题报告.md` / `design.md` v0.3 记录的是
> 41 case / micro F1 = 0.980，而更新的 `results/score_report_v3.json` 是 310 例金标 / F1 = 0.744，
> 与《中期答辩大纲》的 74% 口径一致。关键成果页需统一到其中一套口径。

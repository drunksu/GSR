// slide-03.js — Research background: state pollution problem
const pptxgen = require("pptxgenjs");
const slideConfig = { type: 'content', index: 3, title: '研究背景' };

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: theme.bg };

  // FUDAN header
  slide.addText("FUDAN UNIVERSITY", {
    x: 0.5, y: 0.3, w: 3, h: 0.25,
    fontSize: 9, fontFace: "Arial",
    color: theme.muted
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 0.6, w: 9, h: 0.03,
    fill: { color: theme.light }, line: { color: theme.light }
  });

  // Section indicator
  slide.addText("01", {
    x: 0.5, y: 0.9, w: 0.6, h: 0.4,
    fontSize: 22, fontFace: "Arial",
    color: theme.accent
  });
  slide.addText("研究背景", {
    x: 1.1, y: 0.95, w: 3, h: 0.35,
    fontSize: 16, fontFace: "Microsoft YaHei",
    color: theme.primary
  });

  // Title
  slide.addText("GUI Agent 评测中的状态污染问题", {
    x: 0.5, y: 1.4, w: 9, h: 0.55,
    fontSize: 24, fontFace: "Microsoft YaHei",
    color: theme.primary
  });

  // Left: the problem
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5, y: 2.1, w: 4.4, h: 2.8,
    fill: { color: theme.light }, line: { color: theme.light },
    rectRadius: 0.1
  });
  slide.addText("评测的默认假设", {
    x: 0.7, y: 2.25, w: 4, h: 0.35,
    fontSize: 15, fontFace: "Microsoft YaHei",
    color: theme.primary
  });
  slide.addText("每个任务独立执行，互不影响", {
    x: 0.7, y: 2.6, w: 4, h: 0.3,
    fontSize: 13, fontFace: "Microsoft YaHei",
    color: theme.secondary
  });
  slide.addShape(pres.shapes.LINE, {
    x: 0.7, y: 3.0, w: 4, h: 0,
    line: { color: theme.muted, width: 1 }
  });
  slide.addText("但实际是这样吗？", {
    x: 0.7, y: 3.15, w: 4, h: 0.3,
    fontSize: 14, fontFace: "Microsoft YaHei",
    color: theme.danger
  });

  // Task sequence
  const tasks = [
    { t: "任务A", s: "开夜间模式", c: theme.success },
    { t: "任务B", s: "加好友", c: theme.warn },
    { t: "任务C", s: "搜索关键词", c: theme.danger }
  ];
  tasks.forEach((tk, i) => {
    const x = 0.7 + i * 1.35;
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: x, y: 3.6, w: 1.2, h: 0.55,
      fill: { color: tk.c }, line: { color: tk.c },
      rectRadius: 0.05
    });
    slide.addText(tk.t, {
      x: x, y: 3.62, w: 1.2, h: 0.25,
      fontSize: 11, fontFace: "Microsoft YaHei",
      color: "FFFFFF", align: "center"
    });
    slide.addText(tk.s, {
      x: x, y: 3.87, w: 1.2, h: 0.22,
      fontSize: 8, fontFace: "Microsoft YaHei",
      color: "FFFFFF", align: "center"
    });
    if (i < 2) {
      slide.addText("→", {
        x: x + 1.2, y: 3.7, w: 0.15, h: 0.35,
        fontSize: 10, fontFace: "Arial", color: theme.muted, align: "center"
      });
    }
  });
  slide.addText("→ 后一个任务的起始状态已被改变", {
    x: 0.7, y: 4.25, w: 4, h: 0.3,
    fontSize: 11, fontFace: "Microsoft YaHei",
    color: theme.danger
  });

  // Right: definition
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.2, y: 2.1, w: 4.3, h: 2.8,
    fill: { color: theme.primary }, line: { color: theme.primary },
    rectRadius: 0.1
  });
  slide.addText("什么是状态污染？", {
    x: 5.4, y: 2.25, w: 3.9, h: 0.35,
    fontSize: 15, fontFace: "Microsoft YaHei",
    color: theme.accent
  });
  slide.addText("前一个任务的执行结果，改变了应用的持久化状态", {
    x: 5.4, y: 2.7, w: 3.9, h: 0.6,
    fontSize: 13, fontFace: "Microsoft YaHei",
    color: "FFFFFF"
  });
  slide.addText("（设置、好友关系、搜索历史、消息记录……）", {
    x: 5.4, y: 3.3, w: 3.9, h: 0.3,
    fontSize: 11, fontFace: "Microsoft YaHei",
    color: theme.light
  });
  slide.addText("导致后一个任务的起始条件与预期不符。", {
    x: 5.4, y: 3.7, w: 3.9, h: 0.35,
    fontSize: 13, fontFace: "Microsoft YaHei",
    color: "FFFFFF"
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 5.4, y: 4.15, w: 3.9, h: 0.04,
    fill: { color: theme.accent }, line: { color: theme.accent }
  });
  slide.addText("它不报错、不崩溃，但会悄悄拉低成功率，让评测结果失真", {
    x: 5.4, y: 4.3, w: 3.9, h: 0.5,
    fontSize: 12, fontFace: "Microsoft YaHei",
    color: theme.accent
  });

  slide.addNotes("首先介绍研究背景。现在GUI Agent的评测有一个默认假设：每个任务独立执行、互不影响。但实际情况是，任务是顺序执行的，前一个任务可能开启了夜间模式、加了好友、留下搜索记录，这些状态会遗留到下一个任务。我们把这个现象叫做状态污染。它不报错也不崩溃，但会悄悄拉低任务的成功率，让评测结果失真。");

  // page badge
  slide.addShape(pres.shapes.OVAL, {
    x: 9.3, y: 5.1, w: 0.4, h: 0.4,
    fill: { color: theme.accent }
  });
  slide.addText("3", {
    x: 9.3, y: 5.1, w: 0.4, h: 0.4,
    fontSize: 12, fontFace: "Arial",
    color: "FFFFFF", align: "center", valign: "middle"
  });
}

if (require.main === module) {
  const pres = new pptxgen();
  pres.layout = 'LAYOUT_16x9';
  const theme = { primary: "1a365d", secondary: "2c5282", accent: "3182ce", light: "ebf8ff", bg: "ffffff", warn: "dd6b20", danger: "c53030", success: "2f855a", muted: "718096" };
  createSlide(pres, theme);
  pres.writeFile({ fileName: "slide-03-preview.pptx" });
}
module.exports = { createSlide, slideConfig };

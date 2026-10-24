// slide-02.js — TOC
const pptxgen = require("pptxgenjs");
const slideConfig = { type: 'toc', index: 2, title: '目录' };

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

  slide.addText("目录", {
    x: 0.8, y: 0.9, w: 3, h: 0.6,
    fontSize: 36, fontFace: "Microsoft YaHei",
    color: theme.primary
  });
  slide.addText("CONTENTS", {
    x: 0.8, y: 1.45, w: 3, h: 0.3,
    fontSize: 13, fontFace: "Arial",
    color: theme.muted
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 1.8, w: 1.0, h: 0.05,
    fill: { color: theme.accent }, line: { color: theme.accent }
  });

  const items = [
    { no: "01", title: "研究背景", desc: "GUI Agent 评测中的状态污染问题" },
    { no: "02", title: "研究思路", desc: "检测—生成—执行三阶段方法" },
    { no: "03", title: "关键成果", desc: "阶段 A 离线评测结果" },
    { no: "04", title: "总结与展望", desc: "贡献、不足与后续计划" }
  ];

  items.forEach((item, i) => {
    const y = 2.2 + i * 0.75;
    slide.addShape(pres.shapes.OVAL, {
      x: 0.8, y: y, w: 0.6, h: 0.6,
      fill: { color: theme.primary }, line: { color: theme.primary }
    });
    slide.addText(item.no, {
      x: 0.8, y: y, w: 0.6, h: 0.6,
      fontSize: 18, fontFace: "Arial",
      color: "FFFFFF", align: "center", valign: "middle"
    });
    slide.addText(item.title, {
      x: 1.7, y: y + 0.02, w: 7, h: 0.35,
      fontSize: 22, fontFace: "Microsoft YaHei",
      color: theme.primary
    });
    slide.addText(item.desc, {
      x: 1.7, y: y + 0.38, w: 7, h: 0.25,
      fontSize: 12, fontFace: "Microsoft YaHei",
      color: theme.muted
    });
  });

  slide.addNotes("我的汇报分四个部分：首先介绍研究背景，说明什么是状态污染以及为什么它是个问题；然后讲研究思路，也就是我们提出的三阶段方法；接着汇报关键成果，即阶段A的离线评测结果；最后是总结与展望。");

  // page badge
  slide.addShape(pres.shapes.OVAL, {
    x: 9.3, y: 5.1, w: 0.4, h: 0.4,
    fill: { color: theme.accent }
  });
  slide.addText("2", {
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
  pres.writeFile({ fileName: "slide-02-preview.pptx" });
}
module.exports = { createSlide, slideConfig };

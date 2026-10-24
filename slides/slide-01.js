// slide-01.js — Cover
const pptxgen = require("pptxgenjs");
const slideConfig = { type: 'cover', index: 1, title: '封面' };

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: theme.primary };

  // FUDAN branding
  slide.addText("FUDAN UNIVERSITY", {
    x: 0.6, y: 0.4, w: 4, h: 0.3,
    fontSize: 12, fontFace: "Arial",
    color: theme.light
  });

  // Decorative circles
  slide.addShape(pres.shapes.OVAL, {
    x: 7.8, y: -1.5, w: 4, h: 4,
    fill: { color: theme.secondary }, line: { color: theme.secondary }
  });
  slide.addShape(pres.shapes.OVAL, {
    x: 8.5, y: 3.8, w: 2.5, h: 2.5,
    fill: { color: theme.accent }, line: { color: theme.accent }
  });

  // Title
  slide.addText("面向移动GUI智能体评测的", {
    x: 0.8, y: 1.8, w: 8, h: 0.85,
    fontSize: 38, fontFace: "Microsoft YaHei",
    color: "FFFFFF"
  });
  slide.addText("应用状态污染检测和恢复方法研究", {
    x: 0.8, y: 2.65, w: 8.5, h: 0.85,
    fontSize: 38, fontFace: "Microsoft YaHei",
    color: "FFFFFF"
  });

  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 3.7, w: 1.5, h: 0.06,
    fill: { color: theme.accent }, line: { color: theme.accent }
  });

  slide.addText("Detecting and Recovering from Application State Pollution", {
    x: 0.8, y: 3.9, w: 8, h: 0.3,
    fontSize: 13, fontFace: "Arial",
    color: theme.light
  });
  slide.addText("in Mobile GUI-Agent Evaluation", {
    x: 0.8, y: 4.2, w: 8, h: 0.3,
    fontSize: 13, fontFace: "Arial",
    color: theme.light
  });

  // Footer
  slide.addText("复旦大学曦源本科生自助项目 · 中期答辩", {
    x: 0.8, y: 5.0, w: 5, h: 0.3,
    fontSize: 12, fontFace: "Microsoft YaHei",
    color: theme.light
  });
  slide.addText("2026 年 10 月 29 日", {
    x: 7.5, y: 5.0, w: 2, h: 0.3,
    fontSize: 12, fontFace: "Microsoft YaHei",
    color: theme.light, align: "right"
  });

  slide.addNotes("各位老师好，我是复旦大学曦源项目的本科生，今天汇报的课题是面向移动GUI智能体评测的应用状态污染检测和恢复方法研究。");
}

if (require.main === module) {
  const pres = new pptxgen();
  pres.layout = 'LAYOUT_16x9';
  const theme = { primary: "1a365d", secondary: "2c5282", accent: "3182ce", light: "ebf8ff", bg: "ffffff", warn: "dd6b20", danger: "c53030", success: "2f855a", muted: "718096" };
  createSlide(pres, theme);
  pres.writeFile({ fileName: "slide-01-preview.pptx" });
}
module.exports = { createSlide, slideConfig };

// slide-08.js — Thank you
const pptxgen = require("pptxgenjs");
const slideConfig = { type: 'cover', index: 8, title: '感谢' };

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: theme.primary };

  // Decorative
  slide.addShape(pres.shapes.OVAL, {
    x: -1.5, y: 3, w: 4, h: 4,
    fill: { color: theme.secondary }, line: { color: theme.secondary }
  });
  slide.addShape(pres.shapes.OVAL, {
    x: 7.5, y: -1, w: 3.5, h: 3.5,
    fill: { color: theme.accent }, line: { color: theme.accent }
  });

  slide.addText("感谢您的倾听", {
    x: 0.8, y: 1.8, w: 8.4, h: 1.0,
    fontSize: 44, fontFace: "Microsoft YaHei",
    color: "FFFFFF", align: "center"
  });

  slide.addShape(pres.shapes.RECTANGLE, {
    x: 4.2, y: 2.9, w: 1.6, h: 0.06,
    fill: { color: theme.accent }, line: { color: theme.accent }
  });

  slide.addText("恳请各位评委老师批评指正", {
    x: 0.8, y: 3.1, w: 8.4, h: 0.5,
    fontSize: 20, fontFace: "Microsoft YaHei",
    color: theme.light, align: "center"
  });

  slide.addText("复旦大学曦源本科生自助项目", {
    x: 0.8, y: 4.2, w: 8.4, h: 0.35,
    fontSize: 13, fontFace: "Microsoft YaHei",
    color: theme.light, align: "center"
  });
  slide.addText("2026 年 10 月 29 日", {
    x: 0.8, y: 4.55, w: 8.4, h: 0.3,
    fontSize: 12, fontFace: "Microsoft YaHei",
    color: theme.muted, align: "center"
  });

  slide.addNotes("以上就是我的汇报，恳请各位老师批评指正，谢谢！");
}

if (require.main === module) {
  const pres = new pptxgen();
  pres.layout = 'LAYOUT_16x9';
  const theme = { primary: "1a365d", secondary: "2c5282", accent: "3182ce", light: "ebf8ff", bg: "ffffff", warn: "dd6b20", danger: "c53030", success: "2f855a", muted: "718096" };
  createSlide(pres, theme);
  pres.writeFile({ fileName: "slide-08-preview.pptx" });
}
module.exports = { createSlide, slideConfig };

// slide-07.js — Summary & outlook
const pptxgen = require("pptxgenjs");
const slideConfig = { type: 'summary', index: 7, title: '总结与展望' };

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

  slide.addText("04", {
    x: 0.5, y: 0.9, w: 0.6, h: 0.4,
    fontSize: 22, fontFace: "Arial",
    color: theme.accent
  });
  slide.addText("总结与展望", {
    x: 1.1, y: 0.95, w: 3, h: 0.35,
    fontSize: 16, fontFace: "Microsoft YaHei",
    color: theme.primary
  });

  // Left: contributions
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5, y: 1.5, w: 4.4, h: 3.4,
    fill: { color: theme.primary }, line: { color: theme.primary },
    rectRadius: 0.1
  });
  slide.addText("我们的贡献", {
    x: 0.7, y: 1.65, w: 4, h: 0.35,
    fontSize: 16, fontFace: "Microsoft YaHei",
    color: theme.accent
  });

  const contribs = [
    "提出「状态污染」概念，真机证明它真实存在（成功率掉 12–15 个百分点）",
    "设计检测—生成—执行三阶段方法，把恢复能力从任务内扩展到任务间",
    "完成阶段 A 评测：检出率 74%，方向判断 99% 正确，方案覆盖率 100%"
  ];
  contribs.forEach((c, i) => {
    slide.addShape(pres.shapes.OVAL, {
      x: 0.7, y: 2.15 + i * 0.85, w: 0.14, h: 0.14,
      fill: { color: theme.success }, line: { color: theme.success }
    });
    slide.addText(c, {
      x: 1.0, y: 2.05 + i * 0.85, w: 3.7, h: 0.75,
      fontSize: 12, fontFace: "Microsoft YaHei",
      color: "FFFFFF"
    });
  });

  // Right: limitations + future
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.2, y: 1.5, w: 4.3, h: 3.4,
    fill: { color: "f7fafc" }, line: { color: theme.light },
    rectRadius: 0.1
  });
  slide.addText("不足与后续计划", {
    x: 5.4, y: 1.65, w: 3.9, h: 0.35,
    fontSize: 16, fontFace: "Microsoft YaHei",
    color: theme.danger
  });

  const plans = [
    { p: "缺真机验证", n: "阶段 B：小批量真机实验，验证执行环节" },
    { p: "缺端到端对比", n: "阶段 C：对比不恢复/我们的方法/官方 cleaner" },
    { p: "检出率有提升空间", n: "补强门控规则，拿不准就挂起而非漏判" }
  ];
  plans.forEach((p, i) => {
    const y = 2.1 + i * 0.85;
    slide.addText(p.p, {
      x: 5.4, y: y, w: 3.9, h: 0.3,
      fontSize: 13, fontFace: "Microsoft YaHei",
      color: theme.danger
    });
    slide.addText("→ " + p.n, {
      x: 5.4, y: y + 0.32, w: 3.9, h: 0.4,
      fontSize: 11, fontFace: "Microsoft YaHei",
      color: theme.secondary
    });
  });

  // Bottom: significance
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5, y: 5.05, w: 9, h: 0.4,
    fill: { color: theme.accent }, line: { color: theme.accent },
    rectRadius: 0.06
  });
  slide.addText("意义：让 GUI Agent 评测从「默认任务独立」走向「承认任务会互相影响」，让成功率更可信", {
    x: 0.5, y: 5.05, w: 9, h: 0.4,
    fontSize: 12, fontFace: "Microsoft YaHei",
    color: "FFFFFF", align: "center", valign: "middle"
  });

  slide.addNotes("最后是总结与展望。我们的贡献有三点：一是提出状态污染概念并真机证明它存在；二是设计了检测生成执行三阶段方法；三是完成了阶段A评测，检出率74%、方向判断99%正确、方案覆盖率100%。同时也有不足：还缺真机验证、缺端到端对比、检出率有提升空间，对应的改进计划也已经列出来了。这个工作的意义在于，让GUI Agent的评测从默认任务独立，走向承认任务会互相影响，让成功率这个指标更可信。");

  // page badge
  slide.addShape(pres.shapes.OVAL, {
    x: 9.3, y: 5.1, w: 0.4, h: 0.4,
    fill: { color: theme.accent }
  });
  slide.addText("7", {
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
  pres.writeFile({ fileName: "slide-07-preview.pptx" });
}
module.exports = { createSlide, slideConfig };

// slide-06.js — Key results
const pptxgen = require("pptxgenjs");
const slideConfig = { type: 'content', index: 6, title: '关键成果' };

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

  slide.addText("03", {
    x: 0.5, y: 0.9, w: 0.6, h: 0.4,
    fontSize: 22, fontFace: "Arial",
    color: theme.accent
  });
  slide.addText("关键成果", {
    x: 1.1, y: 0.95, w: 3, h: 0.35,
    fontSize: 16, fontFace: "Microsoft YaHei",
    color: theme.primary
  });

  slide.addText("阶段 A 离线评测：方法可行，效果达标", {
    x: 0.5, y: 1.4, w: 9, h: 0.55,
    fontSize: 22, fontFace: "Microsoft YaHei",
    color: theme.primary
  });

  // Three big numbers
  const numbers = [
    { v: "74%", l: "污染检出率", sub: "综合准确率 F1", color: theme.primary },
    { v: "99%", l: "方向判断对", sub: "恢复还是不恢复，几乎不搞反", color: theme.secondary },
    { v: "100%", l: "恢复方案覆盖", sub: "有污染就有恢复方案", color: theme.accent }
  ];

  numbers.forEach((n, i) => {
    const x = 0.5 + i * 3.05;
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: x, y: 2.1, w: 2.85, h: 1.5,
      fill: { color: theme.light }, line: { color: theme.light },
      rectRadius: 0.1
    });
    slide.addText(n.v, {
      x: x, y: 2.2, w: 2.85, h: 0.75,
      fontSize: 46, fontFace: "Arial",
      color: n.color, align: "center"
    });
    slide.addText(n.l, {
      x: x, y: 2.9, w: 2.85, h: 0.3,
      fontSize: 15, fontFace: "Microsoft YaHei",
      color: theme.primary, align: "center"
    });
    slide.addText(n.sub, {
      x: x, y: 3.2, w: 2.85, h: 0.3,
      fontSize: 11, fontFace: "Microsoft YaHei",
      color: theme.muted, align: "center"
    });
  });

  // Verification note
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5, y: 3.8, w: 9, h: 0.4,
    fill: { color: theme.success }, line: { color: theme.success },
    rectRadius: 0.06
  });
  slide.addText("310 例人工金标验证 · 接地违规 0 条（没有编造任何不存在的状态变更）", {
    x: 0.5, y: 3.8, w: 9, h: 0.4,
    fontSize: 12, fontFace: "Microsoft YaHei",
    color: "FFFFFF", align: "center", valign: "middle"
  });

  // What's next for evaluation
  slide.addText("下一步：真机验证", {
    x: 0.5, y: 4.4, w: 4, h: 0.3,
    fontSize: 14, fontFace: "Microsoft YaHei",
    color: theme.secondary
  });

  const checks = [
    "恢复操作在真机上能否成功执行",
    "执行后状态是否真的回到干净状态",
    "恢复过程会不会留下新的副作用"
  ];
  checks.forEach((c, i) => {
    slide.addText("→ " + c, {
      x: 0.5 + i * 3.05, y: 4.75, w: 2.9, h: 0.3,
      fontSize: 11, fontFace: "Microsoft YaHei",
      color: theme.accent
    });
  });

  slide.addNotes("接下来汇报关键成果。阶段A的离线评测已经完成，用310例人工金标验证。三个核心数字：污染检出率74%，方向判断99%正确，恢复方案100%覆盖。特别值得一提的是接地违规0条，意味着模型没有编造任何不存在的状态变更。下一步要在真机上验证：恢复操作能不能成功执行、状态是不是真的恢复干净、会不会留下新的副作用。");

  // page badge
  slide.addShape(pres.shapes.OVAL, {
    x: 9.3, y: 5.1, w: 0.4, h: 0.4,
    fill: { color: theme.accent }
  });
  slide.addText("6", {
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
  pres.writeFile({ fileName: "slide-06-preview.pptx" });
}
module.exports = { createSlide, slideConfig };

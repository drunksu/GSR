// slide-04.js — Evidence: motivation experiment
const pptxgen = require("pptxgenjs");
const slideConfig = { type: 'content', index: 4, title: '实证' };

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

  slide.addText("真机实验证明：污染真实存在，影响显著", {
    x: 0.5, y: 1.4, w: 9, h: 0.55,
    fontSize: 22, fontFace: "Microsoft YaHei",
    color: theme.primary
  });

  // Setup strip
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5, y: 2.1, w: 9, h: 0.45,
    fill: { color: theme.light }, line: { color: theme.light },
    rectRadius: 0.06
  });
  slide.addText("MobileBench-OL · 310 任务 · 12 款真实 App · 真机 · 2 个模型", {
    x: 0.5, y: 2.1, w: 9, h: 0.45,
    fontSize: 12, fontFace: "Microsoft YaHei",
    color: theme.secondary, align: "center", valign: "middle"
  });

  // Big number
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5, y: 2.75, w: 3.8, h: 2.15,
    fill: { color: theme.primary }, line: { color: theme.primary },
    rectRadius: 0.1
  });
  slide.addText("核心发现", {
    x: 0.5, y: 2.9, w: 3.8, h: 0.3,
    fontSize: 14, fontFace: "Microsoft YaHei",
    color: theme.accent, align: "center"
  });
  slide.addText("12 ~ 15", {
    x: 0.5, y: 3.2, w: 3.8, h: 0.9,
    fontSize: 52, fontFace: "Arial",
    color: "FFFFFF", align: "center"
  });
  slide.addText("个百分点", {
    x: 0.5, y: 4.05, w: 3.8, h: 0.3,
    fontSize: 15, fontFace: "Microsoft YaHei",
    color: theme.light, align: "center"
  });
  slide.addText("不做状态清理时，任务成功率下降", {
    x: 0.5, y: 4.35, w: 3.8, h: 0.3,
    fontSize: 12, fontFace: "Microsoft YaHei",
    color: theme.light, align: "center"
  });

  // Two findings
  const findings = [
    { t: "污染是真实的", d: "不清理 vs 清理，成功率差 12–15 个百分点，统计显著", c: theme.danger },
    { t: "影响与模型能力相关", d: "能力较弱的模型对污染更敏感，强模型有一定抵抗力", c: theme.warn }
  ];
  findings.forEach((f, i) => {
    const y = 2.75 + i * 1.1;
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: 4.6, y: y, w: 4.9, h: 0.95,
      fill: { color: "f7fafc" }, line: { color: theme.light },
      rectRadius: 0.08
    });
    slide.addShape(pres.shapes.RECTANGLE, {
      x: 4.6, y: y, w: 0.07, h: 0.95,
      fill: { color: f.c }, line: { color: f.c }
    });
    slide.addText(f.t, {
      x: 4.85, y: y + 0.1, w: 4.5, h: 0.3,
      fontSize: 15, fontFace: "Microsoft YaHei",
      color: theme.primary
    });
    slide.addText(f.d, {
      x: 4.85, y: y + 0.42, w: 4.5, h: 0.45,
      fontSize: 11, fontFace: "Microsoft YaHei",
      color: theme.muted
    });
  });

  // Takeaway
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5, y: 5.05, w: 9, h: 0.4,
    fill: { color: theme.accent }, line: { color: theme.accent },
    rectRadius: 0.06
  });
  slide.addText("结论：状态污染不是理论假设，而是真实存在、影响显著的问题，需要专门的恢复机制", {
    x: 0.5, y: 5.05, w: 9, h: 0.4,
    fontSize: 12, fontFace: "Microsoft YaHei",
    color: "FFFFFF", align: "center", valign: "middle"
  });

  slide.addNotes("我们用真机实验验证了这个问题。实验用MobileBench-OL数据集，310个任务、12款真实App、两个模型。核心发现是：不做状态清理时，任务成功率下降12到15个百分点，而且统计显著。另外，污染对弱模型的影响更大。这说明状态污染不是理论假设，而是真实存在且影响显著的问题，需要专门的恢复机制。");

  // page badge
  slide.addShape(pres.shapes.OVAL, {
    x: 9.3, y: 5.1, w: 0.4, h: 0.4,
    fill: { color: theme.accent }
  });
  slide.addText("4", {
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
  pres.writeFile({ fileName: "slide-04-preview.pptx" });
}
module.exports = { createSlide, slideConfig };

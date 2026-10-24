// slide-05.js — Method: 3-stage pipeline
const pptxgen = require("pptxgenjs");
const slideConfig = { type: 'content', index: 5, title: '研究思路' };

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

  slide.addText("02", {
    x: 0.5, y: 0.9, w: 0.6, h: 0.4,
    fontSize: 22, fontFace: "Arial",
    color: theme.accent
  });
  slide.addText("研究思路", {
    x: 1.1, y: 0.95, w: 3, h: 0.35,
    fontSize: 16, fontFace: "Microsoft YaHei",
    color: theme.primary
  });

  slide.addText("检测 → 生成 → 执行 三阶段闭环", {
    x: 0.5, y: 1.4, w: 9, h: 0.55,
    fontSize: 24, fontFace: "Microsoft YaHei",
    color: theme.primary
  });

  // Flow: input -> 3 stages
  // Input
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.3, y: 2.15, w: 1.5, h: 0.8,
    fill: { color: theme.light }, line: { color: theme.accent },
    rectRadius: 0.06
  });
  slide.addText("输入", {
    x: 0.3, y: 2.2, w: 1.5, h: 0.25,
    fontSize: 10, fontFace: "Microsoft YaHei",
    color: theme.muted, align: "center"
  });
  slide.addText("任务描述\n+ 执行轨迹", {
    x: 0.3, y: 2.45, w: 1.5, h: 0.45,
    fontSize: 11, fontFace: "Microsoft YaHei",
    color: theme.primary, align: "center"
  });

  slide.addText("→", {
    x: 1.8, y: 2.3, w: 0.4, h: 0.5,
    fontSize: 18, fontFace: "Arial",
    color: theme.accent, align: "center", valign: "middle"
  });

  const stages = [
    { n: "①", name: "检测", en: "污染清单", desc: "哪些状态被改了", color: theme.primary },
    { n: "②", name: "生成", en: "恢复任务", desc: "该怎么恢复", color: theme.secondary },
    { n: "③", name: "执行", en: "恢复+验证", desc: "实际恢复并检查", color: theme.accent }
  ];

  stages.forEach((s, i) => {
    const x = 2.2 + i * 2.45;
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: x, y: 2.1, w: 2.2, h: 1.0,
      fill: { color: s.color }, line: { color: s.color },
      rectRadius: 0.08
    });
    slide.addText(s.n + " " + s.name, {
      x: x, y: 2.18, w: 2.2, h: 0.3,
      fontSize: 14, fontFace: "Microsoft YaHei",
      color: i === 2 ? theme.primary : "FFFFFF", align: "center"
    });
    slide.addText(s.en, {
      x: x, y: 2.48, w: 2.2, h: 0.3,
      fontSize: 12, fontFace: "Microsoft YaHei",
      color: i === 2 ? theme.primary : "FFFFFF", align: "center"
    });
    slide.addText(s.desc, {
      x: x, y: 2.78, w: 2.2, h: 0.25,
      fontSize: 10, fontFace: "Microsoft YaHei",
      color: i === 2 ? theme.primary : theme.light, align: "center"
    });
    if (i < 2) {
      slide.addText("→", {
        x: x + 2.2, y: 2.35, w: 0.25, h: 0.5,
        fontSize: 18, fontFace: "Arial",
        color: theme.accent, align: "center", valign: "middle"
      });
    }
  });

  // Feedback loop note
  slide.addText("↺ 恢复轨迹再检测，确认没有制造新污染", {
    x: 2.2, y: 3.25, w: 7, h: 0.3,
    fontSize: 11, fontFace: "Microsoft YaHei",
    color: theme.muted, align: "center"
  });

  // Core principle
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5, y: 3.7, w: 9, h: 0.45,
    fill: { color: theme.warn }, line: { color: theme.warn },
    rectRadius: 0.06
  });
  slide.addText("核心原则：生成可以自由，执行必须受控 —— 恢复错了等于制造新的污染", {
    x: 0.5, y: 3.7, w: 9, h: 0.45,
    fontSize: 13, fontFace: "Microsoft YaHei",
    color: "FFFFFF", align: "center", valign: "middle"
  });

  // Three key designs
  const designs = [
    { t: "语义级检测", d: "读 Agent 思考过程，判断意图上改了什么" },
    { t: "链式结转", d: "前序残留由代码记录，不靠模型记忆" },
    { t: "硬门控", d: "不可逆操作只生成不执行，交给人" }
  ];
  designs.forEach((d, i) => {
    const x = 0.5 + i * 3.05;
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: x, y: 4.35, w: 2.85, h: 0.65,
      fill: { color: "f7fafc" }, line: { color: theme.light },
      rectRadius: 0.06
    });
    slide.addShape(pres.shapes.OVAL, {
      x: x + 0.1, y: 4.5, w: 0.22, h: 0.22,
      fill: { color: theme.success }, line: { color: theme.success }
    });
    slide.addText("✓", {
      x: x + 0.1, y: 4.5, w: 0.22, h: 0.22,
      fontSize: 11, fontFace: "Arial",
      color: "FFFFFF", align: "center", valign: "middle"
    });
    slide.addText(d.t, {
      x: x + 0.4, y: 4.42, w: 2.3, h: 0.28,
      fontSize: 13, fontFace: "Microsoft YaHei",
      color: theme.primary
    });
    slide.addText(d.d, {
      x: x + 0.4, y: 4.68, w: 2.3, h: 0.28,
      fontSize: 10, fontFace: "Microsoft YaHei",
      color: theme.muted
    });
  });

  slide.addNotes("接下来讲研究思路。我们设计了一个三阶段闭环：第一阶段检测，读任务描述和执行轨迹，输出污染清单，也就是哪些状态被改了；第二阶段生成，根据污染清单写出恢复任务，即该怎么恢复；第三阶段执行，实际操作恢复并验证。恢复后的轨迹还会再跑一遍检测，确认没有制造新的污染。核心原则是生成可以自由，但执行必须受控，因为恢复错了等于制造新的污染。");

  // page badge
  slide.addShape(pres.shapes.OVAL, {
    x: 9.3, y: 5.1, w: 0.4, h: 0.4,
    fill: { color: theme.accent }
  });
  slide.addText("5", {
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
  pres.writeFile({ fileName: "slide-05-preview.pptx" });
}
module.exports = { createSlide, slideConfig };

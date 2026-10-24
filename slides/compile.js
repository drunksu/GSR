const pptxgen = require('pptxgenjs');
const pres = new pptxgen();
pres.layout = 'LAYOUT_16x9';

const theme = {
  primary: "1a365d",
  secondary: "2c5282",
  accent: "3182ce",
  light: "ebf8ff",
  bg: "ffffff",
  warn: "dd6b20",
  danger: "c53030",
  success: "2f855a",
  muted: "718096"
};

for (let i = 1; i <= 8; i++) {
  const num = String(i).padStart(2, '0');
  const slideModule = require(`./slide-${num}.js`);
  slideModule.createSlide(pres, theme);
}

pres.writeFile({ fileName: './output/midterm_defense.pptx' }).then(() => {
  console.log('PPTX generated: ./output/midterm_defense.pptx');
});

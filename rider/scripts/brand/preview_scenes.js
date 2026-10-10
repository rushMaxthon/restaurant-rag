// Renders every scene in light and dark into one contact sheet, from the app's own source.
const fs = require('fs');
const path = require('path');
const ts = require(path.join(__dirname, '..', '..', 'node_modules', 'typescript'));
const { Resvg } = require('@resvg/resvg-js');

function load(file) {
  const src = fs.readFileSync(file, 'utf8');
  const js = ts.transpileModule(src, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2019 } }).outputText;
  const mod = { exports: {} };
  new Function('module', 'exports', 'require', js)(mod, mod.exports, () => ({}));
  return mod.exports;
}
const dir = path.join(__dirname, '..', '..', 'src', 'components', 'illustrations');
const { SCENES } = load(path.join(dir, 'scenes.ts'));
const { illustrationPalette, fillTemplate } = load(path.join(dir, 'palette.ts'));
const light = { primary: '#FF5200', primarySoft: '#FFF0E8', success: '#16A34A', successSoft: '#E8F7EE', textMuted: '#5B6375', bg: '#F6F7FA' };
const dark = { primary: '#FF5200', primarySoft: 'rgba(255, 82, 0, 0.16)', success: '#22C55E', successSoft: 'rgba(34, 197, 94, 0.16)', textMuted: '#A3ABBD', bg: '#0B0D12' };

const names = Object.keys(SCENES);
const W = 240, H = 160, cols = 4;
const only = process.argv[2] ? process.argv[2].split(',') : names;
const list = names.filter(n => only.includes(n));
for (const [mode, colors] of [['light', light], ['dark', dark]]) {
  const pal = illustrationPalette(colors, mode);
  const rows = Math.ceil(list.length / cols);
  let body = `<rect width="${W * cols}" height="${(H + 18) * rows}" fill="${colors.bg}"/>`;
  list.forEach((n, i) => {
    const x = (i % cols) * W, y = Math.floor(i / cols) * (H + 18);
    const inner = fillTemplate(SCENES[n], pal).replace('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 160">', '').replace(/<\/svg>$/, '');
    body += `<g transform="translate(${x} ${y + 16})">${inner}</g><text x="${x + 8}" y="${y + 12}" font-size="11" fill="${mode === 'dark' ? '#ccc' : '#333'}" font-family="Arial">${n}</text>`;
  });
  const sheet = `<svg xmlns="http://www.w3.org/2000/svg" width="${W * cols}" height="${(H + 18) * rows}">${body}</svg>`;
  const out = path.join(__dirname, `scenes_${mode}.png`);
  fs.writeFileSync(out, new Resvg(sheet, { font: { loadSystemFonts: true }, fitTo: { mode: 'width', value: 1440 } }).render().asPng());
  console.log(out);
}

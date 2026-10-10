const fs = require('fs');
const path = require('path');
const { Resvg } = require('@resvg/resvg-js');

const jobs = JSON.parse(fs.readFileSync(path.join(__dirname, 'jobs.json'), 'utf8'));
for (const { svg, out } of jobs) {
  const png = new Resvg(svg).render().asPng();
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, png);
  console.log(path.basename(path.dirname(out)) + '/' + path.basename(out), png.length);
}
// A preview sheet to look at.
const preview = process.argv[2];
if (preview) {
  const svgText = fs.readFileSync(preview, 'utf8');
  fs.writeFileSync(preview.replace(/\.svg$/, '.png'), new Resvg(svgText, { fitTo: { mode: 'width', value: 512 } }).render().asPng());
}

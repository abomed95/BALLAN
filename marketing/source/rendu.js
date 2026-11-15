// Rendu image par image de pub.html.
//   node rendu.js apercu  -> planche de controle (8 instants)
//   node rendu.js video   -> images/f00000.jpg ... a 30 i/s
const fs = require('fs');
const path = require('path');
const { chromium } = require('/opt/node-tools/node_modules/playwright');

const mode = process.argv[2] || 'apercu';
const ici = __dirname;
const DUREE_S = 40;
const IPS = 30;

(async () => {
  const navigateur = await chromium.launch();
  const page = await navigateur.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  await page.route('**/*', (r) => (r.request().url().startsWith('file://') ? r.continue() : r.abort()));
  await page.goto('file://' + path.join(ici, 'pub.html'));
  await page.evaluate(() => document.fonts.ready);

  if (mode === 'apercu') {
    const instants = [3.5, 8, 10.5, 15, 17.5, 24, 32, 38];
    const fichiers = [];
    for (const t of instants) {
      await page.evaluate((ms) => window.rendre(ms), t * 1000);
      const f = path.join(ici, `apercu-${t}.png`);
      await page.screenshot({ path: f });
      fichiers.push(f);
    }
    const p2 = await navigateur.newPage({ viewport: { width: 2160, height: 1920 } });
    const imgs = fichiers.map((f) => `<img src="data:image/png;base64,${fs.readFileSync(f).toString('base64')}">`).join('');
    await p2.setContent(`<style>body{margin:0;display:grid;grid-template-columns:repeat(4,540px)}img{width:540px;height:960px}</style>${imgs}`);
    await p2.screenshot({ path: path.join(ici, 'planche.png') });
  } else {
    const dossier = path.join(ici, 'images');
    fs.mkdirSync(dossier, { recursive: true });
    const total = DUREE_S * IPS;
    for (let i = 0; i < total; i++) {
      await page.evaluate((ms) => window.rendre(ms), (i * 1000) / IPS);
      await page.screenshot({ path: path.join(dossier, `f${String(i).padStart(5, '0')}.jpg`), type: 'jpeg', quality: 92 });
      if (i % 150 === 0) fs.appendFileSync(path.join(ici, 'progression.txt'), `${i}/${total}\n`);
    }
  }
  await navigateur.close();
})();

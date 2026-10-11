// turns the svgs from tools/make-logo.py into the PNGs (needs playwright + chromium)
//   node tools/render-logo.js
const { chromium } = require("playwright"); const fs = require("fs"); const path = require("path");
const root = path.dirname(__dirname);
(async () => {
  const b = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
  const shot = async (svgFile, out, w, h) => {
    const p = await b.newPage({ viewport: { width: w, height: h } });
    await p.setContent(`<style>html,body{margin:0;background:transparent}svg{display:block;width:${w}px;height:${h}px}</style>` + fs.readFileSync(path.join(root, svgFile), "utf8"));
    await p.screenshot({ path: path.join(root, out), omitBackground: true }); await p.close();
  };
  for (const out of ["assets/gurt-logo.png", "site/assets/gurt-logo.png"]) await shot("assets/gurt-logo.svg", out, 1024, 488);
  await shot("site/assets/favicon.svg", "site/assets/apple-touch-icon.png", 180, 180);
  await shot("site/assets/favicon.svg", "site/assets/favicon.png", 64, 64);
  // the "Get now on gurt" badge (tools/make-badge.py)
  await shot("site/assets/get-on-gurt.svg", "site/assets/get-on-gurt.png", 1000, 360);
  await shot("site/assets/get-on-gurt-dark.svg", "site/assets/get-on-gurt-dark.png", 1000, 360);
  await b.close();
})();

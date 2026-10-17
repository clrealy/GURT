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
  // favicon.ico (old browsers, Google's search results): the same icon at 16-256px, PNGs packed into one .ico
  const sizes = [16, 24, 32, 48, 64, 128, 256], pngs = [];
  for (const s of sizes) {
    const p = await b.newPage({ viewport: { width: s, height: s } });
    await p.setContent(`<style>html,body{margin:0;background:transparent}svg{display:block;width:${s}px;height:${s}px}</style>` + fs.readFileSync(path.join(root, "site/assets/favicon.svg"), "utf8"));
    pngs.push(await p.screenshot({ omitBackground: true })); await p.close();
  }
  const head = Buffer.alloc(6 + 16 * sizes.length); head.writeUInt16LE(0, 0); head.writeUInt16LE(1, 2); head.writeUInt16LE(sizes.length, 4);
  let off = head.length;
  sizes.forEach((s, i) => { const e = 6 + 16 * i; head.writeUInt8(s % 256, e); head.writeUInt8(s % 256, e + 1); head.writeUInt16LE(1, e + 4); head.writeUInt16LE(32, e + 6);
    head.writeUInt32LE(pngs[i].length, e + 8); head.writeUInt32LE(off, e + 12); off += pngs[i].length; });
  fs.writeFileSync(path.join(root, "site/favicon.ico"), Buffer.concat([head, ...pngs]));
  // the "Get now on gurt" badge (tools/make-badge.py)
  await shot("site/assets/get-on-gurt.svg", "site/assets/get-on-gurt.png", 1000, 360);
  await shot("site/assets/get-on-gurt-dark.svg", "site/assets/get-on-gurt-dark.png", 1000, 360);
  await b.close();
})();

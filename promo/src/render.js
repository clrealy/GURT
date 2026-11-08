// renders ad.html frame by frame: node render.js <url> <outdir> <w> <h> [fps] [only: comma-separated seconds to preview]
const { chromium } = require("playwright");
const fs = require("fs");
(async () => {
  const [url, out, w, h, fps = "30", only = ""] = process.argv.slice(2);
  fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: +w, height: +h }, deviceScaleFactor: 1 });
  await p.goto(url);
  await p.evaluate(() => window.ready());
  const times = only ? only.split(",").map(Number) : [...Array(Math.round(30 * +fps)).keys()].map(i => i / +fps);
  let i = 0;
  for (const t of times) {
    await p.evaluate(t => window.render(t), t);
    const name = only ? `t${String(t).replace(".", "_")}.jpg` : `f${String(i).padStart(5, "0")}.jpg`;
    await p.screenshot({ path: `${out}/${name}`, type: "jpeg", quality: 90 });
    i++;
  }
  await b.close();
})();

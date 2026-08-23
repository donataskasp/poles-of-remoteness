#!/usr/bin/env node
// Screenshot routine: the UI test suite. Serves site/ with the dev server, stubs the basemap tiles with a
// flat grey tile (the images must not depend on Esri or OSM being reachable or unchanged), and writes the
// fixed set of views. Light scheme, device scale factor 1, en-GB locale. Run from the repo root after
// `npm install playwright` in a scratch directory with NODE_PATH pointed at it, or with playwright installed
// under dev/ (dev/node_modules is git-ignored). See dev/README.md for both, docs/screenshots/README.md for
// the set and the desktop-byte-identical rule.
import { createRequire } from 'node:module';
import { mkdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { startServer } from './serve.mjs';

// Playwright is loaded through a CommonJS require on purpose: ESM `import` ignores NODE_PATH, so a plain
// `import { chromium } from 'playwright'` only ever finds an install inside the repository. This resolves
// an install under dev/ first and a NODE_PATH scratch directory second, which is what keeps the browser
// out of the repo.
const { chromium } = createRequire(import.meta.url)('playwright');

const argv = process.argv.slice(2);
const opt = (name, dflt) => { const i = argv.indexOf(`--${name}`); return i >= 0 ? argv[i + 1] : dflt; };
const DATA = resolve(opt('data', 'dev/out/site'));
const R2 = resolve(opt('r2', 'work/europe/2026-08-19/publish'));
const R2_PREFIX = opt('r2-prefix', 'europe/2026-08-19');
const OUT = resolve(opt('out', 'docs/screenshots'));
const ONLY = opt('only', null);

// The archives and the detail rasters are fetched from the absolute `r2_base` baked into the dev JSON
// (dev/site-json.py writes http://localhost:8000/r2 by default), so the server has to answer on that port
// or every data fetch lands on a port with nothing behind it and the page renders an empty map. Take the
// port from the JSON when it names localhost; --port overrides.
function portFromData() {
  try {
    const regions = JSON.parse(readFileSync(resolve(DATA, 'regions.json'), 'utf8')).regions || [];
    const url = new URL(regions[0].r2_base);
    if ((url.hostname === 'localhost' || url.hostname === '127.0.0.1') && url.port) return Number(url.port);
  } catch { /* no dev JSON, or a real https base: fall back to the default port */ }
  return 8123;
}
const PORT = Number(opt('port', portFromData()));

const DESKTOP = { width: 1440, height: 900 };
const PHONE = { width: 390, height: 844 };

// The run of record's Lithuania pole 1, for the detail view. Data about the run, not behaviour.
const lt = JSON.parse(readFileSync(resolve(DATA, 'europe/units/lt.json'), 'utf8'));
const pole1 = lt.A.poles[0];

const SHOTS = [
  { name: 'desktop-lt', view: DESKTOP, path: '/europe/lt#s=A&l=en' },
  { name: 'desktop-lt-lang-lt', view: DESKTOP, path: '/europe/lt#s=A&l=lt' },
  { name: 'desktop-lt-b', view: DESKTOP, path: '/europe/lt#s=B&l=en' },
  { name: 'desktop-continent', view: DESKTOP, path: '/europe/lt#z=4&lat=56&lon=14&s=A&l=en' },
  { name: 'desktop-detail', view: DESKTOP, path: `/europe/lt#z=13&lat=${pole1.lat}&lon=${pole1.lon}&s=A&l=en`, after: async (p) => { await p.mouse.click(720, 450); await p.waitForTimeout(500); } },
  { name: 'desktop-about', view: DESKTOP, path: '/europe/lt#s=A&l=en', after: async (p) => { await p.click('#about-btn'); await p.waitForTimeout(300); } },
  { name: 'phone-lt', view: PHONE, mobile: true, path: '/europe/lt#s=A&l=en' },
  { name: 'phone-lt-lang-lt', view: PHONE, mobile: true, path: '/europe/lt#s=A&l=lt' },
  { name: 'phone-ranking', view: PHONE, mobile: true, path: '/europe/lt#s=A&l=en', after: async (p) => { await p.click('#panel-handle'); await p.waitForTimeout(400); } },
  // The About button lives in the panel body, which the collapsed phone sheet hides, so the sheet opens first.
  { name: 'phone-about', view: PHONE, mobile: true, path: '/europe/lt#s=A&l=lt', after: async (p) => { await p.click('#panel-handle'); await p.waitForTimeout(400); await p.click('#about-btn'); await p.waitForTimeout(300); } },
];

// A typo in --only would otherwise write nothing, say nothing and exit 0, which reads as a pass.
if (ONLY && !SHOTS.some((s) => s.name === ONLY)) {
  console.error(`no such shot: ${ONLY}\nknown: ${SHOTS.map((s) => s.name).join(', ')}`);
  process.exit(2);
}

async function greyTile(browser) {
  const page = await browser.newPage({ viewport: { width: 256, height: 256 } });
  await page.setContent('<body style="margin:0;background:#a3a9b1"></body>');
  const png = await page.screenshot({ type: 'png' });
  await page.close();
  return png;
}

mkdirSync(OUT, { recursive: true });
const server = await startServer({ site: resolve('site'), data: DATA, r2: R2, r2Prefix: R2_PREFIX, port: PORT });
const browser = await chromium.launch();
const tile = await greyTile(browser);
let failed = 0;
try {
  for (const shot of SHOTS) {
    if (ONLY && shot.name !== ONLY) continue;
    const ctx = await browser.newContext({
      viewport: shot.view, deviceScaleFactor: 1, isMobile: !!shot.mobile, hasTouch: !!shot.mobile,
      colorScheme: 'light', locale: 'en-GB', timezoneId: 'Europe/Vilnius',
    });
    await ctx.route(/openstreetmap\.org|arcgisonline\.com/, (route) => route.fulfill({ status: 200, contentType: 'image/png', body: tile }));
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    await page.goto(`http://localhost:${PORT}${shot.path}`);
    await page.waitForSelector('html[data-ready="1"]', { timeout: 20000 });
    await page.waitForTimeout(800);
    if (shot.after) await shot.after(page);
    // Park the pointer off the map before the shot. A click leaves the cursor where it landed, and a row
    // under it paints its hover state, which is the same colour the ranking uses for the current unit: the
    // phone sheet came out with a random country looking selected. (0, 0) is header background, so no
    // element is hovered and the map gets no mousemove, which on desktop would rewrite the readout.
    await page.mouse.move(0, 0);
    await page.waitForTimeout(100);
    await page.screenshot({ path: resolve(OUT, `${shot.name}.png`), type: 'png' });
    console.log(`${shot.name}.png${errors.length ? `  ERRORS: ${errors.join(' | ')}` : ''}`);
    if (errors.length) failed += 1;
    await ctx.close();
  }
} finally {
  await browser.close();
  server.close();
}
process.exit(failed ? 1 : 0);

#!/usr/bin/env node
// Screenshots of one design option against the real published data (site/data, R2 over the network) and the
// real satellite basemap. Unlike dev/screenshots.mjs nothing is stubbed: the options are judged on the look
// a visitor gets.
// Usage: NODE_PATH=~/personal/scratch/playwright-scratch/node_modules \
//   node design/tools/shoot.mjs --site design/options/01-x --out design/shots/01-x [--port 8301] [--only name]
import { createRequire } from 'node:module';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { homedir } from 'node:os';
import { startServer } from '../../dev/serve.mjs';

const req = createRequire(resolve(homedir(), 'personal/scratch/playwright-scratch') + '/');
const { chromium } = req('playwright');

const argv = process.argv.slice(2);
const opt = (n, d) => { const i = argv.indexOf(`--${n}`); return i < 0 ? d : argv[i + 1]; };
const SITE = resolve(opt('site', 'site'));
const OUT = resolve(opt('out', 'design/shots/current'));
const PORT = Number(opt('port', '8300'));
const ONLY = opt('only', null);
mkdirSync(OUT, { recursive: true });

const server = await startServer({ site: SITE, data: resolve('site/data'), port: PORT });
const base = `http://localhost:${PORT}`;

const VIEWS = [
  { name: 'desktop-lt', vp: { width: 1440, height: 900 }, url: '/europe/lt#l=en' },
  { name: 'desktop-lt-dark', vp: { width: 1440, height: 900 }, url: '/europe/lt#l=en', dark: true },
  { name: 'desktop-continent', vp: { width: 1440, height: 900 }, url: '/europe/no#z=5&lat=62&lon=14&l=en' },
  { name: 'desktop-detail', vp: { width: 1440, height: 900 }, url: '/europe/lt#z=13&lat=54.441478&lon=23.537029&l=en', click: true },
  { name: 'desktop-about', vp: { width: 1440, height: 900 }, url: '/europe/lt#l=en', about: true },
  { name: 'phone-lt', vp: { width: 390, height: 844 }, url: '/europe/lt#l=en', phone: true },
  { name: 'phone-sheet', vp: { width: 390, height: 844 }, url: '/europe/lt#l=en', phone: true, sheet: true },
];

const browser = await chromium.launch();
try {
  for (const v of VIEWS) {
    if (ONLY && !ONLY.split(',').includes(v.name)) continue;
    const ctx = await browser.newContext({ viewport: v.vp, deviceScaleFactor: v.phone ? 2 : 1, locale: 'en-GB',
      colorScheme: v.dark ? 'dark' : 'light', isMobile: !!v.phone, hasTouch: !!v.phone });
    const page = await ctx.newPage();
    page.on('pageerror', (e) => console.error(`[${v.name}] pageerror:`, e.message));
    await page.goto(base + v.url, { waitUntil: 'load' });
    await page.waitForFunction(() => document.documentElement.dataset.ready === '1', null, { timeout: 30000 }).catch(() => {});
    await page.waitForLoadState('networkidle', { timeout: 20000 }).catch(() => {});
    if (v.click) { await page.mouse.click(700, 450); await page.waitForTimeout(800); }
    if (v.about) { await page.evaluate(() => document.getElementById('about-btn')?.click()); await page.waitForTimeout(500); }
    if (v.sheet) { await page.evaluate(() => document.getElementById('panel-handle')?.click()); await page.waitForTimeout(700); }
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${OUT}/${v.name}.png` });
    console.log('wrote', `${OUT}/${v.name}.png`);
    await ctx.close();
  }
} finally {
  await browser.close();
  server.close();
}

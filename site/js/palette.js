// Class byte to colour. The colours come from the CSS tokens so dark mode recolours the data layer too;
// the stops are fixed distances so the legend means the same thing in every region.
import { EDGE, NODATA } from './classes.js';

export const STOPS_M = [1000, 2500, 5000, 10000, 20000, 50000];
const EDGE_ALPHA = 0.35;

export function readTokens(el = document.documentElement) {
  const cs = getComputedStyle(el);
  const get = (name) => cs.getPropertyValue(name).trim();
  return {
    bands: STOPS_M.map((_, i) => get(`--band-${i + 1}`)),
    edge: get('--edge'),
    alpha: Number(get('--band-alpha')) || 0.6,
  };
}

export function hexToRgb(hex) {
  let h = hex.trim().replace(/^#/, '');
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  const n = parseInt(h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function makePalette(table, tokens) {
  const pal = new Uint8ClampedArray(256 * 4);
  const a = Math.round(tokens.alpha * 255);
  for (let c = 0; c < EDGE; c += 1) {
    const lower = table.lower(c);
    let band = -1;
    for (let i = 0; i < STOPS_M.length; i += 1) if (lower >= STOPS_M[i]) band = i;
    if (band < 0) continue;
    const [r, g, b] = hexToRgb(tokens.bands[band]);
    pal.set([r, g, b, a], c * 4);
  }
  const [r, g, b] = hexToRgb(tokens.edge);
  pal.set([r, g, b, Math.round(EDGE_ALPHA * 255)], EDGE * 4);
  // NODATA stays 0,0,0,0
  return pal;
}

export function paint(classes, palette, width, height) {
  const img = new ImageData(width, height);
  const d = img.data;
  for (let i = 0, n = width * height; i < n; i += 1) {
    const p = classes[i] * 4;
    const o = i * 4;
    d[o] = palette[p]; d[o + 1] = palette[p + 1]; d[o + 2] = palette[p + 2]; d[o + 3] = palette[p + 3];
  }
  return img;
}

export function legendRows(tokens) {
  return STOPS_M.map((m, i) => ({ color: tokens.bands[i], label_m: m }));
}

export { NODATA };

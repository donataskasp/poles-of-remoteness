import test from 'node:test';
import assert from 'node:assert/strict';
import { makeClassTable, EDGE, NODATA } from '../../site/js/classes.js';
import { STOPS_M, hexToRgb, makePalette, legendRows, readTokens } from '../../site/js/palette.js';

const tokens = { bands: ['#111111', '#222222', '#333333', '#444444', '#555555', '#666666'], edge: '#7a7f86', alpha: 0.5 };
const table = makeClassTable();

test('palette: hex parsing', () => {
  assert.deepEqual(hexToRgb('#a55f1f'), [165, 95, 31]);
  assert.deepEqual(hexToRgb('a55f1f'), [165, 95, 31]);
  assert.deepEqual(hexToRgb('#fff'), [255, 255, 255]);
});

test('palette: bands by lower edge, transparent below the first stop', () => {
  const pal = makePalette(table, tokens);
  assert.equal(pal.length, 1024);
  const rgba = (c) => Array.from(pal.slice(c * 4, c * 4 + 4));
  assert.deepEqual(rgba(0), [0, 0, 0, 0]);
  assert.deepEqual(rgba(table.toClass(999)), [0, 0, 0, 0]);
  assert.deepEqual(rgba(table.toClass(1000)), [17, 17, 17, 128]);
  assert.deepEqual(rgba(table.toClass(2499)), [17, 17, 17, 128]);
  assert.deepEqual(rgba(table.toClass(2500)), [34, 34, 34, 128]);
  assert.deepEqual(rgba(table.toClass(4999)), [34, 34, 34, 128]);
  assert.deepEqual(rgba(table.toClass(5000)), [51, 51, 51, 128]);
  assert.deepEqual(rgba(table.toClass(9999)), [51, 51, 51, 128]);
  assert.deepEqual(rgba(table.toClass(10000)), [68, 68, 68, 128]);
  assert.deepEqual(rgba(table.toClass(19999)), [68, 68, 68, 128]);
  assert.deepEqual(rgba(table.toClass(20000)), [85, 85, 85, 128]);
  assert.deepEqual(rgba(table.toClass(49999)), [85, 85, 85, 128]);
  assert.deepEqual(rgba(table.toClass(50000)), [102, 102, 102, 128]);
  assert.deepEqual(rgba(253), [102, 102, 102, 128]);
  assert.deepEqual(rgba(EDGE), [122, 127, 134, 89]);
  assert.deepEqual(rgba(NODATA), [0, 0, 0, 0]);
});

test('palette: a band with its own alpha uses it, the others fall back to the shared one', () => {
  const pal = makePalette(table, { ...tokens, alphas: [0.25, 0.5, null, undefined, 0, 1] });
  const alpha = (m) => pal[table.toClass(m) * 4 + 3];
  assert.equal(alpha(1000), 64, 'band 1 at .25');
  assert.equal(alpha(2500), 128, 'band 2 at .5');
  assert.equal(alpha(5000), 128, 'a missing value falls back to --band-alpha');
  assert.equal(alpha(10000), 128);
  assert.equal(alpha(20000), 128, 'zero is no alpha at all, so it falls back too: a band is never invisible');
  assert.equal(alpha(50000), 255);
  assert.deepEqual(Array.from(pal.slice(table.toClass(1000) * 4, table.toClass(1000) * 4 + 3)), [17, 17, 17], 'the colour is unchanged');
  assert.equal(pal[EDGE * 4 + 3], 89, 'the edge keeps its own fixed alpha');
});

test('palette: readTokens reads a per-band alpha where the page sets one', () => {
  const vars = { '--band-1': '#111111', '--band-2': '#222222', '--band-3': '#333333', '--band-4': '#444444', '--band-5': '#555555',
    '--band-6': '#666666', '--edge': '#7a7f86', '--band-alpha': ' 0.7', '--band-alpha-1': '0.4', '--band-alpha-2': '0.55' };
  const saved = globalThis.getComputedStyle;
  globalThis.getComputedStyle = () => ({ getPropertyValue: (n) => vars[n] ?? '' });
  try {
    const tk = readTokens({});
    assert.equal(tk.alpha, 0.7);
    assert.deepEqual(tk.alphas, [0.4, 0.55, 0.7, 0.7, 0.7, 0.7]);
    assert.equal(tk.bands[5], '#666666');
  } finally {
    globalThis.getComputedStyle = saved;
  }
});

test('palette: legend rows follow the stops', () => {
  const rows = legendRows(tokens);
  assert.equal(rows.length, STOPS_M.length);
  assert.deepEqual(rows[0], { color: '#111111', label_m: 1000 });
  assert.deepEqual(rows[5], { color: '#666666', label_m: 50000 });
});

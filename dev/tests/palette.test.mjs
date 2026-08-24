import test from 'node:test';
import assert from 'node:assert/strict';
import { makeClassTable, EDGE, NODATA } from '../../site/js/classes.js';
import { STOPS_M, hexToRgb, makePalette, legendRows } from '../../site/js/palette.js';

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

test('palette: legend rows follow the stops', () => {
  const rows = legendRows(tokens);
  assert.equal(rows.length, STOPS_M.length);
  assert.deepEqual(rows[0], { color: '#111111', label_m: 1000 });
  assert.deepEqual(rows[5], { color: '#666666', label_m: 50000 });
});

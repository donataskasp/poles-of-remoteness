import test from 'node:test';
import assert from 'node:assert/strict';
import { cellAt, rasterEdges } from '../../site/js/detail.js';

// A sidecar as the pipeline writes it: the north-west corner and the pixel size, both in degrees.
const meta = { west: 23.5, north: 54.5, dlon: 0.001, dlat: 0.0005, width: 400, height: 400 };

test('detail: cellAt maps a point to a raster cell', () => {
  assert.deepEqual(cellAt(meta, meta.north, meta.west), { col: 0, row: 0 }, 'the north-west corner is cell 0,0');
  assert.deepEqual(cellAt(meta, meta.north - meta.dlat * 1.5, meta.west + meta.dlon * 1.5), { col: 1, row: 1 });
  const last = cellAt(meta, meta.north - meta.dlat * (meta.height - 0.5), meta.west + meta.dlon * (meta.width - 0.5));
  assert.deepEqual(last, { col: meta.width - 1, row: meta.height - 1 }, 'the last cell is inside');
});

test('detail: rasterEdges places the raster from its north-west corner', () => {
  const e = rasterEdges(meta);
  assert.equal(e.north, 54.5);
  assert.equal(e.west, 23.5);
  assert.ok(Math.abs(e.south - (54.5 - 0.0005 * 400)) < 1e-12);
  assert.ok(Math.abs(e.east - (23.5 + 0.001 * 400)) < 1e-12);
  // The edges and the cell test have to agree: the south-east corner is outside, one cell in is inside.
  assert.equal(cellAt(meta, e.south, e.east), null);
  assert.deepEqual(cellAt(meta, e.south + meta.dlat / 2, e.east - meta.dlon / 2), { col: meta.width - 1, row: meta.height - 1 });
});

test('detail: cellAt refuses a point outside the raster', () => {
  assert.equal(cellAt(meta, meta.north, meta.west + meta.dlon * meta.width), null, 'the east edge is past the last column');
  assert.equal(cellAt(meta, meta.north - meta.dlat * meta.height, meta.west), null, 'the south edge is past the last row');
  assert.equal(cellAt(meta, meta.north, meta.west - 0.0001), null, 'west of the raster');
  assert.equal(cellAt(meta, meta.north + 0.0001, meta.west), null, 'north of the raster');
});

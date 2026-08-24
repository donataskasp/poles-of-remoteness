import test from 'node:test';
import assert from 'node:assert/strict';
import { CLASS_EDGES, EDGE, NODATA, toClass, classLower, classUpper, makeClassTable } from '../../site/js/classes.js';

// The cases the hand-opened browser page used to run (site/js/classes.test.html, deleted: nothing
// test-shaped stays under site/, which is all deployed). The Python side is pinned by
// pipeline/tests/test_classes.py, which runs node on this same module and compares every edge.

test('classes: the default table is 254 classes over the published edges', () => {
  assert.equal(CLASS_EDGES.length, 254);
  assert.equal(CLASS_EDGES[0], 0);
  assert.equal(CLASS_EDGES[253], 240000);
  assert.equal(EDGE, 254);
  assert.equal(NODATA, 255);
  assert.equal(classLower(0), 0);
  assert.equal(classUpper(253), Infinity, 'the top class is open-ended');
});

test('classes: a distance falls in the class whose lower edge is the last one not above it', () => {
  const cases = [[0, 0], [49, 0], [50, 1], [2499, 49], [2500, 50], [9999, 124], [10000, 125], [29999, 204],
    [30000, 205], [59999, 234], [60000, 235], [239999, 252], [240000, 253], [250000, 253]];
  for (const [m, c] of cases) assert.equal(toClass(m), c, `${m} m`);
  assert.throws(() => toClass(-1), RangeError);
  assert.throws(() => toClass(NaN), RangeError);
});

test('classes: a region supplies its own edges', () => {
  // A per-region table the way regions.json supplies one: the default edges doubled.
  const doubled = makeClassTable(CLASS_EDGES.map((e) => 2 * e));
  assert.equal(doubled.toClass(5000), 50);
  assert.equal(doubled.lower(50), 5000);
  assert.equal(doubled.upper(50), 5200);
  assert.equal(doubled.upper(253), Infinity);
  assert.throws(() => doubled.lower(254), RangeError);
});

test('classes: an unusable edge list is refused, not silently accepted', () => {
  assert.throws(() => makeClassTable([1, ...CLASS_EDGES.slice(1)]), RangeError, 'edges must start at 0');
  assert.throws(() => makeClassTable([0, 1.5, ...CLASS_EDGES.slice(2)]), RangeError, 'edges are whole metres');
  assert.throws(() => makeClassTable(CLASS_EDGES.slice(1)), RangeError, 'the table has a fixed length');
  assert.throws(() => makeClassTable([0, 0, ...CLASS_EDGES.slice(2)]), RangeError, 'edges increase strictly');
});

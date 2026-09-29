import test from 'node:test';
import assert from 'node:assert/strict';
import { insidePixels } from '../../site/js/explore.js';

// The coarse tile leaves a detail window empty only where the window covers a whole pixel, so the finer raster
// always answers there and no pixel outside the window loses its colour.
test('explore: a detail window clears the whole pixels inside it, rounded inward', () => {
  assert.deepEqual(insidePixels({ x: 10.2, y: 20.7 }, { x: 30.9, y: 40.1 }), [11, 21, 19, 19]);
  assert.deepEqual(insidePixels({ x: 10, y: 20 }, { x: 30, y: 40 }), [10, 20, 20, 20], 'an aligned window clears exactly itself');
});

test('explore: a window reaching past the tile is clipped to it, and one off the tile clears nothing', () => {
  assert.deepEqual(insidePixels({ x: -40.5, y: 200.2 }, { x: 12.5, y: 300 }), [0, 201, 12, 55]);
  assert.equal(insidePixels({ x: 300, y: 10 }, { x: 400, y: 20 }), null);
  assert.equal(insidePixels({ x: -50, y: -50 }, { x: -1, y: 20 }), null);
  // Narrower than one whole pixel: nothing is cleared, the fringe keeps the coarse colour.
  assert.equal(insidePixels({ x: 5.2, y: 5.2 }, { x: 5.9, y: 30 }), null);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { sortUnits } from '../../site/js/ranking.js';

const u = (code, rankA, rankB) => ({ code, A: rankA == null ? null : { rank: rankA }, B: rankB == null ? null : { rank: rankB } });

test('ranking: sort by the active scenario, null summaries last, ties by the other scenario then code', () => {
  const units = [u('lt', 3, 1), u('no', 1, 2), u('ge', null, 3), u('is', 2, null), u('ad', 3, 4)];
  assert.deepEqual(sortUnits(units, 'A').map((x) => x.code), ['no', 'is', 'lt', 'ad', 'ge']);
  assert.deepEqual(sortUnits(units, 'B').map((x) => x.code), ['lt', 'no', 'ge', 'ad', 'is']);
});

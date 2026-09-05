import test from 'node:test';
import assert from 'node:assert/strict';
import { sortUnits } from '../../site/js/ranking.js';

const u = (code, rankA, rankB) => ({ code, A: rankA == null ? null : { rank: rankA }, B: rankB == null ? null : { rank: rankB } });

test('ranking: sort by the active scenario, null summaries last, ties by the other scenario then code', () => {
  // 'ad' and 'zz' tie on both scenarios, so only the code can separate them; 'lt' ties with them on A and
  // is separated by B. Both tiebreaks are exercised in both directions.
  const units = [u('lt', 3, 1), u('no', 1, 2), u('ge', null, 3), u('is', 2, null), u('ad', 3, 4), u('zz', 3, 4)];
  assert.deepEqual(sortUnits(units, 'A').map((x) => x.code), ['no', 'is', 'lt', 'ad', 'zz', 'ge']);
  assert.deepEqual(sortUnits(units, 'B').map((x) => x.code), ['lt', 'no', 'ge', 'ad', 'zz', 'is']);
});

// The same units read with the islands hidden: a unit is placed by its best mainland pole, which the publish
// stage ranks separately, and a unit whose every pole is on an island carries no mainland summary at all.
const m = (code, rankA, rankB, mainA, mainB) => ({
  code,
  A: rankA == null ? null : { rank: rankA },
  B: rankB == null ? null : { rank: rankB },
  A_mainland: mainA == null ? null : { rank: mainA },
  B_mainland: mainB == null ? null : { rank: mainB },
});

test('ranking: the order follows the islands reading', () => {
  // 'is' wins on A while its islands count and falls to third without them; 'no' has no mainland pole at all.
  const units = [m('lt', 3, 3, 2, 2), m('no', 2, 2, null, null), m('is', 1, 1, 3, 3), m('ee', 4, 4, 1, 1)];
  assert.deepEqual(sortUnits(units, 'A').map((x) => x.code), ['is', 'no', 'lt', 'ee']);
  assert.deepEqual(sortUnits(units, 'A', 1).map((x) => x.code), ['is', 'no', 'lt', 'ee']);
  assert.deepEqual(sortUnits(units, 'A', 0).map((x) => x.code), ['ee', 'lt', 'is', 'no']);
  assert.deepEqual(sortUnits(units, 'B', 0).map((x) => x.code), ['ee', 'lt', 'is', 'no']);
});

test('ranking: a unit with no mainland summary sorts last, like one with no result at all', () => {
  const units = [m('aa', 2, 2, null, null), m('bb', 1, 1, null, null), m('cc', 3, 3, 1, 1)];
  // Both no-mainland units fall behind the one that has a mainland pole, and the code separates the two.
  assert.deepEqual(sortUnits(units, 'A', 0).map((x) => x.code), ['cc', 'aa', 'bb']);
  // A unit document written before the field existed behaves the same way: absent is absent.
  const older = [{ code: 'zz', A: { rank: 1 }, B: { rank: 1 } }, m('cc', 3, 3, 1, 1)];
  assert.deepEqual(sortUnits(older, 'A', 0).map((x) => x.code), ['cc', 'zz']);
});

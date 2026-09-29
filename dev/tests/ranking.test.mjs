import test from 'node:test';
import assert from 'node:assert/strict';
import { sortUnits, createRanking } from '../../site/js/ranking.js';
import { setLang } from '../../site/js/i18n.js';

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

// The tide table itself. createRanking touches a handful of DOM members only, so plain objects stand in: the
// panel with its four parts, document.createElement for the column head, and the few globals measure() reads.
function mountFake() {
  const node = () => ({ innerHTML: '', textContent: '', attrs: {}, setAttribute(k, v) { this.attrs[k] = v; },
    addEventListener() {}, querySelector() { return null; }, getBoundingClientRect: () => ({ height: 60 }) });
  const list = node();
  const parts = { '#ranking': list, '#ranking-note': node(), '#panel-handle': node(), '#panel-body': node() };
  let head = null;
  list.before = (h) => { head = h; };
  const panel = { querySelector: (q) => parts[q], classList: { toggle() {} } };
  const saved = { document: globalThis.document, getComputedStyle: globalThis.getComputedStyle, ResizeObserver: globalThis.ResizeObserver };
  globalThis.document = { createElement: () => node(), documentElement: { style: { setProperty() {} } } };
  globalThis.getComputedStyle = () => ({ borderTopWidth: '1px' });
  globalThis.ResizeObserver = class { observe() {} };
  try {
    const r = createRanking(panel, { onPick() {} });
    return { r, list, head: () => head };
  } finally {
    Object.assign(globalThis, saved);
  }
}

const UNITS = [
  { code: 'lt', name_en: 'Lithuania', A: { dist_m: 3426, rank: 2 }, B: { dist_m: 6675, rank: 1 } },
  { code: 'no', name_en: 'Norway', A: { dist_m: 42400, rank: 1 }, B: null },
];

test('ranking: the tide table has a column head that names the unit, following the scenario', () => {
  setLang('en');
  const { r, head } = mountFake();
  r.setRows(UNITS, 'A', 'lt');
  const h = head();
  assert.ok(h, 'the head is placed before the list');
  assert.equal(h.className, 'ranking__head');
  assert.equal(h.attrs['aria-hidden'], 'true', 'the head is visual: each row button says its own figures');
  assert.ok(h.innerHTML.includes('<span>No.</span><span>Unit</span>'));
  assert.ok(h.innerHTML.includes('<span class="ranking__dist">A, km</span>'));
  assert.ok(h.innerHTML.includes('<span class="ranking__other">B, km</span>'));
  r.setScenario('B');
  assert.ok(h.innerHTML.includes('<span class="ranking__dist">B, km</span>'), 'the active scenario leads');
  assert.ok(h.innerHTML.includes('<span class="ranking__other">A, km</span>'));
  setLang('lt');
  r.refresh();
  assert.ok(h.innerHTML.includes('<span>Nr.</span><span>Vienetas</span>'));
  setLang('en');
});

test('ranking: a row is four columns, the figures without their unit, and no flag', () => {
  setLang('en');
  const { r, list } = mountFake();
  r.setRows(UNITS, 'A', 'lt');
  const rows = list.innerHTML.split('<li').slice(1);
  assert.equal(rows.length, 2);
  assert.ok(rows[0].includes('data-code="no"'), 'sorted by the active scenario');
  // Norway has no B summary: its other column is there and empty, so the columns still line up.
  assert.ok(rows[0].includes('<span class="ranking__dist">42.40</span>'));
  assert.ok(rows[0].includes('<span class="ranking__other"></span>'));
  assert.ok(rows[1].startsWith(' class="ranking__row ranking__row--current">'), 'the unit on screen is marked');
  assert.ok(rows[1].includes('aria-current="true"'));
  assert.ok(rows[1].includes('<span class="ranking__rank">2</span>'));
  assert.ok(rows[1].includes('<span class="ranking__name">Lithuania</span>'));
  assert.ok(rows[1].includes('<span class="ranking__dist">3.43</span>'));
  assert.ok(rows[1].includes('<span class="ranking__other">6.68</span>'));
  assert.ok(!list.innerHTML.includes('km'), 'the head carries the unit, the figures do not');
  assert.ok(!list.innerHTML.includes('ranking__flag') && !/[\u{1F1E6}-\u{1F1FF}]/u.test(list.innerHTML), 'no flags');
  setLang('lt');
  r.refresh();
  assert.ok(list.innerHTML.includes('<span class="ranking__dist">3,43</span>'), 'the figures follow the language');
  setLang('en');
});

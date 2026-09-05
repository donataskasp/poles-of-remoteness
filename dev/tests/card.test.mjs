import test from 'node:test';
import assert from 'node:assert/strict';
import { setLang, t } from '../../site/js/i18n.js';
import { createCard } from '../../site/js/card.js';

// The card only ever touches these three members of its element, so a plain object stands in for the DOM.
function fakeEl() {
  return { hidden: true, innerHTML: '', addEventListener() {} };
}

const region = { id: 'europe', name: 'Europe' };
const noop = () => {};
const handlers = { onScenario: noop, onRanking: noop, onLocate: noop, onPole: noop };

function pole(rank, over = {}) {
  return {
    rank,
    lat: 54.441478,
    lon: 23.537029,
    dist_m: 3426,
    nearest_way: { highway: 'track', name: 'Miško kelias', ref: null },
    nearest_place: { name: 'Kumečiai', type: 'village', dist_m: 3688.6 },
    ...over,
  };
}

function render(view) {
  const el = fakeEl();
  createCard(el, handlers).show({ region, ...view });
  return el;
}

// The summary row the phone sheet's handle carries. It is optional, so the card is built with one only here.
function renderSummary(view) {
  const summary = fakeEl();
  createCard(fakeEl(), { ...handlers, summary }).show({ region, ...view });
  return summary;
}

test('card: a unit name carrying markup is escaped, never injected', () => {
  setLang('en');
  // A two-letter code would be named by Intl.DisplayNames, so this one comes from the data on purpose.
  const unit = { code: 'xx', name_en: '<b>Boom</b>', A: { dist_m: 3426, rank: 42 } };
  const el = render({ unit, units: [unit], doc: { A: { poles: [pole(1)], withheld: 0 } }, scenario: 'A', rank: 1 });
  assert.equal(el.hidden, false);
  assert.ok(el.innerHTML.includes('&lt;b&gt;Boom&lt;/b&gt;'), 'the name is escaped');
  assert.ok(!el.innerHTML.includes('<b>Boom</b>'), 'and never lands as markup');
  assert.ok(el.innerHTML.includes('#42 of 1 in Europe'));
});

test('card: an unnamed road and a missing settlement fall back to words', () => {
  setLang('en');
  const unit = { code: 'xx', name_en: 'Nowhere', A: { dist_m: 3426, rank: 1 } };
  const bare = pole(1, { nearest_way: { highway: 'track', name: null, ref: null }, nearest_place: null });
  const el = render({ unit, units: [unit], doc: { A: { poles: [bare], withheld: 0 } }, scenario: 'A', rank: 1 });
  assert.ok(el.innerHTML.includes(`track, ${t('unnamed')}`));
  assert.ok(el.innerHTML.includes(t('noPlace')));
});

test('card: a rank with no pole falls back to the first one', () => {
  setLang('en');
  const unit = { code: 'xx', name_en: 'Nowhere', A: { dist_m: 3426, rank: 1 } };
  const el = render({ unit, units: [unit], doc: { A: { poles: [pole(1), pole(2)], withheld: 0 } }, scenario: 'A', rank: 9 });
  assert.ok(el.innerHTML.includes('Pole 1'), 'the first pole stands in');
  assert.ok(!el.innerHTML.includes('Pole 9'));
  assert.ok(el.innerHTML.includes('of 2'));
});

test('card: a unit with no poles says why, withheld or not', () => {
  setLang('en');
  const unit = { code: 'xx', name_en: 'Nowhere' }; // no A summary: nothing was published for this scenario
  const none = render({ unit, units: [unit], doc: { A: { poles: [], withheld: 0 } }, scenario: 'A', rank: 1 });
  assert.ok(none.innerHTML.includes(t('reasonNone')));
  assert.ok(!none.innerHTML.includes('withheld by validation'));

  const held = render({ unit, units: [unit], doc: { A: { poles: [], withheld: 2 } }, scenario: 'A', rank: 1 });
  assert.ok(held.innerHTML.includes(t('reasonWithheld')));
  // Every pole withheld still has to say how many: the note cannot depend on there being a pole to show.
  assert.ok(held.innerHTML.includes(t('withheldNote', { n: 2 })));
});

test('card: a withheld count is shown next to the poles that did survive', () => {
  setLang('en');
  const unit = { code: 'xx', name_en: 'Nowhere', A: { dist_m: 3426, rank: 1 } };
  const el = render({ unit, units: [unit], doc: { A: { poles: [pole(1)], withheld: 3 } }, scenario: 'A', rank: 1 });
  assert.ok(el.innerHTML.includes(t('withheldNote', { n: 3 })));
  setLang('en'); // the language is module state, so leave it as found and keep the file order-independent
});

test('card: a unit below country level opens with its own name and no empty flag slot', () => {
  setLang('en');
  const unit = { code: 'xx-1', country: 'xx', name: 'Šiaurė', name_en: 'North', A: { dist_m: 3426, rank: 2 } };
  const el = render({ unit, units: [unit], doc: { A: { poles: [pole(1)], withheld: 0 } }, scenario: 'A', rank: 1 });
  assert.ok(el.innerHTML.includes('<p class="card__headline">North: the remotest point is'));
  assert.ok(!el.innerHTML.includes('card__headline"> '), 'no space where the flag would have been');
});

test('card: a country unit still carries its flag', () => {
  setLang('en');
  const unit = { code: 'lt', country: 'lt', name: 'Lietuva', name_en: 'Lithuania', A: { dist_m: 3426, rank: 1 } };
  const el = render({ unit, units: [unit], doc: { A: { poles: [pole(1)], withheld: 0 } }, scenario: 'A', rank: 1 });
  assert.ok(el.innerHTML.includes('<p class="card__headline">\u{1F1F1}\u{1F1F9} Lithuania: '));
});

test('card: the summary row says the unit, the scenario distance and the rank, and nothing else', () => {
  setLang('en');
  const unit = { code: 'lt', name_en: 'Lithuania', A: { dist_m: 3426, rank: 42 }, B: { dist_m: 6675, rank: 7 } };
  const units = [unit, { code: 'ee', name_en: 'Estonia', A: { dist_m: 4000, rank: 1 }, B: { dist_m: 5000, rank: 1 } }];
  const s = renderSummary({ unit, units, doc: { A: { poles: [pole(1)], withheld: 0 } }, scenario: 'A', rank: 1 });
  assert.equal(s.hidden, false);
  assert.ok(s.innerHTML.includes('\u{1F1F1}\u{1F1F9} Lithuania'), 'the flag and the name');
  assert.ok(s.innerHTML.includes('A 3.43 km'), 'the distance, said with the scenario it belongs to');
  assert.ok(s.innerHTML.includes('#42 of 2 in Europe'));
  // The headline sentence belongs to the card, not to the one row the closed sheet shows.
  assert.ok(!s.innerHTML.includes('the remotest point is'));
});

test('card: the summary follows the scenario', () => {
  setLang('en');
  const unit = { code: 'lt', name_en: 'Lithuania', A: { dist_m: 3426, rank: 42 }, B: { dist_m: 6675, rank: 7 } };
  const s = renderSummary({ unit, units: [unit], doc: { B: { poles: [pole(1)], withheld: 0 } }, scenario: 'B', rank: 1 });
  assert.ok(s.innerHTML.includes('B 6.68 km'));
  assert.ok(s.innerHTML.includes('#7 of 1 in Europe'));
});

test('card: a unit with no result for the scenario summarises the reason and shows no rank', () => {
  setLang('en');
  const unit = { code: 'xx', name_en: 'Nowhere' };
  const s = renderSummary({ unit, units: [unit], doc: { A: { poles: [], withheld: 2 } }, scenario: 'A', rank: 1 });
  assert.ok(s.innerHTML.includes(t('reasonWithheld')));
  assert.ok(!s.innerHTML.includes('card-summary__rank'), 'no rank line where there is no rank');
});

test('card: a unit name carrying markup is escaped in the summary too', () => {
  setLang('en');
  const unit = { code: 'xx', name_en: '<b>Boom</b>', A: { dist_m: 3426, rank: 1 } };
  const s = renderSummary({ unit, units: [unit], doc: { A: { poles: [pole(1)], withheld: 0 } }, scenario: 'A', rank: 1 });
  assert.ok(s.innerHTML.includes('&lt;b&gt;Boom&lt;/b&gt;'));
  assert.ok(!s.innerHTML.includes('<b>Boom</b>'));
});

test('card: with nothing to show the summary is emptied and hidden', () => {
  setLang('en');
  const summary = fakeEl();
  summary.hidden = false;
  createCard(fakeEl(), { ...handlers, summary }).refresh();
  assert.equal(summary.hidden, true);
  assert.equal(summary.innerHTML, '');
});

// Task 10 and 11: the island row on a pole, and the islands toggle that filters the published superset.

test('card: a pole on an island says so, right under the distance, in both languages', () => {
  setLang('en');
  const unit = { code: 'xx', name_en: 'Nowhere', A: { dist_m: 3426, rank: 1 } };
  const view = { unit, units: [unit], doc: { A: { poles: [pole(1, { island_km2: 357.2 })], withheld: 0 } }, scenario: 'A', rank: 1 };
  const en = render(view);
  assert.ok(en.innerHTML.includes('<dt>On an island</dt><dd>357 km\u00B2</dd>'));
  // Right after the distance row and before the road row, which is where the reader is already looking.
  assert.ok(en.innerHTML.indexOf('On an island') > en.innerHTML.indexOf(t('distance')));
  assert.ok(en.innerHTML.indexOf('On an island') < en.innerHTML.indexOf('Nearest road'));
  setLang('lt');
  const lt = render(view);
  assert.ok(lt.innerHTML.includes('<dt>Saloje</dt><dd>357 km\u00B2</dd>'));
  setLang('en');
});

test('card: a pole on the mainland shows no island row, however the field is missing', () => {
  setLang('en');
  const unit = { code: 'xx', name_en: 'Nowhere', A: { dist_m: 3426, rank: 1 } };
  for (const over of [{ island_km2: null }, {}, { island_km2: undefined }]) {
    const el = render({ unit, units: [unit], doc: { A: { poles: [pole(1, over)], withheld: 0 } }, scenario: 'A', rank: 1 });
    assert.ok(!el.innerHTML.includes(t('islandFact')), JSON.stringify(over));
  }
  // And a value that is not a number is not a row either: the row is the number, so there is nothing to escape.
  const hostile = render({ unit, units: [unit], doc: { A: { poles: [pole(1, { island_km2: '<b>357</b>' })], withheld: 0 } }, scenario: 'A', rank: 1 });
  assert.ok(!hostile.innerHTML.includes(t('islandFact')));
  assert.ok(!hostile.innerHTML.includes('<b>357</b>'));
});

test('card: the island area reaches neither the summary row nor the headline', () => {
  setLang('en');
  const unit = { code: 'lt', name_en: 'Lithuania', A: { dist_m: 3426, rank: 42 } };
  const view = { unit, units: [unit], doc: { A: { poles: [pole(1, { island_km2: 357.2 })], withheld: 0 } }, scenario: 'A', rank: 1 };
  const s = renderSummary(view);
  assert.ok(!s.innerHTML.includes('km\u00B2'), 'the sheet handle keeps its three facts');
  const el = render(view);
  assert.ok(!el.innerHTML.split('card__poles')[0].includes('km\u00B2'), 'and so does the headline block');
});

// A published superset for one unit and scenario: two island poles above the first mainland one.
const SUPER = [
  pole(1, { island_km2: 357.2, dist_m: 9000 }),
  pole(2, { island_km2: 12.5, dist_m: 8000 }),
  pole(3, { island_km2: null, dist_m: 7000 }),
  pole(4, { island_km2: null, dist_m: 6000 }),
];
const ISLE_UNIT = { code: 'xx', name_en: 'Nowhere', A: { dist_m: 9000, rank: 1 }, A_mainland: { dist_m: 7000, rank: 4 } };

test('card: the islands toggle renders with the reading it is given pressed', () => {
  setLang('en');
  const on = render({ unit: ISLE_UNIT, units: [ISLE_UNIT], doc: { A: { poles: SUPER, withheld: 0 } }, scenario: 'A', rank: 1, islands: 1 });
  assert.ok(on.innerHTML.includes('<span class="card__islands-label" id="islands-label">Islands</span>'));
  assert.ok(on.innerHTML.includes('data-i="1" aria-pressed="true">Included'));
  assert.ok(on.innerHTML.includes('data-i="0" aria-pressed="false">Excluded'));
  const off = render({ unit: ISLE_UNIT, units: [ISLE_UNIT], doc: { A: { poles: SUPER, withheld: 0 } }, scenario: 'A', rank: 3, islands: 0 });
  assert.ok(off.innerHTML.includes('data-i="1" aria-pressed="false">Included'));
  assert.ok(off.innerHTML.includes('data-i="0" aria-pressed="true">Excluded'));
  // A caller that says nothing about islands gets the whole superset, which is the default reading.
  const dflt = render({ unit: ISLE_UNIT, units: [ISLE_UNIT], doc: { A: { poles: SUPER, withheld: 0 } }, scenario: 'A', rank: 1 });
  assert.ok(dflt.innerHTML.includes('data-i="1" aria-pressed="true">Included'));
});

test('card: with the islands hidden the headline follows the mainland summary', () => {
  setLang('en');
  const other = { code: 'yy', name_en: 'Elsewhere', A: { dist_m: 5000, rank: 2 }, A_mainland: { dist_m: 5000, rank: 1 } };
  const units = [ISLE_UNIT, other];
  const on = render({ unit: ISLE_UNIT, units, doc: { A: { poles: SUPER, withheld: 0 } }, scenario: 'A', rank: 1, islands: 1 });
  assert.ok(on.innerHTML.includes('9.00 km'));
  assert.ok(on.innerHTML.includes('#1 of 2 in Europe'));
  const off = render({ unit: ISLE_UNIT, units, doc: { A: { poles: SUPER, withheld: 0 } }, scenario: 'A', rank: 3, islands: 0 });
  assert.ok(off.innerHTML.includes('7.00 km'), 'the best mainland distance');
  assert.ok(off.innerHTML.includes('#4 of 2 in Europe'), 'and its rank among the units that have one');
});

test('card: the chips are 1..n in what is shown while the selection stays the overall rank', () => {
  setLang('en');
  const on = render({ unit: ISLE_UNIT, units: [ISLE_UNIT], doc: { A: { poles: SUPER, withheld: 0 } }, scenario: 'A', rank: 1, islands: 1 });
  assert.ok(on.innerHTML.includes('data-rank="1" aria-pressed="true">1<'));
  assert.ok(on.innerHTML.includes('data-rank="4" aria-pressed="false">4<'));
  assert.ok(on.innerHTML.includes('Pole 1'));
  assert.ok(on.innerHTML.includes('of 4'));

  const off = render({ unit: ISLE_UNIT, units: [ISLE_UNIT], doc: { A: { poles: SUPER, withheld: 0 } }, scenario: 'A', rank: 3, islands: 0 });
  // Two poles left, numbered 1 and 2, and their buttons still carry ranks 3 and 4: the rank is the pole's
  // identity and what the detail raster was keyed from, the number on the chip is only a label.
  assert.ok(off.innerHTML.includes('data-rank="3" aria-pressed="true">1<'));
  assert.ok(off.innerHTML.includes('data-rank="4" aria-pressed="false">2<'));
  assert.ok(!off.innerHTML.includes('data-rank="1"'), 'the island poles are gone from the chips');
  assert.ok(off.innerHTML.includes('Pole 1'), 'the heading says the place in what is shown');
  assert.ok(off.innerHTML.includes('of 2'));
  assert.ok(!off.innerHTML.includes(t('islandFact')), 'and no island row can be reached');
});

test('card: a unit with no mainland summary says why rather than throwing', () => {
  setLang('en');
  // Every pole of this unit is on an island, so the publish stage wrote no A_mainland at all.
  const unit = { code: 'xx', name_en: 'Nowhere', A: { dist_m: 9000, rank: 1 } };
  const poles = [pole(1, { island_km2: 357.2 }), pole(2, { island_km2: 12.5 })];
  const el = render({ unit, units: [unit], doc: { A: { poles, withheld: 0 } }, scenario: 'A', rank: 1, islands: 0 });
  assert.ok(el.innerHTML.includes(t('reasonNone')));
  assert.ok(!el.innerHTML.includes('the remotest point is'));
  assert.ok(!el.innerHTML.includes('card__pole-title'), 'and there is no pole left to show');
  // The toggle is still there: it is a region-wide reading, not a property of the unit on screen.
  assert.ok(el.innerHTML.includes('data-i="0" aria-pressed="true"'));
  const s = renderSummary({ unit, units: [unit], doc: { A: { poles, withheld: 0 } }, scenario: 'A', rank: 1, islands: 0 });
  assert.ok(s.innerHTML.includes(t('reasonNone')));
});

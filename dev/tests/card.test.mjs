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

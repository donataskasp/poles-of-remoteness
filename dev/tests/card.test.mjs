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

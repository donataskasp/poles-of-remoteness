import test from 'node:test';
import assert from 'node:assert/strict';
import { pickLang, setLang, getLang, t, regionName, regionLabel, unitName, flag, fmtDist, fmtKmExact, fmtKm2, fmtInt, highwayLabel, placeLabel, esc } from '../../site/js/i18n.js';

test('i18n: pickLang order is hash, stored, browser, default en', () => {
  assert.equal(pickLang({ hash: 'lt', stored: 'en', navigator: { languages: ['en-GB'] } }), 'lt');
  assert.equal(pickLang({ hash: null, stored: 'lt', navigator: { languages: ['en-GB'] } }), 'lt');
  assert.equal(pickLang({ hash: null, stored: null, navigator: { languages: ['lt-LT', 'en'] } }), 'lt');
  assert.equal(pickLang({ hash: null, stored: null, navigator: { languages: ['de'] } }), 'en');
  assert.equal(pickLang({ hash: 'xx', stored: 'yy', navigator: { languages: [] } }), 'en');
});

test('i18n: t substitutes and falls back', () => {
  setLang('lt');
  assert.equal(getLang(), 'lt');
  assert.equal(t('rankOf', { rank: 3, count: 52, region: 'Europa' }), '3 vieta iš 52 (Europa)');
  assert.equal(t('no-such-key'), 'no-such-key');
  setLang('en');
  assert.equal(t('rankOf', { rank: 3, count: 52, region: 'Europe' }), '#3 of 52 in Europe');
  assert.equal(setLang('xx'), 'en');
});

test('i18n: names and flags', () => {
  setLang('en');
  assert.equal(regionName('lt'), 'Lithuania');
  assert.equal(regionName('lt', 'lt'), 'Lietuva');
  assert.equal(regionName('us-ak'), null);
  assert.equal(unitName({ code: 'us-ak', name: 'Alaska', name_en: 'Alaska' }), 'Alaska');
  assert.equal(unitName({ code: 'lt', name: 'Lietuva', name_en: 'Lithuania' }, 'lt'), 'Lietuva');
  assert.equal(flag('lt'), '\u{1F1F1}\u{1F1F9}');
  assert.equal(flag('us-ak'), '');
});

test('i18n: regionLabel reads the name for the language from the region, falling back to the data name', () => {
  assert.equal(regionName('150'), null);                      // M49 codes stay out: browsers echo them unchanged
  const eu = { id: 'europe', name: 'Europe', names: { lt: 'Europa' } };
  assert.equal(regionLabel(eu, 'lt'), 'Europa');
  assert.equal(regionLabel(eu, 'en'), 'Europe');
  assert.equal(regionLabel({ name: 'North America', names: {} }, 'lt'), 'North America');
  assert.equal(regionLabel({ id: 'north-america' }, 'lt'), 'north-america');
});

test('i18n: distances', () => {
  setLang('en');
  assert.equal(fmtDist(437), '440 m');
  assert.equal(fmtDist(1240), '1.2 km');
  assert.equal(fmtDist(9960), '10 km');
  assert.equal(fmtDist(23500), '24 km');
  assert.equal(fmtDist(999), '1.0 km');
  assert.equal(fmtDist(1000), '1.0 km');
  assert.equal(fmtDist(9949), '9.9 km');
  assert.equal(fmtDist(10000), '10 km');
  assert.equal(fmtKmExact(3406.4), '3.41 km');
  assert.equal(fmtInt(1234567), '1,234,567');
  setLang('lt');
  assert.equal(fmtDist(1240), '1,2 km');
  assert.equal(fmtDist(1000), '1,0 km');
  assert.equal(fmtInt(1234567), '1\u00A0234\u00A0567');
  assert.equal(placeLabel('village'), 'kaimas');
  assert.equal(highwayLabel('track'), 'miško ar lauko keliukas');
  setLang('en');
  assert.equal(highwayLabel('track'), 'track');
  assert.equal(highwayLabel('bus_guideway'), 'bus_guideway');
  assert.equal(placeLabel('nowhere'), 'nowhere');
});

test('i18n: an exact kilometre needs a number to format', () => {
  setLang('en');
  assert.equal(fmtKmExact(3426), '3.43 km');
  // A published summary can carry no distance at all (a scenario with no result for the unit). Say nothing
  // rather than "NaN km"; the caller decides what stands in its place.
  assert.equal(fmtKmExact(null), '');
  assert.equal(fmtKmExact(undefined), '');
  assert.equal(fmtKmExact(Infinity), '');
});

// One escape for the whole site: card.js and ranking.js both build HTML strings and both import this.
test('i18n: esc neutralises every character that can end an HTML context', () => {
  assert.equal(esc('<script>alert("x")</script>'), '&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;');
  assert.equal(esc("O'Brien & Co"), 'O&#39;Brien &amp; Co');
  assert.equal(esc(42), '42');
  assert.equal(esc(null), 'null');
});

test('i18n: language values are case-normalised', () => {
  assert.equal(pickLang({ hash: 'LT' }), 'lt');
  assert.equal(pickLang(), 'en');
  assert.equal(setLang('LT'), 'lt');
  assert.equal(setLang(42), 'en');
});

test('i18n: an island area is one decimal under ten and none above, in both locales', () => {
  setLang('en');
  assert.equal(fmtKm2(357.2), '357 km\u00B2');
  assert.equal(fmtKm2(3.14), '3.1 km\u00B2');
  assert.equal(fmtKm2(9.9), '9.9 km\u00B2');
  assert.equal(fmtKm2(10), '10 km\u00B2');
  // The same 9.95 guard fmtDist uses: rounding up to ten prints as ten, never as 10.0.
  assert.equal(fmtKm2(9.96), '10 km\u00B2');
  assert.equal(fmtKm2(1234.5), '1,235 km\u00B2');   // rounded, not truncated
  setLang('lt');
  assert.equal(fmtKm2(3.14), '3,1 km\u00B2');
  assert.equal(fmtKm2(1234.5), '1\u00A0235 km\u00B2');
  setLang('en');
  // A unit with no island area has nothing to say, exactly as fmtKmExact does with no distance.
  assert.equal(fmtKm2(null), '');
  assert.equal(fmtKm2(undefined), '');
  assert.equal(fmtKm2(Infinity), '');
});

test('i18n: the island and toggle strings are said in both languages', () => {
  // t() falls back to English for a key the active language is missing, so an lt reading equal to the en one
  // is exactly how a half-added key shows up. All four differ, so all four are really there.
  const keys = ['islandFact', 'islandsGroup', 'islandsOn', 'islandsOff'];
  setLang('en');
  const en = keys.map((k) => t(k));
  setLang('lt');
  const lt = keys.map((k) => t(k));
  assert.deepEqual(en, ['On an island', 'Islands', 'Included', 'Excluded']);
  assert.deepEqual(lt, ['Saloje', 'Salos', '\u012Eskaitomos', 'Ne\u012Fskaitomos']);
  keys.forEach((k, n) => assert.notEqual(en[n], lt[n], `${k} falls back to English`));
  setLang('en');
});

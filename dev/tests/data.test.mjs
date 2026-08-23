import test from 'node:test';
import assert from 'node:assert/strict';
import { getJSON, r2Url, archiveUrl, detailUrl, winner, bboxToBounds, pickStart, unitAt } from '../../site/js/data.js';

const region = { id: 'europe', name: 'Europe', snapshot: '2026-08-19', r2_base: 'https://pub-x.r2.dev/' };
const na = { id: 'north-america', name: 'North America', snapshot: '2026-08-19', r2_base: 'https://pub-x.r2.dev' };
const u = (code, country, rankA, rankB = rankA) => ({ code, country, name: code, name_en: code, bbox: [0, 0, 1, 1],
  A: rankA == null ? null : { dist_m: 10000 / rankA, lat: 0, lon: 0, rank: rankA, withheld: 0 },
  B: rankB == null ? null : { dist_m: 9000 / rankB, lat: 0, lon: 0, rank: rankB, withheld: 0 } });
const EU = [u('lt', 'lt', 3), u('no', 'no', 1), u('is', 'is', 2), u('ge', 'ge', null, 4)];
const NA = [u('us-ak', 'us', 1), u('ca-nu', 'ca', 2), u('us-wy', 'us', 3)];
const load = async (id) => (id === 'europe' ? EU : NA);
const regions = [region, na];
const none = { country: null, region: null };

test('data: urls', () => {
  assert.equal(r2Url(region, 'A.pmtiles'), 'https://pub-x.r2.dev/europe/2026-08-19/A.pmtiles');
  assert.equal(archiveUrl(na, 'B'), 'https://pub-x.r2.dev/north-america/2026-08-19/B.pmtiles');
  assert.equal(detailUrl(region, { detail: 'detail/lt/A-1' }, 'png'), 'https://pub-x.r2.dev/europe/2026-08-19/detail/lt/A-1.png');
  assert.deepEqual(bboxToBounds([20.9, 53.8, 26.8, 56.4]), [[53.8, 20.9], [56.4, 26.8]]);
  assert.throws(() => detailUrl(region, { rank: 1 }, 'png'), /pole has no detail/);
});

test('data: winner and ranks', () => {
  assert.equal(winner(EU).code, 'no');
  assert.equal(winner(EU, 'B').code, 'no');
  assert.equal(winner([u('x', 'x', null, null)]).code, 'x');
  assert.equal(winner([]), null);
});

test('data: pickStart follows the fallback order', async () => {
  assert.deepEqual(await pickStart({ region: 'europe', unit: 'lt' }, none, regions, load), { region: 'europe', unit: 'lt' });
  assert.deepEqual(await pickStart({ region: 'europe', unit: 'zz' }, none, regions, load), { region: 'europe', unit: 'no' });
  assert.deepEqual(await pickStart({ region: 'europe', unit: null }, none, regions, load), { region: 'europe', unit: 'no' });
  assert.deepEqual(await pickStart({ region: 'mars', unit: null }, { country: 'lt', region: null }, regions, load), { region: 'europe', unit: 'lt' });
  assert.deepEqual(await pickStart({ region: null, unit: null }, { country: 'us', region: 'ak' }, regions, load), { region: 'north-america', unit: 'us-ak' });
  assert.deepEqual(await pickStart({ region: null, unit: null }, { country: 'us', region: 'tx' }, regions, load), { region: 'north-america', unit: 'us-ak' });
  assert.deepEqual(await pickStart({ region: null, unit: null }, { country: 'ca', region: null }, regions, load), { region: 'north-america', unit: 'us-ak' });
  assert.deepEqual(await pickStart({ region: null, unit: null }, { country: 'jp', region: null }, regions, load), { region: 'europe', unit: 'no' });
  assert.deepEqual(await pickStart({ region: null, unit: null }, none, regions, load), { region: 'europe', unit: 'no' });
  assert.deepEqual(await pickStart({ region: 'europe', unit: 'lt' }, none, regions, async () => []), { region: 'europe', unit: null });
});

test('data: getJSON caches successes and evicts failures', async () => {
  let calls = 0;
  const fetchFn = async (url) => { calls += 1; return { ok: !url.includes('bad'), status: url.includes('bad') ? 404 : 200, json: async () => ({ url }) }; };
  assert.deepEqual(await getJSON('/x.json', fetchFn), { url: '/x.json' });
  await getJSON('/x.json', fetchFn);
  assert.equal(calls, 1);
  await assert.rejects(getJSON('/bad.json', fetchFn), /HTTP 404/);
  await assert.rejects(getJSON('/bad.json', fetchFn), /HTTP 404/);
  assert.equal(calls, 3);
});

test('data: unitAt picks the smallest unit whose bbox contains the point', () => {
  const units = [
    { code: 'fr', area_km2: 550000, bbox: [-5, 41, 10, 51] },
    { code: 'ad', area_km2: 468, bbox: [1.4, 42.4, 1.8, 42.7] },
  ];
  assert.equal(unitAt(units, { lat: 42.5, lng: 1.5 }).code, 'ad');
  assert.equal(unitAt(units, { lat: 48.8, lng: 2.3 }).code, 'fr');
  assert.equal(unitAt(units, { lat: 60, lng: 20 }), null);
});

// Bboxes as they really overlap in the Baltics: Latvia's south edge reaches into the northern third of
// Lithuania and Belarus's bbox reaches over both, so a point near Utena hits three units.
const BALTIC = [
  { code: 'lv', country: 'LV', area_km2: 64407, bbox: [20.97, 55.67, 28.24, 58.09] },
  { code: 'lt', country: 'LT', area_km2: 64833, bbox: [20.95, 53.89, 26.87, 56.45] },
  { code: 'by', country: 'BY', area_km2: 207273, bbox: [23.18, 51.26, 32.77, 56.17] },
];
// Two units of one country over one point plus a smaller unit of another, in the North American shape
// (unit code 'us-ak', country 'us'). Areas and bboxes here are made up to force the overlap.
const NESTED = [
  { code: 'us-ak', country: 'US', area_km2: 1723337, bbox: [-150, 60, -130, 70] },
  { code: 'us-wy', country: 'US', area_km2: 253335, bbox: [-145, 62, -135, 68] },
  { code: 'ca-yt', country: 'CA', area_km2: 100000, bbox: [-144, 63, -136, 67] },
];

test('data: unitAt prefers a hit in the visitor country, then the smallest area', () => {
  const utena = { lat: 55.9, lng: 25.0 }; // in Lithuania, inside the lv, lt and by bboxes
  assert.equal(unitAt(BALTIC, utena, 'lt').code, 'lt');
  assert.equal(unitAt(BALTIC, utena).code, 'lv'); // no visitor country: the smallest area wins
  assert.equal(unitAt(BALTIC, utena, 'fr').code, 'lv'); // a country none of the hits is in: same fallback
  const north = { lat: 65, lng: -140 };
  assert.equal(unitAt(NESTED, north).code, 'ca-yt');
  assert.equal(unitAt(NESTED, north, 'us').code, 'us-wy'); // inside the country the area rule decides
  assert.equal(unitAt(BALTIC, { lat: 60, lng: 20 }, 'lt'), null);
});

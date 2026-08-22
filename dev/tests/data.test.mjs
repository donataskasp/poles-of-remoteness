import test from 'node:test';
import assert from 'node:assert/strict';
import { getJSON, r2Url, archiveUrl, detailUrl, winner, bboxToBounds, pickStart } from '../../site/js/data.js';

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

import test from 'node:test';
import assert from 'node:assert/strict';
import { parse, toUrl, visitor } from '../../site/js/router.js';

const loc = (pathname, hash = '') => ({ pathname, hash });

test('router: parse path and hash', () => {
  assert.deepEqual(parse(loc('/')), { region: null, unit: null, z: null, lat: null, lon: null, s: null, b: null, l: null });
  const p = parse(loc('/Europe/LT', '#z=9.5&lat=55.12345&lon=24.5&s=B&b=osm&l=lt&junk=1'));
  assert.deepEqual(p, { region: 'europe', unit: 'lt', z: 9.5, lat: 55.12345, lon: 24.5, s: 'B', b: 'osm', l: 'lt' });
  assert.deepEqual(parse(loc('/europe/us-ak/', '#z=99&lat=abc&s=C&b=x&l=fr')),
    { region: 'europe', unit: 'us-ak', z: null, lat: null, lon: null, s: null, b: null, l: null });
  assert.equal(parse(loc('/../etc')).region, null);
  assert.equal(parse(loc('/%E2%82%AC')).region, null);
});

test('router: toUrl round-trips and rounds', () => {
  const url = toUrl({ region: 'europe', unit: 'lt', z: 9.123456, lat: 55.1234567, lon: 24.5, s: 'A', b: 'sat', l: 'en' });
  assert.equal(url, '/europe/lt#z=9.12&lat=55.12346&lon=24.50000&s=A&b=sat&l=en');
  assert.deepEqual(parse(loc('/europe/lt', url.slice(url.indexOf('#')))),
    { region: 'europe', unit: 'lt', z: 9.12, lat: 55.12346, lon: 24.5, s: 'A', b: 'sat', l: 'en' });
  assert.equal(toUrl({ region: null, unit: null }), '/');
  assert.equal(toUrl({ region: 'europe', unit: null, s: 'B' }), '/europe#s=B');
});

test('router: visitor meta', () => {
  const doc = (content) => ({ querySelector: () => (content == null ? null : { getAttribute: () => content }) });
  assert.deepEqual(visitor(doc('LT')), { country: 'lt', region: null });
  assert.deepEqual(visitor(doc('US-AK')), { country: 'us', region: 'ak' });
  assert.deepEqual(visitor(doc('')), { country: null, region: null });
  assert.deepEqual(visitor(doc(null)), { country: null, region: null });
  assert.deepEqual(visitor(doc('<script>')), { country: null, region: null });
});

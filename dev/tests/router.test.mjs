import test from 'node:test';
import assert from 'node:assert/strict';
import { parse, toUrl, write, visitor, changedState, ISLANDS } from '../../site/js/router.js';

const loc = (pathname, hash = '') => ({ pathname, hash });

test('router: parse path and hash', () => {
  assert.deepEqual(parse(loc('/')), { region: null, unit: null, z: null, lat: null, lon: null, s: null, b: null, i: null, l: null });
  const p = parse(loc('/Europe/LT', '#z=9.5&lat=55.12345&lon=24.5&s=B&b=osm&i=0&l=lt&junk=1'));
  assert.deepEqual(p, { region: 'europe', unit: 'lt', z: 9.5, lat: 55.12345, lon: 24.5, s: 'B', b: 'osm', i: 0, l: 'lt' });
  assert.deepEqual(parse(loc('/europe/us-ak/', '#z=99&lat=abc&s=C&b=x&i=2&l=fr')),
    { region: 'europe', unit: 'us-ak', z: null, lat: null, lon: null, s: null, b: null, i: null, l: null });
  assert.equal(parse(loc('/../etc')).region, null);
  assert.equal(parse(loc('/%E2%82%AC')).region, null);
});

test('router: a unit without a valid region is dropped at both ends', () => {
  assert.deepEqual(parse(loc('/../etc')), { region: null, unit: null, z: null, lat: null, lon: null, s: null, b: null, i: null, l: null });
  assert.equal(parse(loc('/9bad/lt')).unit, null);
  assert.equal(parse(loc('/europe/lt/extra')).unit, 'lt');
  assert.equal(toUrl({ region: null, unit: 'lt' }), '/');
});

test('router: hash numbers are shape-checked and names case-normalised', () => {
  const empty = parse(loc('/', '#z=&lat=&lon='));
  assert.deepEqual([empty.z, empty.lat, empty.lon], [null, null, null]);
  assert.equal(parse(loc('/', '#z=0x10')).z, null);
  assert.equal(parse(loc('/', '#z=1e1')).z, null);
  assert.equal(parse(loc('/', '#lat=-55.5')).lat, -55.5);
  const norm = parse(loc('/', '#s=a&b=SAT&l=EN'));
  assert.deepEqual([norm.s, norm.b, norm.l], ['A', 'sat', 'en']);
});

test('router: write pushes, keeps the query and no-ops when unchanged', () => {
  const calls = [];
  const history = { pushState: (a, b, url) => calls.push(['push', url]), replaceState: (a, b, url) => calls.push(['replace', url]) };
  const location = { pathname: '/europe/lt', search: '?utm_source=x', hash: '' };
  const state = { region: 'europe', unit: 'lt', s: 'B' };
  assert.equal(write(state, { history, location }), true);
  assert.deepEqual(calls, [['push', '/europe/lt?utm_source=x#s=B']]);
  location.hash = '#s=B';
  assert.equal(write(state, { history, location }), false);
  assert.equal(calls.length, 1);
  assert.equal(write({ region: 'europe', unit: 'lt', s: 'A' }, { replace: true, history, location }), true);
  assert.deepEqual(calls[1], ['replace', '/europe/lt?utm_source=x#s=A']);
});

test('router: toUrl round-trips and rounds', () => {
  const url = toUrl({ region: 'europe', unit: 'lt', z: 9.123456, lat: 55.1234567, lon: 24.5, s: 'A', b: 'sat', i: 1, l: 'en' });
  assert.equal(url, '/europe/lt#z=9.12&lat=55.12346&lon=24.50000&s=A&b=sat&i=1&l=en');
  assert.deepEqual(parse(loc('/europe/lt', url.slice(url.indexOf('#')))),
    { region: 'europe', unit: 'lt', z: 9.12, lat: 55.12346, lon: 24.5, s: 'A', b: 'sat', i: 1, l: 'en' });
  assert.equal(toUrl({ region: null, unit: null }), '/');
  assert.equal(toUrl({ region: 'europe', unit: null, s: 'B' }), '/europe#s=B');
});

test('router: the basemap and the language survive the round trip too', () => {
  // The defaults are covered above; these are the values a reader has to switch to before Back can lose them.
  const url = toUrl({ region: 'europe', unit: 'lt', s: 'B', b: 'osm', l: 'lt' });
  assert.equal(url, '/europe/lt#s=B&b=osm&l=lt');
  const back = parse(loc('/europe/lt', url.slice(url.indexOf('#'))));
  assert.deepEqual([back.s, back.b, back.l], ['B', 'osm', 'lt']);
});

test('router: changedState names only the keys a history entry actually changes', () => {
  const state = { region: 'europe', unit: 'lt', s: 'A', b: 'sat', i: 1, l: 'en' };
  assert.deepEqual(changedState(parse(loc('/europe/lt', '#s=A&b=sat&i=1&l=en')), state), {});
  assert.deepEqual(changedState(parse(loc('/europe/lt', '#s=B&b=osm&i=0&l=lt')), state), { s: 'B', b: 'osm', i: 0, l: 'lt' });
  assert.deepEqual(changedState(parse(loc('/europe/no', '#s=A&b=sat&i=1&l=en')), state), { unit: 'no' });
  // A key the URL does not carry keeps what is on screen: an entry written before the key existed, or a
  // hand-typed link, must not reset the basemap or the language to a default nobody asked for.
  assert.deepEqual(changedState(parse(loc('/europe/lt')), state), {});
});

test('router: the islands key reads 1, 0 and nothing else, and 0 is a value like any other', () => {
  assert.deepEqual(ISLANDS, [1, 0]);
  assert.equal(parse(loc('/europe/lt', '#i=1')).i, 1);
  assert.equal(parse(loc('/europe/lt', '#i=0')).i, 0);
  // Absent, empty, out of range, and the shapes a hand-typed link tends to carry: all of them mean "not said",
  // and app.js turns that into the default reading rather than the router guessing here.
  assert.equal(parse(loc('/europe/lt')).i, null);
  for (const raw of ['', '2', '-1', 'true', 'yes', '01', '1.0']) {
    assert.equal(parse(loc('/europe/lt', `#i=${raw}`)).i, null, `i=${raw}`);
  }
});

test('router: toUrl writes the islands key whenever it is set, hidden as well as shown', () => {
  // Between b and l, and written for 0 too: the site always carries the key, which is what lets changedState
  // restore it with no exception of its own (a toggle whose absent key means "keep what is on screen" cannot
  // be restored by Back at all).
  assert.equal(toUrl({ region: 'europe', unit: 'lt', s: 'B', b: 'osm', i: 0, l: 'lt' }), '/europe/lt#s=B&b=osm&i=0&l=lt');
  assert.equal(toUrl({ region: 'europe', unit: 'lt', i: 1 }), '/europe/lt#i=1');
  assert.equal(toUrl({ region: 'europe', unit: 'lt' }), '/europe/lt');
  const back = parse(loc('/europe/lt', '#s=B&b=osm&i=0&l=lt'));
  assert.deepEqual([back.s, back.b, back.i, back.l], ['B', 'osm', 0, 'lt']);
});

test('router: back and forward restore the islands reading in both directions', () => {
  const shown = { region: 'europe', unit: 'lt', s: 'A', b: 'sat', i: 1, l: 'en' };
  const hidden = { ...shown, i: 0 };
  assert.deepEqual(changedState(parse(loc('/europe/lt', '#s=A&b=sat&i=0&l=en')), shown), { i: 0 });
  assert.deepEqual(changedState(parse(loc('/europe/lt', '#s=A&b=sat&i=1&l=en')), hidden), { i: 1 });
  // An entry written before the key existed keeps what is on screen, like every other key.
  assert.deepEqual(changedState(parse(loc('/europe/lt', '#s=A&b=sat&l=en')), hidden), {});
});

test('router: visitor meta', () => {
  const doc = (content) => ({ querySelector: () => (content == null ? null : { getAttribute: () => content }) });
  assert.deepEqual(visitor(doc('LT')), { country: 'lt', region: null });
  assert.deepEqual(visitor(doc('US-AK')), { country: 'us', region: 'ak' });
  assert.deepEqual(visitor(doc('')), { country: null, region: null });
  assert.deepEqual(visitor(doc(null)), { country: null, region: null });
  assert.deepEqual(visitor(doc('<script>')), { country: null, region: null });
});

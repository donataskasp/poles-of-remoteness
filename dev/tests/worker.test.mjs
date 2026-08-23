import test from 'node:test';
import assert from 'node:assert/strict';
import { browserFamily, osFamily, referrerHost, landing, visitorCode } from '../../worker.js';

test('worker: browser and OS families are coarse', () => {
  const ua = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36';
  assert.equal(browserFamily(ua), 'Chrome');
  assert.equal(osFamily(ua), 'Android');
  assert.equal(browserFamily('curl/8.4.0'), 'Bot');
  // A client that sends no User-Agent buckets as Other, never as a bot.
  assert.equal(browserFamily(''), 'Other');
  assert.equal(osFamily(''), 'Other');
});

test('worker: referrer host strips www and hides own host', () => {
  const url = new URL('https://example.workers.dev/europe/lt');
  const req = (ref) => new Request(url, { headers: ref ? { referer: ref } : {} });
  assert.equal(referrerHost(req('https://www.linkedin.com/feed/'), url), 'linkedin.com');
  assert.equal(referrerHost(req('https://example.workers.dev/'), url), '');
  assert.equal(referrerHost(req(null), url), '');
  // A referrer that does not parse is dropped, it never reaches Analytics Engine raw.
  assert.equal(referrerHost(req('not a url'), url), '');
});

test('worker: landing parses the page paths only', () => {
  assert.deepEqual(landing('/'), { page: true, region: '', unit: '' });
  assert.deepEqual(landing('/europe'), { page: true, region: 'europe', unit: '' });
  assert.deepEqual(landing('/europe/lt/'), { page: true, region: 'europe', unit: 'lt' });
  assert.equal(landing('/europe/lt/extra').page, false);
  assert.equal(landing('/Europe').page, false);
  assert.equal(landing('/js/app.js').page, false);
  assert.equal(landing('/index.html').page, false);
});

test('worker: visitor code is country plus region code, or nothing', () => {
  assert.equal(visitorCode({ country: 'LT', regionCode: 'VL' }), 'LT-VL');
  assert.equal(visitorCode({ country: 'us', regionCode: 'ak' }), 'US-AK');
  assert.equal(visitorCode({ country: 'LT' }), 'LT');
  assert.equal(visitorCode({ country: 'T1' }), '');
  assert.equal(visitorCode({ country: 'XX', regionCode: '"><script>' }), 'XX');
  assert.equal(visitorCode(undefined), '');
});

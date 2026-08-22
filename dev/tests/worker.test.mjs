import test from 'node:test';
import assert from 'node:assert/strict';
import { browserFamily, osFamily, referrerHost } from '../../worker.js';

test('worker: browser and OS families are coarse', () => {
  const ua = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36';
  assert.equal(browserFamily(ua), 'Chrome');
  assert.equal(osFamily(ua), 'Android');
  assert.equal(browserFamily('curl/8.4.0'), 'Bot');
});

test('worker: referrer host strips www and hides own host', () => {
  const url = new URL('https://example.workers.dev/europe/lt');
  const req = (ref) => new Request(url, { headers: ref ? { referer: ref } : {} });
  assert.equal(referrerHost(req('https://www.linkedin.com/feed/'), url), 'linkedin.com');
  assert.equal(referrerHost(req('https://example.workers.dev/'), url), '');
  assert.equal(referrerHost(req(null), url), '');
});

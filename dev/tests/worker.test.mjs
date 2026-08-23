import test from 'node:test';
import assert from 'node:assert/strict';
import worker, { browserFamily, osFamily, referrerHost, landing, visitorCode } from '../../worker.js';

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
  assert.deepEqual(landing('/europe/lt'), { page: true, region: 'europe', unit: 'lt' });
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

// The default export against a fake assets binding and a writeDataPoint spy. request.cf is undefined in
// Node, so visitorCode returns '' and the HTMLRewriter branch is never reached.
async function drive(path, asset) {
  const rows = [];
  const env = {
    ASSETS: { fetch: async () => asset },
    SITE_VIEWS: { writeDataPoint: (row) => rows.push(row) },
  };
  const res = await worker.fetch(new Request(`https://example.workers.dev${path}`), env);
  return { rows, res };
}

test('worker: a 304 on a page path is a view and is passed through', async () => {
  const { rows, res } = await drive('/europe/lt', new Response(null, { status: 304, headers: { ETag: '"x"' } }));
  assert.equal(rows.length, 1);
  assert.equal(rows[0].blobs[6], 'europe');
  assert.equal(rows[0].blobs[7], 'lt');
  assert.equal(res.status, 304);
});

test('worker: an HTML page load is one view', async () => {
  const html = new Response('<html><head></head><body></body></html>', { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
  const { rows, res } = await drive('/europe/lt', html);
  assert.equal(rows.length, 1);
  assert.equal(res.status, 200);
});

test('worker: a non-HTML answer on a page path is not a view', async () => {
  const js = new Response('export {};', { status: 200, headers: { 'Content-Type': 'text/javascript' } });
  const { rows, res } = await drive('/', js);
  assert.equal(rows.length, 0);
  assert.equal(res.status, 200);
});

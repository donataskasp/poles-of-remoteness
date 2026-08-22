import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { startServer, inside } from '../serve.mjs';

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'poles-serve-'));
  const site = join(root, 'site');
  const data = join(root, 'data');
  const r2 = join(root, 'r2');
  mkdirSync(join(site, 'data'), { recursive: true });
  mkdirSync(join(data, 'europe'), { recursive: true });
  mkdirSync(r2, { recursive: true });
  writeFileSync(join(site, 'index.html'), '<!doctype html><title>x</title>');
  writeFileSync(join(site, 'data', 'regions.json'), '{"from":"site"}');
  writeFileSync(join(site, 'data', 'site-only.json'), '{"from":"site"}');
  writeFileSync(join(data, 'regions.json'), '{"from":"dev"}');
  writeFileSync(join(r2, 'A.pmtiles'), Buffer.from('0123456789abcdef'));
  return { site, data, r2 };
}

test('serve: SPA fallback, dev data first, range on r2', async () => {
  const { site, data, r2 } = fixture();
  const server = await startServer({ site, data, r2, r2Prefix: 'europe/2026-08-19', port: 0 });
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const page = await fetch(`${base}/europe/lt`);
    assert.equal(page.status, 200);
    assert.match(page.headers.get('content-type'), /text\/html/);
    assert.equal(await page.text(), '<!doctype html><title>x</title>');

    const regions = await fetch(`${base}/data/regions.json`);
    assert.equal((await regions.json()).from, 'dev');

    const missing = await fetch(`${base}/js/nope.js`);
    assert.equal(missing.status, 404);

    const range = await fetch(`${base}/r2/europe/2026-08-19/A.pmtiles`, { headers: { Range: 'bytes=2-5' } });
    assert.equal(range.status, 206);
    assert.equal(range.headers.get('content-range'), 'bytes 2-5/16');
    assert.equal(range.headers.get('access-control-allow-origin'), '*');
    assert.equal(await range.text(), '2345');

    const whole = await fetch(`${base}/r2/europe/2026-08-19/A.pmtiles`);
    assert.equal(whole.status, 200);
    assert.equal(whole.headers.get('accept-ranges'), 'bytes');
    assert.equal((await whole.arrayBuffer()).byteLength, 16);

    const outside = await fetch(`${base}/r2/europe/2026-08-19/../../etc/passwd`);
    assert.equal(outside.status, 404);

    const siteOnly = await fetch(`${base}/data/site-only.json`);
    assert.equal((await siteOnly.json()).from, 'site');

    const malformed = await fetch(`${base}/%`);
    assert.equal(malformed.status, 500);
    const still = await fetch(`${base}/data/regions.json`);
    assert.equal(still.status, 200);
  } finally {
    server.close();
  }
});

test('inside: resolves under the root and refuses escapes', () => {
  const root = join(tmpdir(), 'poles-root');
  assert.equal(inside(root, '/a/b.json'), join(root, 'a', 'b.json'));
  assert.equal(inside(root, '/'), root);
  assert.equal(inside(root, '/../secret.txt'), null);
  assert.equal(inside(root, '/a/../../secret.txt'), null);
});

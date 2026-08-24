#!/usr/bin/env node
// Development server for the site. Three roots on one origin so the browser needs no CORS and the dev
// JSON can point its r2_base at this same server:
//   /            the site directory, extension-less paths fall back to index.html (the SPA rule the
//                Workers assets binding applies in production)
//   /data/*      the dev JSON directory first (written by dev/site-json.py), then site/data
//   /r2/<prefix>/<rest>   a local publish directory, served with HTTP ranges like R2 does
// Usage: node dev/serve.mjs --site site --data dev/out/site --r2 work/<region>/<snapshot>/publish \
//          --r2-prefix <region>/<snapshot> [--port 8000]
import http from 'node:http';
import { createReadStream, statSync } from 'node:fs';
import { join, resolve, extname, sep } from 'node:path';

const TYPES = {
  '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.pmtiles': 'application/octet-stream', '.txt': 'text/plain; charset=utf-8',
};

export function inside(root, rel) {
  const p = resolve(root, '.' + rel);
  return p === root || p.startsWith(root + sep) ? p : null;
}

function fileInfo(path) {
  try {
    const st = statSync(path);
    return st.isFile() ? st : null;
  } catch {
    return null;
  }
}

function send(req, res, path, st) {
  const type = TYPES[extname(path).toLowerCase()] || 'application/octet-stream';
  const headers = { 'Content-Type': type, 'Accept-Ranges': 'bytes', 'Access-Control-Allow-Origin': '*',
    'Access-Control-Expose-Headers': 'Content-Range, Content-Length, ETag', 'Cache-Control': 'no-store' };
  const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || '');
  if (m && (m[1] || m[2])) {
    let start = m[1] ? Number(m[1]) : Math.max(0, st.size - Number(m[2]));
    let end = m[1] && m[2] ? Math.min(Number(m[2]), st.size - 1) : st.size - 1;
    if (start > end || start >= st.size) {
      res.writeHead(416, { ...headers, 'Content-Range': `bytes */${st.size}` });
      return res.end();
    }
    res.writeHead(206, { ...headers, 'Content-Range': `bytes ${start}-${end}/${st.size}`, 'Content-Length': end - start + 1 });
    return createReadStream(path, { start, end }).pipe(res);
  }
  res.writeHead(200, { ...headers, 'Content-Length': st.size });
  if (req.method === 'HEAD') return res.end();
  createReadStream(path).pipe(res);
}

export function startServer({ site, data, r2, r2Prefix, port = 8000 }) {
  const siteRoot = resolve(site);
  const dataRoot = data ? resolve(data) : null;
  const r2Root = r2 ? resolve(r2) : null;
  const r2Head = '/r2/' + (r2Prefix || '').replace(/^\/|\/$/g, '') + '/';
  const handle = (req, res) => {
    if (req.method === 'OPTIONS') {
      res.writeHead(204, { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'Range, If-Match',
        'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS' });
      return res.end();
    }
    const url = new URL(req.url, 'http://localhost');
    const pathname = decodeURIComponent(url.pathname);
    // The whole /r2/ namespace is data, so a miss here is a 404 and never the SPA page: a wrong prefix
    // must fail loudly instead of handing index.html to the pmtiles parser as if it were tile bytes.
    if (pathname.startsWith('/r2/')) {
      const p = r2Root && pathname.startsWith(r2Head) ? inside(r2Root, '/' + pathname.slice(r2Head.length)) : null;
      const st = p && fileInfo(p);
      if (!st) { res.writeHead(404); return res.end('not found'); }
      return send(req, res, p, st);
    }
    if (pathname.startsWith('/data/')) {
      for (const root of [dataRoot, join(siteRoot, 'data')].filter(Boolean)) {
        const p = inside(root, pathname.slice('/data'.length));
        const st = p && fileInfo(p);
        if (st) return send(req, res, p, st);
      }
      res.writeHead(404); return res.end('not found');
    }
    const p = inside(siteRoot, pathname);
    const st = p && fileInfo(p);
    if (st) return send(req, res, p, st);
    if (!extname(pathname)) {
      const index = join(siteRoot, 'index.html');
      const ist = fileInfo(index);
      if (ist) return send(req, res, index, ist);
    }
    res.writeHead(404); res.end('not found');
  };
  // One bad request (a malformed escape, a vanished file) must not take the whole dev server down.
  const server = http.createServer((req, res) => {
    try { handle(req, res); } catch (err) { res.writeHead(500); res.end(`error: ${err.message}`); }
  });
  return new Promise((ok) => server.listen(port, '127.0.0.1', () => ok(server)));
}

function argv() {
  const out = {};
  const a = process.argv.slice(2);
  for (let i = 0; i < a.length; i += 1) {
    if (a[i].startsWith('--')) { out[a[i].slice(2)] = a[i + 1]; i += 1; }
  }
  return out;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const a = argv();
  const server = await startServer({ site: a.site || 'site', data: a.data, r2: a.r2, r2Prefix: a['r2-prefix'],
    port: Number(a.port || 8000) });
  console.log(`serving on http://127.0.0.1:${server.address().port}`);
}

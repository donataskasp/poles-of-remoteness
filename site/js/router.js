// URL state. Path: /, /<region>, /<region>/<unit>. Hash: z, lat, lon, s, b, l. The pure functions take a
// location-like {pathname, hash} so they run in Node; only write() and visitor() touch the browser by default.
// Twin of SEG in worker.js. The worker is not a module the site can import (that would need a build step),
// so dev/tests/worker.test.mjs feeds both a shared table of paths to keep the two copies in step.
const SEG = /^[a-z][a-z0-9-]{0,31}$/;
const NUM = /^-?\d+(\.\d+)?$/;
export const SCENARIOS = ['A', 'B'];
export const BASEMAPS = ['sat', 'osm'];
const LANGS = ['en', 'lt']; // twin of the language list in site/js/i18n.js; the router stays dependency-free

function segment(raw) {
  let s;
  try { s = decodeURIComponent(raw).toLowerCase(); } catch { return null; }
  return SEG.test(s) ? s : null;
}

export function parse(loc = location) {
  // Only the first two path segments carry state; a third and anything after it is ignored. A unit is
  // meaningless without its region, so an invalid first segment drops the second one with it.
  const segs = loc.pathname.split('/').filter(Boolean);
  const h = new URLSearchParams((loc.hash || '').replace(/^#/, ''));
  const num = (k, lo, hi) => {
    const raw = h.get(k);
    if (raw == null || !NUM.test(raw)) return null;
    const v = Number(raw);
    return Number.isFinite(v) && v >= lo && v <= hi ? v : null;
  };
  const pick = (k, allowed, norm) => {
    const raw = h.get(k);
    const v = raw == null ? null : norm(raw);
    return allowed.includes(v) ? v : null;
  };
  const lower = (v) => v.toLowerCase();
  const region = segs.length ? segment(segs[0]) : null;
  return {
    region,
    unit: region && segs.length > 1 ? segment(segs[1]) : null,
    z: num('z', 0, 22),
    lat: num('lat', -90, 90),
    lon: num('lon', -180, 180),
    s: pick('s', SCENARIOS, (v) => v.toUpperCase()),
    b: pick('b', BASEMAPS, lower),
    l: pick('l', LANGS, lower),
  };
}

export function toUrl(state) {
  const segs = state.region ? [state.region, state.unit].filter(Boolean) : [];
  const path = '/' + segs.map(encodeURIComponent).join('/');
  const h = new URLSearchParams();
  if (state.z != null) h.set('z', String(Math.round(state.z * 100) / 100));
  if (state.lat != null) h.set('lat', state.lat.toFixed(5));
  if (state.lon != null) h.set('lon', state.lon.toFixed(5));
  if (state.s) h.set('s', state.s);
  if (state.b) h.set('b', state.b);
  if (state.l) h.set('l', state.l);
  const q = h.toString();
  return q ? `${path}#${q}` : path;
}

// What a history entry asks to change: the keys a parsed URL carries that differ from what is on screen.
// Back and forward apply exactly these, so nothing already correct is re-applied and a key the URL does not
// carry (an entry written before the key existed, or a hand-typed link) keeps its current value.
export function changedState(parsed, state, keys = ['s', 'b', 'l', 'unit']) {
  const out = {};
  for (const k of keys) if (parsed[k] != null && parsed[k] !== state[k]) out[k] = parsed[k];
  return out;
}

// The query string is not state, so it is compared out of the no-op guard and copied into whatever is
// written; a link with ?utm_source=... keeps it while the user pans around.
export function write(state, { replace = false, history = globalThis.history, location = globalThis.location } = {}) {
  const url = toUrl(state);
  if (url === location.pathname + (location.hash || '')) return false;
  const cut = url.indexOf('#');
  const path = cut === -1 ? url : url.slice(0, cut);
  const hash = cut === -1 ? '' : url.slice(cut);
  history[replace ? 'replaceState' : 'pushState'](null, '', path + (location.search || '') + hash);
  return true;
}

export function visitor(doc = document) {
  const meta = doc.querySelector('meta[name="visitor"]');
  const content = ((meta && meta.getAttribute('content')) || '').trim();
  const m = /^([A-Za-z]{2})(?:-([A-Za-z0-9]{1,3}))?$/.exec(content);
  if (!m) return { country: null, region: null };
  return { country: m[1].toLowerCase(), region: m[2] ? m[2].toLowerCase() : null };
}

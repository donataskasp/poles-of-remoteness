// URL state. Path: /, /<region>, /<region>/<unit>. Hash: z, lat, lon, s, b, l. The pure functions take a
// location-like {pathname, hash} so they run in Node; only write() and visitor() touch the browser by default.
const SEG = /^[a-z][a-z0-9-]{0,31}$/;
export const SCENARIOS = ['A', 'B'];
export const BASEMAPS = ['sat', 'osm'];
const LANGS = ['en', 'lt'];

function segment(raw) {
  let s;
  try { s = decodeURIComponent(raw).toLowerCase(); } catch { return null; }
  return SEG.test(s) ? s : null;
}

export function parse(loc = location) {
  const segs = loc.pathname.split('/').filter(Boolean);
  const h = new URLSearchParams((loc.hash || '').replace(/^#/, ''));
  const num = (k, lo, hi) => {
    if (!h.has(k)) return null;
    const v = Number(h.get(k));
    return Number.isFinite(v) && v >= lo && v <= hi ? v : null;
  };
  const pick = (k, allowed) => (allowed.includes(h.get(k)) ? h.get(k) : null);
  return {
    region: segs.length ? segment(segs[0]) : null,
    unit: segs.length > 1 ? segment(segs[1]) : null,
    z: num('z', 0, 22),
    lat: num('lat', -90, 90),
    lon: num('lon', -180, 180),
    s: pick('s', SCENARIOS),
    b: pick('b', BASEMAPS),
    l: pick('l', LANGS),
  };
}

export function toUrl(state) {
  const path = '/' + [state.region, state.unit].filter(Boolean).map(encodeURIComponent).join('/');
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

export function write(state, { replace = false } = {}) {
  const url = toUrl(state);
  if (url === location.pathname + location.hash) return false;
  history[replace ? 'replaceState' : 'pushState'](null, '', url);
  return true;
}

export function visitor(doc = document) {
  const meta = doc.querySelector('meta[name="visitor"]');
  const content = ((meta && meta.getAttribute('content')) || '').trim();
  const m = /^([A-Za-z]{2})(?:-([A-Za-z0-9]{1,3}))?$/.exec(content);
  if (!m) return { country: null, region: null };
  return { country: m[1].toLowerCase(), region: m[2] ? m[2].toLowerCase() : null };
}

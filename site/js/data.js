// Site JSON (regions, units, unit documents) with a per-URL cache, R2 URL helpers, and the opening-unit rule.
// Paths are root-absolute: the page is served at nested paths like /<region>/<unit>.
const cache = new Map();

// A failure the caller can tell apart without matching on message text: 'http' carries the status, and
// 'not-json' means the answer was not a JSON document whatever its status said.
function dataError(code, message, status = null) {
  const e = new Error(message);
  e.code = code;
  if (status != null) e.status = status;
  return e;
}

export function getJSON(url, fetchFn = fetch) {
  if (!cache.has(url)) {
    const p = fetchFn(url).then((r) => {
      if (!r.ok) throw dataError('http', `${url}: HTTP ${r.status}`, r.status);
      // The assets binding answers a missing file with index.html and HTTP 200 (not_found_handling is
      // single-page-application), so r.ok is no proof of a JSON body. Without this check the visitor gets
      // the JSON parser's own message in the readout, which says nothing they can act on.
      const type = (r.headers && r.headers.get('Content-Type')) || '';
      if (!/json/i.test(type)) throw dataError('not-json', `${url}: not JSON (${type || 'no content type'})`);
      return r.json();
    }).catch((e) => {
      cache.delete(url);
      throw e;
    });
    cache.set(url, p);
  }
  return cache.get(url);
}

export const loadRegions = () => getJSON('/data/regions.json').then((d) => d.regions);
export const loadUnits = (regionId) => getJSON(`/data/${regionId}/units.json`).then((d) => d.units);
export const loadUnit = (regionId, code) => getJSON(`/data/${regionId}/units/${code}.json`);

export function r2Url(region, key) {
  return `${region.r2_base.replace(/\/+$/, '')}/${region.id}/${region.snapshot}/${key}`;
}
export const archiveUrl = (region, s) => r2Url(region, `${s}.pmtiles`);
export function detailUrl(region, pole, ext) {
  if (!pole || !pole.detail) throw new Error('pole has no detail');
  return r2Url(region, `${pole.detail}.${ext}`);
}

// Leaflet bounds for a unit bbox. A unit that straddles the line is stored the short way round, with its
// east past 180. Leaflet would frame that turn of the world faithfully, but every marker and overlay sits at
// its literal longitude in [-180, 180], a full turn west of such a frame. Shift the box by a turn whenever
// its centre lies past the line, so the frame and the layers share a copy of the world.
export function bboxToBounds([west, south, east, north]) {
  const shift = (west + east) / 2 > 180 ? -360 : 0;
  return [[south, west + shift], [north, east + shift]];
}

// A region with no units yields no winner, so every caller below reads the code through this guard.
const winnerCode = (units) => {
  const w = winner(units);
  return w ? w.code : null;
};

export function winner(units, s = 'A') {
  if (!units.length) return null;
  const ranked = units.filter((u) => u[s] && u[s].rank != null).sort((a, b) => a[s].rank - b[s].rank);
  return ranked[0] || units[0];
}

// The unit whose bbox contains the point, or null. Bboxes overlap badly (Latvia's covers the northern third
// of Lithuania, France's holds Andorra), so a hit in the visitor's own country comes first and only then does
// the smallest area win: the visitor is almost always standing in their own country. Country, not code: a
// North American unit code is 'us-ak' while the visitor country is 'us'. Both rules are guesses; the real fix
// is a point-in-polygon test against lazily loaded unit outlines (#33).
export function unitAt(units, { lat, lng }, country = null) {
  // The bbox can run past 180 (a unit that straddles the line is written the short way round, west in
  // [-180, 180] and east above it), and the point can arrive from a map the reader panned past the line,
  // so the point is brought into the box's own turn of the world before the comparison. Only the east edge
  // is tested: x is w plus less than a turn, so x >= w holds by construction.
  const hits = units.filter(({ bbox: [w, s, e, n] }) => {
    const x = w + ((((lng - w) % 360) + 360) % 360);
    return x <= e && lat >= s && lat <= n;
  });
  const own = (u) => (country && (u.country || '').toLowerCase() === country ? 0 : 1);
  hits.sort((a, b) => own(a) - own(b) || a.area_km2 - b.area_km2);
  return hits[0] || null;
}

// The region control: one link per region, and nothing at all while there is only one. Links rather than a
// switch because the page binds its region and its layers once at start, so another region is a page load.
export function regionLinks(regions, currentId) {
  if (!regions || regions.length < 2) return [];
  return regions.map((r) => ({ id: r.id, code: r.code, name: r.name || r.id, href: `/${r.id}`, current: r.id === currentId }));
}

// Opening unit (spec 5.3): the path; the visitor's own unit (country-region, then country); the winner of
// the first region with any unit in the visitor's country; the first region's winner.
export async function pickStart(parsed, vis, regions, load = loadUnits) {
  const byId = new Map(regions.map((r) => [r.id, r]));
  if (parsed.region && byId.has(parsed.region)) {
    const units = await load(parsed.region);
    if (parsed.unit && units.some((u) => u.code === parsed.unit)) return { region: parsed.region, unit: parsed.unit };
    return { region: parsed.region, unit: winnerCode(units) };
  }
  if (vis && vis.country) {
    const country = vis.country.toLowerCase();
    const codes = [vis.region ? `${country}-${vis.region.toLowerCase()}` : null, country].filter(Boolean);
    for (const r of regions) {
      const units = await load(r.id);
      const own = codes.map((c) => units.find((u) => u.code === c)).find(Boolean);
      if (own) return { region: r.id, unit: own.code };
      if (units.some((u) => (u.country || '').toLowerCase() === country)) return { region: r.id, unit: winnerCode(units) };
    }
  }
  const first = regions[0];
  const units = await load(first.id);
  return { region: first.id, unit: winnerCode(units) };
}

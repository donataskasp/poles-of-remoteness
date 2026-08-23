// Site JSON (regions, units, unit documents) with a per-URL cache, R2 URL helpers, and the opening-unit rule.
// Paths are root-absolute: the page is served at nested paths like /<region>/<unit>.
const cache = new Map();

export function getJSON(url, fetchFn = fetch) {
  if (!cache.has(url)) {
    const p = fetchFn(url).then((r) => {
      if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
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

export function bboxToBounds([west, south, east, north]) {
  return [[south, west], [north, east]];
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

// The smallest unit whose bbox contains the point, or null. Bboxes overlap (France's holds Andorra), so the
// smallest area wins; a bbox hit is only a guess at the unit and the site treats it as one.
export function unitAt(units, { lat, lng }) {
  const hits = units.filter(({ bbox: [w, s, e, n] }) => lng >= w && lng <= e && lat >= s && lat <= n);
  hits.sort((a, b) => a.area_km2 - b.area_km2);
  return hits[0] || null;
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

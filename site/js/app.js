// Bootstrap and wiring. Everything with behaviour lives in the modules.
import { makeClassTable } from './classes.js';
import { pickLang, setLang, getLang, applyDom, t, fmtDist } from './i18n.js';
import { parse, write, visitor } from './router.js';
import { loadRegions, loadUnits, archiveUrl, pickStart, bboxToBounds } from './data.js';
import { readTokens, makePalette, legendRows } from './palette.js';
import { describe, formatSample, mountReadout } from './readout.js';
import { createMap } from './map.js';
import { createExploreLayer } from './explore.js';

const LANG_KEY = 'poles.lang';
const state = { region: null, unit: null, s: 'A', b: 'sat', l: 'en' };
const ui = {};

function markReady() { document.documentElement.dataset.ready = '1'; }

function storedLang() { try { return localStorage.getItem(LANG_KEY); } catch { return null; } }
function storeLang(l) { try { localStorage.setItem(LANG_KEY, l); } catch { /* private mode */ } }

function syncUrl(replace = false) {
  const c = ui.map.getCenter();
  write({ ...state, z: ui.map.getZoom(), lat: c.lat, lon: c.lng }, { replace });
}

function renderLegend() {
  if (!ui.legend) return; // the first applyLanguage runs before the map controls are wired
  const rows = legendRows(readTokens());
  ui.legend.innerHTML = rows.map((r) => `<li class="legend__item"><span class="legend__swatch" style="background:${r.color}"></span>${fmtDist(r.label_m)}</li>`).join('');
}

function applyLanguage(lang) {
  setLang(lang);
  state.l = getLang();
  document.querySelectorAll('#lang-seg .seg__btn').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.lang === state.l)));
  applyDom();
  renderLegend();
  if (ui.refreshAttribution) ui.refreshAttribution();
}

const middle = (bounds) => [(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2];
const headerBounds = (h) => [[h.minLat, h.minLon], [h.maxLat, h.maxLon]];

async function main() {
  const parsed = parse();
  applyLanguage(pickLang({ hash: parsed.l, stored: storedLang(), navigator }));
  state.s = parsed.s || 'A';
  state.b = parsed.b || 'sat';

  const regions = await loadRegions();
  const start = await pickStart(parsed, visitor(), regions);
  const region = regions.find((r) => r.id === start.region);
  const units = await loadUnits(region.id);
  // A region with no units at all opens without one; the archive still covers the whole region.
  const unit = units.find((u) => u.code === start.unit) || null;
  state.region = region.id;
  state.unit = unit && unit.code;

  const table = makeClassTable(region.class_edges);
  let palette = makePalette(table, readTokens());

  const bounds = unit ? bboxToBounds(unit.bbox) : null;
  const fromHash = parsed.z != null && parsed.lat != null && parsed.lon != null;
  const { map, setBasemap, refreshAttribution } = createMap(document.getElementById('map'), {
    center: bounds ? middle(bounds) : [0, 0], zoom: 6, basemap: state.b,
  });
  ui.map = map; ui.refreshAttribution = refreshAttribution;
  ui.legend = document.getElementById('legend');
  ui.readout = mountReadout(document.getElementById('readout'));
  renderLegend();
  refreshAttribution();
  if (fromHash) map.setView([parsed.lat, parsed.lon], parsed.z);
  else if (bounds) map.fitBounds(bounds, { padding: [24, 24] });

  const readyFallback = setTimeout(markReady, 8000);
  const explore = {};
  for (const s of ['A', 'B']) {
    explore[s] = await createExploreLayer({ url: archiveUrl(region, s), table, palette, onReady: () => { clearTimeout(readyFallback); markReady(); } });
  }
  if (!fromHash && !bounds) map.fitBounds(headerBounds(explore.A.header), { padding: [24, 24] });
  map.setMinZoom(Math.max(2, explore.A.options.minZoom));
  explore[state.s].addTo(map);

  function showSample(latlng) {
    const cls = explore[state.s].classAt(latlng);
    ui.readout.show(cls === undefined ? t('readoutLoading') : formatSample(describe(cls, table)));
  }
  map.on('click', (e) => showSample(e.latlng));
  map.on('moveend zoomend', () => syncUrl(true));

  document.querySelectorAll('#basemap-seg .seg__btn').forEach((b) => b.addEventListener('click', () => {
    state.b = setBasemap(b.dataset.base);
    document.querySelectorAll('#basemap-seg .seg__btn').forEach((x) => x.setAttribute('aria-pressed', String(x.dataset.base === state.b)));
    syncUrl(true);
  }));
  document.querySelectorAll('#basemap-seg .seg__btn').forEach((x) => x.setAttribute('aria-pressed', String(x.dataset.base === state.b)));

  document.querySelectorAll('#lang-seg .seg__btn').forEach((b) => b.addEventListener('click', () => {
    applyLanguage(b.dataset.lang);
    storeLang(state.l);
    syncUrl(true);
  }));

  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    palette = makePalette(table, readTokens());
    Object.values(explore).forEach((l) => l.setPalette(palette));
    renderLegend();
  });

  ui.readout.show(t('readoutHint'));
  syncUrl(true);
}

main().catch((e) => {
  console.error(e);
  document.getElementById('readout').hidden = false;
  document.getElementById('readout').textContent = String(e.message || e);
  markReady();
});

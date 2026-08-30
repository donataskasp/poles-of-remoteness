// Bootstrap and wiring. Everything with behaviour lives in the modules.
import { makeClassTable } from './classes.js';
import { pickLang, setLang, getLang, applyDom, t, fmtDist, regionLabel } from './i18n.js';
import { parse, write, visitor, changedState, toUrl } from './router.js';
import { loadRegions, loadUnits, loadUnit, archiveUrl, pickStart, bboxToBounds, unitAt, regionLinks } from './data.js';
import { readTokens, makePalette, legendRows } from './palette.js';
import { describe, formatSample, mountReadout } from './readout.js';
import { createMap } from './map.js';
import { createExploreLayer } from './explore.js';
import { createDetailOverlays } from './detail.js';
import { createMarkers } from './markers.js';
import { createCard } from './card.js';
import { createRanking } from './ranking.js';

const LANG_KEY = 'poles.lang';
const state = { region: null, regions: null, unit: null, s: 'A', b: 'sat', l: 'en', sample: null };
const ui = {};

function markReady() { document.documentElement.dataset.ready = '1'; }

function storedLang() { try { return localStorage.getItem(LANG_KEY); } catch { return null; } }
function storeLang(l) { try { localStorage.setItem(LANG_KEY, l); } catch { /* private mode */ } }

// Set while back or forward is being applied: restoring a history entry must never write to history, and
// the map moves it makes fire moveend like any other.
let restoring = false;

function syncUrl(replace = false) {
  if (restoring) return;
  // getCenter returns the longitude of the world the reader panned into, so it can be 181 or -190 next to
  // the line, and the router only accepts [-180, 180]: an unwrapped value would be dropped on the way back
  // and the shared link would open somewhere else.
  const c = ui.map.getCenter().wrap();
  write({ ...state, z: ui.map.getZoom(), lat: c.lat, lon: c.lng }, { replace });
}

function renderLegend() {
  if (!ui.legend) return; // the first applyLanguage runs before the map controls are wired
  const rows = legendRows(readTokens());
  ui.legend.innerHTML = rows.map((r) => `<li class="legend__item"><span class="legend__swatch" style="background:${r.color}"></span>${fmtDist(r.label_m)}</li>`).join('');
}

// The header's region control. Built as elements, not as an HTML string: the name comes from a data file
// and textContent cannot become markup. The class on the header is what the phone rules key off, so a
// one-region site keeps its header untouched. It reads the regions off state so a language switch can draw
// it again with the names said in the new language.
function renderRegions() {
  const nav = document.getElementById('regions');
  const links = regionLinks(state.regions || [], state.region, state);
  nav.replaceChildren(...links.map((l) => {
    const a = document.createElement('a');
    a.className = 'seg__btn';
    a.href = l.href;
    a.textContent = regionLabel(l);
    if (l.current) a.setAttribute('aria-current', 'page');
    return a;
  }));
  nav.hidden = links.length === 0;
  document.getElementById('hdr').classList.toggle('hdr--regions', links.length > 0);
}

// The home link is a full page load like a region link, so it carries the same three keys (#51); spot and
// position stay off it, home picks the region afresh.
function renderHomeLink() {
  document.getElementById('brand-home').href = toUrl({ s: state.s, b: state.b, l: state.l });
}

// The readout holds a sample, not a string, so it can be said again in another language. The hint, the wait
// for a tile and the three locate messages are samples of their own kind for exactly that reason: they say
// something about the attempt rather than about a place, and each one's I18N key is its kind.
const LOCATE_KINDS = new Set(['locateDenied', 'locateUnavailable', 'locateOutside']);

function readoutText(sample) {
  if (!sample) return '';
  if (sample.kind === 'hint') return t('readoutHint');
  if (sample.kind === 'loading') return t('readoutLoading');
  if (sample.kind === 'error') return t('loadError');
  if (LOCATE_KINDS.has(sample.kind)) return t(sample.kind);
  return formatSample(sample);
}

function say(sample, options) {
  state.sample = sample;
  ui.readout.show(readoutText(sample), options);
}

function applyLanguage(lang) {
  setLang(lang);
  state.l = getLang();
  document.querySelectorAll('#lang-seg .seg__btn').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.lang === state.l)));
  applyDom();
  renderLegend();
  renderHomeLink();
  if (state.regions) renderRegions();   // the first call runs before the regions are loaded
  if (ui.card) ui.card.refresh();
  if (ui.ranking) ui.ranking.refresh();
  if (ui.refreshAttribution) ui.refreshAttribution();
  if (ui.refreshZoomTitles) ui.refreshZoomTitles();
  if (ui.here) ui.here.setTooltipContent(t('locateHere'));
  if (ui.readout) ui.readout.restate(readoutText(state.sample));
}

const middle = (bounds) => [(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2];
const headerBounds = (h) => [[h.minLat, h.minLon], [h.maxLat, h.maxLon]];

async function main() {
  const parsed = parse();
  // Scenario and basemap before the first language render: every link render reads them off state.
  state.s = parsed.s || 'A';
  state.b = parsed.b || 'sat';
  applyLanguage(pickLang({ hash: parsed.l, stored: storedLang(), navigator }));

  const regions = await loadRegions();
  const start = await pickStart(parsed, visitor(), regions);
  const region = regions.find((r) => r.id === start.region);
  state.regions = regions;
  state.region = region.id;
  renderRegions();
  const units = await loadUnits(region.id);
  // A region with no units at all opens without one; the archive still covers the whole region.
  const unit = units.find((u) => u.code === start.unit) || null;
  state.unit = unit && unit.code;

  const table = makeClassTable(region.class_edges);
  let palette = makePalette(table, readTokens());

  const bounds = unit ? bboxToBounds(unit.bbox) : null;
  const fromHash = parsed.z != null && parsed.lat != null && parsed.lon != null;
  const { map, setBasemap, refreshAttribution, refreshZoomTitles } = createMap(document.getElementById('map'), {
    center: bounds ? middle(bounds) : [0, 0], zoom: 6, basemap: state.b,
  });
  ui.map = map; ui.refreshAttribution = refreshAttribution; ui.refreshZoomTitles = refreshZoomTitles;
  ui.legend = document.getElementById('legend');
  ui.readout = mountReadout(document.getElementById('readout'));
  renderLegend();
  refreshAttribution();
  if (fromHash) map.setView([parsed.lat, parsed.lon], parsed.z);
  else if (bounds) map.fitBounds(bounds, { padding: [24, 24] });

  const readyFallback = setTimeout(markReady, 8000);
  const explore = {};
  for (const s of ['A', 'B']) {
    explore[s] = await createExploreLayer({ url: archiveUrl(region, s), palette, onReady: () => { clearTimeout(readyFallback); markReady(); } });
  }
  if (!fromHash && !bounds) map.fitBounds(headerBounds(explore.A.header), { padding: [24, 24] });
  map.setMinZoom(Math.max(2, explore.A.options.minZoom));
  explore[state.s].addTo(map);

  const detail = createDetailOverlays(map, { region, palette });
  const markers = createMarkers(map, { onSelect: (pole) => selectPole(pole.rank, { pan: false }) });
  const card = createCard(document.getElementById('card'), {
    onScenario: (s) => setScenario(s),
    onRanking: () => ui.ranking && ui.ranking.open(),
    onLocate: () => ui.locate && ui.locate(),
    onPole: (rank) => selectPole(rank, { pan: true }),
  });
  ui.card = card;
  // On a phone the sheet is the whole screen, so picking a row closes it behind the reader.
  ui.ranking = createRanking(document.getElementById('panel'), {
    onPick: (code) => {
      openUnit(code, { view: 'pole' });
      if (matchMedia('(max-width: 720px)').matches) ui.ranking.toggle();
    },
  });
  ui.ranking.setRows(units, state.s, unit && unit.code);

  ui.locate = () => {
    say({ kind: 'loading' }, { sticky: true });
    map.locate({ setView: true, maxZoom: 11, timeout: 15000 });
  };
  map.on('locationfound', (e) => {
    if (ui.here) map.removeLayer(ui.here);
    ui.here = L.circleMarker(e.latlng, { radius: 7, color: '#fff', weight: 2, fillColor: '#1d6fe0', fillOpacity: 1 })
      .bindTooltip(t('locateHere')).addTo(map);
    const hit = unitAt(units, e.latlng, visitor().country);
    // Outside every unit bbox the dot is still true, but there is no unit to open and nothing to read there.
    if (!hit) { say({ kind: 'locateOutside' }, { sticky: true }); return; }
    if (hit.code !== state.unit) openUnit(hit.code, { view: 'keep' });
    showSample(e.latlng);
    // The locate has just jumped the view, so the tiles under the new one may still be in flight and the
    // first read says "reading" for good. GridLayer fires load once every visible tile is in: read again
    // then, unless the reader has produced a sample of their own meanwhile. The test is identity, not
    // kind: say() allocates a sample per call, so a second locate's own "reading" is not this one's.
    const pending = state.sample;
    if (explore[state.s].classAt(e.latlng) === undefined) {
      explore[state.s].once('load', () => {
        if (state.sample === pending) showSample(e.latlng);
      });
    }
  });
  map.on('locationerror', (e) => say({ kind: e.code === 1 ? 'locateDenied' : 'locateUnavailable' }, { sticky: true }));

  const about = document.getElementById('about');
  document.getElementById('about-btn').addEventListener('click', () => {
    for (const el of about.querySelectorAll('.snapshot')) el.textContent = t('snapshotNote', { date: region.snapshot });
    for (const el of about.querySelectorAll('.detail-res')) el.textContent = String(region.detail_res_m);
    about.showModal();
  });
  // Close on a click outside the dialog box. Testing the target alone would also close on the dialog's own
  // padding ring, which is part of the dialog and not the backdrop. Both ends of the click have to land
  // outside: a text selection dragged out of the body and released over the backdrop is not a close.
  const outsideDialog = (e) => {
    const r = about.getBoundingClientRect();
    return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
  };
  let pressedOutside = false;
  about.addEventListener('mousedown', (e) => { pressedOutside = outsideDialog(e); });
  about.addEventListener('click', (e) => {
    const pressed = pressedOutside;
    pressedOutside = false; // a keyboard click reads as (0, 0), outside: it must not inherit the last press
    if (pressed && outsideDialog(e)) about.close();
  });

  let current = { unit, doc: null, rank: 1 };

  function polesOf() {
    const block = current.doc && current.doc[state.s];
    return (block && block.poles) || [];
  }

  function renderUnit() {
    if (!current.unit) return; // a region with no units has no card, no markers and no detail rasters
    card.show({ region, unit: current.unit, units, doc: current.doc, scenario: state.s, rank: current.rank });
    markers.setPoles(polesOf(), current.rank);
    detail.setPoles(polesOf());
  }

  function selectPole(rank, { pan }) {
    current.rank = rank;
    card.setPole(rank);
    markers.select(rank);
    const pole = polesOf().find((p) => p.rank === rank);
    if (pan && pole) map.flyTo([pole.lat, pole.lon], Math.max(map.getZoom(), 11), { duration: 0.6 });
  }

  // view: 'unit' fits the unit's bbox, 'pole' flies to pole 1 of the active scenario, 'keep' leaves the map.
  async function openUnit(code, { push = true, view = 'unit' } = {}) {
    const next = units.find((u) => u.code === code);
    if (!next) return;
    let doc;
    try {
      doc = await loadUnit(region.id, code);
    } catch (e) {
      // A place that will not load changes nothing: the unit on screen, its card, its markers and the URL
      // all stay as they were, and the reader is told in their own language.
      console.warn('unit', code, e.message);
      say({ kind: 'error' });
      return;
    }
    current = { unit: next, doc, rank: 1 };
    state.unit = code;
    renderUnit();
    // The URL is written before the map moves: moveend would otherwise write the new view first and this
    // push would find the URL already correct and add no history entry at all.
    syncUrl(!push);
    const pole1 = polesOf()[0];
    if (view === 'pole' && pole1) map.flyTo([pole1.lat, pole1.lon], 10, { duration: 0.8 });
    else if (view !== 'keep') map.fitBounds(bboxToBounds(next.bbox), { padding: [24, 24] });
    if (ui.ranking) ui.ranking.setCurrent(code);
  }

  function setScenario(s) {
    if (s === state.s) return;
    map.removeLayer(explore[state.s]);
    state.s = s;
    explore[s].addTo(map);
    current.rank = 1;
    renderUnit();
    renderRegions();
    renderHomeLink();
    if (ui.ranking) ui.ranking.setScenario(s);
    syncUrl(true);
  }

  function showSample(latlng) {
    const cls = detail.classAt(latlng) ?? explore[state.s].classAt(latlng);
    say(cls === undefined ? { kind: 'loading' } : describe(cls, table));
  }
  map.on('click', (e) => showSample(e.latlng));
  if (matchMedia('(hover: hover) and (pointer: fine)').matches) {
    let last = 0;
    map.on('mousemove', (e) => {
      const now = performance.now();
      if (now - last < 120) return;
      last = now;
      showSample(e.latlng);
    });
  }
  map.on('moveend zoomend', () => syncUrl(true));

  const markBasemap = () => document.querySelectorAll('#basemap-seg .seg__btn')
    .forEach((x) => x.setAttribute('aria-pressed', String(x.dataset.base === state.b)));
  // One place that switches the base map: the segmented control here, and the history restore below.
  function applyBasemap(base) {
    state.b = setBasemap(base);
    markBasemap();
    renderRegions();
    renderHomeLink();
  }
  document.querySelectorAll('#basemap-seg .seg__btn').forEach((b) => b.addEventListener('click', () => {
    applyBasemap(b.dataset.base);
    syncUrl(true);
  }));
  markBasemap();

  document.querySelectorAll('#lang-seg .seg__btn').forEach((b) => b.addEventListener('click', () => {
    applyLanguage(b.dataset.lang);
    storeLang(state.l);
    syncUrl(true);
  }));

  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    palette = makePalette(table, readTokens());
    Object.values(explore).forEach((l) => l.setPalette(palette));
    detail.setPalette(palette);
    renderLegend();
  });

  // Back and forward restore the entry the reader asked for; nothing here may write to history, so the view
  // is set without animation to keep its moveend inside the guarded window and the unit is awaited inside it.
  window.addEventListener('popstate', async () => {
    const p = parse();
    // Every key the URL carries is restored, or the URL and the screen disagree from that point on and the
    // next syncUrl resolves the disagreement by discarding what the URL said.
    const change = changedState(p, state);
    restoring = true;
    try {
      if (change.s) setScenario(change.s);
      if (change.b) applyBasemap(change.b);
      if (change.l) applyLanguage(change.l);
      if (p.z != null && p.lat != null && p.lon != null) map.setView([p.lat, p.lon], p.z, { animate: false });
      if (change.unit) await openUnit(change.unit, { push: false, view: p.z != null ? 'keep' : 'unit' });
    } catch (e) {
      console.warn('popstate', e);
    } finally {
      restoring = false;
    }
  });

  say({ kind: 'hint' });
  if (unit) await openUnit(unit.code, { push: false, view: fromHash ? 'keep' : 'unit' });
  syncUrl(true);
}

main().catch((e) => {
  // The raw error keeps going to the console; the reader gets a sentence in their own language. "Not
  // published yet" and "the load broke" are different facts, and a JSON parser's message is neither.
  console.error(e);
  const missing = e && (e.code === 'not-json' || e.status === 404);
  const readout = document.getElementById('readout');
  readout.hidden = false;
  readout.textContent = t(missing ? 'dataMissing' : 'loadError');
  markReady();
});

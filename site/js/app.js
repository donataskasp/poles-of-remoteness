/* Atokiausia Lietuva — the places farthest from any road.
   Plain ES module. Leaflet is loaded as a global by index.html. */

const L = window.L;

/* ═══════════════════════════ strings ═══════════════════════════ */

const I18N = {
  lt: {
    htmlTitle: 'Atokiausia Lietuva',
    subtitle: 'Toliausiai nuo bet kokio kelio nutolusios vietos',
    scenarioGroup: 'Kelių apibrėžimas',
    scenarioA: 'Su miško keliukais',
    scenarioB: 'Tik tikri keliai',
    scenarioAHint: 'Skaičiuojami visi pravažiuojami keliai, įskaitant miško ir lauko keliukus.',
    scenarioBHint: 'Keliukai neskaičiuojami, lieka tik prižiūrimi keliai nuo magistralių iki gatvių.',
    scenarioHelp: 'Ką reiškia šie du variantai?',
    resetView: 'Rodyti visą Lietuvą',
    searchLabel: 'Ieškoti vietovės arba koordinačių',
    searchPlaceholder: 'Kaimas, miestelis arba koordinatės…',
    searchLoading: 'Kraunamas vietovardžių sąrašas…',
    searchEmpty: 'Nieko nerasta',
    langGroup: 'Kalba',
    clear: 'Išvalyti',
    close: 'Uždaryti',
    togglePanel: 'Suskleisti arba išskleisti skydelį',

    spotsHeading: 'Atokiausios vietos',
    spotsNote: (ways, km) => `Įvertinta ${ways} kelių atkarpų, ${km} km.`,
    spotHint: 'Apskritimo spindulys yra atstumas iki artimiausio kelio. Kelias paliečia jį iš išorės.',
    nearestRoad: 'Artimiausias kelias',
    noSurface: 'danga nenurodyta',
    rankAria: (n) => `${n}-a vieta`,

    legendHeading: 'Atokumo zonos',
    basemapLabel: 'Pagrindas',
    baseOsm: 'Žemėlapis',
    baseSat: 'Palydovas',
    bandsToggle: 'Atokumo zonos',
    legendHint: 'Plotai, nutolę nuo bet kokio kelio bent tiek',
    legendItem: (km) => `${km} km`,

    readoutKicker: 'Pasirinktas taškas',
    readoutPoint: 'Taškas žemėlapyje',
    readoutTitle: 'Iki artimiausio kelio',
    expandCard: 'Išskleisti kortelę',
    collapseCard: 'Suskleisti kortelę',
    nodata: 'Jūra arba užsienis, duomenų nėra',
    noValue: 'Duomenų nėra',
    computing: 'Skaičiuojama…',
    rasterFail: 'Nepavyko įkelti atstumų tinklelio.',
    googleSat: 'Google palydovas ↗',
    say: [
      'Šis taškas yra ant pat kelio.',
      'Kelias visai šalia.',
      'Įprasta Lietuvai: keliai čia tankūs.',
      'Ramesnis kampas nei vidutinė Lietuva.',
      'Tikrai atoku, tokių vietų šalyje nedaug.',
      'Viena atokiausių Lietuvos vietų.',
    ],

    aboutBtn: 'Apie projektą ir metodiką',
    aboutTitle: 'Apie',
    aboutBody: `
      <p>Šis žemėlapis atsako į vieną klausimą: <b>kur Lietuvoje esi labiausiai nutolęs nuo bet kokio kelio?</b>
      Atsakymas priklauso nuo to, ką laikome keliu, todėl jų yra du.</p>
      <p><b>Su miško keliukais</b>: skaičiuojamas kiekvienas važiuojamas kelias, įskaitant miško ir lauko keliukus:
      atokiausia vieta yra Žuvinto rezervato pelkė, <b>3,43 km</b> nuo artimiausio keliuko.
      Čepkelių raistas atsilieka vos 19 metrų, ir tik todėl, kad palei Baltarusijos sieną nubrėžtas pasieniečių keliukas.
      <b>Tik tikri keliai</b>: keliukai neskaičiuojami, ir laimi Čepkelių raistas: <b>6,67 km</b> iki artimiausio kelio.</p>
      <p>Metodika: 25 m tikslumo atstumo tinklelis nuo visų OpenStreetMap kelių (įskaitant kaimynų kelius anapus sienos,
      kad paribiai nebūtų dirbtinai „atokūs“), po to tikslus vektorinis kandidatų patikslinimas.
      Spustelėjus žemėlapį atstumas rodomas iš 50 m tinklelio, todėl tikslumas apie ±100 m.</p>
      <p class="muted">Duomenys: OpenStreetMap, momentinė kopija 2026‑08‑17. Duomenys © OpenStreetMap contributors (ODbL),
      iškarpos iš Geofabrik. Padaryta su Claude.</p>
    `,
    aboutRepo: 'Kodas ir duomenys',
  },

  en: {
    htmlTitle: 'Atokiausia Lietuva',
    subtitle: "Lithuania's places farthest from any road",
    scenarioGroup: 'Definition of a road',
    scenarioA: 'Tracks count',
    scenarioB: 'Real roads only',
    scenarioAHint: 'Every drivable way counts, including forest and field tracks.',
    scenarioBHint: 'Tracks are excluded, only maintained roads from motorways down to streets.',
    scenarioHelp: 'What do these two options mean?',
    resetView: 'Show all of Lithuania',
    searchLabel: 'Search for a place or coordinates',
    searchPlaceholder: 'Village, town or coordinates…',
    searchLoading: 'Loading the gazetteer…',
    searchEmpty: 'Nothing found',
    langGroup: 'Language',
    clear: 'Clear',
    close: 'Close',
    togglePanel: 'Collapse or expand the panel',

    spotsHeading: 'Most remote places',
    spotsNote: (ways, km) => `Measured against ${ways} road segments, ${km} km.`,
    spotHint: 'The circle radius is the distance to the nearest road. That road touches it from outside.',
    nearestRoad: 'Nearest road',
    noSurface: 'surface not recorded',
    rankAria: (n) => `rank ${n}`,

    legendHeading: 'Remoteness bands',
    basemapLabel: 'Basemap',
    baseOsm: 'Map',
    baseSat: 'Satellite',
    bandsToggle: 'Remoteness bands',
    legendHint: 'Areas at least this far from any road',
    legendItem: (km) => `${km} km`,

    readoutKicker: 'Selected point',
    readoutPoint: 'Point on the map',
    readoutTitle: 'To the nearest road',
    expandCard: 'Expand the card',
    collapseCard: 'Collapse the card',
    nodata: 'Sea or abroad, no data',
    noValue: 'No data',
    computing: 'Computing…',
    rasterFail: 'Could not load the distance grid.',
    googleSat: 'Google satellite ↗',
    say: [
      'You are standing on a road.',
      'A road is right there.',
      'Ordinary for Lithuania; roads are dense here.',
      'A quieter corner than the country average.',
      'Genuinely remote; few places like this.',
      'One of the most remote places in Lithuania.',
    ],

    aboutBtn: 'About and method',
    aboutTitle: 'About',
    aboutBody: `
      <p>This map answers one question: <b>where in Lithuania are you farthest from any road?</b>
      The answer depends on what counts as a road, so there are two of them.</p>
      <p><b>Tracks count</b>: every drivable way counts, forest and field tracks included:
      the winner is the mire of the Žuvintas reserve, <b>3.43 km</b> from the nearest track.
      Čepkeliai raised bog trails it by just 19 metres, only because a border patrol track along the Belarusian
      border is mapped. <b>Real roads only</b>: tracks are excluded, and Čepkeliai wins outright:
      <b>6.67 km</b> to the nearest road.</p>
      <p>Method: a 25 m distance grid over every OpenStreetMap road, including the neighbours' roads across the
      border so that the borderlands are not artificially remote, followed by exact vector refinement of the
      candidates. Clicking the map reads a 50 m grid, so those readouts are accurate to roughly ±100 m.</p>
      <p class="muted">Data: OpenStreetMap, snapshot of 2026‑08‑17. Data © OpenStreetMap contributors (ODbL),
      extracts by Geofabrik. Made with Claude.</p>
    `,
    aboutRepo: 'Code and data',
  },
};

const REPO = 'https://github.com/donataskasp/atokiausia-lietuva';

const HIGHWAY = {
  lt: {
    track: 'miško ar lauko keliukas', unclassified: 'vietinės reikšmės kelias',
    residential: 'gyvenvietės gatvė', service: 'privažiavimo kelias',
    tertiary: 'rajoninis kelias', secondary: 'krašto kelias', primary: 'magistralinis kelias',
    trunk: 'greitkelis', motorway: 'automagistralė', living_street: 'gyvenamoji gatvė',
    pedestrian: 'pėsčiųjų gatvė', road: 'neklasifikuotas kelias',
  },
  en: {
    track: 'forest or field track', unclassified: 'minor road',
    residential: 'residential street', service: 'service road',
    tertiary: 'tertiary road', secondary: 'secondary road', primary: 'primary road',
    trunk: 'trunk road', motorway: 'motorway', living_street: 'living street',
    pedestrian: 'pedestrian street', road: 'unclassified road',
  },
};

const SURFACE = {
  lt: {
    asphalt: 'asfaltas', paved: 'kietoji danga', concrete: 'betonas', unpaved: 'negrįstas',
    gravel: 'žvyras', fine_gravel: 'smulkus žvyras', compacted: 'sutankintas gruntas',
    ground: 'gruntas', dirt: 'gruntas', earth: 'gruntas', grass: 'žolė', sand: 'smėlis',
    mud: 'purvas', wood: 'mediena', sett: 'grindinys', cobblestone: 'grindinys',
  },
  en: {},
};

const COUNTRY = {
  lt: {
    Lithuania: 'Lietuva', Latvia: 'Latvija', Poland: 'Lenkija', Belarus: 'Baltarusija',
    'Russia (Kaliningrad)': 'Rusija (Kaliningrado sr.)',
  },
  en: {},
};

const DIRS = {
  lt: { N: 'į šiaurę', S: 'į pietus', E: 'į rytus', W: 'į vakarus',
        NE: 'į šiaurės rytus', NW: 'į šiaurės vakarus', SE: 'į pietryčius', SW: 'į pietvakarius' },
  en: { N: 'N', S: 'S', E: 'E', W: 'W', NE: 'NE', NW: 'NW', SE: 'SE', SW: 'SW' },
};

const PLACE_TYPE = {
  lt: { c: 'miestas', t: 'miestelis', v: 'kaimas' },
  en: { c: 'city', t: 'town', v: 'village' },
};

/* ═══════════════════════════ map constants ═══════════════════════════ */
/* Map overlays keep a fixed palette in both themes: the map is a window,
   the chrome around it adapts. */

const BAND_COLORS = { 1: '#e8c98a', 2: '#d19a4f', 3: '#b06f2a', 4: '#8a4d1b' };
const MAP_ACCENT = '#a55f1f';
const ROAD_TRACK = '#898781';
const ROAD_REAL = '#52514e';
const HALO = 'rgba(250,249,244,.6)';

const BASEMAPS = {
  osm: {
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    opts: { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>' },
  },
  sat: {
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    opts: { maxZoom: 19, attribution: 'Esri, Maxar, Earthstar Geographics' },
  },
};

/* ═══════════════════════════ state ═══════════════════════════ */

/** Lowest-priority language pick: the browser's own list. Hash and prefs override it. */
function browserLang() {
  const tags = navigator.languages && navigator.languages.length
    ? navigator.languages
    : [navigator.language || ''];
  return tags.some((tag) => String(tag).toLowerCase().split('-')[0] === 'lt') ? 'lt' : 'en';
}

const state = {
  lang: browserLang(),
  scenario: 'A',
  spot: null,          // rank number or null
  bands: true,
  base: 'sat',         // default; only base=osm is ever written to the hash
  point: null,         // {lat, lon, name?}
  zoom: null,
  readoutExpanded: false,   // mobile only: a new selection lands as the collapsed pill
};

const data = {
  spots: null,
  grid: null,
  land: null,
  bands: {},           // scenario -> geojson
  places: null,
  raster: {},          // scenario -> Uint8Array
  rasterError: false,
};

const el = {};
let map, baseLayer, baseKind, bandsLayer, landLayer, selLayer, pointMarker, zoomCtl;
let rankMarkers = [];

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const mobileMQ = window.matchMedia('(max-width: 720px)');
const isMobile = () => mobileMQ.matches;
const t = () => I18N[state.lang];

/* ═══════════════════════════ formatting ═══════════════════════════ */

const LOCALE = () => (state.lang === 'lt' ? 'lt-LT' : 'en-GB');

function num(v, min = 0, max = 0) {
  return new Intl.NumberFormat(LOCALE(), { minimumFractionDigits: min, maximumFractionDigits: max }).format(v);
}

/** Precise spot distance: "6,67 km" */
function km2(m) {
  return num(m / 1000, 2, 2);
}

/** Grid readout: coarse on purpose (±100 m). */
function approx(m) {
  if (m === null || m === undefined) return null;
  if (m < 50) return `< 50 m`;
  if (m < 1000) return `≈ ${num(Math.round(m / 50) * 50)} m`;
  return `≈ ${num(m / 1000, 1, 1)} km`;
}

function sayIndex(m) {
  if (m === 0) return 0;
  if (m < 500) return 1;
  if (m < 1500) return 2;
  if (m < 2500) return 3;
  if (m < 4000) return 4;
  return 5;
}

function coordText(lat, lon) {
  return `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
}

/** "6.6 km E of Grybaulia" -> {km, dir, place} */
function parseNear(s) {
  const m = /^([\d.]+)\s*km\s+([NSEW]{1,2})\s+of\s+(.+)$/.exec(s || '');
  if (!m) return null;
  return { km: parseFloat(m[1]), dir: m[2], place: m[3] };
}

function nearText(s) {
  const p = parseNear(s);
  if (!p) return s || '';
  const dir = DIRS[state.lang][p.dir] || p.dir;
  return `${p.place} · ${num(p.km, 1, 1)} km ${dir}`;
}

function prettyTag(v) {
  return String(v).replace(/_/g, ' ');
}

function roadText(r) {
  const lang = state.lang;
  const hw = HIGHWAY[lang][r.highway] || prettyTag(r.highway);
  const parts = [`<b>${esc(hw)}</b>`];
  parts.push(esc(r.surface ? (SURFACE[lang][r.surface] || prettyTag(r.surface)) : t().noSurface));
  const label = r.name || (r.ref ? (lang === 'lt' ? `kelias Nr. ${r.ref}` : `road no. ${r.ref}`) : null);
  if (label) parts.push(esc(label));
  parts.push(esc(COUNTRY[lang][r.country] || r.country));
  return parts.join(' · ');
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function fold(s) {
  return s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
}

/* ═══════════════════════════ boot ═══════════════════════════ */

async function boot() {
  cacheEls();
  readHash();
  restorePrefs();

  const [spots, grid, land] = await Promise.all([
    getJSON('data/spots.json'),
    getJSON('data/grid.json'),
    getJSON('data/land.geojson'),
  ]);
  data.spots = spots;
  data.grid = grid;
  data.land = land;

  initMap();
  wireUI();
  applyLang();
  await setScenario(state.scenario, { initial: true });
  restoreFromHash();

  // Non-blocking extras.
  loadPlaces();
  loadRasters();
}

function cacheEls() {
  el.scenarioSeg = document.getElementById('scenario-seg');
  el.langSeg = document.getElementById('lang-seg');
  el.baseSeg = document.getElementById('basemap-seg');
  el.bandsToggle = document.getElementById('bands-toggle');
  el.mapCtl = document.getElementById('mapctl');
  el.spots = document.getElementById('spots');
  el.spotsNote = document.getElementById('spots-note');
  el.legend = document.getElementById('legend');
  el.legendCard = document.getElementById('legend-card');
  el.readout = document.getElementById('readout');
  el.brandReset = document.getElementById('brand-reset');
  el.scenarioWrap = document.getElementById('scenario-wrap');
  el.scenarioInfo = document.getElementById('scenario-info');
  el.scenarioPop = document.getElementById('scenario-pop');
  el.q = document.getElementById('q');
  el.qList = document.getElementById('q-list');
  el.qClear = document.getElementById('q-clear');
  el.about = document.getElementById('about');
  el.aboutBody = document.getElementById('about-body');
  el.aboutBtn = document.getElementById('about-btn');
  el.panel = document.getElementById('panel');
  el.panelBody = document.getElementById('panel-body');
  el.panelHandle = document.getElementById('panel-handle');
}

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

/* ═══════════════════════════ map ═══════════════════════════ */

function initMap() {
  map = L.map('map', {
    zoomControl: false,
    attributionControl: true,
    minZoom: 6,
    maxZoom: 18,
    worldCopyJump: false,
    zoomSnap: 0.5,
  });

  map.createPane('bandsPane').style.zIndex = 380;
  map.createPane('landPane').style.zIndex = 390;
  map.getPane('bandsPane').style.pointerEvents = 'none';
  map.getPane('landPane').style.pointerEvents = 'none';

  setBasemap(state.base, true);

  const landRenderer = L.canvas({ pane: 'landPane' });
  landLayer = L.layerGroup([
    L.geoJSON(data.land, {
      pane: 'landPane', renderer: landRenderer, interactive: false,
      style: { color: 'rgba(255,255,255,.45)', weight: 3.5, fill: false, lineJoin: 'round' },
    }),
    L.geoJSON(data.land, {
      pane: 'landPane', renderer: landRenderer, interactive: false,
      style: { color: 'rgba(34,39,31,.5)', weight: 1, fill: false, lineJoin: 'round' },
    }),
  ]).addTo(map);

  selLayer = L.layerGroup().addTo(map);

  map.on('click', (e) => {
    setPoint({ lat: e.latlng.lat, lon: e.latlng.lng });
  });
  map.on('zoomend moveend', () => {
    if (state.point) { state.zoom = round1(map.getZoom()); writeHash(); }
  });

  zoomCtl = L.control.zoom({ position: 'topright' }).addTo(map);
  placeControls();
  window.addEventListener('resize', debounce(placeControls, 200));
}

function round1(v) { return Math.round(v * 10) / 10; }

/** The panel owns the top-left on desktop and the bottom on mobile; controls dodge it. */
function placeControls() {
  if (zoomCtl) zoomCtl.setPosition(isMobile() ? 'topleft' : 'topright');
  syncSheetHeight();
  syncReadoutState();
}

function syncSheetHeight() {
  const h = isMobile() ? Math.round(el.panel.getBoundingClientRect().height) : 0;
  document.documentElement.style.setProperty('--sheet-h', `${h}px`);
}

/** The floating cluster owns the map's top-right; the zoom buttons go under it. */
function syncCtlHeight() {
  const h = Math.round(el.mapCtl.getBoundingClientRect().height);
  document.documentElement.style.setProperty('--ctl-h', `${h}px`);
}

function setBasemap(kind, initial) {
  if (baseKind === kind && baseLayer) return;
  baseKind = kind;
  state.base = kind;
  if (baseLayer) map.removeLayer(baseLayer);
  const b = BASEMAPS[kind];
  baseLayer = L.tileLayer(b.url, b.opts).addTo(map);
  for (const btn of el.baseSeg.querySelectorAll('[data-base]')) {
    btn.setAttribute('aria-pressed', String(btn.dataset.base === kind));
  }
  if (bandsLayer) bandsLayer.setStyle(bandStyle);
  try { localStorage.setItem('al.base', kind); } catch { /* ignore */ }
  if (!initial) writeHash();
}

function landBounds() {
  return L.geoJSON(data.land).getBounds();
}

/** Padding in px that keeps content clear of the panel. */
function fitPadding() {
  const r = el.panel.getBoundingClientRect();
  if (isMobile()) return { paddingTopLeft: [14, 14], paddingBottomRight: [14, Math.min(r.height, window.innerHeight * 0.6) + 14] };
  return { paddingTopLeft: [r.width + 28, 20], paddingBottomRight: [20, 24] };
}

function fitCountry(animate = true) {
  const p = fitPadding();
  if (animate && !reduceMotion.matches) map.flyToBounds(landBounds(), { ...p, duration: 0.8 });
  else map.fitBounds(landBounds(), p);
}

/** Centre so the target sits in the part of the map the panel does not cover. */
function focusOn(latlng, zoom, animate = true) {
  const r = el.panel.getBoundingClientRect();
  const pt = map.project(latlng, zoom);
  if (isMobile()) pt.y += Math.min(r.height, window.innerHeight * 0.62) / 2;
  else pt.x -= (r.width + 28) / 2;
  const center = map.unproject(pt, zoom);
  if (!animate || reduceMotion.matches) map.setView(center, zoom, { animate: false });
  else map.flyTo(center, zoom, { duration: 1.0 });
}

/** Frame one spot's circle, never tighter than ~z12.5. */
function viewSpot(s, animate = true) {
  const pad = L.point(isMobile() ? 30 : 40, isMobile() ? 30 : 40);
  const bounds = L.latLng(s.latlng).toBounds(s.distance_m * 2.3);
  const z = Math.min(12.5, map.getBoundsZoom(bounds, false, pad));
  focusOn(L.latLng(s.latlng), z, animate);
}

/* ═══════════════════════════ bands ═══════════════════════════ */

async function bandsFor(scenario) {
  if (!data.bands[scenario]) {
    data.bands[scenario] = await getJSON(`data/bands_${scenario}.geojson`);
  }
  return data.bands[scenario];
}

/* Bands nest, so their fills stack. Imagery needs a lighter hand than the map. */
function bandStyle(f) {
  const c = BAND_COLORS[f.properties.km] || BAND_COLORS[4];
  return { color: c, weight: 1, opacity: 0.9, fillColor: c, fillOpacity: state.base === 'sat' ? 0.24 : 0.35 };
}

async function drawBands() {
  const gj = await bandsFor(state.scenario);
  if (bandsLayer) { map.removeLayer(bandsLayer); bandsLayer = null; }
  const renderer = L.canvas({ pane: 'bandsPane', padding: 0.3 });
  bandsLayer = L.geoJSON(gj, { pane: 'bandsPane', renderer, interactive: false, style: bandStyle });
  if (state.bands) bandsLayer.addTo(map);
  renderLegend(gj);
}

function renderLegend(gj) {
  const kms = [...new Set(gj.features.map((f) => f.properties.km))].sort((a, b) => a - b);
  el.legend.innerHTML = kms
    .map((k) => `<li><span class="sw" style="background:${BAND_COLORS[k]}"></span><span>${esc(t().legendItem(k))}</span></li>`)
    .join('');
  syncLegend();
}

/** The legend only means something while the bands are drawn. */
function syncLegend() {
  el.legendCard.hidden = !state.bands || !el.legend.children.length;
  syncCtlHeight();
}

/* ═══════════════════════════ spots ═══════════════════════════ */

function activeSpots() {
  return data.spots.scenarios[state.scenario].spots;
}

const CROWN = `<svg class="spot__crown" viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M2 12.2 1 4.4l3.6 2.7L8 2.2l3.4 4.9L15 4.4l-1 7.8H2Z" fill="currentColor"/></svg>`;

function renderSpots() {
  const sc = data.spots.scenarios[state.scenario];
  el.spotsNote.textContent = t().spotsNote(num(sc.ways), num(sc.road_km));

  el.spots.innerHTML = activeSpots()
    .map((s) => {
      const win = s.rank === 1;
      const title = s.protected && s.protected.length ? s.protected.join(' · ') : nearText(s.near);
      const near = s.protected && s.protected.length ? nearText(s.near) : '';
      const on = state.spot === s.rank;
      return `<li class="spot-item${win ? ' spot-item--win' : ''}${on ? ' is-on' : ''}" data-item="${s.rank}">
        <button type="button" class="spot" data-rank="${s.rank}" aria-pressed="${on}">
          <span class="spot__rank" aria-hidden="true">${win ? CROWN : s.rank}</span>
          <span class="vh">${esc(t().rankAria(s.rank))}</span>
          <span class="spot__dist">${km2(s.distance_m)}<small>km</small></span>
          <span class="spot__meta">
            <span class="spot__title">${esc(title)}</span>
            ${near ? `<span class="spot__near">${esc(near)}</span>` : ''}
          </span>
        </button>
        <div class="spot__foot">
          <p class="spot__road">${esc(t().nearestRoad)}: ${roadText(s.nearest_road)}
            · <a href="${esc(s.nearest_road.url)}" target="_blank" rel="noopener">OSM ↗</a></p>
          <p class="spot__hint">${esc(t().spotHint)}</p>
        </div>
      </li>`;
    })
    .join('');

  for (const b of el.spots.querySelectorAll('.spot')) {
    b.addEventListener('click', () => {
      const rank = Number(b.dataset.rank);
      selectSpot(state.spot === rank ? null : rank);
    });
  }
  syncScrollHint();
}

function renderRankMarkers() {
  rankMarkers.forEach((m) => map.removeLayer(m));
  rankMarkers = activeSpots().map((s) => {
    const on = state.spot === s.rank;
    const icon = L.divIcon({
      className: '',
      html: `<div class="rank-pin${on ? ' rank-pin--on' : ''}">${s.rank}</div>`,
      iconSize: [24, 24],
      iconAnchor: [12, 12],
    });
    const m = L.marker(s.latlng, { icon, keyboard: true, zIndexOffset: 500 });
    m.on('click', (e) => {
      if (e.originalEvent) L.DomEvent.stopPropagation(e.originalEvent);
      selectSpot(state.spot === s.rank ? null : s.rank);
    });
    m.bindTooltip(`${km2(s.distance_m)} km`, { direction: 'top', offset: [0, -14] });
    return m.addTo(map);
  });
}

function selectSpot(rank, opts = {}) {
  state.spot = rank;
  state.readoutExpanded = false;   // every new selection opens as the pill on mobile
  // One card, one subject: a spot takes the readout over from any clicked point.
  if (rank && state.point) {
    state.point = null;
    state.zoom = null;
    if (pointMarker) { map.removeLayer(pointMarker); pointMarker = null; }
  }
  drawSelection();
  renderRankMarkers();
  for (const b of el.spots.querySelectorAll('.spot')) {
    b.setAttribute('aria-pressed', String(Number(b.dataset.rank) === rank));
  }
  for (const li of el.spots.querySelectorAll('.spot-item')) {
    li.classList.toggle('is-on', Number(li.dataset.item) === rank);
  }
  renderReadout();
  if (!opts.silent) {
    if (rank) {
      viewSpot(activeSpots().find((x) => x.rank === rank));
      const card = el.spots.querySelector(`[data-item="${rank}"]`);
      if (card) card.scrollIntoView({ block: 'nearest', behavior: reduceMotion.matches ? 'auto' : 'smooth' });
      if (isMobile()) el.panel.classList.remove('panel--collapsed');
    } else {
      fitCountry(true);
    }
  }
  writeHash();
}

function drawSelection() {
  selLayer.clearLayers();
  if (!state.spot) return;
  const s = activeSpots().find((x) => x.rank === state.spot);
  if (!s) return;

  // Circle: radius = distance to the nearest road. Cased so it reads on imagery too.
  L.circle(s.latlng, { radius: s.distance_m, color: HALO, weight: 5, fill: false, interactive: false }).addTo(selLayer);
  L.circle(s.latlng, {
    radius: s.distance_m, color: MAP_ACCENT, weight: 2, dashArray: '7 6',
    fillColor: MAP_ACCENT, fillOpacity: 0.05, interactive: false,
  }).addTo(selLayer);

  const nearest = [];
  for (const r of s.roads) {
    if (r.n === 1) { nearest.push(r); continue; }
    L.polyline(r.ll, r.t === 1
      ? { color: ROAD_TRACK, weight: 1.5, dashArray: '4 4', interactive: false }
      : { color: ROAD_REAL, weight: 2, interactive: false }).addTo(selLayer);
  }
  for (const r of nearest) {
    L.polyline(r.ll, { color: HALO, weight: 6.5, interactive: false }).addTo(selLayer);
    L.polyline(r.ll, { color: MAP_ACCENT, weight: 3.5, interactive: false }).addTo(selLayer);
  }
}

/* ═══════════════════════════ scenario ═══════════════════════════ */

async function setScenario(kind, opts = {}) {
  state.scenario = kind;
  for (const btn of el.scenarioSeg.querySelectorAll('[data-scenario]')) {
    btn.setAttribute('aria-pressed', String(btn.dataset.scenario === kind));
  }
  if (state.spot && !activeSpots().some((s) => s.rank === state.spot)) state.spot = null;
  renderSpots();
  renderRankMarkers();
  drawSelection();
  renderReadout();
  // The same rank is a different place in the other scenario: follow it there.
  if (state.spot && !opts.initial) viewSpot(activeSpots().find((s) => s.rank === state.spot));
  await drawBands();
  if (!opts.initial) writeHash();
}

/* ═══════════════════════════ raster readout ═══════════════════════════ */

async function loadRasters() {
  try {
    const [a, b] = await Promise.all([
      loadRaster('data/dist_A.png'),
      loadRaster('data/dist_B.png'),
    ]);
    data.raster.A = a;
    data.raster.B = b;
  } catch (err) {
    data.rasterError = true;
    console.warn('distance grid unavailable:', err && err.message);
  }
  renderReadout();
}

async function loadRaster(url) {
  const g = data.grid;
  const w = g.width, h = g.height;
  const src = await decodeImage(url);
  const cv = document.createElement('canvas');
  cv.width = w;
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  ctx.imageSmoothingEnabled = false;
  const out = new Uint8Array(w * h);
  const CHUNK = 256;
  for (let y = 0; y < h; y += CHUNK) {
    const hh = Math.min(CHUNK, h - y);
    cv.height = hh;                       // also clears the canvas
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(src, 0, y, w, hh, 0, 0, w, hh);
    const px = ctx.getImageData(0, 0, w, hh).data;
    const base = y * w;
    for (let i = 0, n = w * hh; i < n; i++) out[base + i] = px[i * 4];
  }
  if (src.close) src.close();
  cv.width = cv.height = 0;
  return out;
}

async function decodeImage(url) {
  if (typeof createImageBitmap === 'function') {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${url}: ${res.status}`);
    const blob = await res.blob();
    try {
      return await createImageBitmap(blob, { colorSpaceConversion: 'none', premultiplyAlpha: 'none' });
    } catch {
      return await createImageBitmap(blob);
    }
  }
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`${url}: decode failed`));
    img.src = url;
  });
}

/** metres to the nearest road, or null outside the grid / no data */
function sample(scenario, lat, lon) {
  const buf = data.raster[scenario];
  const g = data.grid;
  if (!buf) return undefined;                       // not loaded yet
  const col = Math.floor((lon - g.west) / g.dlon);
  const row = Math.floor((g.north - lat) / g.dlat);
  if (col < 0 || row < 0 || col >= g.width || row >= g.height) return null;
  const v = buf[row * g.width + col];
  return v === g.nodata ? null : v * g.scale_m;
}

/* ═══════════════════════════ point + readout ═══════════════════════════ */

function setPoint(p, opts = {}) {
  state.point = p;
  state.readoutExpanded = false;   // same rule for a clicked or searched point
  if (pointMarker) map.removeLayer(pointMarker);
  pointMarker = L.marker([p.lat, p.lon], { title: p.name || coordText(p.lat, p.lon) }).addTo(map);
  renderReadout();
  if (opts.fly) {
    const z = Math.max(map.getZoom(), 12);
    state.zoom = round1(z);
    focusOn(L.latLng(p.lat, p.lon), z);
  } else {
    state.zoom = round1(map.getZoom());
  }
  writeHash();
  if (isMobile()) el.panel.classList.remove('panel--collapsed');
}

function clearPoint() {
  state.point = null;
  state.zoom = null;
  if (pointMarker) { map.removeLayer(pointMarker); pointMarker = null; }
  renderReadout();
  writeHash();
}

/** The floating card: a clicked point wins over a selected spot, since it is the newer act. */
function renderReadout() {
  const spot = state.spot ? activeSpots().find((s) => s.rank === state.spot) : null;
  const html = state.point ? pointCard(state.point) : spot ? spotCard(spot) : '';

  el.readout.hidden = !html;
  el.readout.innerHTML = html;
  if (html) {
    for (const b of el.readout.querySelectorAll('.readout__close')) b.addEventListener('click', closeReadout);
    el.readout.querySelector('.readout__pill').addEventListener('click', () => setReadoutExpanded(true));
    // Anywhere in the header folds the card back up; the close button keeps its own job.
    el.readout.querySelector('.readout__top').addEventListener('click', (e) => {
      if (!isMobile() || e.target.closest('.readout__close')) return;
      setReadoutExpanded(false);
    });
  }
  syncReadoutState();
}

function setReadoutExpanded(on) {
  state.readoutExpanded = on;
  syncReadoutState();
}

/** Above the breakpoint there is no pill: the card is always the full card. */
function syncReadoutState() {
  const expanded = !isMobile() || state.readoutExpanded;
  el.readout.classList.toggle('readout--expanded', expanded);
  el.mapCtl.classList.toggle('mapctl--expanded', expanded && !el.readout.hidden);   // mobile drops the legend for it
  for (const b of el.readout.querySelectorAll('.readout__pill, .readout__collapse')) {
    b.setAttribute('aria-expanded', String(expanded));
  }
  syncCtlHeight();
}

/** The collapsed state: one line, distance first, place name ellipsised.
    The label carries the reading too: the visible text is ellipsised, and a bare
    "expand" would leave a screen reader with no idea what it is expanding. */
function readoutPill(dist, name) {
  return `<div class="readout__pillrow">
      <button type="button" class="readout__pill" aria-controls="readout-card" aria-expanded="false"
              aria-label="${esc(`${t().expandCard}: ${dist} · ${name}`)}">
        <span class="readout__pill-dist">${esc(dist)}</span>
        <span class="readout__pill-sep" aria-hidden="true">·</span>
        <span class="readout__pill-name">${esc(name)}</span>
        <span class="readout__chev" aria-hidden="true">&rsaquo;</span>
      </button>
      <button type="button" class="readout__close readout__close--pill" aria-label="${esc(t().close)}">&times;</button>
    </div>`;
}

function readoutTop(kicker) {
  return `<div class="readout__top">
      <span class="readout__kicker">${esc(kicker)}</span>
      <button type="button" class="readout__collapse" aria-controls="readout-card" aria-expanded="true"
              aria-label="${esc(t().collapseCard)}"><span class="readout__chev" aria-hidden="true">&rsaquo;</span></button>
      <button type="button" class="readout__close" aria-label="${esc(t().close)}">&times;</button>
    </div>`;
}

function googleLink(lat, lon) {
  return `<a class="readout__link" target="_blank" rel="noopener"
     href="https://www.google.com/maps?q=${lat.toFixed(5)},${lon.toFixed(5)}&t=k">${esc(t().googleSat)}</a>`;
}

function spotCard(s) {
  const prot = s.protected && s.protected.length ? s.protected.join(' · ') : '';
  const near = nearText(s.near);
  const [lat, lon] = s.latlng;
  return `${readoutPill(`${km2(s.distance_m)} km`, prot || near)}
    <div class="readout__card" id="readout-card">
      ${readoutTop(t().rankAria(s.rank))}
      <p class="readout__dist">${esc(km2(s.distance_m))}<small>km</small></p>
      <p class="readout__cap">${esc(t().readoutTitle)}</p>
      <p class="readout__name">${esc(prot || near)}</p>
      ${prot ? `<p class="readout__sub">${esc(near)}</p>` : ''}
      <p class="readout__road">${esc(t().nearestRoad)}: ${roadText(s.nearest_road)}</p>
      <div class="readout__foot">
        <span class="readout__ll">${esc(coordText(lat, lon))}</span>
        <span class="readout__links">
          <a class="readout__link" target="_blank" rel="noopener" href="${esc(s.nearest_road.url)}">OSM ↗</a>
          ${googleLink(lat, lon)}
        </span>
      </div>
    </div>`;
}

function pointCard(p) {
  const a = sample('A', p.lat, p.lon);
  const b = sample('B', p.lat, p.lon);
  const loading = a === undefined || b === undefined;
  const nodata = !loading && a === null && b === null;
  const active = state.scenario === 'A' ? a : b;
  const other = state.scenario === 'A' ? b : a;
  const otherLabel = state.scenario === 'A' ? t().scenarioB : t().scenarioA;

  const head = loading
    ? `<p class="readout__wait">${esc(t().computing)}</p>`
    : active === null
      ? `<p class="readout__wait">${esc(data.rasterError ? t().rasterFail : t().noValue)}</p>`
      : `<p class="readout__dist">${esc(approx(active))}</p>
         <p class="readout__cap">${esc(t().readoutTitle)} · ${esc(state.scenario === 'A' ? t().scenarioA : t().scenarioB)}</p>`;

  const body = nodata
    ? `<p class="readout__wait">${esc(t().nodata)}</p>
       <p class="readout__name">${esc(p.name || t().readoutPoint)}</p>`
    : `${head}
       <p class="readout__name">${esc(p.name || t().readoutPoint)}</p>
       ${other === undefined || other === null ? ''
         : `<p class="readout__road">${esc(otherLabel)}: ${esc(approx(other))}</p>`}
       ${active === null || active === undefined ? ''
         : `<p class="readout__say">${esc(t().say[sayIndex(active)])}</p>`}`;

  const pillDist = loading ? t().computing
    : active === null || active === undefined ? t().noValue
      : approx(active);

  return `${readoutPill(pillDist, p.name || t().readoutPoint)}
    <div class="readout__card" id="readout-card">
      ${readoutTop(t().readoutKicker)}
      ${body}
      <div class="readout__foot">
        <span class="readout__ll">${esc(coordText(p.lat, p.lon))}</span>
        <span class="readout__links">${googleLink(p.lat, p.lon)}</span>
      </div>
    </div>`;
}

/** Closing the card drops the selection behind it, but leaves the viewport alone. */
function closeReadout() {
  if (state.spot !== null) selectSpot(null, { silent: true });
  if (state.point) clearPoint();
}

/** The title is the way back: full country, nothing selected. */
function resetView() {
  if (state.spot !== null) selectSpot(null, { silent: true });
  if (state.point) clearPoint();
  fitCountry(true);
}

/* ═══════════════════════════ search ═══════════════════════════ */

let sugg = [];
let suggIdx = -1;

async function loadPlaces() {
  try {
    const raw = await getJSON('data/places.json');
    data.places = raw.map((p) => {
      const norm = fold(p[0]);
      return { name: p[0], lat: p[1], lon: p[2], t: p[3], norm, words: norm.split(/[^a-z0-9]+/).filter(Boolean) };
    });
  } catch (err) {
    console.warn('gazetteer unavailable:', err && err.message);
  }
  if (el.q.value.trim()) runSearch(el.q.value);
}

function parseCoords(s) {
  const tok = s.trim().split(/[,;\s]+/).filter(Boolean);
  if (tok.length !== 2) return null;
  if (!tok.every((x) => /^-?\d{1,3}(\.\d+)?$/.test(x))) return null;
  const lat = parseFloat(tok[0]), lon = parseFloat(tok[1]);
  if (!isFinite(lat) || !isFinite(lon)) return null;
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { lat, lon };
}

function matchPlaces(q) {
  const n = fold(q.trim());
  if (!n || !data.places) return [];
  const out = [];
  for (const p of data.places) {
    let score = -1;
    if (p.norm.startsWith(n)) score = p.norm.length === n.length ? 0 : 1;
    else if (p.words.some((w) => w.startsWith(n))) score = 2;
    if (score < 0) continue;
    const rank = score * 10 + (p.t === 'c' ? 0 : p.t === 't' ? 1 : 2);
    out.push({ p, rank });
    if (out.length > 400) break;
  }
  out.sort((x, y) => x.rank - y.rank || x.p.name.localeCompare(y.p.name, 'lt'));
  return out.slice(0, 8).map((x) => x.p);
}

function runSearch(q) {
  const coords = parseCoords(q);
  if (coords) {
    sugg = [{ coord: true, name: coordText(coords.lat, coords.lon), lat: coords.lat, lon: coords.lon }];
  } else {
    sugg = matchPlaces(q);
  }
  suggIdx = sugg.length ? 0 : -1;
  renderSuggestions(q);
}

function renderSuggestions(q) {
  const showing = q.trim().length > 0;
  el.qClear.hidden = !showing;
  if (!showing) { closeSuggestions(); return; }

  if (!sugg.length) {
    const msg = data.places ? t().searchEmpty : t().searchLoading;
    el.qList.innerHTML = `<li class="search__opt" role="option" aria-disabled="true" aria-selected="false"><span class="search__name" style="opacity:.7">${esc(msg)}</span></li>`;
  } else {
    el.qList.innerHTML = sugg
      .map((s, i) => `<li class="search__opt" role="option" id="q-opt-${i}" aria-selected="${i === suggIdx}" data-i="${i}">
          <span class="search__name">${esc(s.name)}</span>
          <span class="${s.coord ? 'search__coord' : 'search__badge'}">${esc(s.coord ? '↗' : PLACE_TYPE[state.lang][s.t])}</span>
        </li>`)
      .join('');
    for (const li of el.qList.querySelectorAll('[data-i]')) {
      li.addEventListener('mousedown', (e) => { e.preventDefault(); choose(Number(li.dataset.i)); });
    }
  }
  el.qList.hidden = false;
  el.q.setAttribute('aria-expanded', 'true');
  el.q.setAttribute('aria-activedescendant', suggIdx >= 0 ? `q-opt-${suggIdx}` : '');
}

function closeSuggestions() {
  el.qList.hidden = true;
  el.qList.innerHTML = '';
  el.q.setAttribute('aria-expanded', 'false');
  el.q.removeAttribute('aria-activedescendant');
}

function choose(i) {
  const s = sugg[i];
  if (!s) return;
  el.q.value = s.name;
  closeSuggestions();
  el.q.blur();
  selectSpot(null, { silent: true });
  setPoint({ lat: s.lat, lon: s.lon, name: s.coord ? null : s.name }, { fly: true });
}

function wireSearch() {
  el.q.addEventListener('input', () => runSearch(el.q.value));
  el.q.addEventListener('focus', () => { if (el.q.value.trim()) runSearch(el.q.value); });
  el.q.addEventListener('blur', () => setTimeout(closeSuggestions, 120));
  el.q.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (el.qList.hidden || !sugg.length) return;
      e.preventDefault();
      suggIdx = (suggIdx + (e.key === 'ArrowDown' ? 1 : -1) + sugg.length) % sugg.length;
      renderSuggestions(el.q.value);
    } else if (e.key === 'Enter') {
      if (sugg.length) { e.preventDefault(); choose(suggIdx < 0 ? 0 : suggIdx); }
    } else if (e.key === 'Escape') {
      if (!el.qList.hidden) { e.preventDefault(); closeSuggestions(); }
      else { el.q.value = ''; el.qClear.hidden = true; }
    }
  });
  el.qClear.addEventListener('click', () => {
    el.q.value = '';
    el.qClear.hidden = true;
    closeSuggestions();
    el.q.focus();
  });
}

/* ═══════════════════════════ chrome ═══════════════════════════ */

function wireUI() {
  el.scenarioSeg.addEventListener('click', (e) => {
    const b = e.target.closest('[data-scenario]');
    if (b) setScenario(b.dataset.scenario);
  });

  el.langSeg.addEventListener('click', (e) => {
    const b = e.target.closest('[data-lang]');
    if (!b) return;
    state.lang = b.dataset.lang;
    try { localStorage.setItem('al.lang', state.lang); } catch { /* ignore */ }
    applyLang();
    renderSpots();
    renderRankMarkers();
    renderReadout();
    if (data.bands[state.scenario]) renderLegend(data.bands[state.scenario]);
    writeHash();
  });

  el.baseSeg.addEventListener('click', (e) => {
    const b = e.target.closest('[data-base]');
    if (b) setBasemap(b.dataset.base);
  });

  el.bandsToggle.addEventListener('change', () => {
    state.bands = el.bandsToggle.checked;
    if (bandsLayer) {
      if (state.bands) bandsLayer.addTo(map); else map.removeLayer(bandsLayer);
    }
    syncLegend();
    try { localStorage.setItem('al.bands', state.bands ? '1' : '0'); } catch { /* ignore */ }
  });

  el.brandReset.addEventListener('click', resetView);
  wireScenarioHelp();

  el.aboutBtn.addEventListener('click', () => {
    if (typeof el.about.showModal === 'function') el.about.showModal();
    else el.about.setAttribute('open', '');
  });

  el.panelHandle.addEventListener('click', () => {
    const collapsed = el.panel.classList.toggle('panel--collapsed');
    el.panelHandle.setAttribute('aria-expanded', String(!collapsed));
    setTimeout(() => map.invalidateSize({ animate: false }), 220);
  });

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || el.about.open) return;
    if (popOpen()) { closePop(el.scenarioWrap.contains(document.activeElement)); return; }
    if (state.spot !== null && document.activeElement !== el.q) selectSpot(null);
  });

  wireSearch();
  window.addEventListener('hashchange', () => { readHash(); applyHashState(); });
  mobileMQ.addEventListener('change', placeControls);   // crossing it re-decides pill vs card

  el.panelBody.addEventListener('scroll', syncScrollHint, { passive: true });
  if (typeof ResizeObserver === 'function') {
    const ro = new ResizeObserver(() => { syncSheetHeight(); syncCtlHeight(); syncScrollHint(); });
    ro.observe(el.panel);
    ro.observe(el.mapCtl);
    ro.observe(el.readout);
  }
  syncScrollHint();
}

/* ── scenario explainer ── */

let popPinned = false;
let popTimer;

function popOpen() { return !el.scenarioPop.hidden; }

function openPop() {
  clearTimeout(popTimer);
  el.scenarioPop.hidden = false;
  el.scenarioInfo.setAttribute('aria-expanded', 'true');
}

function closePop(refocus) {
  clearTimeout(popTimer);
  popPinned = false;
  el.scenarioPop.hidden = true;
  el.scenarioInfo.setAttribute('aria-expanded', 'false');
  if (refocus) el.scenarioInfo.focus();
}

/** Hover on a pointer device, click or tap anywhere else; a click pins it open. */
function wireScenarioHelp() {
  const canHover = window.matchMedia('(hover: hover)').matches;
  const leave = () => { if (!popPinned) popTimer = setTimeout(() => closePop(false), 160); };

  el.scenarioInfo.addEventListener('click', () => {
    if (popPinned) { closePop(false); return; }
    popPinned = true;
    openPop();
  });

  if (canHover) {
    el.scenarioInfo.addEventListener('mouseenter', openPop);
    el.scenarioInfo.addEventListener('mouseleave', leave);
    el.scenarioPop.addEventListener('mouseenter', () => clearTimeout(popTimer));
    el.scenarioPop.addEventListener('mouseleave', leave);
  }

  document.addEventListener('pointerdown', (e) => {
    if (!popOpen() || el.scenarioWrap.contains(e.target)) return;
    closePop(false);
  });
}

function syncScrollHint() {
  const b = el.panelBody;
  if (!b) return;
  el.panel.classList.toggle('has-more', b.scrollHeight - b.clientHeight - b.scrollTop > 6);
}

function applyLang() {
  const d = t();
  document.documentElement.lang = state.lang;
  document.title = d.htmlTitle;

  for (const n of document.querySelectorAll('[data-i18n]')) {
    const v = d[n.dataset.i18n];
    if (typeof v === 'string') n.textContent = v;
  }
  for (const n of document.querySelectorAll('[data-i18n-aria]')) {
    const v = d[n.dataset.i18nAria];
    if (typeof v === 'string') n.setAttribute('aria-label', v);
  }
  for (const n of document.querySelectorAll('[data-i18n-title]')) {
    const v = d[n.dataset.i18nTitle];
    if (typeof v === 'string') n.title = v;
  }
  for (const b of el.langSeg.querySelectorAll('[data-lang]')) {
    b.setAttribute('aria-pressed', String(b.dataset.lang === state.lang));
  }

  const segBtns = el.scenarioSeg.querySelectorAll('[data-scenario]');
  segBtns[0].textContent = d.scenarioA;
  segBtns[0].title = d.scenarioAHint;
  segBtns[1].textContent = d.scenarioB;
  segBtns[1].title = d.scenarioBHint;

  el.q.placeholder = d.searchPlaceholder;
  el.aboutBody.innerHTML = `${d.aboutBody}<p><a href="${REPO}" target="_blank" rel="noopener">${esc(d.aboutRepo)} ↗</a></p>`;
}

function restorePrefs() {
  try {
    const lang = localStorage.getItem('al.lang');
    if (!hashHas('lang') && (lang === 'lt' || lang === 'en')) state.lang = lang;
    const base = localStorage.getItem('al.base');
    if (!hashHas('base') && (base === 'osm' || base === 'sat')) state.base = base;
    const bands = localStorage.getItem('al.bands');
    if (bands === '0') state.bands = false;
  } catch { /* ignore */ }
  el.bandsToggle.checked = state.bands;
}

/* ═══════════════════════════ hash state ═══════════════════════════ */

let hashParams = new URLSearchParams();
let writingHash = false;

function readHash() {
  hashParams = new URLSearchParams(location.hash.replace(/^#/, ''));
  const s = hashParams.get('s');
  if (s === 'A' || s === 'B') state.scenario = s;
  const lang = hashParams.get('lang');
  if (lang === 'lt' || lang === 'en') state.lang = lang;
  const base = hashParams.get('base');
  if (base === 'osm' || base === 'sat') state.base = base;
}

function hashHas(k) {
  return new URLSearchParams(location.hash.replace(/^#/, '')).has(k);
}

function restoreFromHash() {
  const spot = Number(hashParams.get('spot'));
  const ll = hashParams.get('ll');
  const z = parseFloat(hashParams.get('z'));

  // Start from a clean slate; the locals above already hold what we need.
  selectSpot(null, { silent: true });
  if (pointMarker) { map.removeLayer(pointMarker); pointMarker = null; }
  state.point = null;
  state.zoom = null;
  renderReadout();

  if (spot >= 1 && activeSpots().some((s) => s.rank === spot)) {
    selectSpot(spot, { silent: true });
    viewSpot(activeSpots().find((s) => s.rank === spot), false);
    return;
  }
  if (ll) {
    const parts = ll.split(',').map(Number);
    if (parts.length === 2 && parts.every(isFinite)) {
      map.setView([parts[0], parts[1]], isFinite(z) ? z : 13, { animate: false });
      setPoint({ lat: parts[0], lon: parts[1] });
      return;
    }
  }
  fitCountry(false);
}

function applyHashState() {
  // Fired on external hash changes (back/forward, a pasted link).
  if (writingHash) return;
  const want = hashParams;                       // setScenario/selectSpot rewrite hashParams
  setScenario(state.scenario, { initial: true }).then(() => {
    applyLang();
    setBasemap(state.base, true);
    hashParams = want;
    restoreFromHash();
    writeHash();
  });
}

function writeHash() {
  const p = new URLSearchParams();
  p.set('s', state.scenario);
  if (state.spot) p.set('spot', String(state.spot));
  else if (state.point) {
    p.set('ll', `${state.point.lat.toFixed(5)},${state.point.lon.toFixed(5)}`);
    if (state.zoom) p.set('z', String(state.zoom));
  }
  p.set('lang', state.lang);            // always: a shared link keeps the sharer's language
  if (state.base !== 'sat') p.set('base', state.base);
  const next = `#${p.toString().replace(/%2C/g, ',')}`;
  if (next === location.hash) return;
  writingHash = true;
  history.replaceState(null, '', next);
  hashParams = p;
  setTimeout(() => { writingHash = false; }, 0);
}

/* ═══════════════════════════ misc ═══════════════════════════ */

function debounce(fn, ms) {
  let id;
  return (...args) => { clearTimeout(id); id = setTimeout(() => fn(...args), ms); };
}

boot().catch((err) => {
  console.error(err);
  document.getElementById('spots-note').textContent = String(err && err.message ? err.message : err);
});

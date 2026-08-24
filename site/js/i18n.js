// UI strings and locale formatting. Country and region names never live here: Intl.DisplayNames gives the
// countries, regions.json carries the region names by language (see regionLabel).
// Add a key to both languages at once; t() falls back to en and then to the key so a miss is visible, not fatal.
export const LANGS = ['en', 'lt'];

const DICT = {
  en: {
    title: 'Poles of remoteness',
    subtitle: 'The places farthest from any road',
    metaDescription: 'The places farthest from any road, computed from OpenStreetMap data on a 250 m grid.',
    langGroup: 'Language',
    regionGroup: 'Region',
    scenarioGroup: 'Distance to',
    scenarioA: 'Any drivable way',
    scenarioAHint: 'forest and field tracks included',
    scenarioB: 'Public roads only',
    scenarioBHint: 'tracks excluded',
    basemapLabel: 'Base map',
    baseSat: 'Satellite',
    baseOsm: 'Map',
    zoomIn: 'Zoom in',
    zoomOut: 'Zoom out',
    legendLabel: 'Distance to the nearest road',
    rankingBtn: 'See the ranking',
    rankingTitle: 'Ranking',
    rankingNote: 'Distance from each unit’s remotest point to the nearest drivable way (A) and to the nearest public road (B).',
    locateBtn: 'Locate me',
    locateDenied: 'Location is off. Tap anywhere on the map to read the distance there.',
    locateUnavailable: 'Location is unavailable here.',
    locateHere: 'You are here',
    locateOutside: 'You are outside the mapped area.',
    headline: '{name}: the remotest point is {km} from {what}.',
    headlineA: 'anything drivable',
    headlineB: 'a public road',
    rankOf: '#{rank} of {count} in {region}',
    noPoles: '{name}: {reason}',
    reasonWithheld: 'the remotest points are withheld pending validation',
    reasonNone: 'no remotest point was found',
    polesLabel: 'Poles',
    poleHeading: 'Pole {rank}',
    poleOf: 'of {count}',
    distance: 'Distance',
    nearestRoad: 'Nearest road',
    nearestPlace: 'Nearest settlement',
    coordinates: 'Coordinates',
    openMaps: 'Open in Google Maps',
    unnamed: 'unnamed',
    noPlace: 'no settlement within the search window',
    withheldNote: '{n} further pole(s) withheld by validation',
    readoutAbout: 'about {d}',
    readoutOver: 'over {d}',
    readoutEdge: 'no data: edge of map data',
    readoutLoading: 'reading',
    readoutHint: 'Tap the map to read the distance to the nearest road',
    loadError: 'Could not load this place, try again',
    dataMissing: 'The map data is not published yet.',
    aboutBtn: 'About this map',
    close: 'Close',
    snapshotNote: 'OpenStreetMap snapshot {date}',
    attribution: '© OpenStreetMap contributors (ODbL). Remoteness data: this site, ODbL',
    attributionSat: 'Imagery: Esri, Maxar, Earthstar Geographics',
    scenarioShort_A: 'A',
    scenarioShort_B: 'B',
    hw_motorway: 'motorway', hw_trunk: 'trunk road', hw_primary: 'primary road', hw_secondary: 'secondary road',
    hw_tertiary: 'tertiary road', hw_unclassified: 'minor road', hw_residential: 'residential street',
    hw_living_street: 'living street', hw_service: 'service road', hw_track: 'track', hw_road: 'road',
    hw_motorway_link: 'motorway link', hw_trunk_link: 'trunk link', hw_primary_link: 'primary link',
    hw_secondary_link: 'secondary link', hw_tertiary_link: 'tertiary link',
    pl_city: 'city', pl_town: 'town', pl_village: 'village', pl_hamlet: 'hamlet',
    pl_isolated_dwelling: 'isolated dwelling', pl_farm: 'farm', pl_locality: 'locality', pl_suburb: 'suburb',
  },
  lt: {
    title: 'Atokiausios vietos',
    subtitle: 'Vietos, toliausiai nutolusios nuo bet kokio kelio',
    metaDescription: 'Vietos, toliausiai nutolusios nuo bet kokio kelio, apskaičiuotos iš OpenStreetMap duomenų 250 m tinkleliu.',
    langGroup: 'Kalba',
    regionGroup: 'Regionas',
    scenarioGroup: 'Atstumas iki',
    scenarioA: 'Bet kokio pravažiuojamo kelio',
    scenarioAHint: 'įskaitant miško ir lauko keliukus',
    scenarioB: 'Tik viešųjų kelių',
    scenarioBHint: 'be keliukų',
    basemapLabel: 'Pagrindas',
    baseSat: 'Palydovas',
    baseOsm: 'Žemėlapis',
    zoomIn: 'Priartinti',
    zoomOut: 'Nutolinti',
    legendLabel: 'Atstumas iki artimiausio kelio',
    rankingBtn: 'Rodyti reitingą',
    rankingTitle: 'Reitingas',
    rankingNote: 'Atstumas nuo kiekvieno vieneto atokiausio taško iki artimiausio pravažiuojamo kelio (A) ir iki artimiausio viešojo kelio (B).',
    locateBtn: 'Kur aš',
    locateDenied: 'Vietos nustatymas išjungtas. Palieskite žemėlapį ir pamatysite atstumą toje vietoje.',
    locateUnavailable: 'Vietos nustatymas čia neveikia.',
    locateHere: 'Jūs čia',
    locateOutside: 'Esate už žemėlapio ribų.',
    headline: '{name}: atokiausias taškas yra {km} nuo {what}.',
    headlineA: 'bet kokio pravažiuojamo kelio',
    headlineB: 'viešojo kelio',
    rankOf: '{rank} vieta iš {count} ({region})',
    noPoles: '{name}: {reason}',
    reasonWithheld: 'atokiausi taškai sulaikyti iki patikros',
    reasonNone: 'atokiausias taškas nerastas',
    polesLabel: 'Taškai',
    poleHeading: '{rank} taškas',
    poleOf: 'iš {count}',
    distance: 'Atstumas',
    nearestRoad: 'Artimiausias kelias',
    nearestPlace: 'Artimiausia gyvenvietė',
    coordinates: 'Koordinatės',
    openMaps: 'Atidaryti Google žemėlapiuose',
    unnamed: 'be pavadinimo',
    noPlace: 'gyvenviečių paieškos lange nėra',
    withheldNote: 'dar {n} tašk. sulaikyta patikros',
    readoutAbout: 'apie {d}',
    readoutOver: 'daugiau nei {d}',
    readoutEdge: 'nėra duomenų: žemėlapio duomenų kraštas',
    readoutLoading: 'skaitoma',
    readoutHint: 'Palieskite žemėlapį ir pamatysite atstumą iki artimiausio kelio',
    loadError: 'Nepavyko įkelti šios vietos, bandykite dar kartą',
    dataMissing: 'Žemėlapio duomenys dar nepaskelbti.',
    aboutBtn: 'Apie šį žemėlapį',
    close: 'Uždaryti',
    snapshotNote: 'OpenStreetMap duomenys {date}',
    attribution: '© OpenStreetMap bendruomenė (ODbL). Atokumo duomenys: ši svetainė, ODbL',
    attributionSat: 'Vaizdai: Esri, Maxar, Earthstar Geographics',
    scenarioShort_A: 'A',
    scenarioShort_B: 'B',
    hw_motorway: 'automagistralė', hw_trunk: 'magistralinis kelias', hw_primary: 'krašto kelias', hw_secondary: 'rajoninis kelias',
    hw_tertiary: 'vietinis kelias', hw_unclassified: 'nedidelis kelias', hw_residential: 'gyvenamoji gatvė',
    hw_living_street: 'gyvenamoji zona', hw_service: 'privažiavimo kelias', hw_track: 'miško ar lauko keliukas', hw_road: 'kelias',
    hw_motorway_link: 'automagistralės jungtis', hw_trunk_link: 'magistralės jungtis', hw_primary_link: 'krašto kelio jungtis',
    hw_secondary_link: 'rajoninio kelio jungtis', hw_tertiary_link: 'vietinio kelio jungtis',
    pl_city: 'miestas', pl_town: 'miestelis', pl_village: 'kaimas', pl_hamlet: 'viensėdis',
    pl_isolated_dwelling: 'vienkiemis', pl_farm: 'ūkis', pl_locality: 'vietovė', pl_suburb: 'priemiestis',
  },
};

let current = 'en';

export function getLang() { return current; }

function norm(lang) {
  const l = typeof lang === 'string' ? lang.toLowerCase() : '';
  return LANGS.includes(l) ? l : null;
}

export function setLang(lang) {
  current = norm(lang) || 'en';
  return current;
}

export function pickLang({ hash, stored, navigator: nav } = {}) {
  if (norm(hash)) return norm(hash);
  if (norm(stored)) return norm(stored);
  const langs = (nav && nav.languages) || [];
  for (const l of langs) {
    const base = String(l).toLowerCase().split('-')[0];
    if (LANGS.includes(base)) return base;
  }
  return 'en';
}

// HTML escaping for the modules that build markup as strings (card.js, ranking.js). One implementation on
// purpose: escaping is a security primitive, and a second copy is a second thing to get right. It lives
// here rather than in a module of its own because both callers already import this one, and a new module
// would need an entry in CI's first-screen budget list.
export function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function t(key, vars) {
  const s = (DICT[current] && DICT[current][key]) ?? DICT.en[key] ?? key;
  return vars ? s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m)) : s;
}

export function applyDom(root = document) {
  root.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
  root.querySelectorAll('[data-i18n-aria]').forEach((el) => { el.setAttribute('aria-label', t(el.dataset.i18nAria)); });
  root.querySelectorAll('[data-i18n-title]').forEach((el) => { el.setAttribute('title', t(el.dataset.i18nTitle)); });
  root.querySelectorAll('[data-i18n-content]').forEach((el) => { el.setAttribute('content', t(el.dataset.i18nContent)); });
  if (root === document) document.documentElement.lang = current;
}

const names = new Map();
export function regionName(code, lang = current) {
  if (!/^[a-z]{2}$/i.test(code || '')) return null;
  try {
    // Construction sits inside the try too: an engine without Intl.DisplayNames degrades to the data names.
    if (!names.has(lang)) names.set(lang, new Intl.DisplayNames([lang], { type: 'region' }));
    const n = names.get(lang).of(code.toUpperCase());
    return n && n !== code.toUpperCase() ? n : null;
  } catch {
    return null;
  }
}

// A region's name for the control and the rank line. The names ride in regions.json by language because
// Intl.DisplayNames knows countries, not continent-sized regions (Chromium returns a UN M49 code unchanged).
export function regionLabel(region, lang = current) {
  return (region.names && region.names[lang]) || region.name || region.id;
}

export function unitName(unit, lang = current) {
  return regionName(unit.code, lang) || (lang === 'en' ? unit.name_en || unit.name : unit.name || unit.name_en) || unit.code;
}

export function flag(code) {
  if (!/^[a-z]{2}$/i.test(code || '')) return '';
  return [...code.toUpperCase()].map((c) => String.fromCodePoint(0x1f1e6 + c.charCodeAt(0) - 65)).join('');
}

function nf(lang, opts) { return new Intl.NumberFormat(lang === 'lt' ? 'lt-LT' : 'en-GB', opts); }

export function fmtInt(n, lang = current) { return nf(lang, { maximumFractionDigits: 0 }).format(n); }

export function fmtDist(m, lang = current) {
  const tens = Math.round(m / 10) * 10;
  if (tens < 1000) return `${nf(lang, { maximumFractionDigits: 0 }).format(tens)} m`;
  const km = m / 1000;
  const digits = km < 9.95 ? 1 : 0;
  return `${nf(lang, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(km)} km`;
}

// A unit can have no result for a scenario, and then there is no distance to say. Nothing beats "NaN km":
// the caller decides what stands in the empty place.
export function fmtKmExact(m, lang = current) {
  if (!Number.isFinite(m)) return '';
  return `${nf(lang, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(m / 1000)} km`;
}

function labelFor(prefix, tag) {
  const key = `${prefix}_${tag}`;
  return (DICT[current] && DICT[current][key]) ?? DICT.en[key] ?? tag;
}

export function highwayLabel(tag) { return labelFor('hw', tag); }

export function placeLabel(tag) { return labelFor('pl', tag); }

// The card: the headline sentence for the unit, the scenario toggle, the two actions, and the selected pole.
// The summary element is the same facts in one row, for the phone sheet's handle; it is optional, so a
// caller with nowhere to put it can leave it out.
import { t, unitName, regionLabel, fmtDist, fmtKmExact, fmtKm2, highwayLabel, placeLabel, esc } from './i18n.js';
import { summaryKey, visiblePoles } from './data.js';

export function createCard(el, { summary, onScenario, onRanking, onLocate, onPole, onIslands }) {
  let view = null; // { region, unit, units, doc, scenario, rank, islands }

  el.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b || !el.contains(b)) return;
    if (b.dataset.s) onScenario(b.dataset.s);
    // dataset.i is the string '0' or '1', so both readings are truthy here and the number is what goes out.
    else if (b.dataset.i) onIslands(Number(b.dataset.i));
    else if (b.dataset.act === 'ranking') onRanking();
    else if (b.dataset.act === 'locate') onLocate();
    else if (b.dataset.rank) onPole(Number(b.dataset.rank));
  });

  // Which of the unit's summaries this reading uses, and the poles it shows. Both are the published superset
  // read one way or the other; nothing is fetched again when the toggle moves.
  const summaryOf = (v) => v.unit[summaryKey(v.scenario, v.islands)];
  const polesOf = (v) => {
    const block = v.doc && v.doc[v.scenario];
    return visiblePoles(block && block.poles, { islands: v.islands });
  };

  // The unit's name, and the flag ahead of it. A unit below country level has no flag (the emoji is built
  // from a two-letter country code), so the slot and the space after it go away rather than render empty.
  // The handheld's screen is monochrome, so the flag emoji the incumbent led with has nowhere to go.
  function names(v) {
    return { name: unitName(v.unit), lead: '' };
  }

  // Why a unit shows no distance for this scenario: held back by validation, or nothing found at all.
  function reasonFor(v) {
    const d = v.doc && v.doc[v.scenario];
    return d && d.withheld ? t('reasonWithheld') : t('reasonNone');
  }

  // How many units of the region have a result in this scenario and this reading: the "of 52" in the rank line.
  const ranked = (v) => v.units.filter((u) => u[summaryKey(v.scenario, v.islands)]).length;

  function headline(v) {
    const { name, lead } = names(v);
    const sum = summaryOf(v);
    if (!sum) return `<p class="card__headline">${lead}${esc(t('noPoles', { name, reason: reasonFor(v) }))}</p>`;
    const what = t(v.scenario === 'A' ? 'headlineA' : 'headlineB');
    const count = ranked(v);
    return `<p class="card__headline">${lead}${esc(t('headline', { name, km: fmtKmExact(sum.dist_m), what }))}</p>
      <p class="card__rank">${esc(t('rankOf', { rank: sum.rank, count, region: regionLabel(v.region) }))}</p>`;
  }

  // The one row the phone sheet carries while it is closed: who, how far, and where that ranks. It says what
  // the headline says in fewer words, so it needs no dictionary entry of its own. The scenario letter is
  // there because the distance changes with it and the toggle is inside the sheet, out of sight.
  function summaryHtml(v) {
    const { name, lead } = names(v);
    const sum = summaryOf(v);
    if (!sum) return `<span class="card-summary__none">${lead}${esc(t('noPoles', { name, reason: reasonFor(v) }))}</span>`;
    // The line breaks below fall between block level boxes and inside a flex row, so none of them paints.
    return `<span class="card-summary__line"><span class="card-summary__name">${lead}${esc(name)}</span>
      <b class="card-summary__dist">${esc(t(`scenarioShort_${v.scenario}`))} ${esc(fmtKmExact(sum.dist_m))}</b></span>
      <span class="card-summary__rank">${esc(t('rankOf', { rank: sum.rank, count: ranked(v), region: regionLabel(v.region) }))}</span>`;
  }

  function poleBlock(v) {
    const block = v.doc && v.doc[v.scenario];
    const poles = polesOf(v);
    const withheld = block && block.withheld ? `<p class="card__note">${esc(t('withheldNote', { n: block.withheld }))}</p>` : '';
    const pole = poles.find((p) => p.rank === v.rank) || poles[0];
    // Every pole of a unit can be withheld: there are no facts to show, but the count still has to be said.
    if (!pole) return withheld ? `<div class="card__poles">${withheld}</div>` : '';
    const way = pole.nearest_way || {};
    const roadName = way.name || way.ref || t('unnamed');
    const place = pole.nearest_place;
    // The chip says the pole's place in what is shown; the button still carries the overall rank, which is
    // the pole's identity and what every other module selects on.
    const chips = poles.map((p) => `<button type="button" class="chip${p.rank === pole.rank ? ' chip--on' : ''}" data-rank="${p.rank}" aria-pressed="${p.rank === pole.rank}">${p.display ?? p.rank}</button>`).join('');
    const lat = pole.lat.toFixed(5);
    const lon = pole.lon.toFixed(5);
    const [num, unitLabel] = splitUnit(fmtKmExact(pole.dist_m));
    const island = Number.isFinite(pole.island_km2)
      ? `<div class="field"><dt>${esc(t('islandFact'))}</dt><dd>${esc(fmtKm2(pole.island_km2))}</dd></div>` : '';
    return `<div class="card__poles">
      <div class="bar bar--sub"><h2 class="card__pole-title">${esc(t('poleHeading', { rank: pole.display ?? pole.rank }))} <span class="card__of">${esc(t('poleOf', { count: poles.length }))}</span></h2></div>
      <div class="chips" role="group" aria-label="${esc(t('polesLabel'))}">${chips}</div>
      <dl class="card__facts">
        <div class="field field--big"><dt>${esc(t('fieldDist'))}</dt><dd><span class="big">${esc(num)}</span><span class="big__u">${esc(unitLabel)}</span></dd></div>
        ${island}<div class="field"><dt>${esc(t('nearestRoad'))}</dt><dd>${esc(highwayLabel(way.highway || 'road'))}, ${esc(roadName)}</dd></div>
        ${placeField(pole, place)}
        <div class="field"><dt>${esc(t('coordinates'))}</dt><dd><span class="coords">${lat}, ${lon}</span>
          <a class="card__maps key" href="https://www.google.com/maps?q=${lat},${lon}" target="_blank" rel="noopener">${esc(t('openMaps'))}</a></dd></div>
      </dl>${withheld}</div>`;
  }

  // The signature field: a compass whose needle points from the pole to the nearest settlement, the one
  // direction the data actually knows. The bearing is the initial great-circle bearing between the two points.
  function placeField(pole, place) {
    if (!place) return `<div class="field"><dt>${esc(t('nearestPlace'))}</dt><dd>${esc(t('noPlace'))}</dd></div>`;
    const deg = bearing(pole.lat, pole.lon, place.lat, place.lon);
    const pts = t('compassPoints').split(',');
    const pt = pts[Math.round(deg / 45) % 8];
    const north = pts[0];
    const ticks = [0, 45, 90, 135, 180, 225, 270, 315].map((a) => `<rect x="37" y="${a % 90 ? 5 : 3}" width="2" height="${a % 90 ? 3 : 5}" transform="rotate(${a} 38 38)"/>`).join('');
    const compass = Number.isFinite(deg) ? `<svg class="compass" viewBox="0 0 76 76" width="76" height="76" role="img" aria-label="${esc(t('compassLabel', { deg, pt }))}" shape-rendering="crispEdges" style="--brg:${deg}deg">
        <circle cx="38" cy="38" r="34" class="compass__rim"/>
        <g class="compass__ticks">${ticks}</g>
        <text x="38" y="20" class="compass__n">${esc(north)}</text>
        <g class="compass__needle"><path d="M38 9 L45 40 L38 35 L31 40 Z"/><rect x="36" y="40" width="4" height="22" class="compass__tail"/></g>
        <rect x="35" y="35" width="6" height="6" class="compass__hub"/>
      </svg>` : '';
    const sub = [placeLabel(place.type), fmtDist(place.dist_m)];
    if (Number.isFinite(deg)) sub.push(t('bearing', { deg, pt }));
    return `<div class="field field--nav">${compass}<div class="field__nav-text"><dt>${esc(t('nearestPlace'))}</dt>
        <dd><span class="field__place">${esc(place.name || placeLabel(place.type))}</span><span class="field__sub">${esc(sub.join(', '))}</span></dd></div></div>`;
  }

  function renderSummary() {
    if (!summary) return;
    summary.innerHTML = view ? summaryHtml(view) : '';
    summary.hidden = !view;
  }

  function render() {
    renderSummary();
    if (!view) { el.hidden = true; return; }
    const v = view;
    const sum = summaryOf(v);
    const tally = sum ? `<span class="bar__n">${sum.rank}/${ranked(v)}</span>` : '';
    el.innerHTML = `<div class="bar card__bar"><span class="bar__t">${esc(names(v).name)}</span>${tally}</div>
      <div class="card__lede">${headline(v)}</div>
      <div class="card__controls">
        <div class="seg card__seg" role="group" aria-label="${esc(t('scenarioGroup'))}">
          <button type="button" class="seg__btn" data-s="A" aria-pressed="${v.scenario === 'A'}"><span class="seg__cap">A</span><span class="seg__label">${esc(t('scenarioA'))}</span></button>
          <button type="button" class="seg__btn" data-s="B" aria-pressed="${v.scenario === 'B'}"><span class="seg__cap">B</span><span class="seg__label">${esc(t('scenarioB'))}</span></button>
        </div>
        <p class="card__hint">${esc(t(v.scenario === 'A' ? 'scenarioAHint' : 'scenarioBHint'))}</p>
        <div class="card__islands">
          <span class="card__islands-label" id="islands-label">${esc(t('islandsGroup'))}</span>
          <div class="seg seg--sm" role="group" aria-labelledby="islands-label">
            <button type="button" class="seg__btn" data-i="1" aria-pressed="${v.islands === 1}">${esc(t('islandsOn'))}</button>
            <button type="button" class="seg__btn" data-i="0" aria-pressed="${v.islands === 0}">${esc(t('islandsOff'))}</button>
          </div>
        </div>
        <div class="card__actions">
          <button type="button" class="btn" data-act="ranking">${esc(t('rankingBtn'))}</button>
          <button type="button" class="btn" data-act="locate">${esc(t('locateBtn'))}</button>
        </div>
      </div>
      ${poleBlock(v)}`;
    el.hidden = false;
  }

  return {
    // Islands shown is the default reading, so a caller that says nothing about them gets the whole superset.
    show(next) { view = { ...(view || {}), ...next }; if (view.islands == null) view.islands = 1; render(); },
    setPole(rank) { if (view) { view.rank = rank; render(); } },
    refresh: render,
    current: () => view,
  };
}

// "3.43 km" into the figure and its unit, so the field can set the figure large. Both locales put one space
// before the unit.
function splitUnit(text) {
  const at = text.lastIndexOf(' ');
  return at < 0 ? [text, ''] : [text.slice(0, at), text.slice(at + 1)];
}

// Initial great-circle bearing from one point to another, in whole degrees clockwise from north.
export function bearing(lat1, lon1, lat2, lon2) {
  if (![lat1, lon1, lat2, lon2].every(Number.isFinite)) return NaN;
  const r = Math.PI / 180;
  const y = Math.sin((lon2 - lon1) * r) * Math.cos(lat2 * r);
  const x = Math.cos(lat1 * r) * Math.sin(lat2 * r) - Math.sin(lat1 * r) * Math.cos(lat2 * r) * Math.cos((lon2 - lon1) * r);
  return Math.round(((Math.atan2(y, x) / r) + 360) % 360) % 360;
}

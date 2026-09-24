// The card: the headline sentence for the unit, the scenario toggle, the two actions, and the selected pole.
// The summary element is the same facts in one row, for the phone sheet's handle; it is optional, so a
// caller with nowhere to put it can leave it out.
import { t, unitName, regionLabel, flag, fmtDist, fmtKmExact, fmtKm2, highwayLabel, placeLabel, esc } from './i18n.js';
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
  function names(v) {
    const mark = flag(v.unit.code);
    return { name: unitName(v.unit), lead: mark ? `${esc(mark)} ` : '' };
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
      <b class="card-summary__dist"><span class="card-summary__code">${esc(t(`scenarioShort_${v.scenario}`))}</span> ${esc(fmtKmExact(sum.dist_m))}</b></span>
      <span class="card-summary__rank">${esc(t('rankOf', { rank: sum.rank, count: ranked(v), region: regionLabel(v.region) }))}</span>`;
  }

  // The description sheet's pictograms: one authored stroke, drawn in the ink colour, each standing in the
  // A column the way an IOF symbol stands in its box.
  const ICON = {
    island: '<path d="M4 15c2-4 5-6 8-6s6 2 8 6"/><path d="M3 19c1.5 0 1.5-1 3-1s1.5 1 3 1 1.5-1 3-1 1.5 1 3 1 1.5-1 3-1 1.5 1 3 1"/>',
    road: '<path d="M8 3v18M16 3v18"/>',
    place: '<path d="M5 20V11l7-6 7 6v9z"/><path d="M10 20v-5h4v5"/>',
    coords: '<circle cx="12" cy="12" r="6"/><path d="M12 2v5M12 17v5M2 12h5M17 12h5"/>',
    maps: '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v6H4V6h6"/>',
    ranking: '<path d="M4 6h16M4 12h16M4 18h10"/>',
    locate: '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
  };
  const icon = (k) => `<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">${ICON[k]}</svg>`;

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
    const placeText = place
      ? `${esc(place.name || placeLabel(place.type))} (${esc(placeLabel(place.type))}, ${esc(fmtDist(place.dist_m))})`
      : esc(t('noPlace'));
    // The chip says the pole's place in what is shown; the button still carries the overall rank, which is
    // the pole's identity and what every other module selects on. Ten boxes always, as a printed sheet has:
    // the ones a unit has no pole for stay empty.
    const chips = poles.map((p) => `<button type="button" class="chip${p.rank === pole.rank ? ' chip--on' : ''}" data-rank="${p.rank}" aria-pressed="${p.rank === pole.rank}">${p.display ?? p.rank}</button>`).join('')
      + '<span class="chip chip--empty" aria-hidden="true"></span>'.repeat(Math.max(0, 10 - poles.length));
    const lat = pole.lat.toFixed(5);
    const lon = pole.lon.toFixed(5);
    const row = (ic, label, value) => `<div class="desc"><span class="desc__sym">${icon(ic)}</span><dt class="desc__label">${esc(label)}</dt><dd class="desc__val">${value}</dd></div>`;
    const island = Number.isFinite(pole.island_km2) ? row('island', t('islandFact'), esc(fmtKm2(pole.island_km2))) : '';
    return `<div class="card__poles">
      <div class="chips" role="group" aria-label="${esc(t('polesLabel'))}">${chips}</div>
      <div class="control">
        <span class="control__num" aria-hidden="true">${pole.display ?? pole.rank}</span>
        <h2 class="card__pole-title">${esc(t('poleHeading', { rank: pole.display ?? pole.rank }))} <span class="card__of">${esc(t('poleOf', { count: poles.length }))}</span></h2>
        <p class="control__dist"><span class="vh">${esc(t('distance'))} </span>${esc(fmtKmExact(pole.dist_m))}</p>
      </div>
      <dl class="card__facts">
        ${island}${row('road', t('nearestRoad'), `${esc(highwayLabel(way.highway || 'road'))}, ${esc(roadName)}`)}
        ${row('place', t('nearestPlace'), placeText)}
        ${row('coords', t('coordinates'), `<span class="mono">${lat}, ${lon}</span>`)}
      </dl>
      <a class="card__maps" href="https://www.google.com/maps?q=${lat},${lon}" target="_blank" rel="noopener"><span class="desc__sym">${icon('maps')}</span><span>${esc(t('openMaps'))}</span></a>
      ${withheld}</div>`;
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
    el.innerHTML = `<div class="sheet">
      ${headline(v)}
      <div class="sheet__courses" role="group" aria-label="${esc(t('scenarioGroup'))}">
        <button type="button" class="course" data-s="A" aria-pressed="${v.scenario === 'A'}"><span class="course__code">A</span><span class="course__name">${esc(t('scenarioA'))}</span></button>
        <button type="button" class="course" data-s="B" aria-pressed="${v.scenario === 'B'}"><span class="course__code">B</span><span class="course__name">${esc(t('scenarioB'))}</span></button>
      </div>
      <p class="card__hint">${esc(t(v.scenario === 'A' ? 'scenarioAHint' : 'scenarioBHint'))}</p>
      <div class="card__islands">
        <span class="card__islands-label" id="islands-label">${esc(t('islandsGroup'))}</span>
        <div class="box-toggle" role="group" aria-labelledby="islands-label">
          <button type="button" class="box" data-i="1" aria-pressed="${v.islands === 1}">${esc(t('islandsOn'))}</button>
          <button type="button" class="box" data-i="0" aria-pressed="${v.islands === 0}">${esc(t('islandsOff'))}</button>
        </div>
      </div>
      <div class="card__actions">
        <button type="button" class="act act--ink" data-act="ranking">${icon('ranking')}<span>${esc(t('rankingBtn'))}</span></button>
        <button type="button" class="act" data-act="locate">${icon('locate')}<span>${esc(t('locateBtn'))}</span></button>
      </div>
      ${poleBlock(v)}</div>`;
    el.hidden = false;
  }

  // The signature: a pole picked from the chips or the map flashes its description, the way a runner's eye
  // drops from the circle on the map to its row on the sheet.
  function flash() {
    const d = el.querySelector('.control');
    const f = el.querySelector('.card__facts');
    [d, f].forEach((x) => x && x.classList.add('is-flash'));
  }

  return {
    // Islands shown is the default reading, so a caller that says nothing about them gets the whole superset.
    show(next) { view = { ...(view || {}), ...next }; if (view.islands == null) view.islands = 1; render(); },
    setPole(rank) { if (view) { const moved = view.rank !== rank; view.rank = rank; render(); if (moved) flash(); } },
    refresh: render,
    current: () => view,
  };
}

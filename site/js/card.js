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

  // The unit's name. The chart world sets no flags: the cartouche carries the name in lettering instead.
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

  // The chart's title block: the unit in spaced capitals, the chart's subtitle saying what the soundings
  // measure, the headline sentence, and the rank where a chart would draw its scale line.
  function headline(v) {
    const { name, lead } = names(v);
    const sum = summaryOf(v);
    const top = `<h2 class="cartouche__name">${esc(name)}</h2>
      <p class="cartouche__sub">${esc(t(v.scenario === 'A' ? 'chartSubA' : 'chartSubB'))}</p>`;
    if (!sum) return `<header class="cartouche">${top}<p class="card__headline">${lead}${esc(t('noPoles', { name, reason: reasonFor(v) }))}</p></header>`;
    const what = t(v.scenario === 'A' ? 'headlineA' : 'headlineB');
    const count = ranked(v);
    return `<header class="cartouche">${top}
      <p class="card__headline">${lead}${esc(t('headline', { name, km: fmtKmExact(sum.dist_m), what }))}</p>
      <p class="card__rank"><span>${esc(t('rankOf', { rank: sum.rank, count, region: regionLabel(v.region) }))}</span></p></header>`;
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
      <b class="card-summary__dist"><span class="card-summary__s">${esc(t(`scenarioShort_${v.scenario}`))}</span> <span class="card-summary__km">${esc(fmtKmExact(sum.dist_m))}</span></b></span>
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
    const placeText = place
      ? `${esc(place.name || placeLabel(place.type))} (${esc(placeLabel(place.type))}, ${esc(fmtDist(place.dist_m))})`
      : esc(t('noPlace'));
    // The chip says the pole's place in what is shown; the button still carries the overall rank, which is
    // the pole's identity and what every other module selects on.
    const chips = poles.map((p) => `<button type="button" class="chip${p.rank === pole.rank ? ' chip--on' : ''}" data-rank="${p.rank}" aria-pressed="${p.rank === pole.rank}">${p.display ?? p.rank}</button>`).join('');
    const lat = pole.lat.toFixed(5);
    const lon = pole.lon.toFixed(5);
    const island = Number.isFinite(pole.island_km2)
      ? `<li><span class="notes__k">${esc(t('islandFact'))}</span> <span class="notes__v">${esc(fmtKm2(pole.island_km2))}</span></li>` : '';
    // The pole's facts as the chart's numbered NOTES block.
    return `<div class="card__poles">
      <h3 class="card__pole-title">${esc(t('poleHeading', { rank: pole.display ?? pole.rank }))} <span class="card__of">${esc(t('poleOf', { count: poles.length }))}</span></h3>
      <div class="chips" role="group" aria-label="${esc(t('polesLabel'))}">${chips}</div>
      <ol class="notes">
        <li><span class="notes__k">${esc(t('distance'))}</span> <span class="notes__v notes__v--snd">${esc(fmtKmExact(pole.dist_m))}</span></li>
        ${island}<li><span class="notes__k">${esc(t('nearestRoad'))}</span> <span class="notes__v">${esc(highwayLabel(way.highway || 'road'))}, ${esc(roadName)}</span></li>
        <li><span class="notes__k">${esc(t('nearestPlace'))}</span> <span class="notes__v">${placeText}</span></li>
        <li><span class="notes__k">${esc(t('coordinates'))}</span> <span class="notes__v"><span class="coord">${lat}, ${lon}</span>
          <a class="card__maps" href="https://www.google.com/maps?q=${lat},${lon}" target="_blank" rel="noopener">${esc(t('openMaps'))}</a></span></li>
      </ol>${withheld}</div>`;
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
    el.innerHTML = `${headline(v)}
      <div class="seg card__seg" role="group" aria-label="${esc(t('scenarioGroup'))}">
        <button type="button" class="seg__btn" data-s="A" aria-pressed="${v.scenario === 'A'}">${esc(t('scenarioA'))}</button>
        <button type="button" class="seg__btn" data-s="B" aria-pressed="${v.scenario === 'B'}">${esc(t('scenarioB'))}</button>
      </div>
      <p class="card__hint">${esc(t(v.scenario === 'A' ? 'scenarioAHint' : 'scenarioBHint'))}</p>
      <div class="card__ctl">
      <div class="card__islands">
        <span class="card__islands-label" id="islands-label">${esc(t('islandsGroup'))}</span>
        <div class="seg seg--sm" role="group" aria-labelledby="islands-label">
          <button type="button" class="seg__btn" data-i="1" aria-pressed="${v.islands === 1}">${esc(t('islandsOn'))}</button>
          <button type="button" class="seg__btn" data-i="0" aria-pressed="${v.islands === 0}">${esc(t('islandsOff'))}</button>
        </div>
      </div>
      <div class="card__actions">
        <button type="button" class="btn" data-act="ranking">${esc(t('rankingBtn'))}</button>
        <button type="button" class="btn btn--ghost" data-act="locate">${esc(t('locateBtn'))}</button>
      </div></div>
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

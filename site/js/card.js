// The card: the headline sentence for the unit, the scenario toggle, the two actions, and the selected pole.
// The summary element is the same facts in one row, for the phone sheet's handle; it is optional, so a
// caller with nowhere to put it can leave it out.
import { t, unitName, regionLabel, flag, fmtDist, fmtKmExact, highwayLabel, placeLabel, esc } from './i18n.js';

export function createCard(el, { summary, onScenario, onRanking, onLocate, onPole }) {
  let view = null; // { region, unit, units, doc, scenario, rank }

  el.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b || !el.contains(b)) return;
    if (b.dataset.s) onScenario(b.dataset.s);
    else if (b.dataset.act === 'ranking') onRanking();
    else if (b.dataset.act === 'locate') onLocate();
    else if (b.dataset.rank) onPole(Number(b.dataset.rank));
  });

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

  // How many units of the region have a result in this scenario: the "of 52" in the rank line.
  const ranked = (v) => v.units.filter((u) => u[v.scenario]).length;

  function headline(v) {
    const { name, lead } = names(v);
    const sum = v.unit[v.scenario];
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
    const sum = v.unit[v.scenario];
    if (!sum) return `<span class="card-summary__none">${lead}${esc(t('noPoles', { name, reason: reasonFor(v) }))}</span>`;
    // The line breaks below fall between block level boxes and inside a flex row, so none of them paints.
    return `<span class="card-summary__line"><span class="card-summary__name">${lead}${esc(name)}</span>
      <b class="card-summary__dist">${esc(t(`scenarioShort_${v.scenario}`))} ${esc(fmtKmExact(sum.dist_m))}</b></span>
      <span class="card-summary__rank">${esc(t('rankOf', { rank: sum.rank, count: ranked(v), region: regionLabel(v.region) }))}</span>`;
  }

  function poleBlock(v) {
    const block = v.doc && v.doc[v.scenario];
    const poles = (block && block.poles) || [];
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
    const chips = poles.map((p) => `<button type="button" class="chip${p.rank === pole.rank ? ' chip--on' : ''}" data-rank="${p.rank}" aria-pressed="${p.rank === pole.rank}">${p.rank}</button>`).join('');
    const lat = pole.lat.toFixed(5);
    const lon = pole.lon.toFixed(5);
    return `<div class="card__poles">
      <div class="chips" role="group" aria-label="${esc(t('polesLabel'))}">${chips}</div>
      <h2 class="card__pole-title">${esc(t('poleHeading', { rank: pole.rank }))} <span class="card__of">${esc(t('poleOf', { count: poles.length }))}</span></h2>
      <dl class="card__facts">
        <dt>${esc(t('distance'))}</dt><dd>${esc(fmtKmExact(pole.dist_m))}</dd>
        <dt>${esc(t('nearestRoad'))}</dt><dd>${esc(highwayLabel(way.highway || 'road'))}, ${esc(roadName)}</dd>
        <dt>${esc(t('nearestPlace'))}</dt><dd>${placeText}</dd>
        <dt>${esc(t('coordinates'))}</dt><dd><span class="mono">${lat}, ${lon}</span>
          <a class="card__maps" href="https://www.google.com/maps?q=${lat},${lon}" target="_blank" rel="noopener">${esc(t('openMaps'))}</a></dd>
      </dl>${withheld}</div>`;
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
      <div class="card__actions">
        <button type="button" class="btn" data-act="ranking">${esc(t('rankingBtn'))}</button>
        <button type="button" class="btn btn--ghost" data-act="locate">${esc(t('locateBtn'))}</button>
      </div>
      ${poleBlock(v)}`;
    el.hidden = false;
  }

  return {
    show(next) { view = { ...(view || {}), ...next }; render(); },
    setPole(rank) { if (view) { view.rank = rank; render(); } },
    refresh: render,
    current: () => view,
  };
}

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

  // The unit's name. The printed sheet carries no flag emoji: a colour pictogram cannot be pulled in one ink,
  // and the second pass copies the text, which a flag ahead of it would push out of line.
  function names(v) {
    return { name: unitName(v.unit), lead: '' };
  }

  // Authored icons, one stroke, drawn in the ink of the element that holds them.
  const ICON = {
    locate: '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="6"/><path d="M12 2v5M12 17v5M2 12h5M17 12h5"/></svg>',
    ranking: '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6h11M9 12h11M9 18h11M4 6h2M4 12h2M4 18h2"/></svg>',
    out: '<svg class="ico ico--sm" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17L17 7M9 7h8v8"/></svg>',
  };
  const printed = (cls, text) => `<p class="${cls} print" data-print="${esc(text)}">${esc(text)}</p>`;

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
    if (!sum) return printed('card__headline card__headline--none', `${lead}${t('noPoles', { name, reason: reasonFor(v) })}`);
    const what = t(v.scenario === 'A' ? 'headlineA' : 'headlineB');
    const count = ranked(v);
    return `${printed('card__headline', t('headline', { name, km: fmtKmExact(sum.dist_m), what }))}
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
    const placeText = place
      ? `${esc(place.name || placeLabel(place.type))} (${esc(placeLabel(place.type))}, ${esc(fmtDist(place.dist_m))})`
      : esc(t('noPlace'));
    // The chip says the pole's place in what is shown; the button still carries the overall rank, which is
    // the pole's identity and what every other module selects on.
    const chips = poles.map((p) => `<button type="button" class="chip${p.rank === pole.rank ? ' chip--on' : ''}" data-rank="${p.rank}" aria-pressed="${p.rank === pole.rank}">${p.display ?? p.rank}</button>`).join('');
    const lat = pole.lat.toFixed(5);
    const lon = pole.lon.toFixed(5);
    const island = Number.isFinite(pole.island_km2)
      ? `<dt>${esc(t('islandFact'))}</dt><dd>${esc(fmtKm2(pole.island_km2))}</dd>` : '';
    return `<div class="card__poles">
      <div class="chips" role="group" aria-label="${esc(t('polesLabel'))}">${chips}</div>
      <h2 class="card__pole-title">${esc(t('poleHeading', { rank: pole.display ?? pole.rank }))} <span class="card__of">${esc(t('poleOf', { count: poles.length }))}</span></h2>
      <dl class="card__facts">
        <dt>${esc(t('distance'))}</dt><dd>${esc(fmtKmExact(pole.dist_m))}</dd>
        ${island}<dt>${esc(t('nearestRoad'))}</dt><dd>${esc(highwayLabel(way.highway || 'road'))}, ${esc(roadName)}</dd>
        <dt>${esc(t('nearestPlace'))}</dt><dd>${placeText}</dd>
        <dt>${esc(t('coordinates'))}</dt><dd><span class="mono">${lat}, ${lon}</span>
          <a class="card__maps" href="https://www.google.com/maps?q=${lat},${lon}" target="_blank" rel="noopener">${esc(t('openMaps'))}${ICON.out}</a></dd>
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
      <div class="card__seg" role="group" aria-label="${esc(t('scenarioGroup'))}">
        <button type="button" class="pass pass--A" data-s="A" aria-pressed="${v.scenario === 'A'}"><span class="pass__letter" aria-hidden="true">${esc(t('scenarioShort_A'))}</span><span class="pass__label">${esc(t('scenarioA'))}</span></button>
        <button type="button" class="pass pass--B" data-s="B" aria-pressed="${v.scenario === 'B'}"><span class="pass__letter" aria-hidden="true">${esc(t('scenarioShort_B'))}</span><span class="pass__label">${esc(t('scenarioB'))}</span></button>
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
        <button type="button" class="btn" data-act="ranking">${ICON.ranking}${esc(t('rankingBtn'))}</button>
        <button type="button" class="btn btn--ghost" data-act="locate">${ICON.locate}${esc(t('locateBtn'))}</button>
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

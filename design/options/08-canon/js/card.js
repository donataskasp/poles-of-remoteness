// The card: the headline sentence for the unit, the scenario toggle, the two actions, and the selected pole.
// The summary element is the same facts in one row, for the phone sheet's handle; it is optional, so a
// caller with nowhere to put it can leave it out.
import { t, unitName, regionLabel, flag, fmtDist, fmtKmExact, fmtKm2, highwayLabel, placeLabel, esc } from './i18n.js';
import { summaryKey, visiblePoles } from './data.js';

export function createCard(el, { summary, pill, onScenario, onRanking, onLocate, onPole, onIslands }) {
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

  // The headline sentence stays whole for screen readers and for copying; the eye gets it set as a hero: the
  // name, the lead, the distance as the big figure, and what it is measured from.
  const icon = (id, cls = '') => `<svg class="ic${cls}" aria-hidden="true"><use href="#${id}"/></svg>`;
  function splitKm(text) {
    const i = text.lastIndexOf(' ');
    return i < 0 ? [text, ''] : [text.slice(0, i), text.slice(i + 1)];
  }
  function headline(v) {
    const { name, lead } = names(v);
    const sum = summaryOf(v);
    if (!sum) {
      return `<div class="hero"><p class="hero__name">${lead}${esc(name)}</p>
        <p class="card__headline hero__none">${esc(t('noPoles', { name, reason: reasonFor(v) }))}</p></div>`;
    }
    const what = t(v.scenario === 'A' ? 'headlineA' : 'headlineB');
    const count = ranked(v);
    const [num, unit] = splitKm(fmtKmExact(sum.dist_m));
    return `<div class="hero">
      <p class="card__headline vh">${lead}${esc(t('headline', { name, km: fmtKmExact(sum.dist_m), what }))}</p>
      <div class="hero__top" aria-hidden="true">
        <p class="hero__name">${lead}${esc(name)}</p>
      </div>
      <p class="hero__lead" aria-hidden="true">${esc(t('heroLead'))}</p>
      <p class="hero__fig" aria-hidden="true"><span class="hero__num">${esc(num)}</span><span class="hero__unit">${esc(unit)}</span></p>
      <p class="hero__tail" aria-hidden="true">${esc(t('heroTail', { what }))}</p>
      <button type="button" class="rankchip card__rank" data-act="ranking">${esc(t('rankOf', { rank: sum.rank, count, region: regionLabel(v.region) }))}${icon('i-chevron-r', ' ic--sm')}</button>
    </div>`;
  }

  // The one row the phone sheet carries while it is closed: who, how far, and where that ranks. It says what
  // the headline says in fewer words, so it needs no dictionary entry of its own. The scenario letter is
  // there because the distance changes with it and the toggle is inside the sheet, out of sight.
  function summaryHtml(v) {
    const { name, lead } = names(v);
    const sum = summaryOf(v);
    if (!sum) return `<span class="card-summary__none">${lead}${esc(t('noPoles', { name, reason: reasonFor(v) }))}</span>`;
    const [num, unit] = splitKm(fmtKmExact(sum.dist_m));
    // The line breaks below fall between block level boxes and inside a grid, so none of them paints.
    return `<span class="card-summary__name">${lead}${esc(name)}</span>
      <span class="card-summary__dist"><span class="card-summary__s">${esc(t(`scenarioShort_${v.scenario}`))}</span>${esc(num)}<small>${esc(unit)}</small></span>
      <span class="card-summary__rank">${esc(t('rankOf', { rank: sum.rank, count: ranked(v), region: regionLabel(v.region) }))}</span>`;
  }

  // The search-like pill at the top left: the unit on screen, the way into the ranking.
  function pillHtml(v) {
    const { name, lead } = names(v);
    const sum = summaryOf(v);
    const rank = sum ? `<span class="pill__rank">${esc(t('rankOf', { rank: sum.rank, count: ranked(v), region: regionLabel(v.region) }))}</span>` : '';
    return `<span class="pill__name">${lead}${esc(name)}</span>${rank}`;
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
    const chips = poles.map((p) => {
      const [num] = splitKm(fmtKmExact(p.dist_m));
      const isl = Number.isFinite(p.island_km2) ? icon('i-island', ' chip__isl') : '';
      return `<button type="button" class="chip${p.rank === pole.rank ? ' chip--on' : ''}" data-rank="${p.rank}" aria-pressed="${p.rank === pole.rank}"><span class="chip__n">${p.display ?? p.rank}${isl}</span><span class="chip__d">${esc(num)}</span></button>`;
    }).join('');
    const lat = pole.lat.toFixed(5);
    const lon = pole.lon.toFixed(5);
    const island = Number.isFinite(pole.island_km2)
      ? `<div class="fact"><dt>${esc(t('islandFact'))}</dt><dd>${esc(fmtKm2(pole.island_km2))}</dd></div>` : '';
    return `<div class="card__poles">
      <div class="chips" role="group" aria-label="${esc(t('polesLabel'))}">${chips}</div>
      <h2 class="card__pole-title">${esc(t('poleHeading', { rank: pole.display ?? pole.rank }))} <span class="card__of">${esc(t('poleOf', { count: poles.length }))}</span></h2>
      <dl class="card__facts">
        <div class="fact"><dt>${esc(t('distance'))}</dt><dd class="num">${esc(fmtKmExact(pole.dist_m))}</dd></div>
        ${island}<div class="fact"><dt>${esc(t('nearestRoad'))}</dt><dd>${esc(highwayLabel(way.highway || 'road'))}, ${esc(roadName)}</dd></div>
        <div class="fact"><dt>${esc(t('nearestPlace'))}</dt><dd>${placeText}</dd></div>
        <div class="fact"><dt>${esc(t('coordinates'))}</dt><dd class="num">${lat}, ${lon}</dd></div>
      </dl>
      <a class="card__maps" href="https://www.google.com/maps?q=${lat},${lon}" target="_blank" rel="noopener">${esc(t('openMaps'))}${icon('i-external', ' ic--sm')}</a>
      ${withheld}</div>`;
  }

  function renderSummary() {
    if (pill) pill.innerHTML = view ? pillHtml(view) : '';
    if (!summary) return;
    summary.innerHTML = view ? summaryHtml(view) : '';
    summary.hidden = !view;
  }

  // A vertical wheel over the pole strip scrolls it sideways, so a mouse without a tilt wheel reaches pole 10.
  el.addEventListener('wheel', (e) => {
    const strip = e.target.closest('.chips');
    if (!strip || Math.abs(e.deltaY) <= Math.abs(e.deltaX) || strip.scrollWidth <= strip.clientWidth) return;
    strip.scrollLeft += e.deltaY;
    e.preventDefault();
  }, { passive: false });

  // The strip is rebuilt on every render; keep where it was scrolled and bring the selected chip into view.
  function keepStrip(prev) {
    const strip = el.querySelector('.chips');
    if (!strip) return;
    strip.scrollLeft = prev;
    const on = strip.querySelector('.chip--on');
    if (!on) return;
    const pad = 18;
    if (on.offsetLeft - pad < strip.scrollLeft) strip.scrollLeft = on.offsetLeft - pad;
    else if (on.offsetLeft + on.offsetWidth + pad > strip.scrollLeft + strip.clientWidth) strip.scrollLeft = on.offsetLeft + on.offsetWidth + pad - strip.clientWidth;
  }

  function render() {
    renderSummary();
    if (!view) { el.hidden = true; return; }
    const v = view;
    const prevStrip = el.querySelector('.chips');
    const prevLeft = prevStrip ? prevStrip.scrollLeft : 0;
    el.innerHTML = `${headline(v)}
      <div class="seg seg--full card__seg" role="group" aria-label="${esc(t('scenarioGroup'))}">
        <button type="button" class="seg__btn" data-s="A" aria-pressed="${v.scenario === 'A'}">${esc(t('scenarioA'))}</button>
        <button type="button" class="seg__btn" data-s="B" aria-pressed="${v.scenario === 'B'}">${esc(t('scenarioB'))}</button>
      </div>
      <p class="card__hint">${esc(t(v.scenario === 'A' ? 'scenarioAHint' : 'scenarioBHint'))}</p>
      <div class="card__islands">
        <span class="card__islands-label" id="islands-label">${esc(t('islandsGroup'))}</span>
        <span class="card__islands-state" aria-hidden="true">${esc(t(v.islands ? 'islandsOn' : 'islandsOff'))}</span>
        <button type="button" class="switch" role="switch" data-i="${v.islands ? 0 : 1}" aria-checked="${v.islands === 1}" aria-labelledby="islands-label"><span class="switch__knob"></span></button>
      </div>
      <div class="card__actions">
        <button type="button" class="btn" data-act="ranking">${icon('i-list')}${esc(t('rankingBtn'))}</button>
        <button type="button" class="btn" data-act="locate">${icon('i-locate')}${esc(t('locateBtn'))}</button>
      </div>
      ${poleBlock(v)}`;
    el.hidden = false;
    keepStrip(prevLeft);
  }

  return {
    // Islands shown is the default reading, so a caller that says nothing about them gets the whole superset.
    show(next) { view = { ...(view || {}), ...next }; if (view.islands == null) view.islands = 1; render(); },
    setPole(rank) { if (view) { view.rank = rank; render(); } },
    refresh: render,
    current: () => view,
  };
}

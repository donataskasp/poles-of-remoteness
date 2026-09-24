// The ranking, set as a star catalogue: every unit of the region sorted by the active scenario, with A and B
// as two aligned figures on every row (the active one in ink, the other faint) and a disc sized by magnitude.
// On phones the container is a bottom sheet with three heights; on desktop it is the side panel.
import { t, unitName, fmtKmExact, esc } from './i18n.js';
import { summaryKey } from './data.js';

const STATES = ['collapsed', 'half', 'full'];

// The order follows the reading: with islands off a unit is placed by its best mainland pole, and a unit with
// no mainland pole at all sorts last exactly as a unit with no result for the scenario does.
export function sortUnits(units, s, islands = 1) {
  const key = summaryKey(s, islands);
  const otherKey = summaryKey(s === 'A' ? 'B' : 'A', islands);
  return [...units].sort((a, b) => {
    const ra = a[key] ? a[key].rank : Infinity;
    const rb = b[key] ? b[key].rank : Infinity;
    if (ra !== rb) return ra - rb;
    const oa = a[otherKey] ? a[otherKey].rank : Infinity;
    const ob = b[otherKey] ? b[otherKey].rank : Infinity;
    if (oa !== ob) return oa - ob;
    return a.code.localeCompare(b.code);
  });
}

export function createRanking(el, { onPick }) {
  const list = el.querySelector('#ranking');
  const note = el.querySelector('#ranking-note');
  const head = el.querySelector('#ranking-head');
  const handle = el.querySelector('#panel-handle');
  const body = el.querySelector('#panel-body');
  let view = { units: [], scenario: 'A', current: null, islands: 1 };
  let sheet;

  // What the phone stack above the sheet rests on: the height of the closed sheet, which is the handle plus
  // the sheet's own top border, and the handle is whatever the card's summary row wraps to at this width in
  // this language. Measured here and published as --sheet-h, so no rule has to state it and no width has to
  // be guessed. Rounded up, because a sheet a fraction shorter than its handle would push the grip off the
  // bottom of the screen. The handle is display:none on desktop, where nothing reads the variable.
  function measure() {
    const border = parseFloat(getComputedStyle(el).borderTopWidth) || 0;
    document.documentElement.style.setProperty('--sheet-h', `${Math.ceil(handle.getBoundingClientRect().height + border)}px`);
  }
  if (typeof ResizeObserver === 'function') new ResizeObserver(measure).observe(handle);
  else window.addEventListener('resize', measure);

  // The one place that scrolls the current unit into view, for the desktop panel and the phone sheet alike.
  // A sheet that has just been opened is still animating its height, so this runs against a container that
  // is about to grow: 'center' would be computed against the closed sheet's height and land the row a few
  // pixels under the top edge once the sheet has grown. 'start' does not read the container's height; the
  // row's scroll-margin-top keeps the body's top padding above it.
  function showCurrent(block) {
    const cur = list.querySelector('.ranking__row--current');
    if (cur) cur.scrollIntoView({ block });
  }

  // reveal says what the reader was after: 'current' the ranking row of the unit on screen, 'top' the card at
  // the head of the body, 'keep' whatever they had scrolled to.
  function setState(next, { reveal = 'current' } = {}) {
    sheet = STATES.includes(next) ? next : 'collapsed';
    STATES.forEach((s) => el.classList.toggle(`panel--${s}`, s === sheet));
    handle.setAttribute('aria-expanded', String(sheet !== 'collapsed'));
    measure();
    if (sheet === 'collapsed') return;
    // Opening the sheet at rank 1 hides the unit the reader is looking at, wherever it ranks (#35).
    if (reveal === 'current') showCurrent('start');
    else if (reveal === 'top' && body) body.scrollTop = 0;
  }

  // A distance's magnitude on the legend's scale: 0 under a kilometre, then one step per stop (1, 2.5, 5, 10,
  // 20, 50 km). The disc beside the name is sized from it, so the catalogue reads like the map's stars.
  const STOPS = [1000, 2500, 5000, 10000, 20000, 50000];
  const magnitude = (m) => STOPS.filter((s) => m >= s).length;

  function row(u) {
    const s = view.scenario;
    // A unit can have no summary for a scenario or for the reading, and a summary can carry no distance:
    // all of them render empty.
    const km = (key) => (u[key] ? fmtKmExact(u[key].dist_m).replace(/\s*km$/, '') : '');
    const key = summaryKey(s, view.islands);
    const figA = km(summaryKey('A', view.islands));
    const figB = km(summaryKey('B', view.islands));
    const rank = u[key] ? u[key].rank : '';
    const mag = u[key] && Number.isFinite(u[key].dist_m) ? magnitude(u[key].dist_m) : -1;
    const cur = u.code === view.current ? ' ranking__row--current' : '';
    const on = (x) => (x === s ? ' ranking__fig--on' : '');
    const label = `${t('scenarioShort_A')} ${figA} km, ${t('scenarioShort_B')} ${figB} km`;
    return `<li class="ranking__row${cur}">
      <button type="button" class="ranking__btn" data-code="${esc(u.code)}" aria-current="${u.code === view.current}">
        <span class="ranking__rank">${rank}</span>
        <span class="ranking__mag" aria-hidden="true">${mag >= 0 ? `<i style="--m:${mag}"></i>` : ''}</span>
        <span class="ranking__name">${esc(unitName(u))}</span>
        <span class="ranking__fig${on('A')}" aria-hidden="true">${esc(figA)}</span>
        <span class="ranking__fig${on('B')}" aria-hidden="true">${esc(figB)}</span>
        <span class="vh">${esc(label)}</span>
      </button></li>`;
  }

  function render() {
    note.textContent = t('rankingNote');
    if (head) {
      const on = (x) => (x === view.scenario ? ' ranking__fig--on' : '');
      head.innerHTML = `<span class="ranking__rank">${esc(t('catRank'))}</span><span></span>
        <span class="ranking__name">${esc(t('catName'))}</span>
        <span class="ranking__fig${on('A')}">${esc(t('scenarioShort_A'))} <small>km</small></span>
        <span class="ranking__fig${on('B')}">${esc(t('scenarioShort_B'))} <small>km</small></span>`;
    }
    list.innerHTML = sortUnits(view.units, view.scenario, view.islands).map(row).join('');
  }

  list.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-code]');
    if (b) onPick(b.dataset.code);
  });
  // The handle opens the card, not the list: on a phone the card's own section is the top of the body, and a
  // sheet that scrolled straight past it to the ranking would look as if the card were gone. Half to full
  // keeps the place the reader had scrolled to. "See the ranking" is the way to the list, and it still is.
  handle.addEventListener('click', () => {
    const next = STATES[(STATES.indexOf(sheet) + 1) % STATES.length];
    setState(next, { reveal: sheet === 'collapsed' ? 'top' : 'keep' });
  });

  // The class on the panel and the variable have to start out saying the same thing, so the starting state
  // is applied rather than assumed.
  setState('collapsed');

  return {
    setRows(units, scenario, current, islands = 1) { view = { units, scenario, current, islands }; render(); },
    setScenario(s) { view.scenario = s; render(); },
    setIslands(i) { view.islands = i; render(); },
    setCurrent(code) {
      view.current = code;
      render();
      showCurrent('nearest');
    },
    open() { setState('half'); },
    toggle() { setState(sheet === 'collapsed' ? 'half' : 'collapsed'); },
    refresh: render,
    state: () => sheet,
  };
}

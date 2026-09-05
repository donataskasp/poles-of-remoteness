// The ranking: every unit of the region sorted by the active scenario, the other scenario in small type.
// On phones the container is a bottom sheet with three heights; on desktop it is the side panel.
import { t, unitName, flag, fmtKmExact, esc } from './i18n.js';

const STATES = ['collapsed', 'half', 'full'];

export function sortUnits(units, s) {
  const other = s === 'A' ? 'B' : 'A';
  return [...units].sort((a, b) => {
    const ra = a[s] ? a[s].rank : Infinity;
    const rb = b[s] ? b[s].rank : Infinity;
    if (ra !== rb) return ra - rb;
    const oa = a[other] ? a[other].rank : Infinity;
    const ob = b[other] ? b[other].rank : Infinity;
    if (oa !== ob) return oa - ob;
    return a.code.localeCompare(b.code);
  });
}

export function createRanking(el, { onPick }) {
  const list = el.querySelector('#ranking');
  const note = el.querySelector('#ranking-note');
  const handle = el.querySelector('#panel-handle');
  const body = el.querySelector('#panel-body');
  let view = { units: [], scenario: 'A', current: null };
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

  function row(u) {
    const s = view.scenario;
    const other = s === 'A' ? 'B' : 'A';
    // A unit can have no summary for a scenario, and a summary can carry no distance: both render empty.
    const km = (key) => (u[key] ? fmtKmExact(u[key].dist_m) : '');
    const main = km(s);
    const otherKm = km(other);
    const side = otherKm ? `${t(`scenarioShort_${other}`)} ${otherKm}` : '';
    const rank = u[s] ? u[s].rank : '';
    const cur = u.code === view.current ? ' ranking__row--current' : '';
    return `<li class="ranking__row${cur}">
      <button type="button" class="ranking__btn" data-code="${esc(u.code)}" aria-current="${u.code === view.current}">
        <span class="ranking__rank">${rank}</span>
        <span class="ranking__flag">${esc(flag(u.code))}</span>
        <span class="ranking__name">${esc(unitName(u))}</span>
        <span class="ranking__dist"><b>${esc(main)}</b><small>${esc(side)}</small></span>
      </button></li>`;
  }

  function render() {
    note.textContent = t('rankingNote');
    list.innerHTML = sortUnits(view.units, view.scenario).map(row).join('');
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
    setRows(units, scenario, current) { view = { units, scenario, current }; render(); },
    setScenario(s) { view.scenario = s; render(); },
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

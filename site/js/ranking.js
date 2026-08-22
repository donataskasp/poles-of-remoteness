// The ranking: every unit of the region sorted by the active scenario, the other scenario in small type.
// On phones the container is a bottom sheet with three heights; on desktop it is the side panel.
import { t, unitName, flag, fmtKmExact } from './i18n.js';

const STATES = ['collapsed', 'half', 'full'];

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

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
  let view = { region: null, units: [], scenario: 'A', current: null };
  let sheet = 'collapsed';

  function setState(next) {
    sheet = STATES.includes(next) ? next : 'collapsed';
    STATES.forEach((s) => el.classList.toggle(`panel--${s}`, s === sheet));
    handle.setAttribute('aria-expanded', String(sheet !== 'collapsed'));
  }

  function row(u) {
    const s = view.scenario;
    const other = s === 'A' ? 'B' : 'A';
    const main = u[s] ? fmtKmExact(u[s].dist_m) : '';
    const side = u[other] ? `${other} ${fmtKmExact(u[other].dist_m)}` : '';
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
  handle.addEventListener('click', () => setState(STATES[(STATES.indexOf(sheet) + 1) % STATES.length]));

  return {
    setRows(region, units, scenario, current) { view = { region, units, scenario, current }; render(); },
    setScenario(s) { view.scenario = s; render(); },
    setCurrent(code) {
      view.current = code;
      render();
      const cur = list.querySelector('.ranking__row--current');
      if (cur) cur.scrollIntoView({ block: 'nearest' });
    },
    open() { setState('half'); const cur = list.querySelector('.ranking__row--current'); if (cur) cur.scrollIntoView({ block: 'center' }); },
    toggle() { setState(sheet === 'collapsed' ? 'half' : 'collapsed'); },
    refresh: render,
    state: () => sheet,
  };
}

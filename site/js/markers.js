// Numbered markers for the poles of the current unit and scenario. The number painted is the pole's place in
// what is shown (`display`, set by data.js when the islands toggle filters the superset); selection is always
// by `rank`, the pole's identity, which does not move when the toggle does.
import { soundingHtml } from './i18n.js';

// A pole is drawn as a chart sounding: a small circled dot on the spot, the distance beside it written the way
// a chart writes a depth, and the pole's number in a small note box. The dot is the anchor.
export function createMarkers(map, { onSelect }) {
  const group = L.layerGroup().addTo(map);
  let items = [];
  let selected = null;

  function icon(pole, active) {
    const label = pole.display ?? pole.rank;
    return L.divIcon({
      className: `pole-marker${active ? ' pole-marker--active' : ''}`,
      html: `<svg class="pole-marker__dot" viewBox="0 0 22 22" aria-hidden="true"><circle class="pole-marker__ring" cx="11" cy="11" r="9.5"/><circle class="pole-marker__circ" cx="11" cy="11" r="4.6"/><circle class="pole-marker__pt" cx="11" cy="11" r="1.5"/></svg>`
        + `${soundingHtml(pole.dist_m)}<span class="pole-marker__n">${label}</span>`,
      iconSize: null,
      iconAnchor: [11, 11],
    });
  }

  // Poles close together would print their figures over each other. After every placement and zoom, the
  // figures are laid down best first (the selected pole, then by rank) and a figure that would land on one
  // already down is left out; its dot and number box stay, so the pole is still there to pick. At most a
  // score of markers: every box is read in one pass, then every class written, so layout runs once.
  const HUSH = 'pole-marker--hush';
  const GAP = 2;
  const hits = (a, b) => a.left < b.right + GAP && b.left < a.right + GAP && a.top < b.bottom + GAP && b.top < a.bottom + GAP;
  function declutter() {
    const els = items.map(({ m }) => m.getElement()).filter(Boolean);
    els.forEach((el) => el.classList.remove(HUSH));
    const order = items
      .map(({ pole, m }) => ({ pole, el: m.getElement() }))
      .filter((x) => x.el)
      .sort((a, b) => (b.pole.rank === selected) - (a.pole.rank === selected) || a.pole.rank - b.pole.rank)
      .map(({ el }) => {
        const part = (sel) => { const n = el.querySelector(sel); return n ? n.getBoundingClientRect() : null; };
        return { el, dot: part('.pole-marker__dot'), fig: part('.snd-fig'), n: part('.pole-marker__n') };
      });
    const taken = [];
    const hush = [];
    for (const x of order) {
      // A figure the stylesheet already hides (the phone rule) has no box and takes no room.
      const shown = x.fig && x.fig.width > 0;
      if (shown && taken.some((r) => hits(r, x.fig))) hush.push(x.el);
      else if (shown) taken.push(x.fig, x.n);
      if (x.dot) taken.push(x.dot);
    }
    hush.forEach((el) => el.classList.add(HUSH));
  }
  map.on('zoomend', declutter);
  // The first pass may run on the fallback face; the chart italic is wider, so measure again once it is in.
  if (typeof document !== 'undefined' && document.fonts && document.fonts.ready) document.fonts.ready.then(declutter);

  function setPoles(poles, selectedRank) {
    group.clearLayers();
    selected = selectedRank;
    items = poles.map((pole) => {
      const active = pole.rank === selectedRank;
      const label = pole.display ?? pole.rank;
      const m = L.marker([pole.lat, pole.lon], { icon: icon(pole, active), title: String(label), zIndexOffset: active ? 1000 : 0 });
      m.on('click', () => onSelect(pole));
      m.addTo(group);
      return { pole, m };
    });
    declutter();
  }

  function select(rank) {
    selected = rank;
    for (const { pole, m } of items) {
      const active = pole.rank === rank;
      m.setIcon(icon(pole, active));
      m.setZIndexOffset(active ? 1000 : 0);
    }
    declutter();
  }

  // Redrawn in the language now set: the sounding's hidden decimal separator follows it.
  const refresh = () => select(selected);

  return { setPoles, select, refresh };
}

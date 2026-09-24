// Numbered markers for the poles of the current unit and scenario. The number painted is the pole's place in
// what is shown (`display`, set by data.js when the islands toggle filters the superset); selection is always
// by `rank`, the pole's identity, which does not move when the toggle does.
import { soundingHtml } from './i18n.js';

// A pole is drawn as a chart sounding: a small circled dot on the spot, the distance beside it written the way
// a chart writes a depth, and the pole's number in a small note box. The dot is the anchor.
export function createMarkers(map, { onSelect }) {
  const group = L.layerGroup().addTo(map);
  let items = [];

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

  function setPoles(poles, selectedRank) {
    group.clearLayers();
    items = poles.map((pole) => {
      const active = pole.rank === selectedRank;
      const label = pole.display ?? pole.rank;
      const m = L.marker([pole.lat, pole.lon], { icon: icon(pole, active), title: String(label), zIndexOffset: active ? 1000 : 0 });
      m.on('click', () => onSelect(pole));
      m.addTo(group);
      return { pole, m };
    });
  }

  function select(rank) {
    for (const { pole, m } of items) {
      const active = pole.rank === rank;
      m.setIcon(icon(pole, active));
      m.setZIndexOffset(active ? 1000 : 0);
    }
  }

  return { setPoles, select };
}

// Numbered markers for the poles of the current unit and scenario. The number painted is the pole's place in
// what is shown (`display`, set by data.js when the islands toggle filters the superset); selection is always
// by `rank`, the pole's identity, which does not move when the toggle does.
export function createMarkers(map, { onSelect }) {
  const group = L.layerGroup().addTo(map);
  let items = [];

  // An IOF control: a hollow overprint circle with its number set beside it, never inside. The selected pole
  // is the finish, the double circle, and its rings draw themselves in (pathLength lets the CSS animate the
  // dash in percent). Each ring is laid twice, a paper halo under the overprint, so it reads on snow and forest.
  function icon(label, active) {
    const ring = (r) => `<circle class="pm__halo" cx="20" cy="20" r="${r}"/><circle class="pm__ring" cx="20" cy="20" r="${r}" pathLength="100"/>`;
    return L.divIcon({
      className: `pole-marker${active ? ' pole-marker--active' : ''}`,
      html: `<svg class="pm" width="64" height="40" viewBox="0 0 64 40" aria-hidden="true">${ring(14)}${active ? ring(9.5) : ''}<text class="pm__num" x="36" y="11">${label}</text></svg>`,
      iconSize: [64, 40],
      iconAnchor: [20, 20],
    });
  }

  function setPoles(poles, selectedRank) {
    group.clearLayers();
    items = poles.map((pole) => {
      const active = pole.rank === selectedRank;
      const label = pole.display ?? pole.rank;
      const m = L.marker([pole.lat, pole.lon], { icon: icon(label, active), title: String(label), zIndexOffset: active ? 1000 : 0 });
      m.on('click', () => onSelect(pole));
      m.addTo(group);
      return { pole, m };
    });
  }

  function select(rank) {
    for (const { pole, m } of items) {
      const active = pole.rank === rank;
      m.setIcon(icon(pole.display ?? pole.rank, active));
      m.setZIndexOffset(active ? 1000 : 0);
    }
  }

  return { setPoles, select };
}

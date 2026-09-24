// Numbered markers for the poles of the current unit and scenario. The number painted is the pole's place in
// what is shown (`display`, set by data.js when the islands toggle filters the superset); selection is always
// by `rank`, the pole's identity, which does not move when the toggle does.
export function createMarkers(map, { onSelect }) {
  const group = L.layerGroup().addTo(map);
  let items = [];

  function icon(label, active) {
    return L.divIcon({
      className: `pole-marker${active ? ' pole-marker--active' : ''}`,
      // A trig point: a ringed triangle with a centre dot, the number set beside it with a paper halo, the way
      // a map letters a spot height. The svg overflows the icon box so the number never moves the anchor.
      html: `<svg class="pole-marker__svg" width="64" height="24" viewBox="0 0 64 24" aria-hidden="true">
        <path class="pole-marker__tri" d="M12 3.5 20 17.5H4Z"/><circle class="pole-marker__dot" cx="12" cy="12.8" r="1.6"/>
        <text class="pole-marker__num" x="23" y="16">${label}</text></svg>`,
      iconSize: [24, 24],
      iconAnchor: [12, 13],
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

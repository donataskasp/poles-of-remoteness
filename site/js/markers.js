// Numbered markers for the poles of the current unit and scenario. The number painted is the pole's place in
// what is shown (`display`, set by data.js when the islands toggle filters the superset); selection is always
// by `rank`, the pole's identity, which does not move when the toggle does.
export function createMarkers(map, { onSelect }) {
  const group = L.layerGroup().addTo(map);
  let items = [];

  function icon(label, active) {
    return L.divIcon({
      className: `pole-marker${active ? ' pole-marker--active' : ''}`,
      html: `<span>${label}</span>`,
      iconSize: [26, 26],
      iconAnchor: [13, 13],
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

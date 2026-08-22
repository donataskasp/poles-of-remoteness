// Numbered markers for the poles of the current unit and scenario.
export function createMarkers(map, { onSelect }) {
  const group = L.layerGroup().addTo(map);
  let items = [];

  function icon(rank, active) {
    return L.divIcon({
      className: `pole-marker${active ? ' pole-marker--active' : ''}`,
      html: `<span>${rank}</span>`,
      iconSize: [26, 26],
      iconAnchor: [13, 13],
    });
  }

  function setPoles(poles, selectedRank) {
    group.clearLayers();
    items = poles.map((pole) => {
      const active = pole.rank === selectedRank;
      const m = L.marker([pole.lat, pole.lon], { icon: icon(pole.rank, active), title: String(pole.rank), zIndexOffset: active ? 1000 : 0 });
      m.on('click', () => onSelect(pole));
      m.addTo(group);
      return { pole, m };
    });
  }

  function select(rank) {
    for (const { pole, m } of items) {
      const active = pole.rank === rank;
      m.setIcon(icon(pole.rank, active));
      m.setZIndexOffset(active ? 1000 : 0);
    }
  }

  return { setPoles, select };
}

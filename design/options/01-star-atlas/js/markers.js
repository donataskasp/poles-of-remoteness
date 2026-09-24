// The poles of the current unit and scenario, drawn as stars. A star's size steps with its place in what is
// shown, the way a catalogue sizes stars by magnitude: the first pole is the brightest. The number beside it
// is the pole's place (`display`, set by data.js when the islands toggle filters the superset); selection is
// always by `rank`, the pole's identity, which does not move when the toggle does.
// The icon box is fixed and the number sits outside the glyph at a fixed offset, so neither scales with the
// zoom and the number never lands on its own star.
const BOX = 52;
const RADII = [8.5, 7.25, 6.5, 6, 5.5, 5, 4.75, 4.5, 4.25, 4];

function radius(place) {
  const i = Math.max(0, Math.min(RADII.length - 1, (Number(place) || 1) - 1));
  return RADII[i];
}

function starSvg(r) {
  const ray = (r * 2.6).toFixed(2);
  const c = BOX / 2;
  return `<svg class="star" viewBox="0 0 ${BOX} ${BOX}" width="${BOX}" height="${BOX}" aria-hidden="true" focusable="false">
    <circle class="star__halo" cx="${c}" cy="${c}" r="${(r * 2.9).toFixed(2)}"/>
    <path class="star__rays" d="M${c} ${c - ray}V${c + Number(ray)}M${c - ray} ${c}H${c + Number(ray)}"/>
    <circle class="star__disc" cx="${c}" cy="${c}" r="${r}"/>
  </svg>`;
}

export function createMarkers(map, { onSelect }) {
  const group = L.layerGroup().addTo(map);
  let items = [];

  function icon(label, active, anyActive) {
    const r = radius(label);
    const state = active ? ' pole-marker--active' : (anyActive ? ' pole-marker--dim' : '');
    // The number rides to the upper right of the glyph, clear of the disc and its rays' inner half.
    const off = Math.round(r + 3);
    return L.divIcon({
      className: `pole-marker${state}`,
      html: `${starSvg(r)}<span class="pole-marker__n" style="left:${BOX / 2 + off}px;bottom:${BOX / 2 + Math.round(r * 0.4)}px">${label}</span>`,
      iconSize: [BOX, BOX],
      iconAnchor: [BOX / 2, BOX / 2],
    });
  }

  function setPoles(poles, selectedRank) {
    group.clearLayers();
    const anyActive = poles.some((p) => p.rank === selectedRank);
    items = poles.map((pole) => {
      const active = pole.rank === selectedRank;
      const label = pole.display ?? pole.rank;
      const m = L.marker([pole.lat, pole.lon], { icon: icon(label, active, anyActive), title: String(label), zIndexOffset: active ? 1000 : -Number(label) });
      m.on('click', () => onSelect(pole));
      m.addTo(group);
      return { pole, m };
    });
  }

  function select(rank) {
    const anyActive = items.some(({ pole }) => pole.rank === rank);
    for (const { pole, m } of items) {
      const active = pole.rank === rank;
      const label = pole.display ?? pole.rank;
      m.setIcon(icon(label, active, anyActive));
      m.setZIndexOffset(active ? 1000 : -Number(label));
    }
  }

  return { setPoles, select };
}

// The collar: the graduated border round the map, drawn the way a national survey sheet draws it. An inner
// neatline on the map's edge, a band of alternating filled and open segments one graticule interval long,
// an outer neatline, ticks and the coordinates of every interval, all computed from the map's live bounds.
// The interval is a round figure (10 degrees down to one second of arc) picked so the labels never touch.
// Which edges carry a collar is the caller's: all four on a desktop sheet, left and bottom on a phone.

const DEG = [30, 20, 10, 5, 2, 1];
const MIN = [30, 20, 15, 10, 5, 2, 1].map((m) => m / 60);
const SEC = [30, 20, 10, 5, 2, 1].map((s) => s / 3600);
const STEPS = [...DEG, ...MIN, ...SEC];

const BAND = 4;       // the graduated band, px
const TICK = 5;       // a major tick beyond the band, px
const MINOR = 2.5;    // a minor tick

// Degrees, minutes and seconds, as fine as the interval needs and no finer.
export function fmtCoord(v, isLat, step) {
  let x = v;
  if (!isLat) x = ((((x + 180) % 360) + 360) % 360) - 180;
  const hemi = isLat ? (x > 0 ? 'N' : x < 0 ? 'S' : '') : (x > 0 && x < 180 ? 'E' : x < 0 ? 'W' : '');
  const ts = Math.round(Math.abs(x) * 3600);
  const d = Math.floor(ts / 3600);
  const m = Math.floor((ts % 3600) / 60);
  const s = ts % 60;
  const pad = (n) => String(n).padStart(2, '0');
  let out = `${d}°`;
  if (step < 1 - 1e-9) out += `${pad(m)}′`;
  if (step < 1 / 60 - 1e-9) out += `${pad(s)}″`;
  return out + hemi;
}

// The smallest round interval whose ticks still sit at least minPx apart across a span of px pixels.
export function pickStep(spanDeg, px, minPx) {
  let best = STEPS[0];
  for (const s of STEPS) {
    if ((px / spanDeg) * s >= minPx) best = s;
    else break;
  }
  return best;
}

export function createCollar(svg, map, mapEl, { edges }) {
  let raf = 0;

  function draw() {
    raf = 0;
    const sheet = svg.getBoundingClientRect();
    const box = mapEl.getBoundingClientRect();
    if (!box.width || !box.height) return;
    const ox = box.left - sheet.left;
    const oy = box.top - sheet.top;
    const W = box.width;
    const H = box.height;
    const on = new Set(edges());
    const b = map.getBounds();
    const c = map.getCenter();
    const west = b.getWest();
    const east = b.getEast();
    const south = Math.max(-85, b.getSouth());
    const north = Math.min(85, b.getNorth());
    const lonStep = pickStep(Math.max(east - west, 1e-6), W, 96);
    const latStep = pickStep(Math.max(north - south, 1e-6), H, 84);
    const xOf = (lon) => map.latLngToContainerPoint([c.lat, lon]).x;
    const yOf = (lat) => map.latLngToContainerPoint([lat, c.lng]).y;

    // The ticks along one axis: index k (so the band's parity is fixed to the earth, not the screen) and the
    // pixel position on the map's edge.
    function ticks(lo, hi, step, pos, len) {
      const out = [];
      const k0 = Math.ceil(lo / step - 1e-9);
      const k1 = Math.floor(hi / step + 1e-9);
      for (let k = k0; k <= k1 && out.length < 400; k += 1) {
        const p = pos(k * step);
        if (p >= -0.5 && p <= len + 0.5) out.push({ k, v: k * step, p });
      }
      return out;
    }
    const lonTicks = ticks(west, east, lonStep, xOf, W);
    const latTicks = ticks(south, north, latStep, yOf, H);
    const sub = (step, px) => ([5, 4, 2].find((n) => px / n >= 9) || 1);
    const lonSub = lonTicks.length > 1 ? sub(lonStep, Math.abs(lonTicks[1].p - lonTicks[0].p)) : 5;
    const latSub = latTicks.length > 1 ? sub(latStep, Math.abs(latTicks[1].p - latTicks[0].p)) : 5;

    const parts = [];
    // Band segments along one edge. along: 'x' or 'y'; the list is in the axis's own order.
    function band(list, step, pos, len, rect) {
      // Boundaries: the edge, every tick, the far edge; the segment after tick k has k's parity.
      const cuts = list.map((t) => t.p);
      const kFirst = list.length ? list[0].k - 1 : Math.floor(0);
      const bounds = [0, ...cuts, len];
      const ks = [kFirst, ...list.map((t) => t.k)];
      for (let i = 0; i < bounds.length - 1; i += 1) {
        const a = Math.min(bounds[i], bounds[i + 1]);
        const z = Math.max(bounds[i], bounds[i + 1]);
        if (z - a < 0.3) continue;
        if (((ks[i] % 2) + 2) % 2 === 0) parts.push(rect(a, z - a));
      }
    }

    const r = (x, y, w, h) => `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}"/>`;
    const l = (x1, y1, x2, y2) => `M${x1.toFixed(1)} ${y1.toFixed(1)}L${x2.toFixed(1)} ${y2.toFixed(1)}`;
    let major = '';
    let minor = '';
    const labels = [];

    // Longitude on the top and bottom edges. The band's parity runs west to east.
    const lonSorted = [...lonTicks].sort((a, b2) => a.p - b2.p);
    const latSorted = [...latTicks].sort((a, b2) => a.p - b2.p); // top to bottom on screen: north first
    for (const edge of ['top', 'bottom']) {
      if (!on.has(edge)) continue;
      const y0 = edge === 'top' ? oy - BAND : oy + H;
      band(lonSorted, lonStep, xOf, W, (a, w) => r(ox + a, y0, w, BAND));
      const yOut = edge === 'top' ? oy - BAND : oy + H + BAND;
      const dir = edge === 'top' ? -1 : 1;
      for (const t of lonSorted) {
        major += l(ox + t.p, yOut, ox + t.p, yOut + dir * TICK);
        labels.push(`<text class="collar__lbl" x="${(ox + t.p).toFixed(1)}" y="${(yOut + dir * (TICK + 3) + (dir > 0 ? 8 : 0)).toFixed(1)}" text-anchor="middle">${fmtCoord(t.v, false, lonStep)}</text>`);
      }
      if (lonSub > 1) {
        const k0 = (lonSorted[0] ? lonSorted[0].k : Math.ceil(west / lonStep)) - 1;
        for (let k = k0; k <= k0 + lonSorted.length + 1; k += 1) {
          for (let j = 1; j < lonSub; j += 1) {
            const x = xOf((k + j / lonSub) * lonStep);
            if (x > 0 && x < W) minor += l(ox + x, yOut, ox + x, yOut + dir * MINOR);
          }
        }
      }
    }
    for (const edge of ['left', 'right']) {
      if (!on.has(edge)) continue;
      const x0 = edge === 'left' ? ox - BAND : ox + W;
      // On screen the band runs north to south, so the parity comes from the index counted the same way.
      const flipped = latSorted.map((t) => ({ ...t, k: -t.k }));
      band(flipped, latStep, yOf, H, (a, h) => r(x0, oy + a, BAND, h));
      const xOut = edge === 'left' ? ox - BAND : ox + W + BAND;
      const dir = edge === 'left' ? -1 : 1;
      for (const t of latSorted) {
        major += l(xOut, oy + t.p, xOut + dir * TICK, oy + t.p);
        const lx = xOut + dir * (TICK + 3) + (dir > 0 ? 8 : 0);
        // Set up the edge, reading from the bottom as a sheet's side labels do.
        labels.push(`<text class="collar__lbl" transform="translate(${lx.toFixed(1)} ${(oy + t.p).toFixed(1)}) rotate(-90)" text-anchor="middle">${fmtCoord(t.v, true, latStep)}</text>`);
      }
      if (latSub > 1) {
        const k0 = (latTicks.length ? Math.min(...latTicks.map((t) => t.k)) : Math.ceil(south / latStep)) - 1;
        for (let k = k0; k <= k0 + latTicks.length + 1; k += 1) {
          for (let j = 1; j < latSub; j += 1) {
            const y = yOf((k + j / latSub) * latStep);
            if (y > 0 && y < H) minor += l(xOut, oy + y, xOut + dir * MINOR, oy + y);
          }
        }
      }
    }

    // Neatlines: the map's own edge, and the band's outer edge, on the collared sides only.
    let neat = '';
    const inner = { top: l(ox, oy, ox + W, oy), bottom: l(ox, oy + H, ox + W, oy + H), left: l(ox, oy, ox, oy + H), right: l(ox + W, oy, ox + W, oy + H) };
    const outer = {
      top: l(ox - (on.has('left') ? BAND : 0), oy - BAND, ox + W + (on.has('right') ? BAND : 0), oy - BAND),
      bottom: l(ox - (on.has('left') ? BAND : 0), oy + H + BAND, ox + W + (on.has('right') ? BAND : 0), oy + H + BAND),
      left: l(ox - BAND, oy - (on.has('top') ? BAND : 0), ox - BAND, oy + H + (on.has('bottom') ? BAND : 0)),
      right: l(ox + W + BAND, oy - (on.has('top') ? BAND : 0), ox + W + BAND, oy + H + (on.has('bottom') ? BAND : 0)),
    };
    for (const e of on) neat += inner[e] + outer[e];
    // The corner squares where two bands meet stay open, as on a printed sheet.

    svg.innerHTML = `<g class="collar__band">${parts.join('')}</g>
      <path class="collar__neat" d="${neat}"/>
      <path class="collar__major" d="${major}"/>
      <path class="collar__minor" d="${minor}"/>
      <g class="collar__labels">${labels.join('')}</g>`;
  }

  function schedule() { if (!raf) raf = requestAnimationFrame(draw); }
  map.on('move zoom viewreset resize', schedule);
  // The map box changes size without a window resize when the phone sheet's closed height is measured, so the
  // map is told and the collar redrawn whenever its box moves.
  if (typeof ResizeObserver === 'function') {
    new ResizeObserver(() => { map.invalidateSize({ pan: false }); schedule(); }).observe(mapEl);
  }
  window.addEventListener('resize', schedule);
  schedule();
  return { redraw: schedule };
}


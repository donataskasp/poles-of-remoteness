// Detail overlays: the 50 m rasters around each pole, shown at zoom 12 and above. A raster is placed by its
// sidecar (north-west corner and pixel size in degrees, EPSG:4326) and its class array answers the readout
// before the z9 tile does. Blank rasters (islets narrower than a pixel) are all NODATA and fall through.
import { NODATA } from './classes.js';
import { paint } from './palette.js';
import { detailUrl } from './data.js';

export const DETAIL_MIN_ZOOM = 12;

// The sidecar gives the north-west corner and the pixel size in degrees, so placing a raster and hit-testing
// it are both plain arithmetic. Pure and exported so they can be tested without a map or a browser.
export function rasterEdges(meta) {
  return {
    north: meta.north,
    west: meta.west,
    south: meta.north - meta.dlat * meta.height,
    east: meta.west + meta.dlon * meta.width,
  };
}

// Which cell a point falls in, or null when it falls outside. The north and west edges belong to the raster,
// the south and east edges belong to the next one along.
export function cellAt(meta, lat, lon) {
  // Tested against the same edges the overlay is placed by, so hit-testing and painting agree to the bit.
  const e = rasterEdges(meta);
  if (lon < e.west || lon >= e.east || lat > e.north || lat <= e.south) return null;
  const col = Math.floor((lon - meta.west) / meta.dlon);
  const row = Math.floor((meta.north - lat) / meta.dlat);
  if (col < 0 || row < 0 || col >= meta.width || row >= meta.height) return null;
  return { col, row };
}

async function fetchJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

async function fetchBlob(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.blob();
}

async function fetchDetail(region, pole) {
  const [meta, png] = await Promise.all([fetchJson(detailUrl(region, pole, 'json')), fetchBlob(detailUrl(region, pole, 'png'))]);
  const bitmap = await createImageBitmap(png, { premultiplyAlpha: 'none', colorSpaceConversion: 'none' });
  const canvas = document.createElement('canvas');
  canvas.width = meta.width;
  canvas.height = meta.height;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(bitmap, 0, 0);
  bitmap.close();
  const { data } = ctx.getImageData(0, 0, meta.width, meta.height);
  const classes = new Uint8Array(meta.width * meta.height);
  for (let i = 0; i < classes.length; i += 1) classes[i] = data[i * 4];
  const e = rasterEdges(meta);
  return { meta, classes, canvas, bounds: L.latLngBounds([[e.south, e.west], [e.north, e.east]]) };
}

export function createDetailOverlays(map, { region, palette }) {
  const entries = new Map(); // pole.detail -> { pole, promise, data, overlay, failed }
  let pal = palette;

  function approxBounds(pole) {
    const half = region.detail_window_m / 2;
    const dlat = half / 111320;
    const dlon = half / (111320 * Math.max(0.05, Math.cos((pole.lat * Math.PI) / 180)));
    return L.latLngBounds([[pole.lat - dlat, pole.lon - dlon], [pole.lat + dlat, pole.lon + dlon]]);
  }

  function render(entry) {
    const { data } = entry;
    data.canvas.getContext('2d').putImageData(paint(data.classes, pal, data.meta.width, data.meta.height), 0, 0);
    const url = data.canvas.toDataURL('image/png');
    if (entry.overlay) entry.overlay.setUrl(url);
    else entry.overlay = L.imageOverlay(url, data.bounds, { interactive: false, className: 'detail-overlay', zIndex: 10 });
  }

  function update() {
    const visible = map.getZoom() >= DETAIL_MIN_ZOOM;
    const view = map.getBounds();
    for (const entry of entries.values()) {
      const bounds = entry.data ? entry.data.bounds : approxBounds(entry.pole);
      const want = visible && view.intersects(bounds) && !entry.failed;
      if (want && !entry.promise) {
        entry.promise = fetchDetail(region, entry.pole).then((data) => {
          entry.data = data;
          render(entry);
          update();
        }).catch((e) => {
          entry.failed = true;
          console.warn('detail', entry.pole.detail, e.message);
        });
      }
      if (entry.overlay) {
        if (want && !map.hasLayer(entry.overlay)) entry.overlay.addTo(map);
        if (!want && map.hasLayer(entry.overlay)) map.removeLayer(entry.overlay);
      }
    }
  }

  // A pole without a detail raster (nothing to fetch) is simply not an entry: the z9 tile answers for it.
  function setPoles(poles) {
    const withDetail = poles.filter((p) => p.detail);
    const keep = new Set(withDetail.map((p) => p.detail));
    for (const [key, entry] of entries) {
      if (keep.has(key)) continue;
      if (entry.overlay && map.hasLayer(entry.overlay)) map.removeLayer(entry.overlay);
      entries.delete(key);
    }
    for (const pole of withDetail) {
      if (!entries.has(pole.detail)) entries.set(pole.detail, { pole, promise: null, data: null, overlay: null, failed: false });
    }
    update();
  }

  function classAt(latlng) {
    if (map.getZoom() < DETAIL_MIN_ZOOM) return undefined;
    for (const entry of entries.values()) {
      const d = entry.data;
      if (!d) continue;
      const cell = cellAt(d.meta, latlng.lat, latlng.lng);
      if (!cell) continue;
      const cls = d.classes[cell.row * d.meta.width + cell.col];
      if (cls !== NODATA) return cls;
    }
    return undefined;
  }

  function setPalette(p) {
    pal = p;
    for (const entry of entries.values()) if (entry.data) render(entry);
  }

  map.on('moveend zoomend', update);
  return { setPoles, classAt, setPalette, update };
}

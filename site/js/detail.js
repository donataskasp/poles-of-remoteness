// Detail overlays: the 50 m rasters around each pole, shown at zoom 12 and above. A raster is placed by its
// sidecar (north-west corner and pixel size in degrees, EPSG:4326) and its class array answers the readout
// before the z9 tile does. Blank rasters (islets narrower than a pixel) are all NODATA and fall through.
import { NODATA } from './classes.js';
import { paint } from './palette.js';
import { detailUrl } from './data.js';

export const DETAIL_MIN_ZOOM = 12;

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
  const south = meta.north - meta.dlat * meta.height;
  const east = meta.west + meta.dlon * meta.width;
  return { meta, classes, canvas, bounds: L.latLngBounds([[south, meta.west], [meta.north, east]]) };
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
      if (!d || !d.bounds.contains(latlng)) continue;
      const col = Math.floor((latlng.lng - d.meta.west) / d.meta.dlon);
      const row = Math.floor((d.meta.north - latlng.lat) / d.meta.dlat);
      if (col < 0 || row < 0 || col >= d.meta.width || row >= d.meta.height) continue;
      const cls = d.classes[row * d.meta.width + col];
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

// The Leaflet map and its two basemaps. Nothing about data here.
import { t } from './i18n.js';

export const BASEMAPS = {
  sat: {
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    options: { maxZoom: 19, maxNativeZoom: 18, attribution: '' },
  },
  osm: {
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    options: { maxZoom: 19, attribution: '' },
  },
};

export function createMap(el, { center, zoom, minZoom = 2, basemap = 'sat' }) {
  const map = L.map(el, {
    center, zoom, minZoom, maxZoom: 19, zoomControl: false, attributionControl: false,
    worldCopyJump: false, zoomSnap: 0.5, preferCanvas: true,
  });
  L.control.zoom({ position: 'bottomright' }).addTo(map);
  const attribution = L.control.attribution({ position: 'bottomright', prefix: false }).addTo(map);
  const layers = Object.fromEntries(Object.entries(BASEMAPS).map(([k, b]) => [k, L.tileLayer(b.url, { ...b.options, className: 'basemap' })]));
  let current = null;
  function setBasemap(key) {
    const next = BASEMAPS[key] ? key : 'sat';
    if (next === current) return current;
    if (current) map.removeLayer(layers[current]);
    layers[next].addTo(map);
    layers[next].bringToBack();
    current = next;
    refreshAttribution();
    return current;
  }
  function refreshAttribution() {
    attribution._attributions = {};
    attribution.addAttribution(t('attribution'));
    if (current === 'sat') attribution.addAttribution(t('attributionSat'));
  }
  setBasemap(basemap);
  return { map, setBasemap, getBasemap: () => current, refreshAttribution };
}

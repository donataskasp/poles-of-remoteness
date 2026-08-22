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
  const zoomCtl = L.control.zoom({
    position: 'bottomright', zoomInTitle: t('zoomIn'), zoomOutTitle: t('zoomOut'),
  }).addTo(map);
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
  // Leaflet has no clear(), so we track what we put in and take it out again by value before re-adding.
  let shown = [];
  function refreshAttribution() {
    shown.forEach((s) => attribution.removeAttribution(s));
    shown = [t('attribution')];
    if (current === 'sat') shown.push(t('attributionSat'));
    shown.forEach((s) => attribution.addAttribution(s));
  }
  // The zoom buttons are Leaflet's own, so their tooltips need re-setting when the language changes.
  function refreshZoomTitles() {
    const titles = [['.leaflet-control-zoom-in', t('zoomIn')], ['.leaflet-control-zoom-out', t('zoomOut')]];
    titles.forEach(([sel, text]) => {
      const el = zoomCtl.getContainer().querySelector(sel);
      if (!el) return;
      el.title = text;
      el.setAttribute('aria-label', text);
    });
  }
  setBasemap(basemap);
  return { map, setBasemap, getBasemap: () => current, refreshAttribution, refreshZoomTitles };
}

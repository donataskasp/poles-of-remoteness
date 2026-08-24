// The continental explore layer: z0 to z9 PNG tiles from a PMTiles archive on R2, one class byte per pixel,
// painted through the palette on a canvas. The decoded class array stays on each tile so the readout can
// answer without a second fetch, and so a palette change (dark mode) repaints without one either.
import { NODATA } from './classes.js';
import { paint } from './palette.js';

const SIZE = 256;

function decodeClasses(bitmap, scratch) {
  const ctx = scratch.getContext('2d', { willReadFrequently: true });
  ctx.clearRect(0, 0, SIZE, SIZE);
  ctx.drawImage(bitmap, 0, 0);
  const { data } = ctx.getImageData(0, 0, SIZE, SIZE);
  const classes = new Uint8Array(SIZE * SIZE);
  for (let i = 0; i < classes.length; i += 1) classes[i] = data[i * 4];
  return classes;
}

export async function createExploreLayer({ url, palette, onReady }) {
  const archive = new pmtiles.PMTiles(url);
  const header = await archive.getHeader();
  const scratch = document.createElement('canvas');
  scratch.width = SIZE; scratch.height = SIZE;

  const Explore = L.GridLayer.extend({
    createTile(coords, done) {
      const tile = document.createElement('canvas');
      tile.width = SIZE; tile.height = SIZE;
      tile.classList.add('explore-tile');
      tile._classes = undefined;
      archive.getZxy(coords.z, coords.x, coords.y).then(async (res) => {
        if (!res) { tile._classes = null; done(null, tile); return; }
        const bitmap = await createImageBitmap(new Blob([res.data], { type: 'image/png' }),
          { premultiplyAlpha: 'none', colorSpaceConversion: 'none' });
        tile._classes = decodeClasses(bitmap, scratch);
        bitmap.close();
        this._paintTile(tile);
        done(null, tile);
      }).catch((e) => done(e, tile));
      return tile;
    },
    _paintTile(tile) {
      if (!tile._classes) return;
      tile.getContext('2d').putImageData(paint(tile._classes, this._palette, SIZE, SIZE), 0, 0);
    },
    // _tiles exists only while the layer is on the map; off-map the new palette is kept for the next add.
    setPalette(pal) {
      this._palette = pal;
      Object.values(this._tiles || {}).forEach((t) => this._paintTile(t.el));
    },
    // The class byte under a point, from the native-zoom tile that covers it. undefined: not loaded yet.
    classAt(latlng) {
      if (!this._map) return undefined;
      const z = Math.min(Math.round(this._map.getZoom()), this.options.maxNativeZoom);
      const p = this._map.project(latlng, z);
      const x = Math.floor(p.x / SIZE);
      const y = Math.floor(p.y / SIZE);
      const t = this._tiles[`${x}:${y}:${z}`];
      if (!t) return undefined;
      if (t.el._classes === null) return NODATA;
      if (!t.el._classes) return undefined;
      const px = Math.min(SIZE - 1, Math.floor(p.x - x * SIZE));
      const py = Math.min(SIZE - 1, Math.floor(p.y - y * SIZE));
      return t.el._classes[py * SIZE + px];
    },
  });

  const layer = new Explore({
    tileSize: SIZE, maxNativeZoom: Math.min(9, header.maxZoom), minZoom: header.minZoom, maxZoom: 19,
    updateWhenZooming: false, keepBuffer: 2, className: 'explore', pane: 'overlayPane', opacity: 1,
  });
  layer._palette = palette;
  layer.header = header;
  if (onReady) layer.once('load', onReady);
  return layer;
}

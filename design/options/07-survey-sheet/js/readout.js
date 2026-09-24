// The readout: what one class byte means, in words, and the small panel that shows it.
import { EDGE, NODATA } from './classes.js';
import { t, fmtDist } from './i18n.js';

export function describe(cls, table) {
  if (cls === NODATA || cls == null) return { kind: 'nodata' };
  if (cls === EDGE) return { kind: 'edge' };
  const lower = table.lower(cls);
  const upperRaw = table.upper(cls);
  const upper = Number.isFinite(upperRaw) ? upperRaw : null;
  return { kind: 'class', cls, lower, upper, mid: upper == null ? null : (lower + upper) / 2 };
}

export function formatSample(sample) {
  if (sample.kind === 'edge') return t('readoutEdge');
  if (sample.kind !== 'class') return '';
  if (sample.upper == null) return t('readoutOver', { d: fmtDist(sample.lower) });
  return t('readoutAbout', { d: fmtDist(sample.mid) });
}

// The key cell a sample sits in: 0 for under the first stop (untinted), 1 to 6 for the bands, 'edge' for the
// grey cells at the data's edge, null when there is nothing to place.
export function keyCell(sample, stops) {
  if (!sample) return null;
  if (sample.kind === 'edge') return 'edge';
  if (sample.kind !== 'class') return null;
  let band = -1;
  stops.forEach((s, i) => { if (sample.lower >= s) band = i; });
  return band + 1;
}

// The readout: the reading in words, and under it the key in miniature with the tapped class marked, so the
// value is always shown with its place on the scale. keyHtml(cell) draws that miniature; it is the caller's
// because the colours live in the tokens.
export function mountReadout(el, { keyHtml, onCell } = {}) {
  let timer = null;
  let last = {};
  function show(text, options = {}) {
    last = options;
    clearTimeout(timer);
    if (!text) { el.hidden = true; if (onCell) onCell(null); return; }
    const cell = options.cell ?? null;
    el.innerHTML = '';
    const p = document.createElement('span');
    p.className = 'readout__text';
    p.textContent = text;
    el.append(p);
    if (cell != null && keyHtml) el.insertAdjacentHTML('beforeend', keyHtml(cell));
    el.dataset.cell = cell ?? '';
    el.hidden = false;
    if (onCell) onCell(cell);
    if (!options.sticky) timer = setTimeout(() => { el.hidden = true; if (onCell) onCell(null); }, 6000);
  }
  return {
    show,
    // Say the same thing again, in another language: only while the pill is up, as sticky as it was, and
    // with its six seconds starting again (the reader has just been given something new to read).
    restate(text) { if (!el.hidden) show(text, last); },
    visible() { return !el.hidden; },
    hide() { clearTimeout(timer); el.hidden = true; if (onCell) onCell(null); },
  };
}

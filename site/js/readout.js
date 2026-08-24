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

export function mountReadout(el) {
  let timer = null;
  let last = {};
  function show(text, options = {}) {
    last = options;
    clearTimeout(timer);
    if (!text) { el.hidden = true; return; }
    el.textContent = text;
    el.hidden = false;
    if (!options.sticky) timer = setTimeout(() => { el.hidden = true; }, 6000);
  }
  return {
    show,
    // Say the same thing again, in another language: only while the pill is up, as sticky as it was, and
    // with its six seconds starting again (the reader has just been given something new to read).
    restate(text) { if (!el.hidden) show(text, last); },
    visible() { return !el.hidden; },
    hide() { clearTimeout(timer); el.hidden = true; },
  };
}

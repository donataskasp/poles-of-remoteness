// The readout: what one class byte means, in words, and the small panel that shows it.
import { EDGE, NODATA } from './classes.js';
import { t, fmtDist, esc } from './i18n.js';

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

// The readout is written as a sounding: the first figure in the sentence set as a chart depth, whole
// kilometres (or metres) full size and the decimal small and lowered. Text without a figure passes through.
// The decimal separator stays in the text, visually hidden, so what aria-live announces is still "about 1.9
// km", never "19 km". The figure is found in the raw text and each piece escaped on its own, so an entity
// the escaping writes (an apostrophe is &#39;) can never be taken for the figure.
const FIGURE = /(\d+(?:[\s\u00a0]\d{3})*)(?:([.,])(\d+))?/;
function sounding(text) {
  const m = FIGURE.exec(text);
  if (!m) return esc(text);
  const [all, w, sep, d] = m;
  const frac = d ? `<span class="vh">${esc(sep)}</span><span class="snd-fig__d">${esc(d)}</span>` : '';
  const fig = `<span class="snd-fig"><span class="snd-fig__w">${esc(w.trim())}</span>${frac}</span>`;
  return esc(text.slice(0, m.index)) + fig + esc(text.slice(m.index + all.length));
}

export function mountReadout(el) {
  let timer = null;
  let last = {};
  function show(text, options = {}) {
    last = options;
    clearTimeout(timer);
    if (!text) { el.hidden = true; return; }
    el.innerHTML = sounding(text);
    el.classList.toggle('readout--snd', /\d/.test(text));
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

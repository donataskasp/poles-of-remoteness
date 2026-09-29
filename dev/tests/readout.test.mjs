import test from 'node:test';
import assert from 'node:assert/strict';
import { makeClassTable, EDGE, NODATA } from '../../site/js/classes.js';
import { setLang } from '../../site/js/i18n.js';
import { describe, formatSample, mountReadout } from '../../site/js/readout.js';

const table = makeClassTable();

test('readout: describe', () => {
  assert.deepEqual(describe(NODATA, table), { kind: 'nodata' });
  assert.deepEqual(describe(EDGE, table), { kind: 'edge' });
  const c = describe(table.toClass(1200), table);
  assert.equal(c.kind, 'class');
  assert.ok(c.lower <= 1200 && c.upper > 1200);
  assert.equal(c.mid, (c.lower + c.upper) / 2);
  const top = describe(253, table);
  assert.equal(top.upper, null);
  assert.equal(top.mid, null);
});

test('readout: wording', () => {
  setLang('en');
  assert.equal(formatSample(describe(NODATA, table)), '');
  assert.equal(formatSample(describe(EDGE, table)), 'no data: edge of map data');
  assert.match(formatSample(describe(table.toClass(1200), table)), /^about \d+(\.\d)? km$/);
  assert.match(formatSample(describe(table.toClass(30), table)), /^about \d+ m$/);
  assert.equal(formatSample(describe(253, table)), `over ${table.lower(253) / 1000} km`);
  setLang('lt');
  assert.match(formatSample(describe(table.toClass(1200), table)), /^apie /);
  setLang('en'); // the language is module state, so leave it as found and keep the file order-independent
});

// The pill is written as markup now (the figure is a sounding), so the stand-in element records innerHTML and
// the one class the readout toggles.
function fakeEl() {
  const classes = new Set();
  return { hidden: true, innerHTML: '', classes, classList: { toggle(c, on) { if (on) classes.add(c); else classes.delete(c); } } };
}
const snd = (w, sep, d) => `<span class="snd-fig"><span class="snd-fig__w">${w}</span>${d ? `<span class="vh">${sep}</span><span class="snd-fig__d">${d}</span>` : ''}</span>`;
// What assistive technology reads: the text of the markup, the hidden separator included.
const text = (html) => html.replace(/<[^>]+>/g, '');

test('readout: the pill restates only while it is up, and keeps its stickiness', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const el = fakeEl();
  const r = mountReadout(el);
  assert.equal(r.visible(), false);

  r.show('about 3 km');
  assert.equal(r.visible(), true);
  t.mock.timers.tick(3000);
  r.restate('apie 3 km');
  assert.equal(el.innerHTML, `apie ${snd('3')} km`);
  t.mock.timers.tick(3000);
  assert.equal(r.visible(), true, 'restating says it again, and its six seconds start again with it');
  t.mock.timers.tick(3000);
  assert.equal(r.visible(), false, 'a restated pill still goes away on its own');

  r.restate('never said');
  assert.equal(el.innerHTML, `apie ${snd('3')} km`, 'a pill that already hid stays hidden and silent');
  assert.equal(r.visible(), false);

  r.show('tap the map', { sticky: true });
  r.restate('palieskite zemelapi');
  t.mock.timers.tick(6000);
  assert.equal(r.visible(), true, 'a sticky pill stays up after being restated');
  assert.equal(el.innerHTML, 'palieskite zemelapi');

  r.hide();
  assert.equal(r.visible(), false);
});

test('readout: the first figure is set as a sounding, in either language, and only a figure marks the pill', () => {
  const el = fakeEl();
  const r = mountReadout(el);
  r.show('about 1.5 km', { sticky: true });
  assert.equal(el.innerHTML, `about ${snd('1', '.', '5')} km`, 'the whole part full size, the decimal lowered');
  assert.equal(text(el.innerHTML), 'about 1.5 km', 'and what aria-live announces is the sentence as written');
  assert.ok(el.classes.has('readout--snd'));
  r.show('apie 1,5 km', { sticky: true });
  assert.equal(el.innerHTML, `apie ${snd('1', ',', '5')} km`, 'a decimal comma splits the same way');
  assert.equal(text(el.innerHTML), 'apie 1,5 km');
  r.show('over 50 km, then 60', { sticky: true });
  assert.equal(el.innerHTML, `over ${snd('50')} km, then 60`, 'only the first figure is a sounding');
  r.show('apie 1\u00a0200 m', { sticky: true });
  assert.equal(el.innerHTML, `apie ${snd('1\u00a0200')} m`, 'a grouped figure stays one figure');
  assert.equal(text(el.innerHTML), 'apie 1\u00a0200 m');
  r.show('no data: edge of map data', { sticky: true });
  assert.equal(el.innerHTML, 'no data: edge of map data');
  assert.ok(!el.classes.has('readout--snd'), 'text without a figure is not a sounding');
});

test('readout: the text around the sounding is escaped, and an escaped character is never the figure', () => {
  const el = fakeEl();
  const r = mountReadout(el);
  r.show('<b>x</b> 3 km', { sticky: true });
  assert.equal(el.innerHTML, `&lt;b&gt;x&lt;/b&gt; ${snd('3')} km`, 'markup in the text lands as text');
  // An apostrophe escapes to &#39;, whose digits must not be read as the distance.
  r.show("the pole's 3 km", { sticky: true });
  assert.equal(el.innerHTML, `the pole&#39;s ${snd('3')} km`);
});

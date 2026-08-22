import test from 'node:test';
import assert from 'node:assert/strict';
import { makeClassTable, EDGE, NODATA } from '../../site/js/classes.js';
import { setLang } from '../../site/js/i18n.js';
import { describe, formatSample } from '../../site/js/readout.js';

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

// Distance class table, the mirror of pipeline/poles/classes.py (spec 3.4). Keep both in step: the
// pipeline test suite compares them whenever node is on PATH.
export const EDGE = 254;
export const NODATA = 255;

function range(start, stop, step) {
  const out = [];
  for (let v = start; v < stop; v += step) out.push(v);
  return out;
}

export const CLASS_EDGES = [
  ...range(0, 2500, 50),
  ...range(2500, 10000, 100),
  ...range(10000, 30000, 250),
  ...range(30000, 60000, 1000),
  ...range(60000, 240000, 10000),
  240000,
];

// Class of a distance in metres: the last edge not above it.
export function toClass(distM) {
  if (!(distM >= 0)) throw new RangeError('distance must be a non-negative number');
  let lo = 0;
  let hi = CLASS_EDGES.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (CLASS_EDGES[mid] <= distM) lo = mid + 1; else hi = mid;
  }
  return lo - 1;
}

export function classLower(c) { return CLASS_EDGES[c]; }
export function classUpper(c) { return c + 1 < CLASS_EDGES.length ? CLASS_EDGES[c + 1] : Infinity; }

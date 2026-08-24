// Distance class table, the mirror of pipeline/poles/classes.py (spec 3.4). Keep both in step: the
// pipeline test suite compares them whenever node is on PATH. The published regions.json carries its
// region's edges, so the site builds its table with makeClassTable(edges) rather than hard-coding one.
export const EDGE = 254;
export const NODATA = 255;

const N_CLASSES = 254; // real classes 0..253; EDGE and NODATA sit above them

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

// A table over one region's lower edges. Class c covers [edges[c], edges[c + 1]) metres and class 253 is
// open-ended. Validated exactly as ClassTable does in Python, but throwing RangeError.
export function makeClassTable(edges = CLASS_EDGES) {
  const e = Array.from(edges, Number);
  if (e.length !== N_CLASSES) {
    throw new RangeError(`class table needs ${N_CLASSES} lower edges, got ${e.length}`);
  }
  if (e.some((v) => !Number.isInteger(v))) {
    throw new RangeError('class edges must be whole metres');
  }
  if (e[0] !== 0 || e.some((v, i) => i > 0 && !(v > e[i - 1]))) {
    throw new RangeError('class edges must start at 0 and increase strictly');
  }
  const checkClass = (c) => {
    if (!Number.isInteger(c) || c < 0 || c >= e.length) {
      throw new RangeError(`class ${c} is outside 0..${e.length - 1}`);
    }
    return c;
  };
  // Class of a distance in metres: the last edge not above it.
  const toClass = (distM) => {
    if (!Number.isFinite(distM) || distM < 0) {
      throw new RangeError('distance must be a finite non-negative number');
    }
    let lo = 0;
    let hi = e.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (e[mid] <= distM) lo = mid + 1; else hi = mid;
    }
    return lo - 1;
  };
  const lower = (c) => e[checkClass(c)];
  const upper = (c) => (checkClass(c) + 1 < e.length ? e[c + 1] : Infinity);
  return { edges: e, toClass, lower, upper };
}

// Shortcuts over the default table, so the binary search lives in one place.
const DEFAULT_TABLE = makeClassTable(CLASS_EDGES);

export const toClass = DEFAULT_TABLE.toClass;
export const classLower = DEFAULT_TABLE.lower;
export const classUpper = DEFAULT_TABLE.upper;

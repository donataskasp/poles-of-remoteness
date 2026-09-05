# Distinct areas, islands, and the islands toggle: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The ten poles of a unit stop being ten spots on one plateau, no pole sits on a rock smaller than a pixel, and a reader who does not care about offshore rocks can switch them off. Four rules, one publish contract change and one new control.

1. The **distinct-area rule**: a candidate counts as a new place only when it is not connected to an already accepted pole inside the superlevel set `{distance >= f * min(d_p, d_q)}` of the scenario's coarse distance grid, connectivity measured over land alone, with the old 10 km separation kept as a floor for plateau ties.
2. The **island floor**: a candidate may not sit on a land component smaller than `min_island_m2`, and every published pole carries `island_km2` when its land component is not its unit's largest.
3. The **superset**: the search overfinds. It keeps accepting under the distinct-area rule until it holds `top_n` poles whose `island_km2` is null, so it also holds every island pole ranked above the `top_n`-th mainland pole, capped at `top_n` island poles. At most `2 * top_n` per unit and scenario, 20 today. Every pole keeps its overall rank in the superset, and the site filters client-side.
4. **Detail rasters keyed by pole identity, not by rank**, so a publish rerun under an unchanged snapshot never overwrites a key the live site is reading.

**Architecture:** One new pure module, `pipeline/poles/areas.py`, owns everything that reads the coarse grid as a landscape: the threshold ladder, the land-masked superlevel labellings with their cache, the connectivity question, and the land components with their areas. `candidates.py` learns nothing about rasters or islands: `Search` gains one optional connectivity callback and one optional quota object, and both default to today's behaviour. The poles stage builds them from the unit's window of the grid. Validation calls the same module through the same entry points, which makes check 7's new invariant a consistency check rather than an independent one; the independent guard stays check 4, which re-runs `search_unit` on the half-shifted grid and therefore inherits every rule with no code of its own. The site learns the rule's numbers from `regions.json` and does the island filtering itself, so nothing on the site names a region or hard-codes a fraction, and the published superset serves both readings from one document.

**Tech Stack:** Python 3.12 in `pipeline/.venv` (numpy, scipy, rasterio, shapely, pyogrio, pyproj, boto3, pytest; `scipy==1.18.0` is already in `pipeline/requirements.txt`, so `scipy.ndimage.label` and `binary_erosion` add no dependency). Node 22 for the site tests and the Playwright screenshot routine. Plain ES modules on the site, no build step.

**Spec:** `docs/EUROPE_SPEC.md` 2.2 (units), 2.3 (definitions, the land bullet), 3.2 stage 5 (the search) and stage 7 (publish), 4.1 (where data lives), 5.2 (URLs), 5.3 (first screen), 5.4 (ranking), 5.5 (what a pole shows), 6 check 7 (invariants). Issues #56 (bunching, the distinct-area rule), #30 (sub-pixel islets), #57 (nothing is deleted from R2 and a same-size re-render is skipped). Owner's decisions of 2026-09-05, carried here as code.

---

## Global constraints

- Work on a branch off `main` (`git switch -c distinct-areas`). The push deploys the **preview** worker; production is untouched until the merge. This is not a convenience, it is the safety property this plan is built around: production keeps serving the old unit documents, which point at the old detail keys, which nothing in this work deletes or overwrites.
- Commit after every working task with explicit paths, never `git add -A`. Verify the author on the first commit of the session: `git log -1 --format='%an <%ae>'` must be Donatas / gmail.
- No em dashes and no en dashes anywhere: code, comments, tests, docs, commit messages, issue comments. `pipeline/tests/test_docs_pins.py::test_no_em_dashes_in_the_docs` enforces it for the docs.
- No new dependencies. scipy and boto3 are already pinned; nothing else is needed.
- Region configs are the only place a region is described. No test, module or site string may name Europe, North America, Iceland, Alaska or Nunavut outside a fixture or the screenshot list.
- Pipeline tests: `cd pipeline && .venv/bin/python -m pytest -q`. **439 pass at the start of this work and that is the floor.** Every task leaves the suite green; a task that changes behaviour writes the test first, watches it fail for the stated reason, then writes the code.
- Site tests: `node --test 'dev/tests/*.test.mjs'` from the repository root. **66 pass at the start and that is the floor.**
- Shell: `export PATH=/opt/homebrew/bin:$PATH` in every shell that calls osmium, ogr2ogr, gdal or pmtiles.
- Memory: 24 GB. `colima stop` before the poles, validate and publish stages. `POLES_WORKERS=4` for Europe, `POLES_WORKERS=2` for North America. `killall mediaanalysisd` if swap fills during a search.
- While a stage is running, no file under `pipeline/poles/` may be edited: macOS workers re-import the modules from disk. Tasks 1 to 12 all finish and are committed before Task 13 starts.
- Nothing under `work/` is deleted beyond the explicit list in Task 13. The road tiles under `poles/roads/` (Europe 28.9 GB, North America 16.5 GB) are an hour to three hours to rebuild and are required by every remaining stage.
- **Nothing under `<region>/<snapshot>/detail/` on R2 is deleted or overwritten** until Task 17, after the merge and the production verify. See the section below.

### The live site during the reruns

The live site on `main` reads `site/data/<region>/units/<code>.json`, and each pole in it carries `detail: "detail/<unit>/<scenario>-<rank>"`, which the browser turns into an R2 URL under the same `<region>/<snapshot>/` prefix a publish rerun writes to. The snapshot date does not change here, because the OSM data did not change: only the rules did. So under today's rank-keyed naming (`publish/detail.py`, `write_detail` and `render`) a rerun would overwrite `detail/lt/A-2.png` with the raster of whatever pole is rank 2 now, and the live site would draw the wrong 20 km window under every pole whose rank moved, from the publish until the merge. Deleting the prefix first, which is what issue #57 records as the workaround, replaces a wrong raster with a 404. Neither is acceptable on a live site.

Task 7 removes the problem at the root by keying a detail raster on the pole's own coordinates instead of its rank. A pole that did not move keeps its key; a new pole gets a new key; no key the live site reads is ever written twice with different bytes. The old rank-keyed objects stay in the bucket, unreferenced by the new documents and still correct for the old ones, until Task 17 prunes them after the merge.

Three keys per region are genuinely mutable and are the exception: `validation/report.json`, `validation/report.html` and `validation/contact-sheet.html` describe the run rather than a pole, they are read by people and not by the site's JavaScript, and they must be replaced. Task 7 gives `upload_tree` an explicit `force_keys` set for exactly those three, because `_upload_one` skips on a size match and a rewritten report of the same length would otherwise keep the old bytes.

### Screenshot baseline

The seven desktop images as committed at the start of this work:

```
28bf94c8c5f11545f19e8904b82ddeb11dfd2043279bf524c804de0e200f91e6  docs/screenshots/desktop-about.png
8fb742f3b11c56d1c3db52b3512de2748a2b8f2df0c741651681fe656f599811  docs/screenshots/desktop-continent.png
7820c595f7cc89218c8e4769fbf8e1025509d82c27b69568e88bdf3b4c199edb  docs/screenshots/desktop-detail.png
169210a83a1989a590b93d6d8f46cd82ed21f02f0ae2ce8eafbf801ef41294ce  docs/screenshots/desktop-lt-b.png
9a097a0ab48b15b6e88328b3abfe9a72f823b34dc0ad7d7f9daab15ba1b538c6  docs/screenshots/desktop-lt-lang-lt.png
86211edd54cc396fc9c0d396dd1759d27abe7fa50b75934ba6355aed9d468aff  docs/screenshots/desktop-lt.png
f378dea7f9bea3aa371cfe1d36e1e165e130ac044df1e28884c5c3dfb16d8e4e  docs/screenshots/desktop-us-ak.png
```

Tasks 1 to 10 and 12 must leave all seven byte-identical: they change no rendered pixel until the card gains a control or the data changes. **Task 11 changes the whole set on purpose**, because the islands toggle is a second control row in the card and the card is on the desktop layout too. This is the first time a card change has moved the desktop images, and it is expected here. **Task 17 changes them again**, because the data behind them changes. The rule for those two tasks is regenerate, open, read and commit, not compare hashes.

---

## Risks and owner checkpoints

Five things need the owner's eye. None blocks starting; all are reported before the branch merges.

1. **The island floor changes Europe's headline result, and the brief assumed it would not.** The distinct-area rule leaves every winner untouched by construction (rank 1 is the first candidate accepted, and no rule can reject it). The island floor does not: it removes candidate cells. Today's Europe A winner is **Kolbeinsey, 71.4 km** (issue #30), an Icelandic rock of a few hundred square metres that rasterises to one all-touched land cell, which is 0.0625 km2 and well under a 1 km2 floor. It will be gone, and with it Iceland's A rank 1 and the Europe A headline in `README.md`, `docs/OVERVIEW.md` and the hero row. The same fate is likely for the Finnish Bogskar and Aland skerry poles, the Norwegian Helgeland skerry, the Croatian Palagruza pole, the Guernsey and Jersey skerries and the Bell Rock and Pembrokeshire rocks (the five blank detail rasters of stage 3 are the same set). North America's headline (Victoria Island, 425.2 km) survives, Victoria Island being 217,291 km2. **Task 17 records the before and after headline for both regions and posts it to #30 before the merge.** If the owner wants Kolbeinsey kept, the answer is a lower `min_island_m2` in that region's config, a one-line change and another rerun, not a code change.
2. **"Island" is unit-relative, and that has consequences the brief's examples do not all cover.** The tag fires when the pole's land component is not the one holding most of that unit's own cells. So an island unit's own mainland is never tagged (Iceland, Malta, Cyprus, Prince Edward Island), which is the point. But **Denmark's Zealand is an island** (Jutland is the larger component), **Greece's Crete is an island**, and **Baffin is an island for Nunavut** if the continental component holds more Nunavut land than Baffin does, which the arithmetic says it does (mainland Nunavut is roughly 750,000 km2 against Baffin's 507,451 km2), contrary to the brief's parenthetical. Under the islands toggle these are not cosmetic: switching islands off moves Denmark's and Greece's poles onto the mainland and changes their place in the regional ranking. Task 17 lists every tagged component with its unit, rank and area, and the owner rules on the list.
   **The parked alternative, not a task here:** an absolute area threshold above which a component counts as mainland-like whatever the unit (say 10,000 km2), so Zealand, Crete and Baffin read as land while Sable Island and St. Matthew stay islands. It is one more config key and one more line in the tag rule. It is written down so the owner can ask for it later; nothing in this plan builds it.
3. **The Lithuanian strings need a native check.** Three of them: the card's island row (`On an island` / `Saloje`, against the noun-phrase alternative `Island area` / `Salos plotas`), and the toggle's labels (`Islands` / `Salos` as the group, `Included` / `Įskaitomos` and `Excluded` / `Neįskaitomos`). Task 11 posts the rendered card in both languages on #30 and takes the owner's pick before the screenshots.
4. **The superset doubles some published quantities.** Up to twice the poles, twice the detail rasters, twice the R2 objects, and up to twice the seconds in validation check 1 and in the detail render. The cost section below has the numbers and the ceilings; the measured reality goes into the spec at Task 17.
5. **Two schema documents grow and neither version bumps.** Task 8 states the compatibility argument and Task 12 records it in DECISIONS.

---

## File structure

Created:

- `pipeline/poles/areas.py`: the threshold ladder, the land-masked superlevel labellings and their cache, the connectivity test, the land components and their areas.
- `pipeline/tests/test_areas.py`: its tests, on synthetic fields.
- `dev/bunching.py`: the nearest-neighbour, island and superset measures over `site/data`, run before and after so #56 and #30 get comparable tables.
- `dev/prune-r2.py`: the one-off orphan prune of Task 17, boto3 in the venv, dry run by default, logging every key it deletes.

Modified in the pipeline:

- `pipeline/poles/config.py`: three new region config keys with types, defaults and validation.
- `pipeline/poles/units.py`: `land_tif()` and `water_tif()` beside the existing `low_tif()`.
- `pipeline/poles/candidates.py`: `Search` gains the `distinct` callback, a `Verdict`, and a `Quota`; `Refined` gains `cell`; the dominance mask stays as it is, bound to the floor.
- `pipeline/poles/poles.py`: `DEDUP_M` becomes a config key; `search_unit` applies the island gate, builds the `AreaField`, the `distinct` callback and the island quota, moves the saturation check behind the gate, tags each pole and rewrites the exhausted reason; `validate_poles_json` counts mainland poles.
- `pipeline/poles/attrib.py`: `pole_record` carries `island_km2`.
- `pipeline/poles/publish/detail.py`: rasters keyed by pole coordinates instead of rank.
- `pipeline/poles/publish/r2.py`: `upload_tree` gains `force_keys`.
- `pipeline/poles/publish/__init__.py`: the mutable validation keys are forced; `upload_set` unchanged in shape.
- `pipeline/poles/publish/sitedata.py`: the `detail` key, the mainland summaries, the two region facts.
- `pipeline/poles/schemas/unit.schema.json`, `units.schema.json`, `regions.schema.json`.
- `pipeline/poles/validate/checks.py`, `validate/__init__.py`, `validate/report.py`.
- `pipeline/regions/europe.yaml`, `pipeline/regions/north-america.yaml`.
- Tests: `test_config.py`, `test_candidates.py`, `test_poles_stage.py`, `test_attrib.py`, `test_checks.py`, `test_report.py`, `test_publish_detail.py`, `test_publish_r2.py`, `test_publish_sitedata.py`, `test_units.py`.

Modified on the site:

- `site/js/router.js`: the `i` hash key.
- `site/js/data.js`: `summaryKey`, `visiblePoles`, `regionLinks` carrying `i`.
- `site/js/app.js`: the islands state, the filtered pole list, `setIslands`, the home link, popstate.
- `site/js/card.js`: the island row in the pole facts, the islands toggle, display ranks.
- `site/js/ranking.js`: the mainland summary when islands are off.
- `site/js/markers.js`: the marker label shows the display rank.
- `site/js/i18n.js`: the island and toggle strings, `fmtKm2`.
- `site/index.html`, `site/css/app.css`: the About sentences and the second seg row's style.
- `dev/tests/card.test.mjs`, `i18n.test.mjs`, `router.test.mjs`, `data.test.mjs`, `ranking.test.mjs`.
- `dev/screenshots.mjs`, `docs/screenshots/*.png`, `docs/screenshots/README.md`.

Documentation, in the same commit as the code that caused it:

- `pipeline/README.md`, `docs/EUROPE_SPEC.md`, `docs/DECISIONS.md`, `docs/OVERVIEW.md`, `docs/diagrams/01-pipeline.md`, `docs/diagrams/02-site-data-flow.md`, and at the close `README.md` and `docs/LOG.md`.

---

### Task 1: Three region config keys

The rule's two numbers and the island floor become region config, because the config is the only place a region is described and because `pipeline/tests/test_docs_pins.py::test_every_region_config_key_is_documented` will not let them exist undocumented.

**Files:**
- Modify: `pipeline/poles/config.py`, `pipeline/regions/europe.yaml`, `pipeline/regions/north-america.yaml`, `pipeline/README.md`, `pipeline/tests/test_config.py`

**Naming, and why not the brief's suggestions.** The brief offered `dedup_km`; every other distance key in this config is an integer of metres (`edge_mask_m`, `max_distance_m`, `detail_window_m`), and `Search` already calls the value `dedup_m`, so `dedup_m` keeps one vocabulary and one unit. The island floor is `min_island_m2` for the same reason and because it is the same 1,000,000 m2 as `MIN_WATER_M2` in `poles.py`, which is the spec's water-body threshold; the doc row says so. `area_col_fraction` is the brief's own name and is right: a col is the saddle between two summits, which is exactly what the rule measures. The island cap of the superset needs no key: it is `top_n`.

- [ ] **Step 1.1: The keys**

```python
# poles/config.py, in RegionConfig and _TYPES
area_col_fraction: float      # (float, int); default 0.5
dedup_m: int                  # (int,);       default 10_000
min_island_m2: int            # (int,);       default 1_000_000
```

Validation, each with a message naming the key: `0 < area_col_fraction < 1` (0 would make every candidate a new place and 1 would demand a drop to zero), `dedup_m >= 0`, `min_island_m2 >= 0`. `area_col_fraction` accepts an int too, so `0` and `1` are rejected by range rather than by type; the bool guard already in `load_region` rejects `true`.

- [ ] **Step 1.2: Both region configs**

```yaml
# Two poles count as one place unless the ground between them drops below this fraction of the
# nearer one's distance to a road, measured over land on the coarse grid (DECISIONS 2026-09-05).
area_col_fraction: 0.5
# The floor under that rule, for a plateau where the col test alone would tile one flat.
dedup_m: 10000
# No pole on a land component smaller than this. Same 1 km2 as the water-body threshold (spec 2.3).
min_island_m2: 1000000
```

Both regions take the same values; they are per region so a region with different geography can differ later.

- [ ] **Step 1.3: The README rows**

Three rows in the "Region config keys" table of `pipeline/README.md`, in the order the config files use them, phrased the way the other rows are.

- [ ] **Step 1.4: Tests**

```
test_the_new_rule_keys_have_defaults_when_a_config_omits_them
test_area_col_fraction_outside_zero_to_one_is_a_config_error_naming_the_key
test_a_negative_dedup_or_island_floor_is_a_config_error_naming_the_key
test_area_col_fraction_accepts_an_int_but_not_a_bool
```

Then `cd pipeline && .venv/bin/python -m pytest -q` and `POLES_REPO_ROOT=$PWD/.. .venv/bin/python -m pytest -q tests/test_docs_pins.py`.

**Done looks like:** both region configs carry the three keys, `load_region` rejects a bad value with a message naming the key, the README key table has three new rows, the docs pin passes, and the suite is 443 green.

---

### Task 2: `pipeline/poles/areas.py`, the coarse grid read as a landscape

Everything the new rules need, with no knowledge of units, scenarios or poles. Written test first and finished before anything imports it.

**Files:**
- Create: `pipeline/poles/areas.py`, `pipeline/tests/test_areas.py`
- Modify: `pipeline/poles/units.py`, `pipeline/tests/test_units.py`

**Interfaces (consumed by Tasks 3, 4, 5 and 9 under exactly these names):**

```python
LADDER_STEP = 0.01          # the threshold ladder's relative step; part of the rule, see below
NO_LEVEL = 65535            # uint16 sentinel: this cell is in no superlevel set the ladder can name

def ladder_index(distance_m, anchor_m: float, step: float = LADDER_STEP) -> np.ndarray | int
def ladder_value(index: int, anchor_m: float, step: float = LADDER_STEP) -> float
def col_threshold(d_a: float, d_b: float, fraction: float) -> float      # fraction * min(d_a, d_b)

@dataclass(frozen=True)
class LandComponents:
    labels: np.ndarray            # int32 over the window, 0 off land
    area_km2: np.ndarray          # float32 by label, index 0 unused

class AreaField:
    """One window of one scenario's coarse grid, land-masked, with cached superlevel labellings."""
    @classmethod
    def read(cls, dist_tif: Path, land_tif: Path, water_tif: Path, frame: Frame,
             window: Window, anchor_m: float, step: float = LADDER_STEP) -> "AreaField"
    @classmethod
    def from_arrays(cls, dist, land, res_m, row_off, col_off, anchor_m, step=LADDER_STEP) -> "AreaField"
    def rowcol(self, rows, cols) -> tuple[np.ndarray, np.ndarray]   # frame indices to window indices
    def labels_at(self, threshold_m: float) -> np.ndarray           # cached by ladder index
    def component_at(self, row: int, col: int, threshold_m: float) -> int   # 0 when outside the set
    def dead_cells(self, rows, cols, component: int, threshold_m: float) -> np.ndarray
    def land_components(self) -> LandComponents
```

**The ladder, and why the rule carries it.** A labelling per candidate would be a `scipy.ndimage.label` call per acceptance test, and on the largest unit the padded window is about 240 M cells. Thresholds are quantised **down** to a fixed ladder `theta_k = anchor * (1 - step) ** k`, anchored on the region's `max_distance_m`, and a labelling is computed once per ladder index and cached. Down is the safe direction: a lower threshold gives a larger superlevel set, hence more connectivity, hence more candidates called "the same place", so the quantisation can only make the rule stricter, never looser. It is part of the rule rather than an implementation detail, which is why validation shares this module instead of asking the same question its own way. At `step = 0.01` the error is one percent of the threshold, which is half a percent of the candidate's distance.

The per-cell state is one `uint16` array, `level`, holding `ladder_index(distance)` for land cells and `NO_LEVEL` for everything else, so the mask at ladder index `k` is `level <= k` and no separate land array is retained. One array of two bytes per cell is what keeps the largest unit inside its memory budget: 240 M cells is 480 MB here against 960 MB as float32 plus 240 MB of land mask.

- [ ] **Step 2.1: The tests, before the module exists**

Create `pipeline/tests/test_areas.py`. Synthetic fields only, built by hand so the expected answer is arithmetic:

```
test_ladder_quantises_down_and_is_monotone
test_col_threshold_takes_the_lower_of_the_two_distances
test_two_peaks_split_by_a_road_valley_are_two_components
    A 1 x 21 ridge: 1000, 1000, ..., 200 in the middle, ..., 1000. At threshold 500 the middle is out
    and label(left) != label(right); at threshold 100 it is one component.
test_two_peaks_on_one_plateau_are_one_component
test_water_does_not_join_two_areas
    Two identical peaks with a two cell gap; the gap is land in one field and not land in the other.
test_an_islet_is_its_own_component_of_one_cell
test_land_components_areas_are_cell_counts_times_the_cell_area
test_labels_at_is_cached_per_ladder_step_and_recomputed_when_the_step_changes
test_dead_cells_only_names_cells_whose_whole_neighbourhood_is_in_the_component
test_component_at_returns_zero_for_a_cell_below_the_threshold_or_off_land
test_rowcol_maps_frame_indices_into_the_window_and_rejects_a_point_outside_it
test_read_takes_the_candidate_rule_land_mask_from_the_two_rasters
```

Run it: `cd pipeline && .venv/bin/python -m pytest -q tests/test_areas.py` fails at collection with `ModuleNotFoundError: No module named 'poles.areas'`. That is the expected first failure.

- [ ] **Step 2.2: The module**

The docstring carries the rule, the ladder's direction argument and the memory argument. Points the implementation must get right:

- `read` builds `level` block by block off `dist_tif` so the float32 window is never materialised whole; each block is masked by `units_land > 0` and `units_water == 0` read over the same block. A cell with distance 0 gets `NO_LEVEL`: the ladder cannot name it, and it is the low ground that separates areas, so it is in no superlevel set, which is the correct answer.
- `labels_at` builds the mask `level <= k`, crops it to the mask's bounding box, calls `scipy.ndimage.label` on the crop with the 8-connected structure, and writes it back into a full-window int32 array. The crop is what keeps a high threshold cheap on a continental window. One entry of cache, keyed by `k`: thresholds arrive non-increasing, so a second entry would never be hit.
- 8-connectivity, not 4: a diagonal step is a walk on the ground, and 4-connectivity would call two areas separate because a ridge is one cell wide on the diagonal.
- `dead_cells` returns true where the cell **and all eight of its neighbours** carry `component`. That neighbourhood is what makes the pruning of Task 4 provably lossless: a refined point never leaves its cell's eight neighbours, so a point refined from a dead cell lands in a cell of the component and would be rejected anyway.
- `land_components` labels `level != NO_LEVEL` once, lazily, and returns the labels with an area per label from `np.bincount`.

- [ ] **Step 2.3: The two path helpers**

In `pipeline/poles/units.py`, beside `low_tif`:

```python
def land_tif(units_tif: Path) -> Path:    # units_land.tif, the all-touched land of the candidate rule
def water_tif(units_tif: Path) -> Path:   # units_water.tif, the cells big water fills
```

`rasterize_units` already writes both under exactly these names, and writes them again on the half-shifted frame of check 4 as `units_shift_land.tif` and `units_shift_water.tif`. Deriving the paths from `units_tif` is what makes check 4 inherit the new rules with no code of its own. Move `rasterize_units` to call these helpers so the naming has one owner, and add `test_land_and_water_tif_name_what_rasterize_units_writes`.

- [ ] **Step 2.4: Green and commit**

```bash
cd pipeline && .venv/bin/python -m pytest -q
git add pipeline/poles/areas.py pipeline/tests/test_areas.py pipeline/poles/units.py pipeline/tests/test_units.py
git commit -m "areas: superlevel-set connectivity and land components on the coarse grid (#56, #30)"
```

**Done looks like:** `poles.areas` exists with the interfaces above, its 13 tests pass, the two ridge tests state the rule in arithmetic anyone can check, `units.land_tif`/`water_tif` name what `rasterize_units` writes, and the suite is green.

---

### Task 3: The island floor in the poles stage

The gate is at the candidate cell, before the search, and it changes what a saturated cell means.

**Files:**
- Modify: `pipeline/poles/poles.py` (`search_unit`), `pipeline/tests/test_poles_stage.py`

- [ ] **Step 3.1: The gate**

In `search_unit`, after `rows, cols` and the coarse read, before the saturation check:

1. Build the `AreaField` for the unit's padded window (Tasks 4 and 5 need it too; build it once here). Window: the recorded window padded by `ceil(top_coarse_m / frame.res)` cells each way, clamped to the frame. **Stated assumption:** a path joining two areas does not leave the unit's box by more than the candidate's own distance. It is an assumption, not a theorem; the margin scales itself, being 20 cells for a microstate and about 1,700 for the largest unit, and the cost of it being wrong is two areas called one, never a pole in the wrong place.
2. `comps = field.land_components()`; per candidate cell take `comp = comps.labels[wr, wc]` and `area = comps.area_km2[comp]`.
3. Keep only cells with `area * 1e6 >= cfg.min_island_m2`. Filter `rows, cols, coarse, xs, ys, lons, lats` together, and keep `cell_island_km2` (float32) and `cell_is_main` (bool) per surviving cell. `cell_is_main` marks the component holding the most of this unit's surviving cells, which is the unit-relative reading of "the unit's largest land component": it is what makes an island unit's own mainland untagged whatever else the window contains.
4. If nothing survives, return the stage's normal empty result with `reason` "no pole: every candidate cell of the unit lies on a land component smaller than `min_island_m2`", not an exception.
5. Log one line per unit and scenario: cells before, cells after, components dropped.

- [ ] **Step 3.2: The saturation check moves behind the gate**

`top_coarse` is computed on the surviving cells, and the `PolesError` for a cell at `max_distance_m` is raised only if a surviving cell saturates. This is the point of the change: `territory_mask` entries such as Europe's Rockall exist because a sub-cell rock saturated the cap and stopped the run. Leave the mask entries in place (they are the owner's product calls, and removing one is a separate decision), but note in the config comment that the class of abort they were added for is now handled by the floor.

- [ ] **Step 3.3: Tests**

```
test_a_candidate_cell_on_a_land_component_below_the_floor_is_not_searched
test_a_unit_of_nothing_but_small_islets_returns_no_pole_with_a_reason_naming_the_floor
test_a_saturated_cell_on_a_dropped_islet_no_longer_stops_the_run
test_the_island_gate_keeps_the_largest_component_of_a_unit_whatever_the_window_holds
```

**Done looks like:** a unit whose only far cell is a one-cell islet returns no pole with a reason instead of a pole or an abort; a unit's real land is untouched; the saturation error still fires for a saturated cell on qualifying land; the suite is green and the desktop screenshots are still byte-identical.

---

### Task 4: The distinct-area rule in the search

**Files:**
- Modify: `pipeline/poles/candidates.py`, `pipeline/poles/poles.py`, `pipeline/tests/test_candidates.py`, `pipeline/tests/test_poles_stage.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class Verdict:
    separate: bool
    dead: np.ndarray | None      # boolean over the search's own sorted cell order, cells to retire

@dataclass
class Refined:
    x: float; y: float; dist_m: float; payload: object = None
    cell: int = -1               # the sorted index the point was refined from

class Search:
    def __init__(self, xs, ys, coarse, pads, res_m, top_n, refiner, dedup_m=10_000.0,
                 distinct: Callable[[Refined, list[Refined]], Verdict] | None = None,
                 quota: "Quota | None" = None, warn_at=500, fail_at=200_000, log=None)
```

**Why the branch and bound stays correct, and why the dominance mask does not move.** The current mask retires every unvisited cell whose farthest point is surely within `dedup_m` of an accepted pole. That argument is untouched: the floor is a **necessary** condition for acceptance under the new rule as well, so a cell that fails it can hold no pole whatever the connectivity says. `dedup_m` becomes a config value instead of a constant and nothing else about that mask changes, which is why the number of refinements does not rise on account of it.

The new rule needs a second retirement, or the search would descend a plateau one candidate at a time. It comes from the monotonicity of superlevel sets. Candidates are finalised in globally descending distance (a point is popped only once it beats the bound on every unrefined cell), so every later candidate has a threshold no larger than this one's, and components only grow as the threshold falls. So a cell connected to the candidate's component **at this threshold** is connected to it at every threshold still to come, and can never be a new place: retire it. That holds whether the candidate was accepted (future candidates there are the same place as it) or rejected (they are the same place as whatever it was rejected against). `dead_cells` takes the eight neighbours as well, so a refined point that laps out of its cell is still inside the component and the retirement loses nothing. This is the pruning that keeps the search inside its budget: without it a large plateau unit would refine its whole plateau.

- [ ] **Step 4.1: The tests, first**

Extend `pipeline/tests/test_candidates.py`. The existing brute-force comparison gains a sibling that models the whole rule:

```
test_the_search_matches_a_brute_force_model_of_the_distinct_area_rule
    _truth_field as today plus a synthetic connectivity: a `distinct` built over a small labelled
    grid, and a brute-force greedy that refines every cell, sorts by distance, and accepts a point
    only when it clears both the floor and the connectivity test against everything accepted so far.
    The accepted distances must match exactly, as the existing test asserts for the floor alone.
test_a_candidate_connected_to_an_accepted_pole_is_rejected_even_though_it_clears_the_floor
test_a_candidate_the_floor_rejects_never_reaches_the_distinct_callback
test_the_verdict_retires_cells_whether_the_candidate_was_accepted_or_rejected
test_dead_cells_from_the_verdict_are_never_refined_again
test_a_search_without_a_distinct_callback_behaves_exactly_as_before
test_refined_carries_the_sorted_index_it_came_from
```

And in `pipeline/tests/test_poles_stage.py`, the three field cases the owner named, on synthetic rasters run through `search_unit` end to end:

```
test_two_peaks_split_by_a_road_valley_both_become_poles
test_two_peaks_on_one_plateau_yield_one_pole_and_a_reason
test_a_peak_on_an_islet_is_a_separate_place_from_the_mainland_peak
    The islet is above the island floor here, so it survives Task 3's gate and the point of the test
    is that water does not join it to the mainland: both are published although they are 6 km apart,
    which the old 10 km dedup would have refused.
```

- [ ] **Step 4.2: `candidates.py`**

`finalize` becomes: pop; test the floor against the accepted set as today; if it fails, continue (the callback is not called, it is the expensive one); call `distinct(p, accepted)`; apply `verdict.dead` to `alive` whatever the verdict; if not separate, continue; otherwise accept and apply the existing floor dominance mask. `distinct` is called for the first candidate too, with an empty accepted list, so that the winner's own component is retired.

Update the module docstring: it currently describes "accepted greedily with the dedup distance" and must describe both conditions, the monotonicity argument for the new retirement, and the fact that the ladder quantisation lives in `areas.py` and makes the rule slightly stricter than its exact statement.

- [ ] **Step 4.3: `poles.py` wiring**

```python
fraction = cfg.area_col_fraction
def distinct(cand: Refined, accepted: list[Refined]) -> Verdict:
    theta = fraction * cand.dist_m
    comp = field.component_at(*field.rowcol(row_sorted[cand.cell], col_sorted[cand.cell]), theta)
    if comp == 0:                      # below the threshold or off land: nothing can be joined to it
        return Verdict(True, None)
    same = any(field.component_at(*field.rowcol(row_sorted[a.cell], col_sorted[a.cell]), theta) == comp
               for a in accepted)
    return Verdict(not same, field.dead_cells(row_sorted, col_sorted, comp, theta))
```

`row_sorted` and `col_sorted` are bound after construction beside the existing `lon_sorted`/`lat_sorted`, because `Search` sorts the cells by their own bound. `refine_cell` sets `cell=i` on the `Refined` it returns. `Search` is constructed with `cfg.dedup_m`. `DEDUP_M` in `poles.py` is deleted and `checks.py`'s import of it goes with Task 9.

- [ ] **Step 4.4: A timing guard while the code is still cheap to change**

Run one small unit and one large one from the existing work directory and compare refinements and seconds against `work/<region>/<snapshot>/poles/timing.json` for the same unit. If a large unit's refinements have risen by more than about 3x, stop and report before Task 13: the likely cause is the component retirement not firing (a threshold above the whole plateau, a `dead_cells` neighbourhood that never matches), and it is far cheaper to find here than in hour four of a run.

**Done looks like:** the brute-force model and the search agree on the accepted distances; the three field cases behave as the owner described; a search with no callback is bit-for-bit what it was; one real unit's refinement count is within about 3x of its recorded value; the suite is green.

---

### Task 5: The superset, so the site can offer both readings

The search stops when it has `top_n` **mainland** poles, and takes island poles along the way up to a cap of `top_n`. Ranks are the overall ranks of that superset and the site filters them.

**Files:**
- Modify: `pipeline/poles/candidates.py` (the `Quota`), `pipeline/poles/poles.py`, `pipeline/tests/test_candidates.py`, `pipeline/tests/test_poles_stage.py`

**Interfaces:**

```python
# candidates.py: what "how many more do we want, and will we take this one" means.
class Quota:
    def wants_more(self) -> bool: ...                       # the loop condition
    def accepts(self, p: Refined) -> bool: ...              # may this pole be taken at all
    def taken(self, p: Refined) -> np.ndarray | None: ...   # record it; cells to retire, or None

class CountQuota(Quota):                                    # the default: today's behaviour exactly
    def __init__(self, top_n: int)

# poles.py
class IslandQuota(Quota):
    def __init__(self, top_n: int, is_island: Callable[[Refined], bool], island_cells: np.ndarray)
```

`Search` takes `quota=None` and builds a `CountQuota(top_n)`, so every existing test and every caller that does not care is unchanged. `run` loops while `quota.wants_more()`, `finalize` accepts only when `quota.accepts(p)` and applies whatever `quota.taken(p)` returns to `alive`. `exhausted` becomes `quota.wants_more()` at the end.

**The island quota.** `wants_more` is "fewer than `top_n` mainland poles so far". `accepts` is "this one is mainland, or fewer than `top_n` islands so far". `taken` records the pole and, at the moment the island count reaches `top_n`, returns `island_cells`, which is `~cell_is_main` over the search's sorted cell order: **every remaining island cell is retired in one operation**. That is what bounds the cost in an archipelago unit. Without it the search would keep refining skerries it can no longer take, all the way down to the tenth mainland pole. Island-ness is a property of the candidate's cell, known before refinement, so the retirement is exact and needs no extra reads.

The cap is monotone (the island count never falls), so retiring on it loses nothing, and it is the same argument that lets `finalize` apply `verdict.dead` whether a candidate was taken or refused.

- [ ] **Step 5.1: Tests, first**

```
test_candidates.py:
  test_the_default_quota_is_the_old_top_n_count            # every existing test still describes it
  test_a_quota_that_refuses_a_pole_leaves_the_search_running
  test_the_cells_a_quota_retires_are_never_refined_again
  test_wants_more_ends_the_search_even_with_candidates_left
test_poles_stage.py:
  test_a_unit_with_islands_publishes_ten_mainland_poles_and_the_islands_above_the_tenth
  test_no_more_than_top_n_island_poles_are_published
  test_a_landlocked_unit_publishes_exactly_top_n_poles           # the superset is inert here
  test_ranks_are_the_overall_order_of_the_superset_with_no_gaps
  test_reaching_the_island_cap_retires_every_remaining_island_cell
  test_validate_poles_json_counts_mainland_poles_not_all_poles
```

- [ ] **Step 5.2: `validate_poles_json`**

Today it fails a unit with fewer than `top_n` poles and no reason. With the superset that becomes: the number of poles with `island_km2 is None` equals `top_n`, or a reason is given; the island count is at most `top_n`; the total is at most `2 * top_n`; ranks are 1..N contiguous. The message names which of those failed.

- [ ] **Step 5.3: The exhausted reason**

`f"only {mainland} mainland pole(s): no further point of the unit is a distinct area, at least {cfg.dedup_m / 1000:.0f} km from the accepted poles and on allowed ground"`, and the empty case keeps its wording. Check 4's shifted search uses the same quota through `search_unit`, so the shifted list is a superset too and `_nearest_shifted` still pairs by distance.

**Done looks like:** an archipelago unit publishes ten mainland poles plus its islands above the tenth, capped at ten; a landlocked unit publishes exactly ten; ranks are contiguous overall ranks; `validate_poles_json` speaks of mainland poles; the island cap retires the rest of the skerries in one step; the suite is green.

---

### Task 6: `island_km2` on the published pole

**Files:**
- Modify: `pipeline/poles/attrib.py`, `pipeline/poles/poles.py`, `pipeline/poles/schemas/unit.schema.json`, `pipeline/tests/test_attrib.py`, `pipeline/tests/test_poles_stage.py`

- [ ] **Step 6.1: The record**

`pole_record(rank, pole, way, place, island_km2)` gains the argument and emits `"island_km2": island_km2`, a number or `None`. `search_unit` passes `None if cell_is_main[acc.cell] else round(float(cell_island_km2[acc.cell]), 1)`. The area is the whole component's, not the part inside the unit, which is what "on an island of 357 km2" means to a reader. The component is the one holding the pole's **cell**; a refined point can lap up to 177 m into a neighbouring cell, and in the pathological case where that neighbour is a different island the cell's answer is the one published. Say so in the docstring.

- [ ] **Step 6.2: The schema**

`unit.schema.json`: `island_km2` in the pole's `properties` as `{"type": ["number", "null"]}` and in its `required` list. The schemas carry `additionalProperties: false`, so the field cannot be written without this edit, which is the point of them.

- [ ] **Step 6.3: Tests**

```
test_pole_record_carries_the_island_area_or_null
test_a_pole_on_the_units_largest_land_component_is_not_tagged
test_a_pole_on_a_smaller_component_carries_that_components_area
test_a_pole_without_island_km2_fails_the_unit_schema
```

**Done looks like:** every published pole carries `island_km2`, the schema requires it, and the suite is green.

---

### Task 7: Detail rasters keyed by pole identity, and the three mutable keys

This task is what makes the reruns safe for the live site. It lands before any of them.

**Files:**
- Modify: `pipeline/poles/publish/detail.py`, `pipeline/poles/publish/r2.py`, `pipeline/poles/publish/__init__.py`, `pipeline/poles/publish/sitedata.py`, `pipeline/poles/schemas/unit.schema.json`, `pipeline/tests/test_publish_detail.py`, `test_publish_r2.py`, `test_publish_sitedata.py`

- [ ] **Step 7.1: The key**

`write_detail(out_dir, code, scenario, lat, lon, arr, g)` writes `<code>/<scenario>-<lat>_<lon>.png` and its `.json` sidecar, with the coordinates formatted exactly as published, `f"{lat:.6f}"` and `f"{lon:.6f}"`, joined by an underscore. `detail/us-ak/A-60.361570_-172.734900.png` is a legal S3 key and a legal URL path, it is self-describing in a bucket listing and in a prune log, and it is stable: a pole that has not moved keeps its key across every rerun for ever. The alternative, a short hash of the pair, is tidier and opaque; the coordinates win because the one operation this naming exists for, reconciling a bucket against the documents, is done by a human reading a list.

`render` looks its files up by the same name, so its existing skip-when-present resume is unchanged. `_published_set` already records `(scenario, code, rank, lat, lon)` and needs no change. `sitedata.build` writes `detail: f"detail/{code}/{s}-{p['lat']:.6f}_{p['lon']:.6f}"`. The unit schema's pattern becomes `^detail/[a-z][a-z0-9-]{0,31}/[AB]--?[0-9]+\.[0-9]{6}_-?[0-9]+\.[0-9]{6}$`; the field stays a plain string, so `site/js/data.js`'s `detailUrl` is untouched.

A note for a later reader, not a task: identity keys also make an incremental detail render possible, because a file named by its coordinates is never stale. The stamp still rebuilds the directory whole when the class table or the edge band changes, which keeps this change small.

- [ ] **Step 7.2: The three mutable keys**

```python
# publish/r2.py
def upload_tree(client, bucket, items, log, workers=8, forced=False, force_keys=frozenset()) -> dict
# _upload_one(..., forced=forced or key in force_keys)

# publish/__init__.py
def mutable_keys(region_id: str, snapshot: str) -> set[str]      # the three validation objects
```

Under an immutable snapshot prefix the validation artefacts are the only objects that describe the run rather than a pole, so they are the only ones a rerun must replace. Everything else is either unchanged bytes (the archives) or a new key (a new pole's raster). The docstring says exactly that, because the next reader's question will be why anything is forced at all.

- [ ] **Step 7.3: Tests**

```
test_publish_detail.py:
  test_a_raster_is_named_by_its_poles_coordinates_not_its_rank
  test_a_pole_that_did_not_move_keeps_its_file_name_across_a_rerun
  test_two_poles_of_one_unit_and_scenario_never_share_a_name
test_publish_r2.py:
  test_a_same_size_object_in_force_keys_is_uploaded_again
  test_a_same_size_object_outside_force_keys_is_still_skipped
test_publish_sitedata.py:
  test_the_unit_document_points_at_the_identity_keyed_raster
  test_a_rank_keyed_detail_value_fails_the_unit_schema
```

**Done looks like:** a detail raster's name is its pole, the unit document points at it, a rerun overwrites only the three validation objects, and the suite is green.

---

### Task 8: The mainland summaries in the site documents

The regional ranking has to follow the toggle, and a single unit document cannot know its own rank among units.

**Files:**
- Modify: `pipeline/poles/publish/sitedata.py`, `pipeline/poles/schemas/units.schema.json`, `unit.schema.json`, `regions.schema.json`, `pipeline/tests/test_publish_sitedata.py`

- [ ] **Step 8.1: The computation**

`regional_ranks(published_scenario)` gains a sibling that ranks units by their best **mainland** pole (the first pole in rank order with `island_km2 is None`), dense-ranked the same way. `_unit_summary` gains a mainland twin returning `{dist_m, lat, lon, rank}` or `null` when the unit has no mainland pole. `build` writes:

- `units.json`, per unit: `A_mainland` and `B_mainland` beside `A` and `B`.
- the unit document, per scenario block: `mainland` beside `poles`, `withheld` and `reason`.

The second copy in the unit document is redundant for the site, which reads the ranking off `units.json`, and it is there anyway so that a consumer who downloads one unit can answer "what is this unit's mainland pole and where does it rank" without fetching the region index. Say that in the docstring so nobody deletes it as duplication.

`regions_entry` gains `area_col_fraction` and `min_island_m2`, the two numbers the About text needs, exactly like `detail_res_m`.

- [ ] **Step 8.2: The schemas, and why no version bump**

`units.schema.json`: a new `$defs/mainland` (`{dist_m, lat, lon, rank}`, `additionalProperties: false`, nullable), `A_mainland` and `B_mainland` in `properties` and in `required`. `unit.schema.json`: `mainland` in the `scenario` def's `properties` and `required`. `regions.schema.json`: the two numbers in `properties` and `required`.

`SCHEMA_VERSION` stays 1 and `regions.schema.json`'s `{"const": 1}` with it. `site/data/` is committed and served from the same commit as the site code, so a document and its reader always ship together. The two mismatches that can still happen are a browser holding a cached older document against newer JavaScript, which the JavaScript handles by treating a missing `A_mainland` as "no mainland result" exactly like a unit with no poles, and a newer document against older JavaScript, which ignores unknown keys. A bump would buy nothing and would force every consumer of `regions.json` and `manifest.json` to be touched. Changing a schema is a DECISIONS entry either way, per `pipeline/README.md`.

- [ ] **Step 8.3: Tests**

```
test_the_mainland_rank_ignores_island_poles
test_a_unit_whose_every_pole_is_an_island_has_a_null_mainland_summary
test_the_mainland_ranking_is_dense_like_the_overall_one
test_the_regions_entry_publishes_the_rule_numbers
test_the_unit_document_and_units_json_agree_on_the_mainland_winner
```

`dev/site-json.py` needs no change: it calls `sitedata.build` and `write_site` and inherits all of it.

**Done looks like:** both documents carry the mainland summary, `regions.json` carries the two rule numbers, every document validates, and `dev/site-json.py` still builds from the run of record on disk.

---

### Task 9: Validation

**Files:**
- Modify: `pipeline/poles/validate/checks.py`, `validate/__init__.py`, `validate/report.py`, `pipeline/tests/test_checks.py`, `test_report.py`

- [ ] **Step 9.1: Check 7 keeps the separation invariant and gains the area one**

`invariants` keeps `{"name": "separation"}` unchanged except that it reads `cfg.dedup_m` instead of the deleted `DEDUP_M`; `top_n_or_reason` counts mainland poles per Task 5; and one result per unit and scenario is added:

```python
CheckResult("invariant", u.code, scenario, ok, True,
            {"name": "distinct_areas", "fraction": cfg.area_col_fraction, "connected_pairs": [...]})
```

computed through `poles.areas` on the same coarse grid: take the published poles in rank order and, for `j = 2 .. n`, label once at `col_threshold(d_1, d_j, f)`, which is `f * d_j` because the poles are in descending distance, and test every `i < j` against it. That is `n - 1` labellings per unit and scenario and reuses the module's cache within a unit. With the superset `n` can be 20, so it is up to 19 labellings.

The signature grows: `invariants(poles, units, cfg, grid_meta, frame, units_tif, dist_tifs, windows)`. `run` has all of them on `prepared` and `grid_dir`, and gives check 7 its own `step(...)` timing line, because it goes from under a second to minutes and a check that quietly costs minutes is a check nobody will believe the timing of.

**This is a consistency check, not an independent one.** It asks the same module the same question about the same grid, so it can only catch a published file that disagrees with the rule (a stale `A.json`, a hand edit, a bug between the search's verdict and the file it wrote), never a bug in the rule itself. The independent guard is check 4, which recomputes the grid half a cell off and re-runs the search: it calls `search_unit`, so it picks up every new rule with no code of its own, and its `units_shift.tif` gets its `units_shift_land.tif` and `units_shift_water.tif` from the same `rasterize_units` call it already makes, which `poles.areas` reads through `units.land_tif`/`water_tif`. Confirm that by reading `shifted_poles` before writing anything, and say so in the DECISIONS entry.

- [ ] **Step 9.2: The contact sheet says which poles are on an island**

In `write_contact_sheet`, the card's `lines` gains, when `p.get("island_km2")`, one line: `on an island of {km2} km2`. One line and one condition, and the sheet is the artefact the owner reviews, so the island tag belongs beside the thumbnail.

- [ ] **Step 9.3: Tests**

```
test_checks.py: test_check_7_reports_two_poles_connected_above_the_col_threshold
                test_check_7_passes_when_every_pair_is_separated_over_land
                test_check_7_still_fails_a_pair_closer_than_the_config_floor
                test_check_7_counts_mainland_poles_for_top_n_or_reason
                test_check_7_reads_the_floor_from_the_region_config_not_a_constant
test_report.py: test_a_pole_with_an_island_area_gets_a_line_on_its_contact_sheet_card
                test_a_pole_without_one_gets_no_such_line
```

**Done looks like:** check 7 reports `separation` and `distinct_areas` per unit and scenario, both blocking; its timing has its own line; the contact sheet shows the island tag; the comment in `checks.py` says in one sentence why this is a consistency check and where check 4 does the independent work.

---

### Task 10: The site, part one: the island row and the About text

**Files:**
- Modify: `site/js/i18n.js`, `site/js/card.js`, `site/index.html`, `site/js/app.js`, `dev/tests/card.test.mjs`, `dev/tests/i18n.test.mjs`

- [ ] **Step 10.1: The strings and the formatter**

```js
islandFact: 'On an island',        // en
islandFact: 'Saloje',              // lt
export function fmtKm2(km2, lang = current)   // '357 km²'; one decimal below 10, none above
```

The English is the owner's wording. **The Lithuanian needs the owner's check** (risk 3): `Saloje` matches the English row for row, while `Salos plotas` ("island area") is the more usual shape for a definition list whose other labels are nouns. Post both with the rendered row on #30.

- [ ] **Step 10.2: The card row**

In `poleBlock`, immediately after the distance row and only when the field is a number:

```js
${pole.island_km2 ? `<dt>${esc(t('islandFact'))}</dt><dd>${esc(fmtKm2(pole.island_km2))}</dd>` : ''}
```

Nothing in the ranking rows and nothing in the summary row: the summary is the phone sheet's handle, where a fourth fact would not fit.

- [ ] **Step 10.3: The About dialog**

One sentence per language at the end of "How it is computed", with the numbers coming from the region rather than the copy:

> English: "Two of the points count as separate places only when every route between them passes within <span class="area-fraction"></span> of the nearer one's distance to a road, over land, and no point may sit on a patch of land smaller than <span class="min-island"></span> km². Points on smaller islands are listed too, and can be switched off in the card."

> Lithuanian: "Du taškai laikomi skirtingomis vietomis tik tada, kai bet kuris kelias tarp jų praeina arčiau kelio nei <span class="area-fraction"></span> artimesniojo taško atstumo, ir tik sausuma; taškas negali būti mažesniame nei <span class="min-island"></span> km² sausumos lopinėlyje. Taškai mažesnėse salose taip pat rodomi, juos galima išjungti kortelėje."

`app.js` fills them where it fills `.snapshot` and `.detail-res`: `area-fraction` as `Math.round(region.area_col_fraction * 100) + '%'`, `min-island` as `region.min_island_m2 / 1e6`.

- [ ] **Step 10.4: Tests**

```
card.test.mjs: the island row appears with the area and the label in both languages
               no island row when island_km2 is null or absent
               the row is escaped like every other
               the summary row and the headline are unchanged by the field
i18n.test.mjs: fmtKm2 above and below 10 in both locales; every key exists in both languages
```

Leave every screenshot alone: Task 11 adds the toggle to the same card, so one regeneration covers both.

**Done looks like:** the card shows the island row when the field is set, both languages render, the About dialog states both rules with the region's own numbers, the node suite is green above 66, and no screenshot is touched.

---

### Task 11: The site, part two: the islands toggle

**Files:**
- Modify: `site/js/router.js`, `site/js/data.js`, `site/js/app.js`, `site/js/card.js`, `site/js/ranking.js`, `site/js/markers.js`, `site/js/i18n.js`, `site/css/app.css`, `dev/screenshots.mjs`, `dev/tests/router.test.mjs`, `data.test.mjs`, `card.test.mjs`, `ranking.test.mjs`, `i18n.test.mjs`, `docs/screenshots/*`

**Interfaces:**

```js
// router.js
export const ISLANDS = [1, 0];        // parse: i=1 shown, i=0 hidden, absent means shown
// data.js
export function summaryKey(s, islands)                     // 'A' or 'A_mainland'
export function visiblePoles(poles, { islands = 1, top = 10 } = {})   // adds `display`, 1..n
```

- [ ] **Step 11.1: The hash key**

`parse` gains `i: pick('i', ISLANDS, (v) => (v === '1' ? 1 : v === '0' ? 0 : null))`, so a missing or malformed key is `null` and `app.js` defaults it to 1. `toUrl` writes it whenever it is set, between `b` and `l`, exactly like `s` and `b`. **It is always written, not only when 0**, and that is deliberate: the default-shown rule lives in `parse`, so a hand-typed or pre-existing link behaves, while a URL the site writes always carries the key, which is what keeps back and forward honest through `changedState` with no per-key exception (that module's own comment says a key the URL does not carry keeps its current value, which for a toggle would be a bug). `changedState`'s default key list gains `'i'`. The existing router tests' expected hash strings change by four characters; that is the change, not a break.

- [ ] **Step 11.2: The filter**

`visiblePoles` takes the superset in rank order and returns at most `top` of them: with islands shown the first `top`; with islands hidden the first `top` whose `island_km2` is null. Each returned object is a copy carrying `display`, 1..n. **`rank` keeps its meaning everywhere**: it is the pole's identity, it selects the marker and the card chip, and it is what the detail key was built from. `display` is only ever a label. That split is what lets the toggle be free of any refetch.

`summaryKey(s, islands)` is the one owner of the `_mainland` naming; `card.js` and `ranking.js` both call it, and neither builds the string itself.

- [ ] **Step 11.3: The control**

In `card.js`, a second `.seg` group directly under the scenario switch, so it is in the phone sheet body too (the card is the top of the sheet since 2026-09-05):

```html
<div class="seg card__seg" role="group" aria-label="${esc(t('islandsGroup'))}">
  <button type="button" class="seg__btn" data-i="1" aria-pressed="...">${esc(t('islandsOn'))}</button>
  <button type="button" class="seg__btn" data-i="0" aria-pressed="...">${esc(t('islandsOff'))}</button>
</div>
```

The click delegation gains `else if (b.dataset.i) onIslands(Number(b.dataset.i))`, which is safe because `dataset.i` is the string `"0"` or `"1"` and both are truthy. Strings, for the owner's check:

```
islandsGroup: 'Islands'  / 'Salos'
islandsOn:    'Included' / 'Įskaitomos'
islandsOff:   'Excluded' / 'Neįskaitomos'
```

The control is always shown, even for a unit with no island poles, because it is a region-wide reading mode: the ranking changes even when the open unit does not.

`site/css/app.css` gains whatever the second seg row needs to sit under the first without changing the card's other metrics; the phone sheet's `--sheet-h` is measured from the handle and is unaffected, but check the phone screenshots for the card's new height.

- [ ] **Step 11.4: The wiring**

- `app.js`: `state.i = parsed.i ?? 1`; `polesOf()` returns `visiblePoles(block.poles, { islands: state.i, top: 10 })`; `setIslands(i)` sets the state, re-renders the unit, the region links, the home link and the ranking, resets `current.rank` to the first visible pole, and calls `syncUrl(true)`; the popstate handler applies `change.i` through `setIslands`; `renderHomeLink` and `renderRegions` pass `i` into `toUrl` and `regionLinks`.
- `card.js`: the headline, the rank line and the "of N" count read `unit[summaryKey(scenario, islands)]`; the chips and the pole heading show `display`; `onPole` still hands back `rank`.
- `ranking.js`: `sortUnits(units, s, islands)` and the row renderer read `summaryKey` for both the active and the small-type scenario; a unit with a null mainland summary sorts last exactly as a unit with no result does today.
- `markers.js`: `icon(pole.display ?? pole.rank, active)` and the marker title likewise; selection stays on `rank`.
- `detail.js`: unchanged, it reads `pole.detail`.

- [ ] **Step 11.5: Tests**

```
router.test.mjs: i parses 1, 0, absent and rubbish; toUrl round-trips it; changedState restores it
data.test.mjs:   summaryKey; visiblePoles with islands on and off, display numbering, a superset
                 shorter than top, a unit whose first mainland pole is rank 4; regionLinks carry i
card.test.mjs:   the toggle renders with the right pressed state; the headline follows the mainland
                 summary when islands are off; chips are 1..10 while the selection is the overall rank;
                 a missing A_mainland renders the no-result line rather than throwing
ranking.test.mjs: the order changes when islands are off; a null mainland summary sorts last
i18n.test.mjs:   the three new keys exist in both languages
```

- [ ] **Step 11.6: Screenshots**

`dev/screenshots.mjs` gains one shot, `desktop-us-ak-mainland` at `/north-america/us-ak#s=A&i=0&l=en`: that unit's winner is on a 357 km2 island, so the shot shows the toggle off, a different pole 1 and ranks recomputed. The existing paths keep working unchanged, because a missing `i` means shown.

**Every image in the set moves in this task**, the seven desktop ones included, because the card gained a control row and the card is on desktop too. That is the first time a card change has moved the desktop set and it is expected here. Regenerate the whole set, open every image, and commit them with the code. Update `docs/screenshots/README.md`: the new row for `desktop-us-ak-mainland`, and the note that the desktop images are byte-identical run to run stays true with new hashes.

**Done looks like:** the toggle switches the card, the chips, the markers, the headline and the ranking without a refetch; the URL carries `i`; back and forward restore it; the region links and the home link carry it; twelve screenshots regenerated, read and committed; the node suite is green well above 66.

---

### Task 12: Docs, in the same commit as the code that caused them

**Files:**
- Modify: `docs/EUROPE_SPEC.md`, `docs/DECISIONS.md`, `docs/OVERVIEW.md`, `docs/diagrams/01-pipeline.md`, `docs/diagrams/02-site-data-flow.md`, `pipeline/README.md`

- [ ] **Step 12.1: The spec**

- **2.2**: the island floor on a unit's candidate cells; the territory mask stays the tool for an archipelago, the floor is the tool for a rock.
- **2.3**, the "Land" bullet: the same threshold as the water rule applied to land, and the limitation that a strait narrower than one coarse cell joins an island to the mainland because the land raster is all-touched.
- **3.2 stage 5**: replace "deduplicated at 10 km" with the distinct-area rule, its fraction, its floor, the ladder quantisation and its direction, the island gate, the island tag and the superset with its cap. This is the paragraph issue #56 calls "section 5 step 5".
- **3.2 stage 7** and **4.1**: detail rasters are keyed by the pole's coordinates, and what a rerun under an unchanged snapshot does and does not touch.
- **5.2**: the `i` hash key. **5.3** and **5.4**: the headline and the ranking follow the toggle. **5.5**: the pole's facts gain the island area, and the card gains the toggle. **5.8**: the measured first-screen bytes.
- **6 check 7**: "poles within a unit are at least `dedup_m` apart and no two of them are connected within the superlevel set at `area_col_fraction` times the lower of their distances, over land", with the sentence saying this is consistency against the shared implementation and that check 4 is where the rule is exercised independently.
- **3.3**: left for Task 17, which has the measured numbers.

- [ ] **Step 12.2: DECISIONS, six entries under a `## 2026-09-05` heading**

1. **The distinct-area rule replaces the fixed 10 km dedup.** `f = 0.5`, the floor kept as `dedup_m`, why it is scale free where a size-scaled floor is not (the option 1 numbers from #56: 57 km would skip real plateaus while 143 km would still tile the largest unit), the evidence from the published data (43 percent of unit-scenarios under 25 km mean nearest-neighbour distance, 71 percent with half their poles within 20 km of another), that winners are unchanged by construction, and the cost if wrong.
2. **The threshold ladder is part of the rule.** One percent steps quantised down, why down is the safe direction, and that validation shares the implementation and is therefore a consistency check.
3. **The island floor and the island tag.** `min_island_m2` at the water rule's 1 km2; the tag is unit-relative, the component holding the most of the unit's own cells being the untagged one; the all-touched strait limitation; the consequence the brief did not expect, that Europe's A headline changes because its winner is a rock; and the edge cases of risk 2 with the parked area-threshold alternative named as parked.
4. **The published set is a superset and the site filters it.** Ten mainland poles plus the islands above the tenth, capped at ten; why the alternative (two published lists, or a refetch on toggle) was not taken; what it costs in poles, rasters, objects and seconds; and that the toggle's URL key is always written so back and forward are honest.
5. **Detail rasters are keyed by the pole, not by its rank.** The live-site corruption this prevents, why deleting the prefix instead was rejected, and that the three validation objects are the only mutable keys under a snapshot prefix.
6. **The schemas gain fields without a version bump.** The argument from Task 8.2, and the compatibility rule the site's JavaScript follows.

- [ ] **Step 12.3: OVERVIEW, the pipeline README, the diagrams**

- `docs/OVERVIEW.md`: the "What works" pipeline and site bullets name the rules and the toggle; the region status lines are updated by Task 17.
- `pipeline/README.md`: the poles stage row says the search finds `top_n` distinct mainland areas plus the islands above them; the publish section says how a detail key is built and what a rerun replaces.
- `docs/diagrams/01-pipeline.md`: the poles stage's `prepare` cylinder gains `units_land.tif, units_water.tif`, the publish cylinder's detail path is renamed, and the "Reflects the code at" line is dated.
- `docs/diagrams/02-site-data-flow.md`: the hash state list gains `i`; the "Reflects the code at" line is dated.

- [ ] **Step 12.4: The pins**

```bash
cd pipeline && POLES_REPO_ROOT=$PWD/.. .venv/bin/python -m pytest -q tests/test_docs_pins.py
cd .. && pipeline/.venv/bin/python -c "import pathlib; d=(chr(0x2014), chr(0x2013)); bad=[str(p) for p in pathlib.Path('.').glob('**/*.md') if '.venv' not in str(p) and any(c in p.read_text(encoding='utf-8') for c in d)]; print(bad or 'clean')"
```

**Done looks like:** the spec states every rule where the code points at it, six dated DECISIONS entries, both diagrams match the code, the docs pins pass, and no en or em dash anywhere.

---

### Task 13: Europe, poles and validate (controller-executed)

From here to Task 16 no file under `pipeline/poles/` is edited: the running stages re-import from disk.

**Files:** none in the repository.

- [ ] **Step 13.1: Preflight**

```bash
git status --porcelain                                  # clean, or the publish records a null commit (#50)
cd pipeline && .venv/bin/python -m pytest -q            # green
colima stop
ls work/europe/2026-08-19/poles/roads | wc -l           # 116 tiles, the thing that must not be lost
```

- [ ] **Step 13.2: Delete only what has to be recomputed**

Under `work/europe/2026-08-19/poles/`, delete the `results/` directory and the four files `A.json`, `B.json`, `done.json` and `timing.json`. Keep everything else: `roads/`, `countries.fgb`, `land_idx.fgb`, `water_big.fgb`, `units.fgb` and its marker, `units.tif` and its marker, `units_low.tif`, `units_land.tif` and its marker, `units_water.tif` and its marker, and `units.json`.

`prepare` finds `units.tif.ok` and rebuilds nothing, so the result cache cannot go stale on it.

- [ ] **Step 13.3: The search**

```bash
cd pipeline && export PATH=/opt/homebrew/bin:$PATH && POLES_WORKERS=4 nohup caffeinate -i \
  .venv/bin/poles run europe --snapshot 2026-08-19 --work ../work --stage poles \
  > ../work/europe/2026-08-19/poles-run-areas.log 2>&1 &
```

Do not block the session on it. **Expected: 834 s becomes roughly 1,200 to 1,900 s.** If the log passes 3,000 s, stop and report rather than waiting: the likely cause is a retirement not firing, which is a code question.

Watch: `tail -n 40`, the finished result count (104 when done), the per-job refinement count against the old `timing.json`, and the pole count per job, which is now between 10 and 20.

- [ ] **Step 13.4: Validate**

Under `work/europe/2026-08-19/validate/`, delete `done.json`, `shifted_winners.json` and its marker, and the three report files (`report.json`, `report.html`, `contact-sheet.html`). Keep the shifted rasters and their markers (`dist_A_shift.tif`, `dist_B_shift.tif`, `roads_A_shift.tif`, `roads_B_shift.tif`, `units_shift.tif`, `units_shift_land.tif`, `units_shift_water.tif`), `frame_shift.json` and the `tiles/` cache.

Then the same command with `--stage validate`. **Expected: 1,429 s becomes roughly 2,100 to 2,800 s** (check 1 grows with the pole count, check 4 re-searches with the new rules, check 7 goes from under a second to minutes). Zero blocking failures is the gate. What to look at first if something fails:

- `distinct_areas` failing: the search and the check disagree, which with a shared implementation means the published file is not what the search produced.
- `separation` failing: the floor did not reach `Search`.
- `top_n_or_reason` failing: the quota counted islands as mainland, or the tag is wrong.
- `grid_shift` failing on a unit whose poles all moved: expected on plateaus and already non-blocking as a tie; a distance outside tolerance is real and blocks.

- [ ] **Step 13.5: Record**

Seconds per stage and per check, refinements, poles per unit split into mainland and island, the excluded list, the new A and B winners, and how many units returned fewer than `top_n` mainland poles with a reason. That last number is the one to watch: exhaustion is now normal for a small unit, and a large jump means the fraction is too high for this geography.

**Done looks like:** `poles/A.json` and `B.json` rebuilt as supersets, validation with zero blocking failures, both logs kept, and the numbers written down for Task 17.

---

### Task 14: Europe publish and the site data commit (controller-executed)

**Files:** `site/data/regions.json`, `site/data/manifest.json`, `site/data/europe/units.json`, `site/data/europe/units/*.json`

- [ ] **Step 14.1: Nothing is deleted from R2**

No prefix deletion, in either region, at any point in this task. New poles write new identity keys; poles that did not move rewrite the same bytes under the same key and are skipped on the size match, which is correct for them; the old rank-keyed objects stay untouched behind the live site on `main`. The only keys replaced are the three validation objects, which `mutable_keys` forces (Task 7). Record the bucket's object count and bytes before the run for Task 17's before and after.

- [ ] **Step 14.2: Publish, one region alone**

```bash
cd pipeline && export PATH=/opt/homebrew/bin:$PATH && POLES_WORKERS=4 \
  POLES_R2_ACCOUNT_ID=... POLES_R2_BUCKET=poles-data \
  POLES_R2_TOKEN_FILE=... POLES_R2_ACCESS_KEY_ID_FILE=... POLES_R2_SECRET_FILE=... \
  POLES_R2_BASE=https://data.polesofremoteness.com \
  nohup caffeinate -i .venv/bin/poles run europe --snapshot 2026-08-19 --work ../work --stage publish \
  > ../work/europe/2026-08-19/publish-run-areas.log 2>&1 &
```

The working tree must be clean or `_pipeline_commit` records `null` and the region has to be published again (#50). **Expected: roughly 700 to 1,400 s local** (the explore chain is adopted unchanged because `publish/inputs.json` still matches; `detail/published.json` does not, so `detail/` is rebuilt whole, which was 463 s for 909 rasters and is up to 926 s for up to 1,818) plus about two minutes of upload and verification.

- [ ] **Step 14.3: Commit before the second region**

```bash
git add site/data/regions.json site/data/manifest.json site/data/europe
git commit -m "europe: republished as a distinct-area superset with island tags (#56, #30)"
```

`sitedata.write_site` merges into the manifest on disk, so North America's files must be present and committed while this runs, which they are.

- [ ] **Step 14.4: Check the preview, and check production**

The push deploys the preview worker, which serves this branch's `site/data` and reads R2. Open a unit with island poles on the preview and confirm the detail overlay draws and the toggle works. Then open the **production** site and confirm its detail overlay still draws for a unit whose ranks moved: that is the proof that the identity keys did their job.

**Done looks like:** every Europe key verified over `data.polesofremoteness.com`, the manifest's Europe entry carrying a real pipeline commit, `site/data/europe/` committed, the preview showing the new data, production unchanged and correct, and the log recording how many detail rasters came out blank (the number that answers #30's second half).

---

### Task 15: North America, poles and validate (controller-executed)

The same shape as Task 13 with the region's own numbers. This is the long one and it runs overnight.

- [ ] **Step 15.1: Delete and run**

Under `work/north-america/2026-08-22/poles/`, delete the `results/` directory and the four files `A.json`, `B.json`, `done.json` and `timing.json`; keep `roads/` (214 tiles, 16.5 GB, about two hours to rebuild) and every `units.*` artefact. Then:

```bash
cd pipeline && export PATH=/opt/homebrew/bin:$PATH && POLES_WORKERS=2 nohup caffeinate -i \
  .venv/bin/poles run north-america --snapshot 2026-08-22 --work ../work --stage poles \
  > ../work/north-america/2026-08-22/poles-run-areas.log 2>&1 &
```

`POLES_WORKERS=2`: these units take 2 to 6.5 GB per worker today and the area index adds up to about 0.5 GB on the largest of them (a padded window of roughly 240 M cells is 480 MB of `uint16` levels plus a transient int32 label array over the cropped superlevel set). Watch the first big unit's RSS; if the machine swaps, `killall mediaanalysisd` first and drop to one worker for the tail rather than letting it thrash.

**Expected: 6,163 s becomes roughly 9,000 to 13,500 s (2.5 to 3.75 hours).** The archipelago units are the ones that overfind, and the island-cap retirement is what stops them refining every skerry; if a single job passes 6,000 s, capture its progress lines before deciding anything.

- [ ] **Step 15.2: Validate**

The same deletions as Step 13.4 under this region's `validate/`, then the same command with `POLES_WORKERS=2`. **Expected: 8,079 s becomes roughly 11,500 to 15,500 s (3.2 to 4.3 hours)**, check 4 being 6,748 s of it today and growing with the search and the superset.

- [ ] **Step 15.3: Record**

The same list as Step 13.5, plus which poles carry an island tag and which components they name. This is the evidence for risk 2 and it decides the Baffin, Zealand and Crete question.

**Done looks like:** both stages finished, zero blocking failures, the logs kept, and the numbers written down.

---

### Task 16: North America publish and the site data commit (controller-executed)

- [ ] **Step 16.1:** No deletion, same as Step 14.1. Record the object count and bytes first.
- [ ] **Step 16.2:** Publish with `POLES_WORKERS=4` (that pool is the detail render, not the search) and the five R2 variables plus `POLES_R2_BASE`. **Expected: roughly 1,800 to 3,300 s local** (the detail rebuild alone was 1,492 s for 1,262 rasters and is up to 2,984 s for up to 2,524) plus about three minutes of upload and verification. The tree must be clean and Europe's `site/data` must already be committed.
- [ ] **Step 16.3:** Commit `site/data/manifest.json`, `site/data/regions.json` and `site/data/north-america/`, then confirm the manifest holds both regions with two real pipeline commits.
- [ ] **Step 16.4:** Preview check and production check, as in Step 14.4.

**Done looks like:** both regions published under the new rules, `manifest.json` naming a non-null commit for each, `site/data/` committed, the preview correct and production still correct.

---

### Task 17: The measures, the merge, the prune, the close-out

**Files:**
- Create: `dev/bunching.py`, `dev/prune-r2.py`
- Modify: `docs/EUROPE_SPEC.md` (3.3 and 5.8), `docs/OVERVIEW.md`, `README.md`, `docs/LOG.md`, `docs/screenshots/*`

- [ ] **Step 17.1: The measures, before and after**

`dev/bunching.py` reads `site/data/<region>/units/*.json` and prints, per unit and scenario, the mean and minimum nearest-neighbour geodesic distance among the published poles, how many sit within 20 km of another, and the region totals issue #56 quotes. A second mode prints the island measures: how many poles carry `island_km2`, per region, with every tagged component named by unit, rank and area, and the mainland-only ranking beside the overall one. Run both on the **previous** `site/data` (from `git show <commit before Task 14>:site/data/...` into a temporary directory) and on the new one, so the tables are the same script on both datasets. Run the bunching measure with islands shown and with islands hidden, because #56's target is about what a reader sees.

The target from #56: no unit with all ten poles within 20 km of one another.

- [ ] **Step 17.2: Screenshots against the new data**

```bash
pipeline/.venv/bin/python dev/site-json.py --region europe --snapshot 2026-08-19
pipeline/.venv/bin/python dev/site-json.py --region north-america --snapshot 2026-08-22
NODE_PATH=~/personal/scratch/playwright-scratch/node_modules node dev/screenshots.mjs \
  --data dev/out/site --r2 work/europe/2026-08-19/publish --r2-prefix europe/2026-08-19 --out docs/screenshots
NODE_PATH=~/personal/scratch/playwright-scratch/node_modules node dev/screenshots.mjs \
  --data dev/out/site --r2 work/north-america/2026-08-22/publish --r2-prefix north-america/2026-08-22 \
  --out docs/screenshots --only desktop-us-ak
# and the same again with --only desktop-us-ak-mainland
```

Every image moves again, this time because the data moved. Read them for four things: the About sentence in both languages and at both viewports, the island row on the card whose unit's winner is on a 357 km2 island, the toggle switching that card to a different pole 1 in `desktop-us-ak-mainland`, and the numbered markers of the Lithuanian view being spread rather than clustered, which is the whole point of the change made visible.

- [ ] **Step 17.3: The numbers in the docs**

- `docs/EUROPE_SPEC.md` 3.3: both regions' poles, validate and publish rows re-measured, with refinement totals, the slowest job, per-check seconds, and the pole counts split into mainland and island. 5.8: the measured first-screen bytes. Every number run or grepped, none carried over by eye.
- `docs/OVERVIEW.md`: both region status lines, the pipeline and site bullets, and a line saying what changed and when.
- `README.md`: the headline table. **Europe's A row almost certainly changes** (risk 1). Re-read it against `site/data/europe/units.json` rather than editing from memory, and check whether `docs/hero.png`'s caption still matches its unit.
- `docs/LOG.md`: one entry, the rules changed and both regions republished.

- [ ] **Step 17.4: Merge, deploy, verify**

Merge to `main` only after the owner has seen the headline change of risk 1 and ruled on the tagged-component list of risk 2. Then push, watch the run to conclusion (`gh run watch`), and check the live site with a cache-buster: the About dialog in both languages, a unit whose pole is on an island, the toggle on and off with the ranking following it, and one unit's detail overlay at zoom 13.

- [ ] **Step 17.5: The prune, after the production verify and not before**

`dev/prune-r2.py`, boto3 in the venv, **dry run by default**: for each region it lists `<region>/<snapshot>/`, collects every `detail` value from the committed `site/data/<region>/units/*.json` for both scenarios and every pole, and reports every `detail/` key the documents do not reference. Those are the rank-keyed objects the old documents used plus the rasters of poles that no longer exist. It never touches `A.pmtiles`, `B.pmtiles` or `validation/`. Read the list, check that its size matches the expectation (roughly the old object counts, 1,818 for Europe and 2,524 for North America), then run it for real and log every key it deletes into the work directory.

This runs **after** the merge and the production verify, because until that moment production is still serving the old documents and the old keys are live data. Record the object count and bytes before and after, per region and for the bucket, so the free-tier headroom is visible.

Then correct **issue #57**: its body records the prefix deletion as the adopted workaround, which this plan overruled for exactly the reason it was unsafe. Add a comment saying identity-keyed rasters replaced it, that `force_keys` covers the three mutable objects, and that the durable reconciliation and the content-hash skip test are still open.

- [ ] **Step 17.6: The issues**

- **#56**: the before and after bunching tables with islands shown and hidden, the fraction and floor that shipped, the search and validate timings for both regions. Close it if the target is met; if a unit still has ten poles inside 20 km, say which and why and leave it open.
- **#30**: the island floor as shipped, how many poles it removed and from which units, the new blank detail raster count (zero is the goal, since a pole on a component of at least 1 km2 covers at least 400 pixels of a 50 m raster), the island tag count and the full tagged list, the toggle as shipped, the Lithuanian strings the owner picked, and the risk 2 edge cases with the parked area-threshold alternative. Close it if the blank count is zero and the owner has ruled.
- **#57**: the comment above.

**Done looks like:** both measures posted with before and after, twelve screenshots regenerated and read, the spec's 3.3 and 5.8 carrying measured numbers, `README.md` telling the truth about the new winners, the live site serving the new data with the toggle working, the bucket pruned with its before and after counts recorded, and #56, #30 and #57 answered with evidence.

---

## Cost analysis

**Search.** Only a unit that has island poles above its `top_n`-th mainland pole accepts more candidates, and it accepts at most `top_n` of them. A landlocked unit is bit-for-bit unaffected by the superset. The descent that the distinct-area rule forces is the larger of the two effects and it is bounded by the two retirements: the component retirement kills a plateau in one operation, and the island-cap retirement kills every remaining island cell in one more. Europe 834 s becomes an expected 1,200 to 1,900 s; North America 6,163 s becomes 9,000 to 13,500 s.

**Validation check 1** rechecks every published pole geodesically, so it scales with the pole count: at most 2x, and only in units that overfind. Europe 375 s for 918 poles becomes at most 750 s for at most 1,818; North America 947 s for 1,266 becomes at most 1,894 s for at most 2,524. Check 4 re-runs the whole search and grows with it. Check 7 goes from under a second to minutes because of its labellings.

**Detail rasters:** one per published pole, so at most 2x. Europe 909 rasters and 463 s become at most 1,818 and 926 s; North America 1,262 and 1,492 s become at most 2,524 and 2,984 s.

**R2 objects and bytes.** Two objects per raster, plus two archives and three validation files per region. Today: Europe 1,823 keys and 268,576,827 bytes (detail 909 rasters, 13,449,861 bytes), North America 2,529 keys and 436,256,747 bytes (detail 1,262 rasters, 16,018,638 bytes), the bucket 4,352 keys and 704,833,574 bytes, which is 6.6 percent of the free tier's 10 GB. Nothing is deleted until Task 17, so the bucket peaks at the sum of the old and the new sets: at most 4,352 + 3,636 + 5,048 = 13,036 keys and about 764 MB, 7.6 percent of the free tier. After the prune, at most 8,694 keys and about 723 MB. Class A operations for a full republish are about 8,700 uploads and two listings against a million a month; Class B about 8,700 verification probes against ten million. Neither is close.

**Site JSON against the 256 KB first-screen budget.** The first screen measures 97,973 compressed bytes today, of which the data is `regions.json` 932, `europe/units.json` 5,507 and the opening unit document 1,674. `units.json` gains two small summary objects per unit, about 7 KB raw for 52 units and roughly 1.5 KB compressed, because the repeated keys compress well. The opening unit document gains `island_km2` per pole and one `mainland` object per scenario; for a unit that does not overfind that is a few hundred bytes. A worst-case archipelago unit doubles its pole list: the largest today is 7,398 raw and 953 compressed, so at most about 1.9 KB compressed. The worst case is therefore under 102 KB against a budget of 256 KB, roughly 60 percent headroom, and the CI budget step needs no change. Measure it again in Task 17 and put the number in the spec's 5.8.

---

## Wall clock, all in

| Stage | Europe today | Europe expected | North America today | North America expected |
|---|---|---|---|---|
| poles | 834 s | 1,200 to 1,900 s | 6,163 s | 9,000 to 13,500 s |
| validate | 1,429 s | 2,100 to 2,800 s | 8,079 s | 11,500 to 15,500 s |
| publish | 962 s local | 700 to 1,400 s local plus 120 s upload | 2,569 s local | 1,800 to 3,300 s local plus 180 s upload |

About 1.75 hours for Europe and about 9 hours for North America, all of it unattended with `caffeinate` and colima stopped. The publish figures stay near the originals because the explore archives are adopted unchanged (the grid did not move) and only the detail rasters are rebuilt, but the superset can double that rebuild.

---

## Legend

Every task ends green: `cd pipeline && .venv/bin/python -m pytest -q` and `node --test 'dev/tests/*.test.mjs'` from the repository root. A task that changes behaviour writes its test first and watches it fail for the stated reason. A task that touches the site checks the screenshots against the baseline above, except Tasks 11 and 17, which replace it.

# Eight directions

Each direction is a complete visual world, joined to how the map, the card, the ranking and the phone sheet behave in it. The product (PRODUCT.md) supplies every fact; the world supplies form. The category default this list refuses: a satellite map with rounded white floating cards and one warm accent (the current site), and its predictable opposite, a near-black "dark map app" with glowing neon edges.

Seed key 09bac60a (impeccable concept-seed, scope direction, mode experience). Ordering is by resonance with the audience: map people, outdoor people, curious visitors from a LinkedIn link, landing on their own country.

---

## 01-star-atlas: "Remoteness is darkness" (the roll's assignment)

THESIS: The farther from any road, the darker and quieter the land, so the site becomes a celestial atlas plate: poles are stars, their distance is their magnitude, the ranking is a star catalogue. Refuses the white-card map app.

OWN-WORLD: Night. The satellite imagery is taken down to a deep blue-black night plate with a CSS filter on `.basemap` (desaturate, darken, cool tint) so land reads as dim relief. The remoteness bands glow in pale silver-blue to warm starlight gold as distance rises (the most remote land is the brightest: the quiet places shine). Markers are drawn stars (authored SVG, 4 or 5 point with fine rays, or a filled disc with a halo ring) whose size steps with the pole's rank or distance like stellar magnitude; the number sits beside the star in small caps like a Bayer letter, not inside a circle. Hairline graticule feeling in panels, fine rules, catalogue tables with tabular figures. Type: a classic astronomical-atlas voice, for example a sharp transitional or didone serif for names and titles (not the banned list; consider Bodoni Moda, Libre Caslon Display, Gloock, or similar) with a precise small sans or old-style figures for data.

LIGHT SCHEME: the printed atlas plate (think Norton's Star Atlas or Bečvář's Atlas Coeli): white paper, black and deep-blue ink, stars as black discs; the basemap filtered to a pale engraved grey. Dark scheme is the night sky. Both must be designed.

FIRST VIEWPORT (desktop): the map is the plate and fills most of the screen. The card is a catalogue entry set in the plate's margin (top left): the unit name large in the serif, the distance as the headline number, then the scenario switch as a two-state "filter" control, the islands toggle, and the pole facts as a catalogue record. The ranking is the star catalogue on the right: rank, name, magnitude in km, the other scenario as a faint second column; the current unit's row marked. Header: the site title set like an atlas title, small, with region and language controls as quiet text controls.

SIGNATURE: the stars. Selecting a pole brightens its star (a slow halo bloom, 300 to 600 ms, ease-out) and dims the others slightly.

PHONE: the sheet is a dark catalogue drawer; its closed face shows the unit and the magnitude.

RAISES (from declined challengers): from the night instrument panel, every reading shows its value and its comparison: the ranking row pairs A and B as two aligned figures rather than a main and a footnote. From the transit diagram, fixed-size label discipline: marker numbers and labels never scale with zoom and never collide with the star glyph.

RISK: dark imagery hides the satellite detail people use to judge the terrain; mitigate by keeping the Map/Satellite switch and letting zoom 12+ lift the night filter partly so the detail overlay stays readable.

---

## 02-orienteering: "The control description sheet" (IMPECCABLE'S PICK)

THESIS: Orienteering maps are the one map genre whose whole point is finding a precise point in roadless terrain, and Lithuanian, Nordic and Baltic visitors know them by heart. The poles become control points in the IOF overprint; the card becomes a control description sheet. Refuses the generic card.

OWN-WORLD: ISOM print on white. Overprint purple-magenta (the IOF overprint colour, roughly #C8288C to #A626A4 range; choose one) for everything the site adds: control circles, numbers, the selected state, focus rings. Markers: hollow magenta circles (about 30px, 2.5px stroke, NO fill) with the control number set beside the circle, upright bold sans, magenta. The selected pole gets the finish double circle. The remoteness bands in the ISOM vegetation greens and yellows logic: pale yellow (open) for the nearest band through light, medium, dark green for the most remote (the "fight" green), so the layer reads like an orienteering map; legend still in km. Type: the plain, bold, slightly condensed sans of orienteering maps and IOF sheets (Arial/Helvetica lineage but sourced: for example Archivo Narrow, Barlow Condensed/Semi Condensed, Roboto Condensed; not the banned list). Black ink rules, square corners, a strict grid. Tabular figures everywhere.

CARD: a control description sheet. The real IOF sheet is an 8-column table (A to H) of boxes. Make the pole facts that table: a header row with the event (unit name) and the course (scenario A or B), then one row per fact in boxed cells: control number, distance, nearest road, nearest settlement, island area when present, coordinates, a Maps link. The ten poles are ten numbered boxes (the chips) in a row. Scenario and islands controls are square black-bordered toggles.

RANKING: an orienteering results list: position, name, "time" column = distance in km with the other scenario as the split column, monospaced alignment by tabular figures, the current unit highlighted in magenta tint.

HEADER: a thin black band like the map's title strip with the site title, region and language as boxed toggles.

SIGNATURE: selecting a pole draws its control circle in (stroke-dashoffset animation, about 400 ms) and flashes the corresponding description row.

DARK: the same sheet under a head torch: near-black ground, overprint turns a brighter magenta-pink, greens deepen; designed, not inverted.

RAISE (from the declined brick instruction book): the stud-grid module discipline: every panel, row and box snaps to one module (for example 8px) and one line weight.

RISK: familiar to map people, possibly opaque to casual visitors who never saw an orienteering map; the magenta on satellite must stay legible (test on forest and on snow).

---

## 03-sea-chart: "Depth from the road"

THESIS: Treat the road network as the coastline and remoteness as depth: the land is sounded like a nautical chart, in chart blues that deepen away from every road, and each pole is the deepest sounding. Refuses the warm-accent card map.

OWN-WORLD: an Admiralty or NOAA chart. Chart buff for panels and paper (a warm light buff, not cream-and-serif editorial: the chart's own buff with blue and magenta inks), chart blues for the remoteness bands (the nearest band a very pale blue, deepening through to a strong blue for 50 km; alpha tuned so the satellite still shows), magenta for notes, cautions and the selected state (charts use magenta for exactly that), black for text. The satellite basemap can be desaturated toward a sepia buff with a CSS filter so the blue soundings dominate; decide by what looks best, keep the switch. Markers: the pole as a sounding figure: the distance written as a chart sounding (whole km large with the decimal subscript, for example 3 with 43 small and lowered) with a small circled dot, the pole number small beside; selected pole ringed in magenta. Type: chart lettering: an upright Roman for land names and an italic for the soundings and water-ish readings; choose a sturdy classic face (for example Libre Caslon Text, Spectral, EB Garamond, Old Standard TT; not the banned list) plus a small clean sans for controls if needed.

CARD: the chart title block (the cartouche): unit name in spaced caps, "Soundings in kilometres from the nearest drivable way" as the chart's subtitle (write it in both languages), the scale line replaced by the rank, then the pole facts as the chart's NOTES block, numbered.

RANKING: set like a tide table or a list of lights: ruled columns, small caps headings, tabular figures.

HEADER: a chart margin strip; a compass rose (authored SVG, fine lines) may appear once, perhaps as the About button or in the legend.

SIGNATURE: the legend as a depth scale bar (six stepped blue blocks with the km figures) and the readout written as a sounding.

DARK: a night-bridge chart display (ECDIS night palette): deep blue-black, dimmed chart colours, red-orange text for night vision is optional but the world supports it.

RAISE (from the declined screenprint challenger): its total palette commitment: blue owns whole regions of the page, not just accents.

RISK: blue on land may read as water at a glance; the legend and headline must make "distance from the road" explicit immediately.

---

## 04-park-brochure: "The Unigrid"

THESIS: Massimo Vignelli's Unigrid system for US National Park Service brochures is how North Americans and Europeans know wilderness information design: a black title band, a strict modular grid, bold sans, maps as the hero. The site becomes one of those brochures. Refuses soft floating cards.

OWN-WORLD: a heavy black band across the top (about 72 to 96px on desktop) with the title set large in white bold sans, left aligned, and the region/language controls inside the band as white text toggles. Below: the map as the brochure map panel. The card and ranking are brochure panels on a strict grid: white (light) paper, black type, generous leading, section headings bold, facts in two columns, thin black rules between modules, no rounded corners, no shadows (a brochure is flat). The remoteness bands in the NPS map palette logic: restrained greens and tans of park maps, from pale sage to deep forest green (or an earthy ochre-to-brown ramp), tuned over satellite. Markers: black squares or circles with white numerals, like NPS map point symbols; selected pole in the band colour inverted. Type: a strong neo-grotesk used at real weight (Helvetica lineage but sourced from Google Fonts: for example Archivo, Hanken Grotesk, Schibsted Grotesk, Public Sans, Work Sans; avoid the banned list). One accent is allowed: the NPS arrowhead brown (a deep brown) used sparingly for the primary button or the selected state. Do not use the NPS arrowhead logo or name, only the design grammar.

FIRST VIEWPORT (desktop): black band full width; below it a grid: map across roughly two thirds, a right column of stacked panels (the card on top as the "unit" panel with a big distance figure, the ranking below it), both on the same module.

SIGNATURE: the black band carries the live headline: "Lithuania. 3.43 km from any drivable way." updates when the unit or scenario changes (use existing i18n strings or add new ones in both languages).

DARK: the band stays black; the paper becomes a dark charcoal with off-white type; designed, not inverted.

RAISE (from the declined transit diagram): the discipline of fixed label sizes and one angle system: every rule horizontal or vertical, every label at one of three sizes.

RISK: strong association with US parks might feel off for Europe; it is also the most conservative of the bold options.

---

## 05-gps-handheld: "The handheld unit"

THESIS: The tool people actually carry into roadless terrain is a handheld GPS with a transflective monochrome screen and hard-labelled soft keys. The whole site becomes that device's screen: the map page, the data-field page ("DIST TO ROAD"), the waypoint list. Refuses every web-app card convention.

OWN-WORLD: a transflective LCD: the page ground is the grey-green LCD (for example #B7C2A5 range), ink is the dark LCD segment colour (near-black blue-green), with one or two grey levels. The satellite basemap goes through a CSS filter (grayscale, contrast up, a green-grey tint via sepia and hue-rotate, maybe multiply) so the map looks like it is on the unit's screen; the remoteness bands in 4 to 6 dark LCD tints plus a dither feel if achievable (a subtle repeating pattern overlay is acceptable). Type: a pixel or LCD face for data fields and labels (for example Silkscreen, Pixelify Sans, VT323, Micro 5, Handjet; pick one that is readable at 13 to 16px) and a compact, plain sans for the longer About text so it stays readable. Data fields as the device's boxed fields: a label in small caps above a big number ("DIST TO ROAD 3.43 km", "NEAREST RD track", "WAYPT 1/10"). Buttons as hard key labels in brackets or boxed, all caps. A status bar at the top with a small battery and satellite-bars glyph (authored SVG, pixel style), the unit name and the time or the snapshot date.

FIRST VIEWPORT (desktop): a three-pane device layout: the map page large in the middle, a data-fields page on the left (the card), the waypoint list (the ranking, as "WAYPOINTS" or "POLES LIST") on the right. No device frame drawn around it; the screen IS the viewport. The pole markers are the device's waypoint flags (pixel flag glyph with the number).

SIGNATURE: a compass or a distance "arrow" field in the data page, and a blinking cursor or inverse-video row for the selected pole in the list.

DARK: the backlight mode: dark ground with the LCD ink glowing a cool green or amber; designed, not inverted.

RAISE (from the declined algorave challenger): upcoming changes are visible before they happen: hovering a waypoint row previews its position on the map (a dotted crosshair) before a click commits.

RISK: the most gimmicky of the set; pixel type at length hurts reading, so the About text must use the plain face; the filtered satellite loses colour cues.

---

## 06-screenprint: "Two passes" (fused challenger: screenprint transparent overlap)

THESIS: The two readings of remoteness (A with tracks, B public roads only) are two ink passes of one screenprint: switch the scenario and the other pass is pulled. The site is a hand-pulled poster: flat translucent spot inks over paper, stencil caps, registration marks. Refuses corporate map UI.

OWN-WORLD: two or three translucent spot inks, for example fluorescent pink and a medium blue (or amber and teal); choose a pair with real character. The remoteness layer is printed in scenario A's ink (for example the bands as increasing density of one ink) and scenario B's ink when B is on; use `mix-blend-mode: multiply` on the data layer pane over a desaturated, slightly lightened satellite basemap (CSS filter on `.basemap`) so the ink sits on the image like print. Panels are paper: an off-white stock with a faint paper grain (an inline SVG noise filter as a background is fine, keep it subtle), flat ink rectangles, no shadows, slight misregistration on the headline (a second copy of the title offset 2px in the other ink, 60% opacity) as the signature. Registration crosses in the corners of the card. Type: stencil or poster caps for the title and headline (for example Big Shoulders Stencil, Stardos Stencil, Allerta Stencil, or a heavy condensed poster grotesk like Anton or Bebas Neue), a clean readable sans for body and facts.

FIRST VIEWPORT (desktop): the title huge and poster-like across the top left, overprinting the map edge; the card as a printed ticket; the ranking as a printed list on the right with big rank numerals in ink.

Markers: flat ink discs with knocked-out white numerals; selected pole gets the second ink overprinted, visibly offset.

SIGNATURE: the scenario switch animates the pass change: the old ink fades as the new one slides in 3 to 6px out of register then settles (about 400 ms).

DARK: black paper printed with light inks (a real screenprint on black stock); designed.

RISK: playful energy vs the product's dry, precise voice; the multiply blend may muddy the satellite in forests.

---

## 07-survey-sheet: "The sheet and its collar"

THESIS: Every national topographic series (Swiss, Nordic, Ordnance Survey) frames its map with a collar: graticule ticks and coordinates around the edge, a sheet title, a legend and an index of adjoining sheets in the margin. The browser window becomes one sheet of that series, with a live collar. Refuses floating cards over a borderless map.

OWN-WORLD: Swiss-school cartography (Imhof): calm, exact, a slightly cool paper white, black and a single deep red or deep blue as the series colour, the remoteness bands in the refined hypsometric tints of a Swiss map (pale yellow-green through ochre to a warm violet-brown, or a violet-grey ramp), fine 0.5 to 1px black rules. The map sits inside a margin (about 28 to 36px on desktop) that is the collar: coordinate ticks every graticule interval along all four edges with small numeric labels, computed live from the map bounds and updated on move (the signature; write it as a small module that listens to Leaflet `move` events, graceful at any zoom, round intervals like 1, 0.5, 0.25, 0.1 degree depending on zoom). Outside the collar: the sheet title block (the unit, "Sheet 39 of 52" style using the rank), the legend as a proper map key with the band swatches and "km from the nearest drivable way", the ranking as the index of sheets. Type: a precise, slightly technical sans of Swiss cartography (for example Frutiger lineage sourced: Hind, Mukta, Barlow, Source Sans 3 is fine; or Univers-like: Nunito Sans no; choose something with character but restraint, not the banned list), small caps and tabular figures for coordinates.

Markers: small black-ringed triangles (trig-point style) or circles with the number set beside in the series colour; the selected pole in the series colour.

FIRST VIEWPORT (desktop): the sheet with its collar takes most of the width; a right margin column holds the title block, key and index of sheets.

DARK: the sheet under a map light: a warm dark grey sheet, the collar ticks in light ink, designed.

PHONE: the collar becomes ticks on the left and bottom only; the margin column becomes the bottom sheet.

RAISE (from the declined instrument panel): every gauge shows trend as well as value: the readout pill shows the tapped class and where it sits in the key (the key swatch highlights).

RISK: the collar costs screen area; on small laptops the map gets a little smaller.

---

## 08-canon: "Best-in-class map app, played straight" (the standing exit)

THESIS: The category standard at full craft: what Apple Maps, Felt or Strava would ship for this data. No world metaphor, no irony; clarity and finish are the whole point.

OWN-WORLD: refined neutral surfaces (light: near-white panels with subtle translucency is NOT allowed as decoration; use solid surfaces with soft real shadows), one confident accent colour picked for the data (the remoteness bands as a single perceptual ramp, for example a viridis-like or a cool teal-to-deep-indigo ramp, legible on satellite), a modern workhorse UI sans sourced from Google Fonts (for example Geist, Figtree, Onest, Manrope, Albert Sans; not the banned list) with tabular numerals. Big confident numbers: the distance is the hero figure in the card. Rounded 12 to 16px radii, consistent 4/8px spacing, crisp icons (authored SVG) on every control (layers, locate, ranking, info, language), a floating search-like pill for the unit name at top left that opens the ranking as a searchable list (a simple filter input over the units is allowed as the one new interaction, since the ranking has 52 to 64 entries).

FIRST VIEWPORT (desktop): full-bleed map under a slim floating top bar; a left floating panel with the unit, its hero distance, rank, scenario segmented control, islands switch, the pole selector as a horizontal strip, facts in a clean list; the ranking as a second floating panel or a tab of the same panel; map controls as a vertical icon stack on the right; the legend as a compact horizontal gradient scale with ticks.

PHONE: Apple Maps style bottom sheet with a real grabber, three detents, the unit and hero distance on the closed face.

DARK: a proper dark mode with elevated surfaces.

RISK: it is the familiar choice; it will look like many other good map apps. That is its point.

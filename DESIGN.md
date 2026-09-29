---
name: Poles of remoteness
description: The sea chart. Roads are the coastline, remoteness is depth, each pole is the deepest sounding.
colors:
  paper: "#f2e7c9"
  paper-2: "#e8dab1"
  sea: "#d3e5ec"
  sea-2: "#bcd6e2"
  ink: "#17160f"
  ink-2: "#4a4433"
  ink-sea: "#1f3a4c"
  blue: "#0e4678"
  blue-ink: "#0c3f6d"
  magenta: "#9c1569"
  magenta-soft: "rgba(156, 21, 105, .11)"
  hair: "rgba(23, 22, 15, .2)"
  hair-strong: "rgba(23, 22, 15, .55)"
  depth-ink: "#15592f"
  band-1: "#d1db9f"
  band-2: "#94b166"
  band-3: "#5d8b3d"
  band-4: "#337031"
  band-5: "#15592b"
  band-6: "#004021"
  edge: "#8b8574"
typography:
  display:
    fontFamily: "Libre Caslon Text, Iowan Old Style, Georgia, serif"
    fontSize: "21px"
    fontWeight: 400
    lineHeight: 1.15
    letterSpacing: ".22em"
  headline:
    fontFamily: "Libre Caslon Text, Iowan Old Style, Georgia, serif"
    fontSize: "20px"
    fontWeight: 400
    lineHeight: 1.2
    letterSpacing: ".18em"
  title:
    fontFamily: "Libre Caslon Text, Iowan Old Style, Georgia, serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.1
    letterSpacing: ".2em"
  body-serif:
    fontFamily: "Libre Caslon Text, Iowan Old Style, Georgia, serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.4
  body:
    fontFamily: "Libre Franklin, Franklin Gothic Book, Helvetica Neue, Arial, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: "tnum"
  sounding:
    fontFamily: "Libre Caslon Text, Iowan Old Style, Georgia, serif"
    fontSize: "19px"
    fontWeight: 400
    lineHeight: 1
  note-italic:
    fontFamily: "Libre Caslon Text, Iowan Old Style, Georgia, serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.35
  label:
    fontFamily: "Libre Franklin, Franklin Gothic Book, Helvetica Neue, Arial, sans-serif"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: ".08em"
rounded:
  none: "0px"
  r: "2px"
spacing:
  xs: "4px"
  sm: "6px"
  md: "8px"
  lg: "12px"
  xl: "14px"
  xxl: "20px"
components:
  seg-button:
    textColor: "{colors.ink-2}"
    typography: "{typography.body}"
    rounded: "{rounded.r}"
    padding: "6px 12px"
  seg-button-on:
    backgroundColor: "{colors.magenta-soft}"
    textColor: "{colors.magenta}"
  button-primary:
    backgroundColor: "{colors.blue}"
    textColor: "{colors.paper}"
    rounded: "{rounded.r}"
    padding: "6px 11px"
  button-primary-hover:
    backgroundColor: "{colors.blue-ink}"
  button-ghost:
    textColor: "{colors.blue-ink}"
    rounded: "{rounded.r}"
    padding: "6px 11px"
  button-ghost-hover:
    backgroundColor: "{colors.sea}"
  chip:
    textColor: "{colors.ink}"
    rounded: "{rounded.r}"
    height: "25px"
    padding: "0 6px"
  chip-on:
    backgroundColor: "{colors.magenta}"
    textColor: "{colors.paper}"
  card:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.none}"
    padding: "18px 20px 16px"
    width: "384px"
  ranking-panel:
    backgroundColor: "{colors.sea}"
    textColor: "{colors.ink}"
    width: "372px"
  ranking-row-current:
    backgroundColor: "{colors.magenta-soft}"
    textColor: "{colors.magenta}"
  scale:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.r}"
    padding: "8px 12px"
  readout:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.r}"
    padding: "6px 12px 8px"
---

# Design System: Poles of remoteness

## Overview

**Creative North Star: "Depth from the road"**

The site is a nautical chart laid over land. The road network plays the coastline and distance from it plays depth: the ground is sounded in six stepped bands that deepen away from every drivable way, and each pole is written as the chart's deepest sounding. Panels are chart buff paper with black lettering; chart blue draws the controls and links; magenta, as on a real chart, marks notes, cautions and the current selection. The night scheme is a bridge display (ECDIS night palette): blue-black ground, dimmed buff lettering, a ramp that brightens with distance.

One owner amendment departs from the Admiralty palette: the depth bands are a park-map green, not chart blue, because blue on land read as water or ice. Blue therefore owns the ranking's water tint and the controls, never the land. The satellite basemap stays the default and is desaturated toward buff so the green soundings lead.

Density is a working chart's: ruled, numbered, small type, tabular figures, no decoration that does not carry a reading.

**Key Characteristics:**
- Chart grammar throughout: title block (cartouche), numbered notes, soundings, depth scale, graduated neatline, one compass rose.
- Upright roman capitals for names, italic for soundings and anything that reads a measurement.
- Square, ruled forms: 2px corners on controls, 0 on the framed sheets.
- Light soft shadow only where a sheet floats over the map.
- Every colour is a CSS custom property on `:root` with a `prefers-color-scheme: dark` counterpart; the map layer reads the band tokens through `js/palette.js`.

## Colors

Buff paper, black ink, chart blue for action, magenta for selection, a green depth ramp on the land.

### Primary
- **Chart Blue Ink** (blue, blue-ink): filled primary buttons, ghost button lettering, links, scrollbar thumbs. Never on the land layer.

### Secondary
- **Chart Magenta** (magenta, magenta-soft): the selected state everywhere (pressed segment, current ranking row, active chip, the active pole's ring, dot and number box), note numerals, the pole section title, About subheadings, focus rings, text selection, the compass rose.

### Tertiary
- **Depth Ramp** (band-1 to band-6, stops 1, 2.5, 5, 10, 20, 50 km): green-tan by the road to forest green far from it, OKLCH hue 116 to 155, lightness .87 to .325. Each band has its own alpha (`--band-alpha-1..6`: .50, .58, .66, .72, .76, .80 by day; .62 to .80 at night) so the near bands let the ground show. At night the ramp inverts: muted sage (#667c50) brightening to #80d994. The unmeasured edge is warm grey (edge) at alpha .35.
- **Depth Ink** (depth-ink): lettering that names or quotes a sounding: the chart subtitle, the readout figure, the phone summary distance. The ramp's deep end, dark enough for text on buff.

### Neutral
- **Chart Buff** (paper) and **Deeper Buff** (paper-2): every panel, the header strip, hover fills on buff controls. Also the marker halo.
- **Shallow Water** (sea) and **Sounded Water** (sea-2): the ranking panel ("tide table") and its row hover; also the map's loading background and ghost button hover.
- **Lettering Black** (ink), **Faded Lettering** (ink-2), **Sea Lettering** (ink-sea): primary text, secondary text, secondary text set on the sea tint.
- **Hairline** (hair) and **Strong Hairline** (hair-strong): dividers between rows and segments; control borders.

### Named Rules
**The Land Is Green Rule.** The remoteness layer is the green ramp only. Blue on land reads as water; blue belongs to the controls and the ranking's water.

**The Magenta Means Selected Rule.** Magenta marks the current thing and the chart's notes, nothing else. Never a decorative accent, never a second call to action.

**The Tokens Drive The Map Rule.** Band colours and alphas are set only in `:root` and its dark block; `js/palette.js` reads them, so the legend and the tiles recolour together.

## Typography

**Display Font:** Libre Caslon Text 400 and 400 italic (with Iowan Old Style, Georgia)
**Body Font:** Libre Franklin variable (with Franklin Gothic Book, Helvetica Neue, Arial)

**Character:** Chart lettering: a sturdy Caslon roman in spaced capitals for names and titles, its italic for soundings and readings, and a small clean Franklin for controls and data labels. All six woff2 files are self-hosted, Latin and Latin Extended subsets.

### Hierarchy
- **Display** (400, 21px, 1.15, .22em, uppercase): the unit name in the cartouche.
- **Headline** (400, 20px, 1.2, .18em, uppercase): the About dialog title.
- **Title** (400, 16px, 1.1, .2em, uppercase): the site title in the header. Smaller section titles (12px, .18 to .2em, uppercase, magenta) head the pole notes and About sections.
- **Body serif** (400, 15px, 1.4 to 1.55): the card headline sentence, About paragraphs (max 68ch), ranking unit names at 14px.
- **Body** (Franklin 400, 14px, 1.45, tabular figures on `body`): controls (13px), note values (13px).
- **Sounding** (Caslon italic 400, 19px on markers, 26px in the readout, 15 to 16px in the ranking and notes): whole kilometres full size, the hundredths at .62em lowered .34em, no visible separator (a visually hidden one is kept for screen readers).
- **Note italic** (Caslon italic 400, 12 to 14px): the header subtitle, chart subtitle, scale caption, hints, the About button.
- **Label** (Franklin 400, 11px, .08em, uppercase, ink-2): note keys (DISTANCE, NEAREST ROAD).

### Named Rules
**The Drawn Weight Rule.** Caslon exists in 400 only; `font-synthesis-weight: none` is set on `html`. Titles are regular roman capitals, as chart titles are. Do not add a Caslon bold: the 700 was cut to keep the first screen under its 256 KB budget.

**The Italic Measures Rule.** A number that is a distance is set in Caslon italic; names are upright.

## Layout

Fixed header strip (62px desktop, 58px phone), the map below it. On desktop the ranking panel is a fixed 372px column at the right; the card floats top left of the map (14px inset, max 384px wide); the map controls (basemap switch, depth scale, readout) stack bottom right of the map, 14px left of the panel and 30px up. A unit is fitted into the map area right of the measured card and clear of the legend.

Phone (<=720px) rules live only in the one media query at the end of `app.css`; desktop rendering must not change when phone rules change. On phones the map fills the screen, the card and ranking move into a bottom sheet (collapsed to a measured `--sheet-h`, half at 48%, full), the header subtitle and About label hide, and only the selected pole writes its sounding.

Spacing is small and irregular in the chart's manner: 4, 6, 8, 12, 14, 16, 20px, with 18 to 20px inner padding on the framed sheets.

## Elevation & Depth

Depth lives in the map, not in the chrome. The chrome is flat paper; only pieces that float over the imagery (card, scale, readout, About, zoom bar) carry one soft, low shadow.

### Shadow Vocabulary
- **Floating sheet** (`box-shadow: 0 1px 2px rgba(40, 32, 10, .16), 0 3px 8px rgba(40, 32, 10, .14)`; night `0 1px 2px rgba(0,0,0,.6), 0 3px 9px rgba(0,0,0,.45)`): any paper piece over the map.
- **Phone sheet** (`box-shadow: 0 -2px 8px rgba(20, 16, 6, .2)`): the bottom sheet's top edge.
- **Marker halo** (eight 1 to 1.5px text-shadows in `--halo`): lettering on imagery reads as chart lettering knocked out of the ground.

## Shapes

Square and ruled. Controls take a 2px corner; the framed sheets (card, About) have 0 radius with a double rule: a 1px ink border plus a 1px ink outline inset 5 to 6px. The **graduated neatline**, alternating ink and buff 30px divisions in a 7px band between two rules (20px divisions on phones), runs once horizontally at the header's foot and once vertically at the ranking panel's left edge. The rank sits between two double rules where a chart draws its scale line. Selection is drawn as an inset 1.5px magenta rule, never a size or transform change.

## Components

### Buttons
- **Shape:** gently squared (2px).
- **Primary:** chart blue fill, buff lettering, Franklin 13px 600, 6px 11px. Hover to blue-ink.
- **Ghost:** transparent with a blue rule and blue-ink lettering; hover fills with the sea tint.
- **Focus:** 2px magenta outline, 2px offset, site-wide.

### Segmented controls
Square chart boxes in a 1px strong-hairline frame with hairline dividers; Franklin 13px (12px small). The pressed one turns magenta, 600, on magenta-soft with an inset 1.5px magenta rule. Used for region, language, scenario, islands and basemap.

### Chips
Pole number boxes, 25px tall, min 27px wide, 1px strong-hairline border, Franklin 12px. The active one is solid magenta with buff lettering.

### Card (the cartouche)
Buff, double-ruled frame, 0 radius. Centred title block: unit name in display caps, the italic depth-ink subtitle ("Soundings in kilometres from the nearest drivable way"), the headline sentence, the rank between rules. Below, the controls, then the pole facts as a numbered NOTES list: magenta serif numerals, uppercase Franklin keys, values beneath, the distance as an italic sounding.

### Ranking (the tide table)
On the sea tint. A sticky head with a 2px ink rule above and 1px below, 11px serif spaced capitals in ink-sea; columns 34px / 1fr / 62px / 54px (rank, unit, active scenario, other scenario). Hairlines between rows, a strong hairline every fifth row. The current row is magenta-soft with an inset magenta rule and magenta 600 lettering.

### Pole marker (signature)
A 22px circled dot, the sounding figure beside it, the pole number in a tiny buff box with an ink rule (Franklin 600, 9.5px). Selected: ink turns magenta, a 2px magenta ring grows in over 400ms, the number box fills magenta. A figure that would overprint a better pole's is hidden; its dot and number stay.

### Depth scale (signature legend)
A buff box with an italic caption; six 44px blocks hanging deeper with distance (height 4px plus 3px per step) under a 2.5px ink shoreline, italic figures beneath, "km" at the end.

### Readout
A buff box writing the tapped distance as a 26px depth-ink sounding within an italic sentence.

### Compass rose
The chart's one rose, an authored fine-line SVG (0.8 stroke, magenta) on the About button, 34px (30px on phones), turning -22.5deg on hover over 600ms.

## Do's and Don'ts

### Do:
- **Do** set every colour through the `:root` tokens and give each a value in the dark block.
- **Do** write distances as soundings (Caslon italic, decimals small and lowered) on the map and in the readout.
- **Do** say selection in magenta and an inset rule, never by moving or resizing the element (Leaflet owns marker transforms).
- **Do** keep phone rules inside the single `max-width: 720px` query and verify desktop screenshots stay byte-identical.
- **Do** use the standard easing (`180ms cubic-bezier(.16, 1, .3, 1)`) for colour and height transitions.

### Don't:
- **Don't** paint the land in blue; the depth ramp is green.
- **Don't** use magenta for anything but the selection, notes and cautions.
- **Don't** add a Caslon bold or let the browser synthesise one.
- **Don't** load fonts or assets from a third-party host; the faces are self-hosted and counted in the first-screen budget.
- **Don't** add a second compass rose or another decorative chart ornament; the rose, the neatline and the double-ruled frames are the whole ornament set.

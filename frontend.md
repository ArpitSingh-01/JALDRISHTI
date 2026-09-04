# frontend.md — JALDRISHTI

**The single source of truth for the frontend build.** Everything a delegate needs
to build the JALDRISHTI web application is in this file: the design system, every
route, the exact backend data contract (real field names, not invented ones), the
API to build against, the Supabase schema, the map architecture, and the honesty
rules that make this product defensible in front of a technical jury.

Written by the backend author, who holds the full picture. **Every field name,
colour hex, class label, sentinel value and JSON key in this document is copied
from live backend source, not from memory.** A wrong name here becomes a silent
bug in a machine that cannot verify it. If something in this file disagrees with
the backend code, the backend code wins and this file is the bug — say so.

Companion file: **`frontend/design/tokens.css`** is the machine-readable half of
the design system (OKLCH palette, type, spacing, motion, the generated ramp
mirror). This document is the reasoning; that file is the values. Neither
duplicates the other.

---

## 0 · How to read this document

- **§1–§2** — what the product is and the design language. Read first.
- **§3–§5** — the pages, the components, the flows.
- **§6** — the data contract. **This is the section that must be correct.** It is
  the interface between a backend that exists and a frontend that doesn't yet.
- **§7** — the API surface to build (it does not exist yet — build against the
  mock fixtures in §12).
- **§8** — Supabase, free tier, with the storage arithmetic that keeps it free.
- **§9–§11** — map, honesty, responsive.
- **§12–§15** — fixtures, a11y, traps, and the recommended build order.

`§N.M` cross-references are used throughout. Backend source is cited as
`backend/jaldrishti/<path>` so any claim here can be checked against the code.

---

## 1 · The product

### 1.1 What it is

JALDRISHTI simulates dam-break and river-blockage floods over real Indian terrain
and turns the result into something a district emergency officer can act on. A
user picks a dam or blockage, defines a failure scenario, and the system returns
**depth, velocity, arrival time, population/infrastructure exposure and damage
range**, exported as GeoTIFF, Shapefile, KML and a response-ready PDF.

Smart India Hackathon 2026, **Problem Statement 26161** — "Dam Break Inundation
Modelling Using Hydrodynamic Modelling of any River." Organisation: National
Technical Research Organisation (NTRO). Theme: Disaster Management.

### 1.2 The differentiator — build the whole UI around this

Every competing team renders a blue blob on a map. The blue blob is table stakes.

**The product is the sentence "water reaches this village in 47 minutes, about
12,000 people must move."** Arrival time and exposure are the differentiator, not
the inundation extent. The frontend's job is to make that sentence unmissable —
it is the `headline` field of every result (§6.2), it is the first thing on the
console, it is the largest type on the page.

Design consequence: **arrival time is the primary map layer, shown first.** Depth
is secondary. This mirrors the backend, where `raster_specs()` deliberately emits
`arrival_time_min` as the first band "because a directory listing is a user
interface" (`backend/jaldrishti/export/raster.py`).

### 1.3 Who reads the screen

Two registers, two audiences, one product:

- **The public / the jury / a district officer glancing at a projector** — reads
  the **landing page** and the **PDF**. Needs the story, the credibility, the
  statutory framing. This is the *chromatic* register: the Indian tricolour, full
  confidence, printable.
- **An analyst running scenarios** — lives in the **console** (`/runs/*`). Needs
  density, precision, dark mode for a control room, and no decoration competing
  with the map. This is the *achromatic* register: neutral chrome, one accent, the
  colour budget spent entirely on the hazard and arrival ramps.

The design system carries both (§2). The palette does not change between them; the
*amount of colour* does.

### 1.4 Non-negotiable honesty posture

The PS uses the words "probable" and "confidence-based" repeatedly. The backend
enforces this in code — `is_presentable()`, `unverified_inputs`, `limitations`,
the `MODEL_DISCLAIMER`. **The frontend must never present as certain what the
backend flags as uncertain.** §11 is the full honesty UI spec; it is not optional
polish, it is the thing that makes a jury trust the tool. A prettier UI that hides
a limitation is a worse product here.

---

## 2 · Design system

The values live in `frontend/design/tokens.css`. This section is why they are what
they are, and the laws that components must obey. **Hallmark theme: "Tricolour
Instrument" — a custom, tuned theme** (the user named a specific brand palette, so
this is the Hallmark custom-theme route, not a catalog pick).

### 2.1 The palette is the flag, tuned — not the flag, raw

The tricolour's published values are India Saffron `#FF9933`, white, India Green
`#138808`, Navy `#000080`. Used raw they break an instrument:

- `#FF9933` sits at **78.5% OKLCH lightness**. White text on it is ~2.2:1 —
  fails WCAG at every size. **Saffron is therefore never a text colour and never a
  text background with light text.** The primary button is saffron fill with a
  **navy label** (`--color-accent-ink`, ~6:1). This is flag-honest *and*
  accessible.
- `#000080` is more chromatic (C≈0.19) than any ink should be. Navy is tuned down
  to `oklch(32% 0.13 258)` for chrome and ink so it reads as authoritative, not
  neon.

The hue axis is preserved exactly on all three — the hue is what carries the
national reference. Only L and C are tuned. See `tokens.css` §1.

### 2.2 Colour law — this is where the product earns or loses trust

Four rules, all enforceable, all consequential:

1. **Saffron = action only.** Primary buttons, the active nav item, the "Run
   scenario" CTA, a selected row. Never decoration, never a divider, never a
   background wash for its own sake. If saffron appears, it means *do this / you
   are here*.
2. **Green = verified state only.** The "verified against primary source" badge,
   "mass conserved", "on the downstream trace". It is free to mean this because
   **nothing green ever appears inside the map canvas** — the DEFRA ramp is
   yellow→red, the arrival ramp is blues. Green cannot be confused with a hazard.
3. **The hazard and arrival ramps are OFF the brand palette, permanently.** They
   are perceptual scales bound to physical quantities, generated from Python
   (§6.5, §6.6). A hazard colour is not a brand colour and must never be
   "harmonised" toward saffron to look nicer. Memory `jaldrishti-frontend-palette`
   and three backend modules all state this independently.
4. **Error red is banned from the map canvas and every legend.** `--color-error`
   at `oklch(48% 0.19 22)` sits between DEFRA "Significant" `#f03b20` and "Extreme"
   `#7f0000`; inside a legend it reads as a hazard band. It is for form validation
   and system errors only, where it is unambiguous.

### 2.3 Locked tokens — no inline colour, ever

Every colour in every component references a token (`var(--color-accent)`,
`var(--ramp-defra-2)`). An inline `#`, `rgb()` or `oklch()` literal anywhere in a
component is a defect. If a needed value is missing, add it to `tokens.css` as a
named token and reference that. (Hallmark gate 48.)

### 2.4 Typography

Two Latin voices, one numeric, one script extension — full rationale in
`tokens.css` §2:

- **Bricolage Grotesque** — display/headings. Roman only; **italic headings are
  banned** (Hallmark gate 38a — the single most reliable AI tell). Emphasis is
  carried by weight or the accent underline, never by slanting a heading.
- **Public Sans** — body and UI. Chosen because it is a government-forms face
  *and* because it is deliberately **not Inter** (Inter is the default every
  generated UI reaches for).
- **IBM Plex Mono** — **every number that means anything.** Arrival minutes,
  depths, populations, coordinates, run IDs. `font-variant-numeric: tabular-nums
  slashed-zero` is mandatory: an arrival-time column that changes width between
  "9" and "47" is unreadable at a glance, and glancing is the entire use case.
  Apply via the `.num` class or the element tokens in `tokens.css` §9.
- **IBM Plex Sans Devanagari** — for "जलदृष्टि" and for Hindi place labels beside
  the transliteration. A script extension, not a fourth voice.

### 2.5 Motion & morphism — the user is open to it; spend it precisely

The user explicitly invited animation, motion graphics, and morphism. The rule
that keeps it from reading as generic: **motion must encode meaning, never
decorate.** An instrument that reports flood arrival does not bounce.

Where motion earns its place:

- **The front-advance scrubber** (§9.3) — the one genuinely spatial, genuinely
  meaningful animation. The flood front advancing as a time threshold sweeps. This
  is the demo moment. Interpolate the isochrone boundary with `--ease-out`.
- **Counter roll-ups** — the headline population and area count up once on result
  load (`--dur-4`, 600ms). Once, not on every scroll.
- **Panel disclosure** — exposure/limitation panels expand with `--dur-2`.
- **Route transitions** — a restrained cross-fade/slide at `--dur-3` between
  landing sections.
- **Morphism, used with discipline** — a *single* signature treatment, not
  everywhere. Recommended: a **frosted-glass (backdrop-blur) floating legend/HUD**
  over the dark map canvas in the console — it reads as an instrument overlay,
  which is exactly right. Glassmorphism on the landing page's scenario cards is
  acceptable as one accent; glass on every surface is slop. Neumorphism (soft
  extruded shadows) is **not** used — it fails contrast and reads as 2020 SaaS.

Hard motion rules:

- **`prefers-reduced-motion` collapses spatial motion to an opacity crossfade**,
  not merely a faster version — the scrubber still works, it just stops
  interpolating (`tokens.css` §9 handles the global floor; mark spatial elements
  `data-motion="spatial"`).
- No overshoot/bounce on any control state. No infinite ambient animation near
  numbers a user is trying to read.
- Motion library: **Motion (`motion`/framer-motion)** — but the map's own
  animation is deck.gl transitions, not DOM motion.

### 2.6 The two registers, concretely

| | Landing (`/`, `/scenarios`, `/validation`, `/methodology`, `/about`) | Console (`/runs/*`) |
|---|---|---|
| register attr | `data-register="landing"` | `data-register="console"` |
| chrome colour | full tricolour | neutral (paper/ink/rule) + saffron accent only |
| dark mode | none — it is public & printable | yes, default in-app (`data-theme="dark"`) |
| density | generous, editorial | dense, instrument |
| colour budget | brand-forward | spent on ramps |

Dark mode applies to the console **only**; the landing page has one correct
register (`tokens.css` §7). The ramps do not change between light and dark —
a hazard colour that means something different after dark is worse than no dark
mode.

### 2.7 Elevation, radius, spacing

Two shadow levels only (flat panels + rules read as an instrument; four shadow
depths read as decoration). Small radii (2–8px) — this is an instrument, not a
soft consumer app. 4pt spacing scale. All in `tokens.css` §3–§5.

---

## 3 · Route map

Next.js App Router. **11 routes.** Landing group is public and static-friendly;
console group is authenticated and dynamic.

```
/                         Landing — the story + the differentiator + credibility
/scenarios                The three scenarios as a catalog
/scenarios/[key]          Scenario detail + failure-configuration + "Run"
/validation               The validation ladder charts (never-cut credibility)
/methodology              Physics & numerics, explained honestly
/about                    Project, SIH context, statutory framing, citations
/login  /signup           Supabase auth (console access)
/runs                     Run history (console register)
/runs/[run_id]            THE CONSOLE — map, arrival, exposure, export, honesty
/runs/[run_id]/report     Print-optimised, mirrors the PDF (shareable link)
```

`[key]` ∈ `{malpasset, tehri, rishi_ganga}` — the three study-area keys
(`backend/jaldrishti/config.py`, `STUDY_AREAS`). The URL slug **is** the backend
key: `rishi_ganga`, not `chamoli`. Display the human title "Chamoli 2021" in the
H1 and nav, but every `[key]` in a path, fetch, or DB column is `rishi_ganga`.
Do NOT introduce a `chamoli → rishi_ganga` alias map — one canonical name.
`[run_id]` is the backend run identifier (§6.2).

Nav archetype: **landing** uses a centered logo + right-aligned links + a saffron
"Open console" CTA (Hallmark N-series, one clear primary action). **Console** uses
a slim left rail (run list, layer switch) + top status bar — no marketing nav.
Footer archetype: landing gets a full editorial footer with the statutory
citations and the disclaimer; console gets a one-line status footer (run id, CRS,
build hash).

---

## 4 · Pages

Each page below lists **purpose, sections, the exact backend data it binds, and
the traps.** Bind only to fields that appear in §6.

### 4.1 `/` — Landing

**Purpose:** in 15 seconds, make a juror believe this is compliance
infrastructure, not a hackathon toy. Make the differentiator land.

Sections, in order (this is the macrostructure — do **not** default to
hero→3-features→CTA):

1. **Hero.** The name जलदृष्टि / JALDRISHTI, one line: *"Dam-break flood
   simulation that tells you who has to move, and when."* One saffron CTA → "Open
   the console." A restrained hero visual: a still frame of the Tehri arrival-time
   map (isochrones), not a spinning globe. Caption it honestly as simulation
   output.
2. **The differentiator, stated.** A large-type panel: the `headline` sentence
   pattern, spelled out — arrival time + exposure. This is the thesis.
3. **The three scenarios** as a triptych (links to §4.2): Malpasset (how we know
   it's right), Tehri (a real Indian dam), Chamoli (the river-blockage case the PS
   itself cites). Each a card; glass accent permitted here.
4. **How we know it works** — a strip pointing to `/validation`: "validated
   against surveyed field data and analytical solutions," with a sparkline of the
   Ritter/Stoker fit. Real charts live on `/validation`; this is the teaser.
5. **Statutory framing.** Dam Safety Act 2021 mandates dam-break studies and
   Emergency Action Plans. Reframes the tool as legally-grounded. Cite NDMA GLOF
   guidelines, CWC inundation guidelines, Sendai Priority 4.
6. **Honesty, up front.** A short panel: "What this is not." Not a survey, not an
   official hazard map, arrival ≠ warning time. Counter-intuitively this *builds*
   trust and it pre-empts the jury's hardest question. Pull the exact
   `MODEL_DISCLAIMER` (§6.9).
7. **Footer** — editorial: nav, the four statutory citations, the full
   disclaimer, "SIH 2026 · PS 26161 · NTRO", credit.

**Traps:** no invented metrics anywhere (Hallmark gate 46) — no "10× faster," no
"trusted by N agencies," no fake logos. This product's credibility is *validation
and honesty*, and a single fabricated stat destroys it faster here than on any
ordinary marketing site. Use the real Malpasset/analytical numbers from
`/validation` or use none.

### 4.2 `/scenarios` and `/scenarios/[key]`

**`/scenarios`** — the three study areas as cards. Each: title, one-line purpose,
`scenario_kind` (dam-break vs blockage), a thumbnail of the domain. Data from the
study-areas list endpoint (§7).

**`/scenarios/[key]`** — detail + run setup:

- **Dam / blockage specification.** For Tehri: height, crest, FRL, gross & live
  storage, reservoir area, installed capacity, catchment — all from the
  `DamSpec`/`Domain` in `config.py`, served via §7.
  **CRITICAL HONESTY BINDING:** every one of these figures is currently
  `verified=False` (backend B1). Each spec value carries a `Source{citation,
  verified, note}`. **Render any `verified:false` figure with the unverified
  treatment (§11.2) — hatched/marked, "unverified" label.** Do not print a clean
  reservoir volume as fact. When B1 clears backend-side, the flag flips and the
  treatment falls away automatically. This is the mechanism working as designed.
- **The domain** — extent, CRS (UTM 44N for Tehri), and the two resolutions: 90 m
  interactive (`shape` 649×702, ~1–2 min) and 30 m high-res
  (1946×2106 = 4,098,276 cells, ~15–30 min — note this runtime is **unverified**,
  backend R3; label it "estimated").
- **Failure configuration form** — bound to `BreachSpec`
  (`mode ∈ instantaneous|parametric|overtopping`, `breach_width_m`,
  `breach_depth_m`, `side_slope`, `formation_time_s` with its
  `formation_time_range_s`). Sensible defaults pre-filled from the study area
  (Tehri: parametric, 600 m × 230 m, 3600 s, range 1800–10800 s). A resolution
  toggle (90 m / 30 m).
- **"Run scenario"** — POST to §7, redirect to `/runs/[run_id]`.
- **The six Tehri limitation strings** from `config.py` shown before the run
  button, not buried after.

**Trap:** do **not** display "the DEM matches FRL to 0.3 m" or any DEM/FRL
agreement claim. Backend ROADMAP §8.7: that agreement was cell luck; at the NRLD
coordinate the DEM reads 819.4 m, not 830 m. (The `config.py` code *comment* still
overclaims this — that is a known backend doc bug being fixed separately; **do not
propagate it to the UI**.)

### 4.3 `/validation` — the credibility page (never cut)

**Purpose:** prove the solver is correct. This is on `CLAUDE.md`'s never-cut list.

The validation ladder, one section per rung, each with its chart (backend
`validation/figures.py` emits PNGs; the frontend shows them, or re-plots from
emitted CSV if provided):

1. **Lake at rest** — residual velocity vs time, log axis. The point: still water
   stays still to ~2×10⁻¹⁴ m/s. Well-balancedness.
2. **Ritter** (dry-bed dam break) — numerical depth vs analytical, three times.
3. **Stoker** (wet-bed dam break) — same, wet downstream.
4. **Manning normal depth** — friction convergence + the first-order
   splitting-error line.
5. **Malpasset** — against surveyed high-water marks (rung 4 is backend-blocked on
   bathymetry, B3; if not ready, show rungs 1–4 and mark Malpasset "in progress"
   honestly rather than faking it).

Each chart shows L2 and L∞ error in the title. Include the jury-defence note that
the **Manning bug** was caught here (friction was wrong by a factor of `h`, making
arrival times too early — the dangerous direction), stated as a *strength*: our
validation caught a real bug.

### 4.4 `/methodology` — how it works, honestly

Physics and numerics for a technical juror. Sections: the shallow-water equations;
finite-volume + HLLC + MUSCL in plain terms; well-balancedness and
wetting/drying; the CFL 0.4 safety factor; the resolution design point (90/30 m);
**the Delft3D position, stated exactly** (§6.9 `SOLVER_ATTRIBUTION` verbatim — we
did NOT run Delft3D); **Chamoli is a debris flow** the SWE only approximates via
bulking factor + elevated roughness. Diagrams welcome; no fake benchmark numbers.

### 4.5 `/about`

Project, SIH context, the solo-builder story is fine, statutory framing repeated,
full citation list, contact. Keep it short and real.

### 4.6 `/login`, `/signup`

Supabase Auth (§8). Email+password and/or magic link. Minimal. Console access
only — the landing group is public. On success → `/runs`.

### 4.7 `/runs` — history

Console register. A table of past runs: `run_id`, `study_area`, `scenario`,
flooded area, first arrival, presentable-as-fact badge (§11.1), created-at. Row →
`/runs/[run_id]`. Empty state → "Run your first scenario" → `/scenarios`. Data:
user's runs from Supabase (§8), each row mirroring `results` headline fields.

### 4.8 `/runs/[run_id]` — THE CONSOLE

The main event. Full spec in §9 (map) and §11 (honesty). Layout:

```
┌──────────────────────────────────────────────────────────────┐
│ status bar: run_id · study area · scenario · presentable badge │
├────────┬─────────────────────────────────────────┬────────────┤
│ layer  │                                         │  exposure   │
│ switch │         deck.gl map canvas              │  panel      │
│ (rail) │    (arrival default · frosted HUD)      │  + headline │
│        │                                         │  + settle-  │
│        │  ┌───────────────────────────────────┐  │  ments      │
│        │  │ front-advance scrubber  ◀━━●━━▶    │  │  table      │
│        │  └───────────────────────────────────┘  │             │
├────────┴─────────────────────────────────────────┴────────────┤
│ honesty drawer (limitations · unverified · disclaimer) · export│
└──────────────────────────────────────────────────────────────┘
```

- **Headline** — `summary.headline` (§6.2), largest type on the page, top of the
  right panel. The population/area count-up lands here.
- **Layer switch** — arrival (default) · depth · speed · depth×velocity · hazard
  DEFRA · hazard AIDR. Exactly the raster bands of §6.4. Each with its correct
  legend (§6.5, §6.6).
- **Front-advance scrubber** — §9.3.
- **Exposure panel** — §6.7; the cross-tab, infrastructure, "reported" (2-sig-fig)
  population. Only if exposure present.
- **Settlements-at-risk table** — §6.8; name, arrival (−1 = "not reached", not
  "0"), depth, hazard class. The literal embodiment of the differentiator.
- **Export bar** — §6.10; GeoTIFF, Shapefile (.zip), KML, PDF, metadata.json,
  MANIFEST.json. Buttons map to manifest keys.
- **Honesty drawer** — §11; always present, never dismissable to zero.

### 4.9 `/runs/[run_id]/report`

A print-CSS view mirroring the PDF: maps, exposure tables, per-settlement arrival
table, assumptions & limitations page, citations. Shareable URL. `@media print`
must produce something a district office can actually print in B/W (hazard classes
must survive greyscale — rely on the class *labels*, not colour alone).

---

## 5 · Component inventory

Build these as the reusable set. All consume tokens (§2.3); all interactive ones
ship all 8 states (default/hover/focus-visible/active/disabled/loading/error/
success).

- **Button** (primary saffron+navy-label / secondary outline / ghost / danger).
- **Stat / metric tile** — mono tabular number + label + optional unverified mark.
- **Headline banner** — the one-sentence result, count-up capable.
- **Legend** — reads a ramp from `ramps.generated.ts` (§6.5); DEFRA/AIDR/arrival
  variants; class-label-first so it survives greyscale.
- **Layer switcher** — segmented control, keyboard-navigable, no scroll-jump.
- **Scrubber** — the front-advance time control (§9.3).
- **Map HUD panel** — frosted-glass floating overlay (the one morphism signature).
- **Exposure table / cross-tab grid.**
- **Settlements table** — sortable, mono arrival column, "not reached" styling.
- **Unverified mark / badge** — the hatched treatment (§11.2).
- **Presentable-as-fact badge** — pass (green) / blocked (neutral + reasons).
- **Limitation list** — bulleted, prose-width capped (`--measure-prose`).
- **Disclaimer block** — renders the verbatim backend strings.
- **Provenance viewer** — collapsible metadata.json tree.
- **Scenario card**, **Dam-spec table**, **Breach-config form**, **Run-status /
  progress** (streams §7 progress), **Export bar**, **Empty/error/loading states.**
- **Chart** (validation) — line + analytical overlay; uses the dataviz skill's
  neutral palette, **not** the hazard ramps (a validation chart is not a hazard
  map).

---

## 6 · The data contract  ⟵ THE SECTION THAT MUST BE RIGHT

Everything here is copied from live backend source. **Bind to these names
exactly.** Where the backend has no field, the frontend has no data — do not
invent one.

### 6.1 Grid, CRS, and how rasters reach the browser

Every raster in a run shares one `grid`: `shape` (rows, cols), `dx_m`, `crs`,
`transform` (6-element affine). Rasters are **projected** (Tehri = UTM 44N, EPSG
:32644), not lon/lat. deck.gl works in Web Mercator / lon-lat, so tiles must be
served reprojected **or** the frontend consumes the COG via a tile endpoint that
handles reprojection (§7, §9.1). Do not assume raster pixel coords are lon/lat.

### 6.2 `GET /api/runs/{run_id}` → `ScenarioSummary.to_dict()`

Source: `backend/jaldrishti/analysis/summary.py::to_dict`. **Exact shape:**

```jsonc
{
  "run_id": "string",
  "study_area": "string",           // "tehri" | "malpasset" | "rishi_ganga"
  "scenario": "string",             // e.g. "instantaneous full breach"
  "headline": "string",             // THE sentence — render prominently (§1.2)

  "grid": {
    "shape": [rows, cols],
    "dx_m": 90.0,
    "crs": "EPSG:32644",
    "transform": [a, b, c, d, e, f] // affine, or null
  },

  "run": {
    "duration_s": 0.0,              // simulated seconds
    "wall_time_s": 0.0,             // compute seconds
    "steps": 0,
    "volume_error": 0.0,            // relative mass-conservation error (signed)
    "solver": { }                   // free-form solver settings
  },

  "results": {
    "flooded_area_km2": 0.0,        // NEW flooding only — NOT total wetted (§6.3)
    "total_wetted_area_km2": 0.0,   // includes reservoir; rarely the headline
    "peak_depth_m": 0.0,
    "peak_speed_ms": 0.0,
    "first_arrival_min": 0.0,       // number OR null — null = never reached (§6.3)
    "last_arrival_min": 0.0,        // number OR null
    "area_by_hazard_km2": { },      // DEFRA class name -> km²  (§6.5)
    "area_by_aidr_class_km2": { },  // AIDR class -> km²        (§6.5)
    "area_by_arrival_band_km2": { },// band label -> km²        (§6.6)
    "interpolated_flooded_cells": 0,// weaker-evidence cell count (§11)

    "exposure": { /* present only if computed — §6.7 */ },
    "damage":   { /* present only if computed — §6.7; forces not-presentable */ }
  },

  "provenance": {
    "terrain": { },                 // DEM source + conditioning steps
    "breach":  { }                  // breach parameters used
  },

  "honesty": {
    "presentable_as_fact": true,    // the release gate (§11.1)
    "blocking_reasons": [ ],        // why not, if false
    "unverified_inputs": [ ],       // every verified=false citation that fed the run
    "limitations": [ ]              // every caveat, deduped, human-readable
  }
}
```

### 6.3 Three semantics that will cause silent bugs if ignored

1. **`null` means "never reached," not zero.** `first_arrival_min` /
   `last_arrival_min` are `null` when water never arrived (the backend's
   `_json_safe()` converts NaN→null so `JSON.parse` doesn't throw). Render `null`
   as **"not reached"**, never "0 min." (The backend once had exactly this bug —
   the reservoir is wet at t=0, so a naive min gave "0 min after failure.")
2. **`flooded_area_km2` is NEW flooding; `total_wetted_area_km2` adds the
   reservoir.** The headline uses the new-flooding figure. Quoting total adds
   Tehri's ~52 km² reservoir surface to every result. Default every "area flooded"
   display to `flooded_area_km2`.
3. **Areas are dictionaries keyed by class/band label**, not arrays. Iterate
   keys; do not assume order or index. The label strings are the canonical join
   key to the legend (§6.5, §6.6).

### 6.4 Raster bands (map layers)

Source: `backend/jaldrishti/export/raster.py::raster_specs`. Band file names, in
the order the backend emits them (arrival first, deliberately):

| band file | quantity | units | masked over pre-existing water? |
|---|---|---|---|
| `arrival_time_min` | minutes to first wetting | min | **yes** — reservoir → nodata |
| `arrival_band` | isochrone band index | class | (sentinels −1/−2) |
| `max_depth_m` | peak depth | m | no — reservoir depth is real |
| `max_speed_ms` | peak speed | m/s | no |
| `max_depth_velocity` | peak of depth×speed | m²/s | no |
| `hazard_rating` | Defra HR = d(v+0.5)+DF | HR | **yes** |
| `hazard_class_defra` | Defra band 0–3 | class | **yes** |
| `hazard_class_aidr` | AIDR class 0–5 (H1–H6) | class | **yes** |
| `dem_valid` (optional) | 1=real DEM, 0=interpolated | flag | — |

**Float raster nodata = `-9999.0`; integer/class nodata = `-1`.** The frontend
tile renderer must treat these as transparent, never as data. `max_depth_velocity`
is the running max of d×v, **not** `max_depth × max_speed` (those peaks occur at
different times; multiplying them overstates hazard). Don't recompute hazard
client-side from depth×speed — read the band.

### 6.5 Hazard classes & colours

Source: `backend/jaldrishti/analysis/hazard.py`.

**DEFRA / EA** — 4 classes, thresholds on HR = `DEFRA_BANDS = (0.75, 1.25, 2.5)`:

| idx | name | colour | meaning (abridged — use full `DEFRA_CLASS_MEANING`) |
|---|---|---|---|
| 0 | Low | `#ffeda0` | Caution |
| 1 | Moderate | `#feb24c` | Dangerous for some (children, elderly) |
| 2 | Significant | `#f03b20` | Dangerous for most |
| 3 | Extreme | `#7f0000` | Dangerous for all, incl. emergency services |

`DEFRA_CLASS_NAMES = ("Low","Moderate","Significant","Extreme")`,
`DEFRA_CLASS_COLOURS = ("#ffeda0","#feb24c","#f03b20","#7f0000")`.

**AIDR / AR&R** — 6 classes H1–H6,
`AIDR_CLASS_COLOURS = ("#ffffb2","#fed976","#feb24c","#fd8d3c","#e31a1c","#800026")`,
each with a per-class description in `AIDR_CLASSES`.

The `area_by_hazard_km2` dict is keyed by the DEFRA **class name**;
`area_by_aidr_class_km2` by the AIDR class label. Join on the string.

### 6.6 Arrival bands & isochrones

Source: `backend/jaldrishti/analysis/arrival.py`.

- `DEFAULT_BANDS_MIN = (15.0, 30.0, 60.0, 120.0)`
- `band_labels()` → `["0-15 min","15-30 min","30-60 min","60-120 min",">120 min"]`
- `BAND_COLOURS = ("#08306b","#2171b5","#4292c6","#7fb8d9","#bdd7e7")` — **fastest
  is darkest**, so the eye lands first on the least time. The lightest step
  `#bdd7e7` (">120 min") is deliberately not near-white so it stays visible on grey
  land — this constrains the basemap (§9.2).
- `PRE_EXISTING_WATER_COLOUR = "#8c96a8"` — reservoir/channel; off the urgency ramp
  entirely.
- Sentinels: **`NEVER_FLOODED = -1`**, **`INITIALLY_WET = -2`.** Never summed,
  never averaged, always distinct in the legend ("not reached" vs "water before
  failure").
- `isochrone_polygons()` GeoJSON columns: `band`, `label`, `min_minutes`,
  `max_minutes`, `area_km2`, `geometry`.

### 6.7 Exposure & damage (present only if computed)

**Exposure** (`results.exposure`), source `analysis/exposure.py` + the `to_dict`
mapping in `summary.py`:

```jsonc
"exposure": {
  "total_population": 0,        // raw
  "reported_population": 0,     // 2-sig-fig — DISPLAY THIS ONE (§11.3)
  "by_hazard": { },             // hazard class -> people
  "by_arrival_band": { },       // arrival band -> people
  "cross_tab": { },             // (hazard × band) -> people
  "infrastructure": { },        // counts (buildings, road km, facilities…)
  "resample_report": { }        // population raster resampling audit
}
```

Display `reported_population` (2 sig figs) as the headline exposure number.
Reporting a raw "12,437" implies a per-person census we do not have. The full
`total_population` may appear once in a provenance/detail view, labelled as raw.
The cross-tab is one mask (`haz_wet & arr_wet`) — the by-hazard and by-band
marginals agree by construction; don't recompute a total that outsums them.

**Damage** (`results.damage`), source `analysis/damage.py`:

```jsonc
"damage": {
  "unit": "INR",
  "low": 0.0, "central": 0.0, "high": 0.0,   // range = central × [0.5, 2.0]
  "formatted": "string",                     // e.g. "₹120–480 crore" — use verbatim
  "by_category": { "cat": {"low","central","high"} },
  "structural_failure_buildings": 0
}
```

**If `damage` is present, `honesty.presentable_as_fact` is `false`, permanently
and by design** (`summary.py::is_presentable` — monetary loss is the product of
four uncertain factors; no verification makes a rupee a fact). Always render
damage as a **range** using `formatted`, always inside the unverified/estimate
treatment, never a single point value. Never show a damage number without the
"order-of-magnitude estimate" framing.

### 6.8 Settlements-at-risk (vector layer)

Source: `backend/jaldrishti/export/vector.py::settlements_at_risk`. GeoJSON
feature properties:

| property | meaning |
|---|---|
| `name` | settlement name |
| `arr_min` | arrival minutes — **`-1` = not reached** (kept in the layer deliberately) |
| `flooded` | bool |
| `depth_m` | peak depth at the settlement |
| `speed_ms` | peak speed |
| `haz_class` | hazard class name |
| `band` | arrival band index |
| `population` | present only when the gazetteer has it |

`arr_min == -1` → render "not reached" (consistent with the `null` rule of §6.3;
the vector layer uses `-1` where the JSON summary uses `null`, because a Shapefile
numeric column can't hold null — same meaning, different sentinel).

### 6.9 Verbatim strings — render exactly, do not paraphrase

Source: `backend/jaldrishti/export/metadata.py`. These are legally-framed; the
frontend must show the backend's exact bytes (fetch from the metadata/summary
endpoint; the copies below are for fixtures and must match).

**`SOLVER_ATTRIBUTION`:**

> Hydrodynamics computed by JALDRISHTI's own 2D shallow-water solver (finite
> volume, HLLC approximate Riemann solver, MUSCL reconstruction, well-balanced
> bed-slope source term, Manning friction, explicit CFL-limited time stepping).
> Delft3D was NOT run to produce this output. Where Delft3D is referenced, the
> comparison is against PUBLISHED benchmark results from the literature, and the
> interoperability claim is limited to a Delft3D-compatible input/output adapter.

**`MODEL_DISCLAIMER`:**

> This is simulation output, not a survey and not an official flood hazard map. It
> is intended for humanitarian planning and exercise use. Arrival time is measured
> from the moment of failure and is NOT warning time — warning time additionally
> requires detection, decision and dissemination, which this model does not
> represent. Statutory dam-break inundation mapping in India is governed by the
> Dam Safety Act, 2021 and CWC guidelines; this tool supports such work, it does
> not substitute for it.

The disclaimer appears on: landing (§4.1 §6), the console honesty drawer, and the
report. The attribution appears on: methodology, and anywhere Delft3D is
mentioned. **Never** add UI copy implying Delft3D was run.

### 6.10 Export manifest → download buttons

Source: `backend/jaldrishti/export/__init__.py::write_all` +
`metadata.py::write_manifest`. `MANIFEST.json.files[].path` are POSIX paths
relative to the run dir. Known keys the export bar maps to buttons:

```
arrival_time_min.tif   arrival_band.tif   max_depth_m.tif   max_speed_ms.tif
max_depth_velocity.tif hazard_rating.tif  hazard_class_defra.tif
hazard_class_aidr.tif  dem_valid.tif (optional)
shapefile/<layer>.zip  kml/<layer>.kml (or .kmz)
README.txt   metadata.json   report.pdf   MANIFEST.json
EXPORT_ERRORS.json (present ONLY if a stage failed — surface as a warning)
```

Vector layers (each shipped under both `shapefile/` and `kml/`):
`inundation_extent`, `arrival_isochrones`, `hazard_zones_defra`,
`hazard_zones_aidr`, `settlements_at_risk`. **A Shapefile ships as
`shapefile/<layer>.zip`** (the .shp/.shx/.dbf/.prj bundled), not a bare `.shp`.
Build the export bar by reading the manifest, not by hardcoding a file list — if
`EXPORT_ERRORS.json` exists, show which stage failed and still offer what
succeeded.

---

## 7 · API contract to build against

**`api/` does not exist yet.** The frontend builds against **mock JSON fixtures**
(§12) shaped exactly like §6, then swaps the base URL when the backend lands. This
is the backend author's spec for what `api/` will implement (FastAPI).

| method + path | returns | notes |
|---|---|---|
| `GET /api/study-areas` | `[{key, title, scenario_kind, purpose, thumbnail}]` | for §4.2 |
| `GET /api/study-areas/{key}` | dam/blockage/domain/breach specs + `Source` flags | §4.2; carries `verified` |
| `POST /api/runs` | `{run_id}` | body: `{area, failure_spec, resolution}` |
| `GET /api/runs` | `[summary-lite]` | history (§4.7) |
| `GET /api/runs/{run_id}` | **`ScenarioSummary.to_dict()`** (§6.2) | the core payload |
| `GET /api/runs/{run_id}/progress` | SSE/WebSocket stream | `{step, pct, t_sim, volume_error, msg}` |
| `GET /api/runs/{run_id}/manifest` | `MANIFEST.json` | drives the export bar (§6.10) |
| `GET /api/runs/{run_id}/artifacts/{key}` | file bytes | `key` = a manifest path |
| `GET /api/runs/{run_id}/isochrones.geojson` | isochrone FeatureCollection | §6.6 columns |
| `GET /api/runs/{run_id}/settlements.geojson` | settlements FeatureCollection | §6.8 columns |
| `GET /api/runs/{run_id}/tiles/{band}/{z}/{x}/{y}.png` | COG tiles | reprojected; band ∈ §6.4 |

Contract rules the frontend must assume: responses are strict JSON (no NaN — the
backend guarantees `allow_nan=False`); numbers may be `null` (§6.3); a run may be
`pending`/`running`/`done`/`failed` — poll `GET /api/runs/{run_id}` or stream
progress; on `failed`, show `honesty`/error, not a blank map.

---

## 8 · Supabase (free tier)

Auth + metadata + run bookkeeping. **Large binary artifacts (COGs, ZIPs, the
population raster) do NOT live in Supabase** — the free tier is 500 MB DB + 1 GB
storage + 5 GB egress, and one 30 m Tehri COG plus the 531 MB population raster
would blow that instantly. The heavy files stay with the backend/object store and
are streamed via §7. Supabase stores **rows and small JSON**, not rasters.

### 8.1 Schema

```sql
-- profiles (extends auth.users)
create table profiles (
  id uuid primary key references auth.users on delete cascade,
  display_name text,
  org text,
  created_at timestamptz default now()
);

-- one row per simulation run (metadata only; rasters live elsewhere)
create table runs (
  run_id text primary key,              -- backend-issued id
  user_id uuid references auth.users on delete cascade,
  study_area text not null,             -- tehri | malpasset | rishi_ganga
  scenario text not null,
  resolution_m real not null,           -- 90 | 30
  status text not null default 'pending',-- pending|running|done|failed
  headline text,                        -- summary.headline (denormalised for lists)
  flooded_area_km2 real,
  first_arrival_min real,               -- nullable = never reached
  presentable_as_fact boolean,
  summary jsonb,                        -- full ScenarioSummary.to_dict() (§6.2)
  manifest jsonb,                       -- MANIFEST.json (§6.10)
  created_at timestamptz default now(),
  completed_at timestamptz
);

-- failure configuration submitted for a run (audit trail)
create table failure_specs (
  id uuid primary key default gen_random_uuid(),
  run_id text references runs on delete cascade,
  mode text not null,                   -- instantaneous|parametric|overtopping
  breach_width_m real, breach_depth_m real, side_slope real,
  formation_time_s real,
  created_at timestamptz default now()
);
```

`summary jsonb` holds the whole payload so the history and console can render
without a backend round-trip for old runs; the raster tiles still come from §7.

### 8.2 Row-level security

Enable RLS on all tables. `runs`, `failure_specs`, `profiles`:
`user_id = auth.uid()` for select/insert/update/delete. Study-area *definitions*
are public/static (they ship with the app, not in Supabase). A run inserted by the
backend on the user's behalf uses the service role; the browser reads its own rows
only.

### 8.3 Realtime

Use Supabase Realtime on `runs` to flip a card from "running" → "done" live in
`/runs`, complementing the §7 progress stream on the console.

---

## 9 · Map architecture (deck.gl)

### 9.1 Layers

- **Basemap** — a light neutral base (§9.2). Not a busy street map; this is
  terrain + water, and street clutter fights the ramps.
- **Terrain** — `TerrainLayer` from the DEM (the honest answer to the PS's "large
  data" requirement is GPU 3D). Hillshade baked or via `--map-land-shade`.
- **Raster overlay** — the active band (§6.4) as a `TileLayer`/`BitmapLayer` from
  the COG tile endpoint (§7). One active band at a time; nodata transparent.
- **Isochrones** — `GeoJsonLayer` from `isochrones.geojson`, filled by
  `BAND_COLOURS` (§6.6), for the arrival view and the scrubber.
- **Settlements** — `GeoJsonLayer`/`IconLayer` from `settlements.geojson`;
  click → popup with name, arrival (or "not reached"), depth, hazard class.
- **Frosted HUD** — DOM overlay (the morphism signature), not a deck layer:
  legend + scrubber + layer title, backdrop-blurred over the canvas.

### 9.2 The basemap lightness is load-bearing

`tokens.css` §6 fixes `--map-land` at `oklch(90% …)` light / `oklch(46% …)` dark —
**mid-grey in dark mode, never near-black.** Reason: the arrival ramp's lightest
band `#bdd7e7` must stay visible against unflooded land. Push the base toward white
and ">120 min" vanishes; push it toward black and that band becomes the brightest
thing on the map, inverting the urgency reading. Both failures are silent. Do not
"improve" the basemap to pure white or true-black dark mode.

### 9.3 Front-advance scrubber — the demo moment, and its honesty label

There are **no per-timestep depth rasters** in the backend output — it exports
maxima and arrival time only. So a literal "replay the simulation" scrubber is
**not buildable** from current data, and a delegate must not design one against
data that doesn't exist.

**But the arrival-time raster *is* a time field.** Thresholding
`arrival_time_min ≤ t` yields the set of cells flooded by minute `t` — an honest
advancing front. The scrubber sweeps `t` from 0 to `last_arrival_min`; the front
grows monotonically; isochrone bands (§6.6) light up as `t` crosses 15/30/60/120.

**This must be labelled "front advance (from arrival time)," never "simulation
playback."** It shows *where the wave has reached by minute t*, not the depth
field at minute t. Depth shown alongside is peak depth, not depth-at-t. Getting
this label wrong is an overclaim; getting it right is another honesty win. Under
`prefers-reduced-motion`, the scrubber steps between the four band thresholds
instead of interpolating.

---

## 10 · (folded into §9 and §11)

---

## 11 · Honesty UI — not optional

The backend does the accounting; the frontend must show it. This is the section a
juror will implicitly grade.

### 11.1 The presentable-as-fact badge

Every result carries `honesty.presentable_as_fact` (§6.2). Render a badge on the
console status bar and every history row:

- **`true`** → green (`--color-verified`) "Presentable as fact — all inputs
  verified."
- **`false`** → neutral (never red — this is not an error), with a click-through
  to `blocking_reasons`. A run with damage figures is *always* false; that is
  correct, not a bug (§6.7).

### 11.2 The unverified treatment

Any figure whose source is `verified:false` (dam specs pre-B1; anything in
`unverified_inputs`) renders with a distinct, **achromatic** treatment:
`--pattern-unverified` (a 135° hatch) behind the number, plus the spelled-out word
"unverified" and the citation on hover. **Achromatic on purpose** (`tokens.css`
§1): the colour budget is already spent on the ramps, so uncertainty is carried by
pattern + word, not a hue. This is the single most important non-ramp colour
decision in the system. Never carry "unverified" by tinting a number orange or
red.

### 11.3 Number-honesty rules

- Exposure headline uses `reported_population` (2 sig figs), not
  `total_population` (§6.7).
- `null` / `arr_min == -1` → "not reached," never "0" (§6.3, §6.8).
- Damage is always a range via `formatted`, always inside the estimate treatment
  (§6.7).
- `interpolated_flooded_cells > 0` → a footnote that some flooded cells sit on
  interpolated DEM terrain and are weaker evidence.
- `volume_error` shown in provenance; if `|error| > 1e-6` the backend already adds
  a limitation string — surface it.

### 11.4 The limitations list & disclaimer

`honesty.limitations` (deduped, human-readable) renders as a bulleted list in the
console drawer and the report, capped at `--measure-prose`. The `MODEL_DISCLAIMER`
(§6.9) renders verbatim on landing, console, and report. Includes the standing
caveats: **arrival ≠ warning time**; **Chamoli is a debris flow** the SWE only
approximates; resolution limits.

---

## 12 · Mock fixtures

Build the whole frontend against these before `api/` exists. Put them in
`frontend/src/mocks/`. Shape them **exactly** like §6. Illustrative Tehri example
(numbers are placeholder-but-plausible and **must be labelled mock** in any UI that
shows them during development — they are not a real run):

```jsonc
// frontend/src/mocks/run-tehri-90m.json  — SHAPE is contract; NUMBERS are mock
{
  "run_id": "mock-tehri-90m-0001",
  "study_area": "tehri",
  "scenario": "instantaneous full breach",
  "headline": "instantaneous full breach at tehri floods 210 km2; first arrival 12 min after failure; about 68,000 people exposed.",
  "grid": { "shape": [702, 649], "dx_m": 90.0, "crs": "EPSG:32644",
            "transform": [90.0, 0.0, 600000.0, 0.0, -90.0, 3400000.0] },
  "run": { "duration_s": 21600.0, "wall_time_s": 96.0, "steps": 41200,
           "volume_error": 3.1e-9, "solver": { "cfl": 0.4, "riemann": "HLLC" } },
  "results": {
    "flooded_area_km2": 210.0, "total_wetted_area_km2": 262.0,
    "peak_depth_m": 48.2, "peak_speed_ms": 14.6,
    "first_arrival_min": 12.0, "last_arrival_min": 143.0,
    "area_by_hazard_km2": { "Low": 41.0, "Moderate": 58.0, "Significant": 62.0, "Extreme": 49.0 },
    "area_by_aidr_class_km2": { "H1": 22.0, "H2": 30.0, "H3": 41.0, "H4": 44.0, "H5": 40.0, "H6": 33.0 },
    "area_by_arrival_band_km2": { "0-15 min": 34.0, "15-30 min": 47.0, "30-60 min": 58.0, "60-120 min": 51.0, ">120 min": 20.0 },
    "interpolated_flooded_cells": 1840,
    "exposure": {
      "total_population": 68420, "reported_population": 68000,
      "by_hazard": { "Low": 9000, "Moderate": 17000, "Significant": 22000, "Extreme": 20000 },
      "by_arrival_band": { "0-15 min": 15000, "15-30 min": 19000, "30-60 min": 18000, "60-120 min": 12000, ">120 min": 4000 },
      "cross_tab": { "Extreme|0-15 min": 8000, "Significant|15-30 min": 7000 },
      "infrastructure": { "buildings": 14200, "road_km": 88.0, "hospitals": 3, "schools": 21 },
      "resample_report": { "conserved": true, "residual_fraction": 0.002 }
    }
    // NOTE: omit "damage" in the default fixture; add a second fixture WITH damage
    // to exercise the permanently-not-presentable path (§6.7).
  },
  "provenance": {
    "terrain": { "dem": "MERIT/SRTM (mock)", "conditioning": ["pit-fill", "burn-streams"] },
    "breach": { "mode": "parametric", "width_m": 600, "depth_m": 230, "formation_s": 3600 }
  },
  "honesty": {
    "presentable_as_fact": false,
    "blocking_reasons": ["11 input citation(s) are not verified against a primary source"],
    "unverified_inputs": ["Tehri reservoir gross storage 3.54e9 m3 (source not yet verified)"],
    "limitations": [
      "Arrival time is measured from failure and is NOT warning time.",
      "1,840 flooded cells (0.9%) sit on interpolated DEM terrain; depths there are weaker evidence."
    ]
  }
}
```

Also provide: `study-areas.json` (the three), `run-tehri-90m-with-damage.json` (to
exercise §6.7), `run-nothing-flooded.json` (`first_arrival_min: null`, to exercise
§6.3), `isochrones-tehri.geojson`, `settlements-tehri.geojson` (with at least one
`arr_min: -1`), and `manifest-tehri.json`.

---

## 13 · Accessibility

WCAG 2.2 AA. Consequences already baked into tokens: saffron never carries light
text (§2.1); focus ring is navy (light) / bright-saffron (dark), never
transitioned. Additionally: hazard/arrival meaning must **never** be
colour-only — the legend leads with the class label and the map popups state the
class in words (a red-green colour-blind user, or a B/W printout, must still read
"Extreme — 12 min"). Keyboard: layer switch, scrubber, and settlements table are
fully operable; scrubber is an ARIA slider with `aria-valuetext` = "minute 45 of
143." Respect `prefers-reduced-motion` (§2.5, §9.3). Devanagari and Latin both hit
AA contrast.

---

## 14 · Traps — read before building

1. **Do not invent metrics** anywhere (Hallmark gate 46). Credibility here is
   validation + honesty; one fake stat destroys it. Use real numbers or none.
2. **`null`/`-1` = "not reached," never "0."** (§6.3, §6.8.)
3. **`flooded_area_km2` for the headline, not `total_wetted_area_km2`.** (§6.3.)
4. **`reported_population` (2 sig figs), not `total_population`.** (§6.7.)
5. **Damage is always a range and always not-presentable-as-fact.** (§6.7.)
6. **Ramps are generated, off-brand, and never harmonised toward saffron.**
   (§2.2, §6.5.) Import from `frontend/src/lib/ramps.generated.ts`; a CI check
   fails the build if that file drifts from the backend constants.
7. **No "simulation playback" — it's "front advance from arrival time."** (§9.3.)
8. **Never imply Delft3D was run.** Render `SOLVER_ATTRIBUTION` verbatim. (§6.9.)
9. **No DEM/FRL agreement claim.** (§4.2.)
10. **Heavy rasters are not in Supabase.** (§8.)
11. **Basemap lightness is fixed; don't purify it to white or true-black.** (§9.2.)
12. **No re-drawn browser/phone/IDE chrome** (Hallmark gate 47) — real screenshots
    in a `<figure>`, or nothing.
13. **Mobile floor 320/375/414/768 px**, no horizontal scroll (`overflow-x: clip`,
    never `hidden`), no two-line clickable text, `minmax(0,1fr)` on image tracks,
    `overflow-wrap: anywhere` on display headings. The console map degrades to a
    stacked layout on mobile (map → headline → settlements), not a broken 3-column
    grid.

---

## 15 · Recommended build order for the delegate

1. **Design system** — wire `frontend/design/tokens.css`, load the four fonts,
   build the base primitives (Button, Stat tile, Legend, Badge, Unverified mark).
   Verify all four mobile widths and both registers before building pages.
2. **Mock layer** — the §12 fixtures + a typed client that reads them, with the
   base URL swappable to §7 later. Type the §6.2 shape in TypeScript now; it is the
   contract.
3. **Landing group** — `/`, `/scenarios`, `/scenarios/[key]`, `/validation`,
   `/methodology`, `/about`. Static-friendly, chromatic register. Screenshots for
   the deck come from here — get an honest-looking landing early.
4. **Auth + Supabase** — `/login`, `/signup`, the schema (§8), RLS.
5. **Console** — `/runs`, then `/runs/[run_id]`: headline → layer switch → map →
   settlements table → exposure panel → honesty drawer → export bar → scrubber
   last (it's the hardest and the least essential to a first working demo).
6. **`/runs/[run_id]/report`** — print CSS.
7. **Swap mocks → real API** when `api/` (§7) lands.

Everything in §6 is a hard contract. Everything in §2 and §11 is what separates
this from every other team's blue blob. Build both.

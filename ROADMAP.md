# ROADMAP — remaining work

Forward-looking plan, written 29 August 2026. `PLAN.md` remains the master
reference for physics, validation strategy and jury Q&A; this file covers **what
is left to build, in what order, and how we will know each piece is done.**

Read the ledger first, then the dependency spine, then the work items.

---

## 1. Where things stand

Full test suite: **433 tests, all passing, 48 s.**

### Simulation core — the hard part, nearly done

| Component | Lines | Tests | % | Note |
|---|---|---|---|---|
| `solver/flux.py` (HLLC Riemann) | 157 | 105 | **100%** | Consistency, symmetry, contact upwinding, dry states |
| `solver/reconstruct.py` (MUSCL limiters) | 116 | 60 | **100%** | TVD, linear exactness, antisymmetry |
| `solver/swe2d.py` (2D SWE core) | 1429 | 142 | **92%** | Ladder rungs 1–3 green; rung 4 blocked (B3) |
| `scenario/breach.py` | 1002 | 80 | **95%** | Blocked on source verification (B2) |
| `validation/analytical.py` | 176 | — | **90%** | Backs Ritter + Stoker |
| `solver/sph2d.py` | — | — | **0%** | Not started (W8) |

### Terrain & configuration

| Component | Lines | Tests | % | Gap |
|---|---|---|---|---|
| `terrain/hydrology.py` | 609 | 36 | **90%** | Two snap defects (B4) — **blocks trustworthy runs** |
| `terrain/dem.py` | 611 | **0** | **70%** | No tests |
| `terrain/roughness.py` | 509 | **0** | **70%** | No tests |
| `config.py` | 873 | — | **85%** | 11 figures `verified=False` (B1) |

### Product layer — all at zero

| Component | State | % |
|---|---|---|
| `analysis/` — arrival time, hazard, exposure, damage | empty `__init__.py` | **0%** |
| `export/` — GeoTIFF, COG, **Shapefile, KML**, PDF | empty `__init__.py` | **0%** |
| `scenario/run.py` — orchestrator | absent | **0%** |
| `api/` — FastAPI | no files | **0%** |
| `frontend/` — Next.js + deck.gl | `src/` exists, **zero files** | **0%** |
| `gee/` — Sentinel-1 | empty `__init__.py` | **0%** |
| Delft3D interop | absent | **0%** |
| Validation figures | ladder asserts, emits no charts | **0%** |

### Overall: ~40% by deliverable, ~60% by risk retired

Two framings, because they differ and the difference is the point.

**~40% of deliverables exist.** The missing product layer is roughly 45% of the
remaining build effort.

**~60% of the risk is retired.** A validated 2D shallow-water solver was the one
thing that could have failed outright. It hasn't. What remains is largely
conventional full-stack and geospatial work with known answers.

### The uncomfortable part

`CLAUDE.md` says: *"The differentiator is arrival time + exposure, not the
inundation map"*, and *"**Never cut:** validation charts, arrival-time map,
exposure numbers, .shp/.kml export."*

**Three of those four are at 0%.** The solver computes arrival time internally
(`SWE2D.arrival_time`, `track_maxima`) but nothing extracts, analyses or exports
it. As of today the project cannot produce one file a district officer could
open.

---

## 2. Dependency spine

```
config.py ──► terrain (dem → roughness → hydrology) ──┐
                                                       ├──► SWE2D run ──► analysis ──► export
scenario/breach.py ────────────────────────────────────┘         │            │
                                                                 │            └──► PDF / SHP / KML / COG
                        population raster (D1) ──────────────────┤
                        settlement gazetteer (D3) ───────────────┘

scenario/run.py  wires all of the above
      └──► api/  ──►  frontend/

independent:  validation figures · SPH · Delft3D adapter · GEE
```

Three things follow from this graph:

1. **`analysis/` is the neck.** Export, PDF, API and frontend all consume it.
   Nothing downstream can start in earnest until it exists.
2. **Exposure has an unmet data dependency (D1, D3).** The headline number needs
   a population raster and settlement names, and neither is on disk.
3. **B4 (hydrology snap) gates every real run.** If the breach injects into a
   12 km² tributary instead of the 196 km² Bhagirathi trunk, every depth,
   velocity, arrival time and exposure figure downstream is wrong. This must be
   fixed *before* the first headline run, not after.

---

## 3. Work items

Each has a goal, the PS linkage, files, and an acceptance test — "done" means the
acceptance criterion is demonstrated, not that code exists.

### W1 · Finish `solver/` — the last 8%
- **Do:** `tests/test_boundaries.py`, pinning both halves of the open-boundary
  trade-off documented in `_extend_static`: (a) lake-at-rest holds to machine
  precision with the flat bed copy; (b) continuing the bed instead breaks it,
  producing a spurious current at Manning normal velocity; (c) the outflow
  backwater stays inside `OPEN_BC_INFLUENCE_CELLS`.
- **Accept:** tests green; a test references `OPEN_BC_INFLUENCE_CELLS` so the
  constant cannot drift from the measured extent.
- **Size:** small. **Blocked:** no.

### W2 · Validation figures
- **Do:** `validation/figures.py` + `scripts/make_validation_figures.py`.
  One PNG per rung into `outputs/figures/`: lake-at-rest residual velocity vs
  time (log axis), Ritter depth profile vs analytical at three times, Stoker the
  same on a wet bed, Manning normal-depth convergence plus the first-order
  splitting-error line, and a mass-conservation trace.
- **Why:** `CLAUDE.md` never-cut list; `PLAN.md` wants these for the deck. The
  ladder currently passes invisibly — nothing shows a jury that it passes.
- **Accept:** five PNGs, each overlaying numerical against analytical with L2 and
  L∞ error in the title.
- **Size:** small. **Blocked:** no. **High value per hour — do early.**

### W3 · `analysis/` — the differentiator
- `hazard.py` — depth×velocity hazard classification against a **published**
  scheme (DEFRA/EA hazard rating, or AIDR/AR&R classes). `SWE2D.max_dv` already
  provides the product. Cite the scheme; do not invent thresholds.
- `arrival.py` — arrival-time post-processing: threshold masking, conversion to
  minutes, isochrone extraction at 15/30/60/120 min as polygons.
- `exposure.py` — zonal population (rasterstats) and infrastructure (osmnx
  buildings/roads) per hazard class **and** per arrival band. Needs D1 + D3.
- `damage.py` — depth–damage curves from a cited source; report **ranges, not
  point values**, per the never-overclaim rule.
- `summary.py` — the response-ready result object that `export/` consumes,
  carrying uncertainty and resolution caveats as first-class fields.
- **Accept:** given a finished run plus a `TerrainGrid`, produce a dataclass with
  max-depth/velocity/hazard rasters, arrival raster + isochrones, population per
  (hazard × arrival band), infrastructure counts, a damage *range* with its
  citation, and explicit limitation strings. Tests use synthetic fields with
  analytically known answers (uniform depth over a known population raster gives
  an exact expected count).
- **Size:** large. **Blocked:** partially — exposure needs D1/D3; hazard,
  arrival and damage do not. Build in that order so progress is not gated.

### W4 · `export/` — the PS-mandated formats
- `raster.py` — GeoTIFF and COG (rio-cogeo) for depth, velocity, hazard, arrival.
  Correct nodata; carry `TerrainGrid.mask_valid` so interpolated DEM voids are
  visible rather than silently presented as data.
- `vector.py` — polygonise the inundation extent (`rasterio.features.shapes` plus
  scikit-image cleanup) → GeoDataFrame → **Shapefile** (pyogrio) and **KML**
  (simplekml). Isochrones too.
- `report.py` — reportlab PDF: maps, exposure tables, per-settlement arrival
  table, an assumptions-and-limitations page, citations.
- `metadata.py` — JSON provenance sidecar: DEM source and conditioning steps,
  Manning source, breach parameters, solver settings, CFL, resolution, and
  **every `verified=False` flag that fed the run**.
- **Accept:** one scenario yields `.tif`, `.cog.tif`, `.shp` (+`.shx`/`.dbf`/
  `.prj`), `.kml`, `.pdf`, `.json`; the vector outputs round-trip through
  geopandas and open in QGIS/Google Earth.
- **Size:** medium. **Blocked:** needs W3.

### W5 · `scenario/run.py` — orchestrator
- **Do:** `run_scenario(area, failure_spec, resolution) -> ScenarioResult`,
  wiring config → terrain → roughness → hydrology → breach → solver → analysis →
  export, with progress callbacks and a reproducible run manifest under
  `outputs/<run_id>/`.
- **Accept:** one CLI command produces every artefact for Tehri at 90 m, and the
  manifest is sufficient to reproduce the run.
- **Size:** medium. **Blocked:** needs W3, W4, **and B4** — see the spine.

### W6 · `api/` — FastAPI
- Endpoints: list study areas, submit run, stream progress (websockets), fetch
  artefacts, serve COG tiles.
- **Accept:** local uvicorn drives a full run and serves results; OpenAPI docs
  render.
- **Size:** medium. **Blocked:** needs W5.

### W7 · `frontend/` — Next.js + deck.gl
- Indian-flag palette for chrome (saffron / white / green / navy) with a
  **separate perceptual ramp** for depth and hazard — the two must not be
  conflated.
- Views: 3D terrain with inundation, arrival-time isochrones, exposure panel,
  timeline scrubber, export buttons.
- **Accept:** pick Tehri, run it, watch the wave, read arrival time at a named
  village, download `.shp`/`.kml`.
- **Size:** large. **Blocked:** needs W6 (can begin against mock JSON).

### W8 · SPH near-field (`solver/sph2d.py`)
- 2D weakly-compressible SPH for breach dynamics, coupled out as a hydrograph so
  the routing solver is unchanged. `CLAUDE.md`'s cut order permits degrading this
  to a 1D demo case.
- **Accept:** a 1D/2D dam-break SPH case that reproduces the analytical or
  published result, and whose outflow hydrograph can drive `add_inflow`.
- **Size:** large. **Blocked:** no, but lower value than W3–W5.

### W9 · Delft3D interop
- **Scope, given the standing constraint:** a Delft3D-FM–compatible **case
  exporter** (UGRID NetCDF mesh + `.mdu` + boundary conditions — `netcdf4` is in
  the environment for exactly this) plus an **importer for published Delft3D
  output** so we can plot ours against theirs.
- **Non-negotiable:** we have not run Delft3D, and no artefact — code comment,
  slide, PDF or spoken answer — may imply we have. The claim is *"solver-agnostic
  framework with a Delft3D-compatible I/O adapter, compared against published
  Delft3D benchmark output."*
- **Accept:** exported case is structurally valid UGRID; comparison chart against
  a published Delft3D Malpasset result.
- **Size:** medium. **Blocked:** no.

### W10 · GEE Sentinel-1 (`gee/flood_observe.py`)
- SAR flood observation for the Chamoli case. **Must** use
  `ee.batch.Export.image.toDrive()` — never `toCloudStorage()`, as the Community
  tier has no billing account.
- **Size:** medium. **Blocked:** no. **First item in the cut order.**

### W11 · Documentation truth-up
- `context.md` §15 (Delft3D workflow, build-state table, Tehri provenance, domain
  extent) is stale.
- `PLAN.md:19` "GEE approval takes days" and the DEM-acquisition risk row are
  stale — both resolved.
- `CLAUDE.md` "Current state" says only `PLAN.md`/`environment.yml`/`.gitignore`
  are done; it is many thousands of lines out of date.
- `CLAUDE.md`'s 15–30 min claim for the 30 m run is **unverified** (R3).
- `backend/requirements.txt` does not exist. Per the environment design rule it
  should probably stay that way; if the API deployment needs one, generate it with
  the `--no-deps` caveat recorded.

---

## 4. Blocked items

| ID | Item | Blocker | Unblock |
|---|---|---|---|
| **B1** | 11 `verified=False` figures in `config.py` | Research quota exhausted | Retry CWC / NRLD / THDC sources. **Hard gate: nothing unverified reaches a slide.** |
| **B2** | 4 `EMPIRICAL_SOURCES` entries in `breach.py` all `False` | Same | Froehlich, MacDonald, USBR, Xu–Zhang primary references |
| **B3** | Malpasset validation rung 4 | Reyran valley bathymetry absent | Source valley bathymetry + 17 surveyed high-water marks + 2 police-gauge timings |
| **B4** | Two `terrain/hydrology.py` snap defects | Design decision needed | See below — **gates W5** |

**B4 in detail.** Tehri currently injects into a 12.1 km² tributary while the
196.4 km² Bhagirathi trunk sits 1.70 km away (flagged SUSPECT). Rishikesh snaps
silently into a 5.5 km² channel that is not on the downstream trace, while
Haridwar correctly picks up 2,770.9 km² and is on it. The 2× suspect radius
(±1.44 km) is too small to find the Ganga at Rishikesh. Likely fix: snap to
maximum contributing area within a radius scaled to the *expected* trunk area,
and allow hand-placed coordinates in `config.py` carrying explicit provenance.

---

## 5. Data gaps

| ID | Need | For | Status |
|---|---|---|---|
| **D1** | Population raster (WorldPop 100 m constrained, or GHSL GHS-POP) | Exposure — **the headline number** | **Absent.** `data/` holds only `dem/`, `landcover/`, `reference/`. Large download — start early. |
| **D2** | OSM buildings/roads | Infrastructure exposure | Fetched live by osmnx; cache an extract for reproducibility |
| **D3** | Settlement gazetteer (OSM places or Census 2011 village points) | Naming villages in the arrival table | **Absent.** Without it, "water reaches this village in 47 minutes" has no village. |
| **D4** | Malpasset bathymetry | B3 | Absent |

---

## 6. Risk register

| ID | Risk | Severity | Mitigation |
|---|---|---|---|
| **R1** | The differentiator (exposure) is 0% built *and* data-blocked | **High** | Start D1/D3 acquisition before writing `exposure.py` |
| **R2** | B4 snap defects put the breach in the wrong channel, invalidating every downstream number | **High** | Fix B4 before the first headline run; keep the SUSPECT flag loud |
| **R3** | 30 m runtime unverified against the claimed 15–30 min | Medium | Time it once the orchestrator exists; correct the claim if wrong |
| **R4** | An unverified figure reaches a slide | **High** (credibility) | `export/metadata.py` records every `verified=False` input; treat as a release gate |
| **R5** | Frontend is 0% and is the demo surface | Medium | Can be built against mock JSON in parallel with W5/W6 |
| **R6** | Chamoli was a debris flow; SWE only approximates it | Medium | Already the standing position: bulking factor + elevated roughness, stated plainly, never hidden |

---

## 7. Recommended order

The originally stated order was solver → breach → config → hydrology. Worth
revisiting: **`breach.py` (95%), `config.py` (85%) and `hydrology.py` (90%) are
all blocked on the exhausted research quota** — their remaining work is source
verification, not code. Meanwhile the never-cut deliverables sit at 0% and are
fully unblocked.

**Phase 1 — make it a product (all unblocked)**
1. W1 finish `solver/`
2. W2 validation figures
3. Start D1 + D3 data acquisition (long downloads, run in background)
4. W3 `analysis/` — hazard, arrival, damage first; exposure when D1/D3 land
5. B4 hydrology snap fix — **before** any headline run
6. W4 `export/`
7. W5 `scenario/run.py`

End of Phase 1: a real end-to-end run producing GeoTIFF, Shapefile, KML and a
PDF, with an arrival-time map and exposure numbers. That is the PS satisfied.

**Phase 2 — make it demonstrable**
8. W6 `api/` · 9. W7 `frontend/`

**Phase 3 — differentiate further**
10. W9 Delft3D interop · 11. W8 SPH · 12. W10 GEE

**Phase 4 — truth-up**
13. W11 docs · 14. B1/B2 verification when the research quota returns · 15. B3/D4
    Malpasset rung if bathymetry can be sourced

**Cut order if time compresses** (from `CLAUDE.md`): GEE first, then SPH down to
a 1D demo, then 3D terrain down to 2D. Never cut validation charts, the
arrival-time map, exposure numbers, or `.shp`/`.kml` export.

---

## 8. Jury-defence ledger

Findings that must be stated aloud rather than buried. Volunteering an understood
limitation is what earns trust.

1. **Manning friction had a real bug, caught by a purpose-built rung.** The term
   was wrong by exactly a factor of `h` — invisible at 1 m depth, 20× too weak at
   20 m. At Bhagirathi flood depths it made a forested gorge (n = 0.087) behave
   like smooth concrete, so **every arrival time was too early** — the most
   dangerous possible direction. Nothing caught it because Ritter, Stoker and
   lake-at-rest are all frictionless. Manning normal depth is the only closed-form
   check on friction, and it now exists.
2. **The friction substep is exact, not merely stable**, so the entire friction
   time error lives in the operator split. That error has a closed form,
   `u_steady/u_normal = 1 − dt·g·S₀/(2·u_normal)`, converges at first order as
   measured, and biases arrival times slightly **late** — the safe direction.
3. **The open-boundary bed treatment is a deliberate trade-off, not an
   oversight.** A zero-gradient transmissive boundary cannot be exact for both
   still water and uniform flow on a slope. We keep the still-water-exact form
   (residual velocity 2×10⁻¹⁴ m/s); the alternative makes uniform flow exact but
   accelerates a still lake to 2.15 m/s — Manning normal velocity — which is the
   failure the well-balanced property exists to prevent. The cost is a backwater
   confined to ~8 cells at the outflow, recorded as
   `OPEN_BC_INFLUENCE_CELLS = 10`; the domain must extend that far past anything
   we report (900 m at 90 m, 300 m at 30 m).
4. **HLL-family solvers overestimate flux at a fully dry interface** by 2.25×
   versus Ritter's exact value. That is the known cost of collapsing a
   rarefaction fan onto one state; scheme-level dry-bed accuracy is established by
   the Ritter rung over a resolved front, not by a single face.
5. **We have not run Delft3D**, and will not claim to. The position is a
   solver-agnostic framework with a Delft3D-compatible I/O adapter, compared
   against *published* Delft3D benchmark output.
6. **Chamoli was a debris flow**, a sediment slurry that the shallow water
   equations only approximate via a bulking factor and elevated roughness.
7. **The Tehri DEM/FRL agreement was cell luck.** At the NRLD coordinate the DEM
   reads 819.4 m (90 m) / 816.6 m (30 m) against a published FRL of 830.0 m. Do
   not put "matches FRL to 0.3 m" on a slide.
8. **Resolution is a design point, not a compromise:** 90 m for interactive runs,
   30 m precomputed for high-resolution output.

Statutory framing: Dam Safety Act 2021 (mandates dam-break studies and Emergency
Action Plans), NDMA GLOF guidelines, CWC inundation-mapping guidelines, Sendai
Framework Priority 4.

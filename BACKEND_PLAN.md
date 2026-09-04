# BACKEND_PLAN.md — the road to 100%

**Written 2 September 2026.** This is the authoritative backend completion plan.
It supersedes the "product layer — all at zero" rows in `ROADMAP.md` §1, which were
written on 29 Aug and are stale (analysis/, export/ and scenario/run.py have since
been built and a full Tehri run has succeeded).

It folds in three scope decisions taken 2 Sep 2026:

1. **Delft3D — hybrid now, full replacement later.** Keep the validated custom
   SWE2D solver as the live/interactive engine; **also run real open-source
   Delft3D (D-Flow FM)** on Malpasset + Tehri so the claim *"we ran Delft3D and our
   engine reproduces it"* is **literally true**. After the submission (≈4 months, to
   December 2026) migrate to Delft3D as the primary engine and add true-3D.
2. **GEE stays in** — Sentinel-1 SAR near-real-time flood observation (PS iv).
3. **Database on Supabase** — Postgres + PostGIS for metadata/vectors, Supabase
   Storage for rasters/PDF, Supabase Auth for the existing login/signup pages.

> **The Delft3D honesty rule is unchanged and absolute.** We may say "we ran
> Delft3D" **only after** a real D-Flow FM run exists and is reproducible from a
> committed case. Until that run exists, no code comment, slide, PDF or spoken
> answer may imply it. The hybrid decision does not relax the rule — it *earns* the
> claim by actually doing the run.

---

## 0. What "100%" means — the PS deliverable map

The problem statement (26161) has five explicit deliverables. "100% backend" =
every one of these is demonstrably satisfied by server-side code, with the honesty
gates green.

| PS deliverable | Backend obligation | Today |
|---|---|---|
| **(i)** Generalized framework: dam-break / river-blockage, sudden surge **+ loss & damage**, using **SPH** *and* **Delft3D**, **and compare** | SWE2D (done) + **SPH** (to build) + **real Delft3D run** (to do) + **comparison module** + damage (done) | partial |
| **(ii)** Customized tool, **different input datasets** | `run_scenario(area, ...)` parametrised by `config.py` (done); extend to all 3 areas | mostly done |
| **(iii)** Dashboard I/O + visualization; **large volume of data**; output to **.shp / .kml** | export (done) + **FastAPI** serving (to build) + COG for large data (done) | partial |
| **(iv)** Near-real-time flood analysis via **Google Earth Engine**, open-source data | `gee/flood_observe.py` — Sentinel-1 SAR (to build) | 0% |
| **(v)** Simulate on **any Indian dam/river, open-source data**, at final demo | Tehri + Rishi Ganga runs, **verified** config | partial |

Cross-cutting, not a single deliverable but required to ship: **persistence
(Supabase)**, **serving (FastAPI)**, and the **honesty gates** (validation figures,
verified config, near-field fix, mass conservation).

---

## 1. Where the backend actually stands today (2 Sep 2026)

Grounded in the current tree and the last end-to-end run — not from memory.

### Built and working
| Area | Files | State |
|---|---|---|
| **SWE2D solver** | `solver/swe2d.py`, `flux.py`, `reconstruct.py` | HLLC + MUSCL + well-balanced + wet/dry + Manning; **validation rungs 1–3 green**. The one thing that could have failed outright has not. |
| **Terrain** | `terrain/dem.py`, `hydrology.py`, `roughness.py` | Copernicus fetch → metric grid → void/pit fill → flow routing → Manning-n. Runs. |
| **Breach** | `scenario/breach.py` | Lumped parametric breach + empirical peak regressions (Froehlich/USBR/MLM) as a cross-check. |
| **Orchestrator** | `scenario/run.py` | Wires config→terrain→breach→solver→analysis→export. **A full Tehri 90 m run completed, exit 0, no NaN, mass error −3.4e−3 (legit outflow).** |
| **Analysis** | `analysis/{hazard,arrival,exposure,damage,summary}.py` | Depth×velocity hazard (published scheme), arrival isochrones, zonal exposure, damage **ranges**, and the `ScenarioSummary` honesty ledger. |
| **Export** | `export/{raster,vector,report,metadata}.py` | GeoTIFF/COG, **Shapefile**, **KML**, PDF, JSON provenance sidecar. |

### Not built / incomplete against the 100% target
| Gap | Impact | PS link |
|---|---|---|
| **`solver/sph2d.py` — absent** | PS **names** SPH; no near-field model, no SPH breach hydrograph | (i) |
| **Real Delft3D run — not done** | PS **names** Delft3D + "compare"; only `netcdf4` groundwork exists | (i) |
| **Comparison module — absent** | "Compare the scenario" has nothing to compare | (i) |
| **`api/` — absent** | No way for the dashboard to reach the engine | (iii) |
| **Supabase / any DB — absent** | No persistence; runs live as loose files; specs in `config.py` | (iii),(v) |
| **`gee/` — empty** | No near-real-time observation | (iv) |
| **`validation/figures.py` — absent** | Ladder passes invisibly; never-cut charts don't exist | gate |
| **`config.py` — 18 numbers `verified=False`** | Nothing unverified may reach a slide | gate / (v) |
| **Near-field `reportable_mask` fix — applied, unverified** | Headline peak was a source artefact; fix not yet re-run | gate |
| **B4 hydrology snap — general fix outstanding** | Works for Tehri; Rishikesh/others still mis-snap | (v) |

### Honest progress number

**Backend ≈ 58%.** Two framings, both true:
- **By risk retired: ~75%.** The solver — the only irrecoverable failure mode — is
  built and validated. Most of what remains is conventional geospatial + full-stack
  assembly with known answers.
- **By deliverable surface: ~55%.** SPH, the real Delft3D run, the comparison, the
  API, the database and GEE are each substantial and sit near zero.

> **Why this is lower than the "~80%" you heard elsewhere.** That estimate counted
> only the compute pipeline (solver + terrain + analysis + export), which *is* ~85%
> done. It predated adding **real Delft3D**, **SPH** and **Supabase** to the
> definition of done, and it never counted the **API/DB/GEE** that were always
> required. Against the full PS scope you've now confirmed, ~58% is the honest read.
> This is not backtracking — the target got larger and more correct.

---

## 2. Target architecture — how SPH, Delft3D and SWE2D fit together

The PS wants two named models and a comparison. Here is the honest, coherent split
(and it is defensible physics, not a hack to tick a box):

```
                       ┌─────────────────────────────────────────────┐
                       │  BREACH / NEAR FIELD  (violent, non-hydrostatic) │
   reservoir  ─────►   │        SPH  (solver/sph2d.py, ours)          │
   (published storage) │   free-surface, plunging flow — SWE invalid here │
                       └───────────────┬─────────────────────────────┘
                                       │  outflow hydrograph Q(t), u(t)
                          ┌────────────┴────────────┐
                          ▼                          ▼
        ┌───────────────────────────┐   ┌───────────────────────────────┐
        │ FAR FIELD — FAST / LIVE    │   │ FAR FIELD — REFERENCE          │
        │ our SWE2D (validated)      │   │ real Delft3D D-Flow FM (2DH)   │
        │ 90 m interactive, 30 m HR  │   │ Malpasset + Tehri, batch       │
        └─────────────┬──────────────┘   └───────────────┬───────────────┘
                      └──────────────┬───────────────────┘
                                     ▼
                     COMPARISON MODULE  ("compare the scenario", PS i)
              extent · peak depth · peak velocity · arrival time · hydrograph
              our SWE2D  vs  real Delft3D  vs  published benchmark
```

Physical justification (the jury will ask):
- **SPH near the breach** because the flow there is violently non-hydrostatic —
  vertical acceleration is *not* negligible, so the depth-averaged shallow-water
  assumption is invalid. SPH is meshfree and handles the free surface and the
  plunging jet. Its job is to produce a defensible **breach outflow hydrograph**,
  which then drives *both* far-field engines. This is standard near-field/far-field
  coupling.
- **Depth-averaged 2D (2DH) for far-field routing** because once the wave is
  spreading over kilometres of valley, depth ≪ horizontal scale and hydrostatic
  pressure is an excellent assumption. This is the industry standard for inundation
  extent, and **Delft3D itself is run in 2DH for flood mapping.** True 3D (vertical
  layers) buys almost nothing for the flood *map* and is deferred to December.
- **Two far-field engines** because the PS asks us to compare. Agreement between an
  independent professional code (Delft3D) and our own solver is the strongest
  validation statement we can make, and disagreement is diagnostic.

"3D" for the jury is the **deck.gl terrain visualization** (frontend), not 3D
physics. That distinction stays crisp in every artefact.

---

## 3. Phases and work items

Ordered by dependency and value. Each item: **goal · PS link · files · acceptance
· risk**. "Done" = the acceptance test is demonstrated, not that code exists.

Two tracks run in the background from day one because they are slow and mostly
research, not code:
- **T-DATA** — acquire population raster (WorldPop/GHSL, D1) + settlement gazetteer
  (D3). The exposure headline number is blocked on these.
- **T-VERIFY** — verify the 18 `verified=False` numbers in `config.py` against
  CWC / National Register of Large Dams / THDC (B1, B2). Fan-out-able to subagents.

### Phase 0 — Close the honesty gaps on the pipeline we already have
Small, high-value, unblocks a trustworthy demo. Do first.

**P0.1 · Verify the near-field `reportable_mask` fix**
- Goal: re-run Tehri 90 m and confirm the headline peak depth/velocity are now taken
  *outside* the near-field source zone and the open-boundary buffer, with the raw
  near-field peak reported separately (not hidden).
- Files: none (run `scripts/check_scenario.py --dx 90 --run`); inspect `summary()`.
- Accept: headline peak depth is physically plausible (water surface below dam
  crest away from the source); `peak_depth_nearfield_m` is reported and labelled
  "source zone — NOT reportable".
- Risk: low. Fix is applied; this is verification.

**P0.2 · B4 canonical hydrology snap fix**
- Goal: generalise the pool-aware trunk search that works for Tehri so Rishikesh
  and other POIs snap to the real trunk, not a 5 km² side channel. Allow
  hand-placed coordinates in `config.py` carrying explicit provenance, and scale
  the search radius to the *expected* trunk contributing area.
- Files: `terrain/hydrology.py`, `config.py`, `tests/test_hydrology.py`.
- Accept: every configured POI either lands on a cell whose contributing area is
  within a stated fraction of the expected trunk area, or is flagged SUSPECT loudly.
- Risk: medium. Gates trustworthy multi-area runs (PS v).

**P0.3 · Validation figures (`validation/figures.py`)** — *never-cut deliverable*
- Goal: one PNG per rung into `outputs/figures/`: lake-at-rest residual velocity vs
  time (log), Ritter depth profile vs analytical at 3 times, Stoker on a wet bed,
  Manning normal-depth convergence + splitting-error line, mass-conservation trace.
- Files: `validation/figures.py`, `scripts/make_validation_figures.py`.
- Accept: 5 PNGs, each overlaying numerical vs analytical with L2 / L∞ in the title.
- Risk: low. High value per hour — it's what shows a jury the solver is correct.

**P0.4 · Inspect the exported bundle**
- Goal: confirm the last run's `.tif/.cog.tif/.shp/.kml/.pdf/.json` open correctly
  (QGIS / Google Earth / geopandas round-trip).
- Accept: vector round-trips through geopandas; KML opens in Google Earth; COG is
  valid; PDF carries the limitations page and any UNVERIFIED watermark.
- Risk: low.

### Phase 1 — The PS-named models: SPH + real Delft3D + comparison
This is the heart of deliverable (i) and the biggest correctness win.

**P1.1 · SPH near-field (`solver/sph2d.py`)** — *PS-named*
- Goal: 2D weakly-compressible SPH for breach dynamics; output a breach outflow
  **hydrograph** Q(t), u(t) that drives `SWE2D.add_inflow`. Start with a validated
  1D/2D dam-break SPH case; degrade to 1D only if 2D proves unstable in the time we
  have (it won't be time-boxed away — correctness is binding — but 1D is an
  acceptable first rung).
- Files: `solver/sph2d.py`, `tests/test_sph.py`, hook in `scenario/breach.py`.
- Accept: SPH dam-break reproduces the Ritter/analytical solution within a stated
  tolerance; its hydrograph feeds `run_scenario` and the resulting far-field run is
  sane. Peak outflow is cross-checked against the empirical regressions already in
  `breach.py`.
- Physics to explain: weak compressibility (Tait EOS), kernel choice (Wendland),
  XSPH, artificial viscosity, δ-SPH density diffusion, boundary particles. All
  defensible, all standard.
- Risk: medium–high (SPH stability). Independent of everything else — can build in
  parallel with Phase 0.

**P1.2 · Delft3D case exporter + importer (`export/delft3d.py`, `io/delft3d.py`)**
- Goal: write our terrain + breach hydrograph as a **D-Flow FM case** (UGRID NetCDF
  network, `.mdu` master file, boundary `.ext`/`.bc`); read D-Flow FM map output
  (`*_map.nc`) back onto our grid for comparison. `netcdf4` is already in the env
  for exactly this.
- Files: `export/delft3d.py`, `jaldrishti/io/delft3d.py`, tests.
- Accept: exported case is structurally valid UGRID; a published Delft3D Malpasset
  result imports and plots against ours.
- Risk: medium. Format details (`.mdu` keys, UGRID conventions) confirmed at build
  time — see the research spike in §7.

**P1.3 · Actually run Delft3D (D-Flow FM) — Malpasset, then Tehri**
- Goal: install open-source D-Flow FM on Windows; run **Malpasset** (the canonical
  dam-break benchmark) in **2DH**, then **Tehri**. This is what converts "adapter"
  into "we ran Delft3D."
- Steps: research spike (§7) → install → build the two cases via P1.2 → run batch →
  import results → archive the case + logs under `outputs/delft3d/<case>/` so the
  run is reproducible and the claim is earned.
- Accept: a committed, reproducible D-Flow FM case + its output for Malpasset and
  Tehri; the import round-trips.
- Risk: medium (Windows install is the unknown). Not on the interactive path, so a
  slow batch run is fine.

**P1.4 · Comparison module (`analysis/compare.py`)** — *"compare the scenario"*
- Goal: quantitatively compare, on a common grid: our SWE2D vs real Delft3D vs
  published benchmark — on inundation extent (IoU), peak depth, peak velocity,
  arrival time, and the outflow hydrograph (SPH vs empirical). Emit a comparison
  figure + table.
- Files: `analysis/compare.py`, `scripts/make_comparison.py`.
- Accept: for Malpasset, a table of our-vs-Delft3D-vs-surveyed high-water marks and
  arrival times, with error metrics; a figure for the deck.
- Risk: low once P1.2/P1.3 land. **This is the single most jury-persuasive artefact
  in the whole project** — it answers the PS's exact word "compare".

### Phase 2 — Persistence (Supabase) + serving (FastAPI)
Turns the batch pipeline into a product the dashboard can drive. See §5, §6.

**P2.1 · Supabase schema + data-access layer** — §5
- Files: `db/schema.sql` (migrations), `jaldrishti/db/` (SQLAlchemy models +
  storage client via `httpx`).
- Accept: a completed run persists its manifest, honesty ledger, exposure table and
  isochrone geometry to Postgres/PostGIS, and its rasters/PDF/vectors to Storage;
  everything is retrievable by `run_id`.
- Risk: low. Conda-pure path (no pip): `sqlalchemy` + `psycopg` to Postgres,
  `httpx` to the Storage REST API.

**P2.2 · FastAPI app (`api/`)** — §6
- Files: `jaldrishti/api/{main,routes,schemas,deps}.py`.
- Accept: local `uvicorn` lists study areas, submits a run, streams progress over
  websockets, serves artefacts + isochrone GeoJSON + the settlement arrival table +
  the honesty ledger; OpenAPI docs render. Response shapes **match the frontend
  mocks** (`src/mocks/*.json`) so the frontend flips from mock to live by setting
  `NEXT_PUBLIC_API_BASE`.
- Risk: low–medium (websocket progress streaming from the solver callback).

### Phase 3 — GEE near-real-time (deliverable iv)

**P3.1 · Sentinel-1 SAR flood observation (`gee/flood_observe.py`)**
- Goal: SAR-based flood extent for the Rishi Ganga / Chamoli case (and a Tehri
  downstream AOI), exported with **`ee.batch.Export.image.toDrive()`** (never
  `toCloudStorage()` — Community tier has no billing). Ingest the exported mask as
  an *observation* layer to overlay/compare against the *simulated* extent.
- Files: `gee/flood_observe.py`, `gee/auth.py`, `scripts/gee_export.py`.
- Accept: a SAR flood mask GeoTIFF lands in Drive, ingests onto our grid, and
  overlays the simulated extent with an agreement metric.
- Risk: medium (GEE auth + export latency). Additive; does not block the core.

### Phase 4 — Truth-up + final-demo readiness (deliverable v)

**P4.1 · Complete T-VERIFY** — no `verified=False` number on any slide; fix the
Koteshwar POI coordinate.
**P4.2 · Rishi Ganga river-blockage run** — the PS-cited event; state the
debris-flow limitation (bulking factor + elevated n) plainly.
**P4.3 · 30 m high-res + valley mask** — feasibility for the high-res deliverable;
time the run and correct the stale 15–30 min claim.
**P4.4 · Docs truth-up** — `context.md`, `ROADMAP.md`, `CLAUDE.md` "Current state";
generate `backend/requirements.txt` (with the `--no-deps` caveat) for Linux
deployment of the API.

---

## 4. Sequencing / what unblocks what

```
Phase 0 (honesty gates) ──► trustworthy demo of the EXISTING pipeline
   P0.2 (B4) gates every multi-area run

Phase 1 can start in parallel:
   P1.1 SPH        ─ independent
   P1.2 exporter ─► P1.3 run Delft3D ─► P1.4 comparison   (the PS "compare" artefact)

Phase 2 needs a working run (have it) + a decision on Supabase project:
   P2.1 DB ─► P2.2 API ─► frontend flips to live (frontend track)

Phase 3 GEE — independent, additive
Phase 4 — verification (background T-VERIFY) + final-demo runs + docs

Background from day 1:  T-DATA (population + settlements),  T-VERIFY (config specs)
```

Recommended immediate order: **P0.1 → P0.3 → P0.2**, start **T-DATA + T-VERIFY** in
the background, then **P1.1 (SPH)** and **P1.2 (Delft3D exporter)** in parallel,
converging on **P1.4 (comparison)**. Persistence/API (Phase 2) can begin as soon as
you want the dashboard live — it only needs the run output shape, which exists.

---

## 5. Supabase data model

**Principle: metadata + vectors in Postgres/PostGIS; heavy rasters in Storage.**
Never put multi-megabyte GeoTIFFs in a Postgres row.

Enable PostGIS: `create extension if not exists postgis;`

Tables (sketch):
- `study_areas` — key, name, dam spec, breach spec, domain, POIs, **provenance +
  verified flags** (mirror of `config.py`; `config.py` stays the source of truth,
  this is the served copy).
- `runs` — `run_id` (pk), study_area, scenario, params (jsonb), engine
  (`swe2d` | `delft3d`), dx, `created_at`, `duration_s`, `wall_time_s`, steps,
  `volume_error`, `presentable_as_fact` (bool), `honesty` (jsonb: limitations,
  unverified_inputs, blocking_reasons), headline text.
- `run_artifacts` — run_id fk, kind (`depth_cog` | `shp` | `kml` | `pdf` | `json` |
  `delft3d_case`), storage_path, bytes, checksum.
- `exposure_results` — run_id fk, population by (hazard × arrival band) (jsonb),
  infrastructure counts, resample_report.
- `settlements` — gazetteer (D3): name, admin, geometry(Point, 4326), population.
- `isochrones` — run_id fk, band_minutes, geometry(MultiPolygon, 4326).
- `inundation` — run_id fk, geometry(MultiPolygon, 4326), max_depth_class.

Storage buckets: `rasters/` (COG depth/velocity/hazard/arrival), `reports/` (PDF),
`vectors/` (shp bundle + kml), `delft3d/` (case + output). Bucket policy: private;
signed URLs handed out by the API.

Access from Python (conda-pure — **no pip needed**):
- `sqlalchemy` + `psycopg` (both conda-forge; **add to `environment.yml`**) against
  the Supabase Postgres connection string.
- `httpx` (already in env) to the Supabase Storage REST API for uploads + signed
  URLs.
- (Alternative: the `supabase` python client, but it is pip-only → would need
  `pip install --no-deps supabase`. The psycopg + httpx path avoids touching the
  geospatial stack and is preferred.)

Auth: Supabase Auth backs the existing `login/` and `signup/` frontend routes. The
API validates the Supabase JWT on protected endpoints.

---

## 6. FastAPI surface

The frontend already defines the response shapes in `frontend/src/mocks/*.json`
(`study-areas`, `run-tehri-90m`, `manifest`, `isochrones`, `settlements`). The API
contract is therefore *already partly specified* — build to those shapes so the
frontend flips from mock to live by setting `NEXT_PUBLIC_API_BASE`.

Endpoints:
- `GET  /study-areas` → list (from `config.py` / `study_areas` table).
- `POST /runs` → submit `{area, scenario, dx, options}`; returns `run_id`.
- `GET  /runs/{id}` → manifest + honesty ledger + status.
- `WS   /runs/{id}/progress` → live progress from the solver `callback`.
- `GET  /runs/{id}/isochrones` → GeoJSON.
- `GET  /runs/{id}/settlements` → arrival table (name, arrival_min, hazard).
- `GET  /runs/{id}/artifacts` → list; `GET /runs/{id}/artifacts/{kind}` → signed
  Storage URL (shp / kml / tif / pdf).
- COG serving: hand the client a signed URL to the range-readable COG in Storage
  and let deck.gl/maplibre read it directly (simplest); revisit a tile endpoint
  (`rio-tiler`/`titiler`) only if needed.

`uvicorn` + `websockets` + `python-multipart` are already in `environment.yml`.

---

## 7. Delft3D hybrid — the honest plan

**Now (submission): run open-source Delft3D D-Flow FM in 2DH on Malpasset + Tehri
as the reference engine; keep our SWE2D as the live engine.** After submission
(to December): make Delft3D the primary engine and add true-3D on one case.

**Research spike (do before P1.3 — I cannot assert these blind).** Confirm, at
build time, on Windows:
- Which distribution: the free **Delft3D FM Suite** download (Deltares, registration)
  vs the open-source **D-Flow FM** computational core; pick the one with a working
  Windows binary and a batch/CLI entry point.
- Exact input formats for the version we install: `.mdu` master file keys, the UGRID
  `_net.nc` network, boundary forcing (`.ext` + `.bc`), initial/observation files.
- Output: `*_map.nc` (UGRID) variable names for depth/velocity, and how to sample
  them onto our Cartesian grid.
- How to script a headless batch run (so it's reproducible and archivable).

This spike is fan-out-able to a research subagent (breadth), but the actual install
+ run stays in the main loop where the numerics live.

**Malpasset first** because it is *the* documented dam-break benchmark for Delft3D
and TELEMAC, our reference CSVs (surveyed high-water marks, gauge/transformer
timings) are already in the repo, and it gives an apples-to-apples
our-vs-Delft3D-vs-surveyed comparison — the strongest possible validation.

**Honesty checkpoints:**
- Until P1.3 produces a committed, reproducible run, every artefact says
  *"Delft3D-compatible I/O; comparison against published Delft3D benchmark"* — not
  "we ran it".
- After P1.3, artefacts may say *"we ran Delft3D D-Flow FM (2DH) on Malpasset and
  Tehri; results archived at outputs/delft3d/"* — because it is then true.
- We run **2DH** (depth-averaged), matching our physics and the inundation task. We
  never imply 3D physics. True-3D is a December item, clearly labelled experimental.

---

## 8. SPH — the other PS-named model

Deliverable (i) names SPH explicitly, so it is not optional. Role: resolve the
**near-field breach** where shallow-water is invalid, and hand a defensible outflow
hydrograph to both far-field engines.

- Method: 2D weakly-compressible SPH — Tait equation of state, Wendland kernel,
  artificial viscosity + δ-SPH density diffusion for stability, XSPH velocity
  correction, dynamic/repulsive boundary particles.
- Validation: a 1D/2D dam-break SPH case reproducing Ritter within tolerance; peak
  outflow cross-checked against the Froehlich/USBR/MLM regressions in `breach.py`.
- Coupling: SPH → hydrograph → `SWE2D.add_inflow` (and → the Delft3D boundary
  condition), so the *same* breach forcing drives every far-field run and the
  comparison is fair.
- Fallback ladder (if 2D SPH is unstable in the time available): 1D SPH dam-break
  demo case, still coupled out as a hydrograph. Not cut — degraded, and stated.

---

## 9. GEE near-real-time (deliverable iv)

- `gee/flood_observe.py`: Sentinel-1 GRD, VV/VH, speckle-filtered, thresholded (Otsu
  or a fixed dB threshold) to a water mask; pre/post-event change for the Chamoli
  case; **export with `ee.batch.Export.image.toDrive()`**.
- `gee/auth.py`: service-account or interactive auth; never commit credentials
  (`.gitignore` already excludes `service-account*.json`).
- Product: an *observed* flood layer to overlay against the *simulated* extent, with
  an agreement metric — closing the loop between model and satellite, which is
  exactly the "near real-time flood analysis" the PS asks for.

---

## 10. Honesty ledger — what this plan adds to the "state it aloud" list

Carried from `ROADMAP.md` §8, plus new items this plan introduces:
1. **We ran Delft3D D-Flow FM in 2DH** (once P1.3 lands) — and we say *2DH*, not 3D.
   Before that, adapter + published-benchmark only.
2. **SPH resolves only the near field**; the far field is depth-averaged SWE — we
   do not claim SPH for the whole domain.
3. **The breach hydrograph is the coupling interface**; the same forcing drives our
   solver and Delft3D, so the comparison is fair and stated as such.
4. All existing caveats stand: Chamoli debris-flow approximation, Malpasset
   calibrated-not-measured n, reservoir volume from published storage not DEM
   bathymetry, resolution as a design point, `verified=False` numbers gated from
   slides.

---

## 11. Post-submission (≈4 months, to December 2026)

- **Delft3D as primary engine**: migrate the interactive path onto D-Flow FM (or
  keep SWE2D for speed and Delft3D for authority — decide after the comparison
  numbers are in).
- **True-3D hydrodynamics** on a selected case (vertical layers) — clearly
  experimental, for stratification/plunge structure, not the inundation map.
- Broaden study areas (the PS says "any river"), harden the API, and productionise
  the Supabase deployment.

---

## 12. Dependencies to add to `environment.yml`

All conda-forge (keeps the no-`pip` rule intact):
- `sqlalchemy`, `psycopg` — Supabase Postgres access.
(`httpx`, `fastapi`, `uvicorn`, `pydantic`, `websockets`, `python-multipart`,
`netcdf4`, `earthengine-api` are already present.) Delft3D is an **external binary**,
not a Python package — installed separately per §7, not via conda.

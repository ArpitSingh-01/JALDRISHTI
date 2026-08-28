# CLAUDE.md — JALDRISHTI

Project instructions. Read `PLAN.md` for the full roadmap, physics explanation, validation strategy, and day-by-day schedule. This file is the quick brief.

## What this project is

**Smart India Hackathon 2026, Problem Statement 26161** — "Dam Break Inundation Modelling Using Hydrodynamic Modelling of any River." Organisation: National Technical Research Organisation (NTRO). Theme: Disaster Management. Category: Software.

We are building a dam-break and river-blockage flood simulation platform for humanitarian disaster response (HADR). User picks a dam or blockage point in India, defines a failure scenario, and the system simulates the flood wave over real terrain and returns depth, velocity, **arrival time**, population/infrastructure exposure, and damage estimates — exported as GeoTIFF, **Shapefile, KML** (explicitly required by the PS), and a response-ready PDF.

**The differentiator is arrival time + exposure, not the inundation map.** Every competing team will render a blue blob. Telling a district officer "water reaches this village in 47 minutes, 12,400 people must move" is the actual product.

## Working context

- **Arpit Singh** — student, strong full-stack web dev, **new to hydrodynamics and numerical methods**. Explain the physics and numerics as you go; he has to defend this to a technical jury unaided.
- **Effectively a solo builder.** No ML/scientific-computing teammate. Don't design anything that needs a second person.
- **Deadline: ~Friday 4 September 2026.** Both the SIH idea-submission PPT *and* a working prototype are due.
- College/internal round already cleared (on a different PS).
- Windows machine. Conda (Miniforge) for the geospatial stack — **do not pip-install GDAL/rasterio/geopandas on Windows.**

## Locked decisions — do not relitigate

- **Language/stack:** Python + NumPy + **Numba** for the simulation core (pure NumPy is ~100x too slow). FastAPI for the API. Next.js + **deck.gl** for the frontend (GPU 3D terrain = the honest answer to the PS's "large volume of data" requirement).
- **Solvers:** own 2D shallow-water solver (finite volume, **HLLC** Riemann, MUSCL reconstruction, well-balanced bed-slope source term, wetting/drying, Manning friction, CFL-limited explicit stepping) for far-field routing + own **2D weakly-compressible SPH** for near-field breach dynamics, coupled via the SPH outflow hydrograph.
- **Delft3D:** NOT integrated — impossible in a week. Position: solver-agnostic framework, Delft3D-compatible I/O adapter, comparison against *published* Delft3D benchmark output. Never claim we ran Delft3D.
- **Three scenarios:** (A) **Malpasset 1959** for validation against surveyed field data; (B) **Tehri Dam, Bhagirathi** for the headline live demo on a real Indian dam; (C) **Rishi Ganga / Chamoli Feb 2021** for the "river blockage" requirement — the PS cites this event itself.
- **Resolution strategy:** 90 m grid for interactive/live runs (1–2 min), 30 m precomputed for high-res demo output (15–30 min). This is a deliberate design point, not a compromise.

## Repo layout

```
PLAN.md              master roadmap — physics, validation, schedule, jury Q&A
environment.yml      conda env (name: jaldrishti)
data/                DEMs, landcover, population — gitignored
outputs/             simulation results — gitignored
jaldrishti/
  config.py          study-area definitions, dam specs
  terrain/           DEM fetch, reproject, pit fill, flow routing, Manning n
  solver/            swe2d.py (Numba), sph2d.py, breach.py
  analysis/          max depth, velocity, arrival time, hazard, exposure
  export/            GeoTIFF, COG, Shapefile, KML, PDF
  gee/               Sentinel-1 SAR flood observation
  api/               FastAPI app
frontend/            Next.js + deck.gl dashboard
tests/               validation ladder — see below
```

## Numerics rules — this is where solvers die

1. **Build the validation ladder before trusting anything:** lake-at-rest → Ritter (dry-bed analytical) → Stoker (wet-bed) → Malpasset. Tests live in `tests/` and each one produces a chart for the deck.
2. **Wetting/drying is the #1 source of bugs.** Always use a depth threshold (`h_min ≈ 1e-3 m`); never divide by depth without guarding. Velocity = discharge/depth blows up to millions of m/s otherwise and the run NaNs out.
3. **Well-balanced source terms are mandatory.** Still water on a slope must stay still to machine precision, or the model invents flooding out of nothing.
4. **CFL safety factor 0.4**, not 0.9. Robustness beats speed here.
5. **Conserve mass and assert it.** Log total volume every N steps; if it drifts, stop and fix rather than continuing.
6. When a run misbehaves, dump the depth/momentum fields to GeoTIFF and inspect in QGIS. Don't debug numerics by staring at scalars.

## Presentation constraints that shape the code

- **Never overclaim.** The PS says "probable" and "confidence-based" repeatedly. Report uncertainty; flag resolution limits; state that the Chamoli case was a *debris flow* (sediment slurry) which the shallow water equations only approximate via bulking factor and elevated roughness. Volunteering understood limitations is what makes a jury trust you.
- **Cite the Dam Safety Act, 2021** — it legally mandates dam-break studies and Emergency Action Plans for specified Indian dams. This reframes the tool as compliance infrastructure, not a hackathon toy. Also relevant: NDMA GLOF guidelines, CWC inundation-mapping guidelines, Sendai Framework Priority 4.
- Screenshots for the PPT must exist by **Day 3 (Mon 31 Aug)** — get an ugly-but-real inundation map early. The deck is the hard deadline; polish is negotiable.
- **If time runs short, cut in this order:** GEE integration, then SPH down to a 1D demo case, then 3D terrain view down to 2D. **Never cut:** validation charts, arrival-time map, exposure numbers, .shp/.kml export.

## Current state

Done: `PLAN.md`, `environment.yml`, `.gitignore`.

Next up, in order:
1. `conda env create -f environment.yml` (long-running — start it early)
2. Account registrations — **Google Earth Engine approval takes days, apply immediately**; NASA Earthdata; OpenTopography
3. `jaldrishti/config.py` — study areas and dam specifications
4. Terrain pipeline — DEM fetch and hydrological conditioning for the Tehri domain
5. SWE solver + validation ladder

**Dam specifications in `config.py` must be verified against CWC / National Register of Large Dams sources before they appear on any slide.** Reservoir volumes and full-reservoir levels cited from memory are not reliable enough for a jury.

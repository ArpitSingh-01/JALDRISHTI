# JALDRISHTI — Master Plan
### SIH 2026 · PS 26161 · Dam Break Inundation Modelling Using Hydrodynamic Modelling of any River
**Organisation:** National Technical Research Organisation (NTRO) · **Theme:** Disaster Management · **Category:** Software

*Working name: **JALDRISHTI** (जल-दृष्टि, "water-sight"). Alternatives if you prefer: PRAVAAH, JALRAKSHAK, SETU. Rename freely — but pick one today, because it goes on every slide.*

---

## 1. The mission in one paragraph

We are building a **dam-break and river-blockage flood simulation platform for humanitarian disaster response**. A user selects a dam or a landslide-blockage point on a map of India, specifies a failure scenario, and the system downloads the terrain, simulates the resulting flood wave using hydrodynamic physics, and returns: where the water goes, how deep, how fast, **when it arrives**, who is in its path, and what will be destroyed — exported as maps, shapefiles, KML, and a response-ready PDF report.

The last item is the one that matters. Every team that attempts this PS will show a blue blob on a map. The winning move is **arrival time and exposure**: telling a district magistrate that water reaches their village in 47 minutes and 12,400 people need to move is what "Humanitarian Assistance and Disaster Relief" actually means. Simulation is the engine; evacuation intelligence is the product.

## 2. Do these tonight — they have lead times

These block later work, so they happen before any code.

1. **Apply for Google Earth Engine access** at `https://code.earthengine.google.com` (sign up for noncommercial/research use, register a Cloud project). **This is the single most time-critical item — approval can take several days**, and PS deliverable (iv) explicitly requires GEE. Do it first.
2. **Register for NASA Earthdata Login** (`urs.earthdata.nasa.gov`) — needed for SRTM and ASTER GDEM downloads.
3. **Register for OpenTopography** (`portal.opentopography.org`) — easier programmatic DEM access, gives you an API key.
4. **Install Miniforge** (`github.com/conda-forge/miniforge`). Do *not* try to pip-install the geospatial stack on Windows — GDAL, rasterio, and geopandas will fight you. Conda-forge makes this painless.
5. **Install QGIS** (free). You need it to sanity-check every raster and shapefile we produce, and to make presentation-quality map figures for the deck.
6. **Pick the project name** and create the GitHub repo.

## 3. Study area and scenarios

We run **three scenarios**, each doing a specific job. This is deliberate — it covers the PS's requirements while giving us both scientific credibility and emotional impact.

**Scenario A — Malpasset Dam, France, 1959. Job: validation.**
This is the standard real-world benchmark case in dam-break literature. A 66 m arch dam failed catastrophically; post-event field surveys recorded flood-wave arrival times at electrical transformers and maximum water marks along the valley. Because measured data exists, we can prove our solver is correct rather than merely assert it. **A validation chart against Malpasset is worth more to a technical jury than three extra features.**

**Scenario B — Tehri Dam, Bhagirathi River, Uttarakhand. Job: the headline demo.**
India's tallest dam at 260 m, holding roughly 3.5 km³. Downstream lie Rishikesh and Haridwar. This gives clean dam-break physics in a valley that widens into plains, an enormous exposed population for the loss-and-damage module, and fully published open specifications. This is what we demo live, satisfying PS deliverable (v) — a real Indian river and dam.

**Scenario C — Rishi Ganga / Tapovan, Chamoli, Uttarakhand, February 2021. Job: river blockage.**
The PS names this event in its own background text. A rock-ice avalanche blocked the river and the resulting flash flood destroyed two hydropower projects. This covers the "river blockage analysis" requirement, which is separate from dam break and which most teams will ignore entirely.

**One caveat to state openly, not hide:** the Chamoli flow was a debris flow — a sediment-water slurry, not clear water. Its rheology differs from the shallow water equations. We will say so explicitly on the slide and note that we apply an increased effective roughness and a bulking factor to approximate it. Volunteering a limitation you understand is how you look like an engineer instead of a student.

## 4. Requirement traceability

Every PS deliverable maps to a named module. Build this table into the deck — juries score against their own wording.

| PS deliverable | Our module | Priority |
|---|---|---|
| (i) Dam break / river blockage framework via **SPH** and **Delft3D**, with comparison | `solver/sph2d.py` + `solver/swe2d.py` + Delft3D-compatible I/O adapter, side-by-side comparison view | Must |
| (i) Loss and damage analysis | `analysis/exposure.py` — population, buildings, roads, depth-damage curves | Must |
| (ii) Scenario generation from different input datasets | `pipeline/` — pluggable DEM sources (SRTM / ASTER / CartoDEM / FABDEM), configurable breach parameters | Must |
| (iii) Dashboard GUI, large data volumes, **.shp / .kml export** | Next.js + deck.gl frontend; tiled Cloud-Optimized GeoTIFFs; `export/` writers | Must |
| (iv) Near-real-time analysis via **Google Earth Engine** | `gee/flood_observe.py` — Sentinel-1 SAR change detection | Should |
| (v) Live demo on real Indian dam | Scenario B (Tehri), precomputed at high resolution + live coarse run | Must |

## 5. Architecture

```
┌───────────────────────────────────────────────────────────┐
│  FRONTEND — Next.js + deck.gl                             │
│  3D terrain · animated flood · time slider · scenario     │
│  builder · exposure panel · export controls               │
└──────────────────────────┬────────────────────────────────┘
                           │ REST + WebSocket (job progress)
┌──────────────────────────┴────────────────────────────────┐
│  API — FastAPI                                            │
│  scenario CRUD · job queue · tile server · exports         │
└──────────────────────────┬────────────────────────────────┘
                           │
┌──────────────────────────┴────────────────────────────────┐
│  SIMULATION CORE — Python + NumPy + Numba                 │
│                                                           │
│  1. Terrain    DEM fetch → mosaic → reproject → pit fill  │
│                → flow routing → Manning n from landcover  │
│  2. Breach     Froehlich parametric breach → outflow       │
│                hydrograph  (or instantaneous full breach)  │
│  3. SPH        near-field breach jet, weakly compressible  │
│  4. SWE 2D     far-field routing — finite volume, HLLC     │
│                Riemann, MUSCL, wetting/drying, friction    │
│  5. Analysis   max depth · velocity · arrival time ·       │
│                hazard rating · exposure · damage           │
│  6. Export     GeoTIFF · COG · Shapefile · KML · PDF       │
└──────────────────────────┬────────────────────────────────┘
                           │
      DATA: SRTM/ASTER/FABDEM DEM · ESA WorldCover ·
      WorldPop · OSM (Overpass) · Sentinel-1 via GEE ·
      GRanD dam database · India-WRIS / NRLD
```

**Why this stack.** Python for the core is not optional — rasterio, geopandas, pysheds, and Numba have no real equivalent elsewhere. Numba matters specifically: a pure-NumPy shallow water solver is roughly a hundred times too slow, and Numba's JIT gets us to C-like speed while keeping the code readable enough that you can defend it line by line. deck.gl on the frontend because it renders 3D terrain plus millions of cells on the GPU, which is the honest answer to "the program should support the large volume of data."

**The performance design point.** At 90 m resolution the Tehri domain runs in one to two minutes, so the dashboard feels interactive. At 30 m it takes roughly fifteen to thirty minutes, so we precompute those runs before the demo. Multi-resolution is not a compromise here, it is the correct engineering answer, and it is exactly what operational flood forecasting systems do.

## 6. The physics, in language you can defend

You will be asked about this, so learn this section rather than the code.

**The shallow water equations.** Water in a river is wide and thin — kilometres across, metres deep. That lets us average the full three-dimensional fluid equations over depth and track only water depth and horizontal momentum per cell. The result is a system of three conservation laws: mass, x-momentum, y-momentum. They are the industry standard for flood modelling and they are what Delft3D, HEC-RAS 2D, and TELEMAC all solve.

**Why a Riemann solver.** A dam break creates a shock — a near-vertical wall of water. Naive numerical schemes either smear shocks into mush or produce oscillations and negative depths. So at every cell interface we solve a small local "which way does the discontinuity move" problem. HLLC is the standard approximate solver: cheap, robust, and it handles the dry-bed front correctly, which is exactly the hard part of dam break modelling.

**Wetting and drying.** Most flood-solver bugs live here. Cells transition between dry and wet, and if you divide by a near-zero depth you get velocities of a million metres per second and the simulation explodes. We use a depth threshold and a well-balanced source term treatment so still water on a slope stays still — the classic "lake at rest" test.

**Where SPH fits.** SPH represents water as moving particles rather than a fixed grid, which makes it good at violent, splashing, free-surface flow — precisely what happens in the first moments at the breach — and poor at cheaply routing a flood eighty kilometres downstream. So we use each where it is strong: SPH for near-field breach dynamics, SWE for far-field routing, coupled by passing the SPH outflow hydrograph into the SWE domain. That is a defensible engineering choice, and saying *why* you did not use SPH for everything demonstrates more understanding than using it everywhere.

**On Delft3D — the honest position.** Delft3D is a heavyweight Deltares package that cannot be meaningfully integrated in one week. Do not claim you did. The defensible position: the framework is solver-agnostic, our native SWE and SPH engines are implemented and validated, a Delft3D-compatible input/output adapter exists so Delft3D can be plugged in as a backend, and we compare our results against published Delft3D benchmark output. Stated that way it is a strength — you built the framework the PS asked for, and validated it against the tool the PS named.

## 7. Validation strategy — this is your differentiator

Four tests, in increasing difficulty. Each produces a chart for the deck.

1. **Lake at rest.** Still water on uneven terrain must stay still. Catches source-term errors. Pass criterion: velocities stay at machine zero.
2. **Ritter's analytical solution.** An instantaneous dam break on a dry, frictionless, flat bed has an exact closed-form answer from 1892. Our numerical result should overlay it almost perfectly.
3. **Stoker's solution.** Same, but onto a wet bed — tests shock capture.
4. **Malpasset 1959.** Real terrain, real failure, surveyed arrival times and high-water marks. Report RMSE against observations.

If you present nothing else technical, present these. Numerical validation against analytical solutions is what separates a simulation from an animation, and almost no hackathon team does it.

## 8. Day-by-day schedule

Deadline assumed **Friday 4 September 2026**. The PPT is protected by getting a presentable inundation map by Day 3 — screenshots must exist well before the deck is due.

**Day 0 — Friday 28 Aug (today).** Your account applications from section 2. I scaffold the repo, write the environment spec, and set up the project skeleton.

**Day 1 — Saturday 29 Aug.** Terrain pipeline. DEM download and preprocessing, reprojection, pit filling, flow routing, roughness assignment. Deliverable: a clean, hydro-conditioned elevation grid of the Tehri study area that you can open in QGIS.

**Day 2 — Sunday 30 Aug.** Solver core plus validation tests 1 to 3. Deliverable: charts showing our solver matching Ritter and Stoker. This is the day the project becomes scientifically real.

**Day 3 — Monday 31 Aug.** Breach model and the first full 2D run on real Tehri terrain. Deliverable: **the first genuine inundation map.** From here the deck is safe.

**Day 4 — Tuesday 1 Sep.** SPH module, Malpasset validation, and the .shp/.kml/GeoTIFF exporters. I also start drafting the PPT in parallel.

**Day 5 — Wednesday 2 Sep.** Frontend dashboard — 3D map, animated flood, time slider, scenario builder. The visual payoff day.

**Day 6 — Thursday 3 Sep.** Loss and damage module, GEE Sentinel-1 integration, PDF report generation.

**Day 7 — Friday 4 Sep.** Finalise the PPT, full end-to-end verification, demo rehearsal, buffer for whatever broke.

**If you fall behind, cut in this order:** GEE integration first, then SPH reduced to a 1D demonstration case, then the 3D terrain view flattened to 2D. **Never cut:** the validation charts, the arrival-time map, the exposure numbers, or the .shp/.kml export. Those four are the score.

## 9. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| GEE access not approved in time | Medium | Applied Day 0; fall back to pre-exported Sentinel-1 GeoTIFFs and present GEE as the live pathway |
| Solver instability (NaNs, explosions) | **High** | Validation ladder catches it early; depth thresholding, CFL safety factor 0.4, well-balanced source terms |
| 30 m run too slow for live demo | High | Precompute high-res; live demo runs 90 m coarse grid |
| DEM too coarse for narrow Himalayan gorges | Medium | Use FABDEM or CartoDEM 30 m; state resolution limits explicitly |
| Debris-flow rheology ≠ clear water (Chamoli) | Certain | Disclose it; apply bulking factor and elevated roughness; frame as future work |
| Jury asks why not Delft3D | **Certain** | Rehearse the section 6 answer verbatim |
| Solo builder illness / time crunch | Medium | Cut-list in section 8; deck protected from Day 3 |

## 10. Questions the jury will ask

Rehearse answers to all of these. NTRO evaluators are technical.

- Why the shallow water equations and not full 3D Navier-Stokes?
- What is your grid resolution and why is that defensible?
- How did you validate this? *(Your strongest answer — lead with it.)*
- Why did you not use Delft3D as the PS specified?
- How do you choose Manning's roughness coefficient?
- What is your breach formation assumption, and how sensitive are results to it?
- How long does a simulation take, and can this run during an actual emergency?
- What is the uncertainty on your inundation extent?
- How would this integrate with NDMA or CWC workflows?
- What happens with sediment, debris, and bridges obstructing flow?

## 11. Policy hooks — cite these, they win points

- **Dam Safety Act, 2021** — legally mandates dam-break studies and Emergency Action Plans for specified dams in India. Our tool directly serves a statutory requirement. This is the strongest framing available: not a hackathon toy, but compliance infrastructure.
- **NDMA Guidelines on GLOF risk management** — glacial lake outburst floods, directly relevant to Scenario C.
- **Central Water Commission** guidelines on dam break analysis and inundation mapping.
- **Sendai Framework for Disaster Risk Reduction** — India is a signatory; Priority 4 is preparedness and response.

## 12. Division of labour

**I write:** the solver, terrain pipeline, breach model, SPH module, exposure analysis, exporters, API, frontend, PDF reports, and the PPT.

**You do:** account registrations, run the code locally and report errors back to me, verify rasters and shapefiles in QGIS, learn section 6 well enough to defend it unaided, and rehearse the demo out loud at least twice.

**The one thing I cannot do for you:** understand the physics on stage. Read section 6 until it is yours. A jury forgives rough code and does not forgive a presenter who cannot explain their own model.

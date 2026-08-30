# context.md — JALDRISHTI

**Single-file handoff document.** Everything a fresh agent or collaborator needs to
work on this project productively without reading anything else first. If you are
picking this up cold, read this file top to bottom and you will know the problem,
the product thesis, the physics, the numerics, what is built, what is measured,
what is broken, and what to do next.

> **Maintenance rule:** this file is a living document and goes stale fast. Update
> it at the end of any session that changes the build state — see
> [§16 Update protocol](#16-update-protocol) for exactly what to touch.

**Last updated:** 2026-08-29 · **Commit at time of writing:** `3b055fe` on `master`
· **Build state:** ~31% complete by weighted effort

---

## Table of contents

1. [The problem statement](#1-the-problem-statement)
2. [The product thesis — what actually wins](#2-the-product-thesis--what-actually-wins)
3. [Who is building this, and the constraints that follow](#3-who-is-building-this-and-the-constraints-that-follow)
4. [Locked decisions — do not relitigate](#4-locked-decisions--do-not-relitigate)
5. [The three scenarios](#5-the-three-scenarios)
6. [The physics, explained](#6-the-physics-explained)
7. [The numerics, and why each choice](#7-the-numerics-and-why-each-choice)
8. [Repo layout and file-by-file status](#8-repo-layout-and-file-by-file-status)
9. [The validation ladder — measured results](#9-the-validation-ladder--measured-results)
10. [The terrain pipeline](#10-the-terrain-pipeline)
11. [The provenance system in config.py](#11-the-provenance-system-in-configpy)
12. [Build state: what is done, what is not](#12-build-state-what-is-done-what-is-not)
13. [Critical path and schedule](#13-critical-path-and-schedule)
14. [Environment and how to run things](#14-environment-and-how-to-run-things)
15. [Known bugs, open questions, and traps](#15-known-bugs-open-questions-and-traps)
16. [Update protocol](#16-update-protocol)

---

## 1. The problem statement

**Smart India Hackathon 2026, Problem Statement 26161.**

| Field | Value |
|---|---|
| Title | Dam Break Inundation Modelling Using Hydrodynamic Modelling of any River |
| Organisation | National Technical Research Organisation (NTRO) |
| Theme | Disaster Management |
| Category | Software |
| Deadline | ~Friday 4 September 2026 (both idea-submission PPT **and** working prototype) |

**Explicitly required by the PS text** — these are not optional and must not be cut:

- Hydrodynamic modelling of dam-break flood propagation over a real river
- Handling of **river blockage** scenarios (the PS cites the Chamoli 2021 event by name)
- Export to **Shapefile** and **KML** (named in the PS)
- Handling of "large volume of data"
- Language of **"probable"** and **"confidence-based"** outputs throughout — the PS
  is explicitly asking for uncertainty, not false precision

**Legal and policy framing** (use this — it reframes the tool as compliance
infrastructure rather than a hackathon demo):

- **Dam Safety Act, 2021** — legally mandates dam-break studies and Emergency
  Action Plans for specified Indian dams. This is the single strongest framing
  point available.
- **NDMA GLOF guidelines** — glacial lake outburst flood protocol
- **CWC inundation-mapping guidelines**
- **Sendai Framework Priority 4** — "Enhancing disaster preparedness for effective
  response"

---

## 2. The product thesis — what actually wins

> **The differentiator is arrival time + exposure, not the inundation map.**

Every competing team will render a blue blob over terrain. That is the easy part
and it is not decision-useful. What a district magistrate or NDRF commander needs
is:

> *"Water reaches this village in 47 minutes. 12,400 people must move. This bridge
> is gone at minute 31, so evacuate west, not east."*

So the priority ordering of outputs is:

1. **Arrival time** (minutes to a stated depth threshold, per location) ← the product
2. **Exposure** (population and infrastructure inside the hazard footprint)
3. **Depth and velocity** maxima, and a depth×velocity hazard classification
4. **Damage estimate** in ₹
5. The inundation map itself — necessary, but table stakes

**User flow:** pick a dam or blockage point in India → define a failure scenario →
simulate the flood wave over real terrain → get depth, velocity, arrival time,
exposure, and damage → export GeoTIFF / Shapefile / KML / response-ready PDF.

**Cut order if time runs short** (from `CLAUDE.md`, still authoritative):

1. Cut GEE / Sentinel-1 integration first
2. Then SPH down to a 1D demo case
3. Then 3D terrain view down to 2D

**Never cut:** validation charts · arrival-time map · exposure numbers · `.shp` and
`.kml` export.

---

## 3. Who is building this, and the constraints that follow

**Arpit Singh** — student, strong full-stack web developer, **new to
hydrodynamics and numerical methods**. Effectively a **solo builder**: no
ML/scientific-computing teammate.

Consequences for how to work on this project:

- **Explain the physics and numerics as you go.** He has to defend every choice to
  a technical jury unaided. A correct implementation he cannot explain is worth
  less than a slightly simpler one he can.
- **Do not design anything that needs a second person.** No microservice fleets, no
  distributed compute, no "we'll hire a GIS specialist for this bit".
- **Explain before acting.** Direct standing instruction: *"don't go on rampage at
  least let me know what is happening here."* No long silent tool chains — say
  what you are about to do and why, then do it.
- **Windows machine.** Conda (Miniforge) for the geospatial stack. **Do not
  pip-install GDAL / rasterio / geopandas on Windows** — it breaks in ways that
  cost hours.
- College/internal SIH round already cleared (on a different problem statement).

---

## 4. Locked decisions — do not relitigate

These were argued out already. Reopening them costs days we do not have.

| Area | Decision | Why |
|---|---|---|
| Simulation language | **Python + NumPy + Numba** | Pure NumPy is ~100× too slow for explicit timestepping; Numba JIT gets it to C speed without leaving Python |
| Far-field solver | **Own 2D shallow-water solver** — finite volume, HLLC Riemann, MUSCL reconstruction, well-balanced bed slope, wetting/drying, Manning friction, CFL-limited explicit stepping | Owning it means we can explain and defend every line, and it is the only way to hit arrival-time accuracy we can quantify |
| Near-field solver | **Own 2D weakly-compressible SPH** for breach dynamics, coupled to the SWE model via the SPH outflow hydrograph | Breach flow is violently non-hydrostatic; SWE is invalid there. SPH is also a strong visual |
| API | **FastAPI** | Async, typed, trivial to deploy |
| Frontend | **Next.js + deck.gl** | GPU 3D terrain rendering is the honest answer to the PS's "large volume of data" requirement |
| Frontend palette | **Indian flag colours** (saffron / white / green / navy) for UI chrome. Hazard and depth ramps stay a **separate perceptual scale** | Flag colours are not perceptually ordered and would misrepresent magnitude |
| Delft3D | **Adapter, not integration.** Solver-agnostic framework + Delft3D-compatible I/O + comparison against *published* Delft3D benchmark output | Running Delft3D in a week is impossible. **NEVER claim we ran Delft3D.** This clause is absolute |
| Resolution | **90 m** for interactive/live runs (1–2 min) · **30 m** precomputed for high-res demo output | A deliberate design point, not a compromise. Present it as such |

**On Delft3D specifically:** the user has authorised *building the adapter*. The
prohibition on *claiming we ran Delft3D* is untouched and must be preserved in
every artefact — code comments, PPT, PDF report, jury answers.

---

## 5. The three scenarios

Defined in `backend/jaldrishti/config.py` as `STUDY_AREAS`.

### A. Malpasset, Reyran valley, France — 2 December 1959 · key `malpasset`

**Purpose: validation against surveyed field data.** The reference case for
dam-break modelling worldwide, and the only one of the three where the real answer
is known. A 66.5 m double-curvature concrete arch dam whose left abutment failed in
the underlying gneiss; the arch unzipped in seconds. **423 people died.** The
survey that followed is why the case exists as a benchmark.

- Frame: **EDF local planimetric coordinate system, metres.** No EPSG code exists.
- Reservoir level 100.0 m · gross storage 55×10⁶ m³ · Manning n = 0.025 (**calibrated, not measured** — say so)
- Breach: **instantaneous** total removal (the accepted idealisation, and what every published benchmark uses, which is what makes our numbers comparable)
- Grid: 20 m validation / 10 m high-res — finer than our operational grids because the reference data resolves the valley at that scale

**Reference data, already in repo** at `backend/tests/reference/malpasset/`:

| File | Contents |
|---|---|
| `police_survey_p1_p17.csv` | 17 field-surveyed high-water marks. Columns `point,x_m,y_m,bank,ws_obs_m`. P1 = (4913.1, 4244.0) right bank, 79.15 m … P17 = (12333.7, 2269.7) right bank, 14.00 m |
| `gauges_g6_g14.csv` | 9 gauges from the 1:400 LNH-EDF **physical scale model**. Columns `gauge,x_m,y_m,at_lab_s,ws_lab_m`. G6 = (4947.4, 4289.7), t=10.2 s, 84.2 m … G14 = (12723.7, 2485.1), t=1139.0 s, 12.9 m |
| `transformers_abc.csv` | 3 electrical transformers whose failure times were recorded. Columns `transformer,x_m,y_m,x_telemac_m,at_obs_s,at_rel_to_A_s,ds_from_prev_m,v_obs_ms`. A=(5500,4400) t=100 s · B=(11900,3250) t=1240 s, 5.70 m/s · C=(13000,2700) t=1420 s, 6.83 m/s |

**Source for all three:** Biscarini, Di Francesco, Ridolfi & Manciola (2016),
*Water* 8(11):545, doi:`10.3390/w8110545` (CC-BY), Tables 2–4, plus the
openTELEMAC `malpasset` case.

**Critical reading notes — get these wrong and the whole comparison is garbage:**

- Values are water-surface **ELEVATIONS** on the same datum as the 100.0 m
  reservoir level. **They are NOT depths.** Add bed elevation to modelled depth
  before comparing.
- Transformer arrival times carry an **unknown absolute offset**. Only the
  *relative* times are usable: B−A = 1140 s, C−A = 1320 s.
- Gauges G6–G14 are from a **1:400 physical model**, not the field, and carry
  scale effects of their own.

### B. Tehri Dam, Bhagirathi river, Uttarakhand · key `tehri`

**Purpose: the headline live demo on a real Indian dam.** India's tallest, on a
Himalayan river, upstream of dense settlement and of the Ganga confluence, and
squarely inside the Dam Safety Act 2021 requirement.

- Dam at **30.3775 N, 78.4806 E** — *verified against the DEM*, see §10
- Earth-core rockfill embankment · height 260.5 m · crest 575 m · FRL 830.0 m · MDDL 740.0 m
- Gross storage 3.54×10⁹ m³ · live 2.615×10⁹ m³ · catchment 7511 km² · commissioned 2006 · 1000 MW
- Breach: **parametric** (an embankment erodes, it does not vanish). Width 600 m, depth 230 m, side slope 1.0, formation time 3600 s with a **range of 1800–10800 s**
- Manning n = 0.045 (steep boulder-bed Himalayan channel, not a plain)
- Downstream POIs: **Koteshwar Dam** (cascade risk) · **Devprayag** (Bhagirathi+Alaknanda confluence, where the Ganga begins) · **Rishikesh** · **Haridwar**

> ⚠️ **EVERY number in this block is UNVERIFIED** and must be read off CWC /
> National Register of Large Dams before it appears on a slide. They exist so the
> pipeline has something to run against, and they are wrong until checked.

**The cascade point is a strength, not a weakness.** Koteshwar sits a short
distance downstream and would be overtopped by any significant Tehri release. A
dam-break study that stops at the first structure downstream is incomplete;
modelling the cascade and saying so scores points.

**Framing that must accompany every Tehri output:** *"Hypothetical. There is no
suggestion that Tehri is unsafe — a dam-break study is a legal requirement under
the Dam Safety Act 2021 and is performed precisely for dams that are being operated
responsibly."*

### C. Rishi Ganga / Ronti Gad, Chamoli, Uttarakhand — 7 February 2021 · key `rishi_ganga`

**Purpose: satisfies the PS's river-blockage requirement, on the event the PS
itself cites.**

- Ronti Gad rock-ice avalanche · source volume 27×10⁶ m³ · **bulking factor 1.6** · `debris_flow=True`
- Manning n = **0.10** — elevated roughness standing in for debris-flow resistance
- Breach mode: **overtopping**
- POIs: Raini / Rishiganga HEP (13.2 MW, destroyed) · Tapovan-Vishnugad NTPC (520 MW barrage, destroyed) · Joshimath

> ⚠️ **THIS WAS A DEBRIS FLOW, NOT A FLOOD.** The shallow water equations assume a
> constant-density Newtonian fluid. We approximate the sediment load with a bulking
> factor and an elevated Manning n. We do **not** solve the two-phase problem, and
> peak depths in the steep upper reach are **indicative only**. Also: SWE assumes
> small bed slopes and the upper Ronti Gad violates that.

Volunteering this limitation unprompted is one of the highest-value things we can
do in front of a jury. It also matters that the 2021 event was a **direct avalanche
into the channel**, not a long-lived landslide lake that later failed — we model
the generic blockage-and-breach sequence and state the difference. We do not claim
to reproduce the 2021 hydrograph.

---

## 6. The physics, explained

*This section exists so the physics can be defended, not just executed.*

### The equations

We solve the **2D depth-averaged shallow water equations** (SWE), also called the
Saint-Venant equations. They come from depth-averaging the Navier–Stokes equations
under one assumption: **the water is shallow relative to the horizontal scale of
the flow**, so vertical acceleration is negligible and pressure is hydrostatic.

For a flood 10 m deep spreading over kilometres of valley, that assumption is
excellent. For water plunging through a dam breach, it is not — hence SPH for the
near field.

Conserved variables, per unit area:

- `h` — water depth [m]
- `hu` — momentum in x [m²/s]
- `hv` — momentum in y [m²/s]

The system, in conservative form:

```
∂h/∂t  + ∂(hu)/∂x        + ∂(hv)/∂y        = 0                        (mass)
∂hu/∂t + ∂(hu² + ½gh²)/∂x + ∂(huv)/∂y      = -gh ∂z/∂x - friction_x   (x-momentum)
∂hv/∂t + ∂(huv)/∂x        + ∂(hv² + ½gh²)/∂y = -gh ∂z/∂y - friction_y (y-momentum)
```

- `z` — bed elevation [m]; `η = h + z` is the water-surface elevation
- `½gh²` — the depth-integrated hydrostatic pressure term. This is what makes water spread out under its own weight
- `-gh ∂z/∂x` — the **bed-slope source term**. This is gravity pulling water downhill
- friction — Manning's law, see below

### Wave speed and the character of the flow

The gravity wave speed is `c = √(gh)`. Two regimes:

- **Subcritical** (`|u| < c`, Froude number Fr < 1) — information travels both
  upstream and downstream. Normal river flow.
- **Supercritical** (`|u| > c`, Fr > 1) — information only travels downstream. Dam-break
  fronts and steep-channel flow. A **hydraulic jump** (bore) is the transition from
  supercritical back to subcritical, and it is a genuine discontinuity.

This is why we need a **shock-capturing** scheme. A dam-break wave on a wet bed
propagates as a bore — a near-vertical jump in water surface — and a scheme that
smears it gets the arrival time wrong.

### Manning friction

```
friction_x = g · n² · u · √(u² + v²) / h^(1/3)
```

`n` is Manning's roughness coefficient. Physically it encodes bed material,
vegetation and channel irregularity. Values we use:

| Setting | n | Reasoning |
|---|---|---|
| Malpasset | 0.025 | Calibrated in the literature. **This is a fitted parameter, not a measurement** |
| Tehri / Bhagirathi | 0.045 | Steep boulder-bed Himalayan channel |
| Rishi Ganga | 0.10 | Elevated surrogate for debris-flow resistance |

Note `h^(1/3)` in the denominator: friction **blows up as depth → 0**. This is one
of the two reasons wetting/drying is dangerous (the other is `u = hu/h`).

### Why arrival time is physically well-posed but numerically delicate

Arrival time is *"the first moment depth at this location exceeds a threshold."* It
is a **front-position** measurement, so it inherits every error in the front. A
scheme that is 5% slow on the front is 5% wrong on every arrival time, and the
error **grows linearly with distance travelled** — the worst possible error
structure for an early-warning product.

We report arrival time at a **0.1 m depth threshold**, and this choice is
defensible three ways:

1. Copernicus DEM vertical accuracy is specified at better than 4 m (90% LE), so a
   10 cm water depth is already an order of magnitude below the error bar of the
   terrain it sits on. Reporting a 1 mm contour would be precision theatre.
2. Standard depth–velocity hazard criteria classify depths below ~0.1–0.3 m as low
   hazard for an adult.
3. Operational flood mapping conventionally uses a wet threshold of 0.1 m or higher.

---

## 7. The numerics, and why each choice

*Every item here is load-bearing. Removing any one of them produces a solver that
still runs and still makes pretty pictures while being quietly wrong.*

### Finite volume on a Cartesian grid

Cell-centred, uniform, square cells. **Square cells in metres are mandatory** — the
flux and CFL logic assumes `dx == dy`. A geographic (lat/lon) grid has cells ~13%
narrower in x than in y at 30° latitude, so running on degrees would stretch the
flood by that factor in one direction.

Cartesian rather than unstructured because **our terrain arrives as a raster.**
Staying on the raster avoids an interpolation step that would blur the very
elevations the flood depth is measured against.

### HLLC approximate Riemann solver, with dry-bed wave speeds

At every cell face we solve a local Riemann problem to get the flux. HLLC (Harten–
Lax–van Leer–Contact) resolves the left wave, right wave, and the contact/shear
wave — which matters in 2D because the transverse velocity `v` rides on the contact.

**The dry-bed correction is the single most important detail in the whole solver.**
Water accelerating into a dry bed produces a front travelling at **u ± 2c**, not
u ± c. A solver using the wet–wet estimate everywhere gets a front that lags by
tens of percent. Since front position *is* arrival time, that is a direct hit on
the headline output — and **nothing else in the validation ladder catches it**
except Ritter (rung 2).

Implemented in `backend/jaldrishti/solver/flux.py::hllc_x`.

### MUSCL reconstruction — on the right variables

Second-order accuracy needs a linear reconstruction inside each cell. Two choices
matter enormously:

- **Reconstruct `η = h + z`, not `h`.** Reconstructing depth destroys the still-water
  balance immediately: on a sloping bed, constant `η` means *varying* `h`, so a
  limiter applied to `h` sees a gradient where there is no flow.
- **Reconstruct primitive velocities `u, v`, not momenta `hu, hv`.** Momentum
  reconstruction produces garbage velocities in thin water.

Limiter codes in `solver/reconstruct.py`:

| Name | Code | Character |
|---|---|---|
| `none` | `LIMITER_NONE = 0` | Returns slope 0.0 → genuinely first-order piecewise constant. Most diffusive, safest. **Not** "unlimited" |
| `minmod` | `LIMITER_MINMOD = 1` | Most diffusive TVD limiter, very robust |
| `mc` | `LIMITER_MC = 2` | Monotonized central — sharper fronts, still TVD. **Default** |

All three are monotone. That is asserted, not assumed — see rung 3.

### Well-balancedness: Audusse hydrostatic reconstruction + centred bed source

**This is the difference between a flood model and a random-number generator.**

In the momentum equation the pressure-gradient flux and the bed-slope source are
individually large and, in still water, exactly equal and opposite. For a 100 m
reservoir on a 1-in-10 slope both are ~100 m²/s². Get the discretisation right only
to 1% and you have ~1 m²/s² of unbalanced force applied *every timestep* — and the
model shows a calm reservoir spontaneously sloshing, or quietly draining downstream
and "flooding" villages that were never at risk.

That failure mode is insidious because **it looks plausible**. A blue blob appears,
spreads downhill, and nothing in the output announces that it is an artefact.

Three co-operating mechanisms give exact balance:

1. Reconstruct `η`, not `h` (`reconstruct.py`)
2. **Audusse et al. (2004) hydrostatic reconstruction** at every face (`swe2d._rhs`)
3. A **matching centred in-cell bed source term** (`swe2d._rhs`)

…and one restraint:

4. **`fastmath` MUST stay OFF.** `_JIT = dict(cache=True, fastmath=False, nogil=True)`.
   `fastmath` lets the compiler reassociate floating-point arithmetic, and the
   cancellation we depend on is *exactly* what reassociation destroys. This is not
   a performance preference — it is a correctness requirement.

### Wetting and drying — the #1 source of bugs

Two distinct thresholds, and conflating them is a bug:

| Constant | Value | Role |
|---|---|---|
| `h_min` | `1e-3` m (configurable) | Physical dry threshold. Cells below this are "dry" for velocity and friction purposes |
| `H_DRY` | `1e-12` | Numerical floor. Guards divisions that must never see zero |

**Never divide by depth without guarding.** `u = hu/h` with `h = 1e-9` gives
velocities in the millions, which breaks CFL, which NaNs the entire domain within a
few steps.

The guard is **Kurganov & Petrova (2007) desingularization**:

```python
u = 2*h*q / (h**2 + max(h**2, h_min**2))
```

This is smooth, tends to `q/h` for `h >> h_min`, and tends to 0 for `h << h_min`.
Crucially it does **not** make the answer depend on `h_min` — verified in rung 2 by
varying `h_min` over two orders of magnitude and measuring that the front barely
moves. (Before this fix it *did*: the thin-film lag ran from 46 m to 26 m as `h_min`
went 1e-3 → 1e-6, i.e. an arbitrary solver parameter was controlling the physics.)

### Time integration and stability

- **SSP-RK2 (Heun's method)** — two-stage, strong-stability-preserving. Second-order
  in time to match the spatial order, and SSP means it cannot create new extrema
  that the spatial limiter forbade.
- **Point-implicit Manning friction.** Friction is stiff in thin water (that `h^(1/3)`
  denominator); treating it explicitly would demand absurdly small timesteps.
- **CFL safety factor 0.4**, not the theoretical 0.9. `dt ≤ cfl / ((|u|+c)/dx + (|v|+c)/dy)`.
  Robustness beats speed. Do not raise this to "make the demo faster."

### Mass conservation, asserted

Finite volume conserves mass by construction, which makes a measured drift a direct
test of the **boundary conditions** and the **dry-cell clipping** — not of the flux
scheme. Total volume is logged every N steps and asserted in tests. A drift means
the model would report the wrong flood volume, which propagates straight into the
exposure and damage numbers.

**Standing rule from `CLAUDE.md`:** if volume drifts, stop and fix it. Do not
continue.

### Debugging protocol

When a run misbehaves: **dump the depth/momentum fields to GeoTIFF and open them in
QGIS.** Do not debug numerics by staring at scalars. `TerrainGrid.to_geotiff()`
takes an `array=` argument specifically for this.

### A note on "3D"

**The model is 2D depth-averaged.** Only the deck.gl *rendering* is 3D. Never let
the presentation imply we solve 3D Navier–Stokes — a jury member who knows the
field will catch it instantly and everything else becomes suspect.

---

## 8. Repo layout and file-by-file status

```
SIH2026 PS161/
├── CLAUDE.md                  project instructions — the quick brief
├── PLAN.md                    master roadmap (⚠️ partly stale, see §15)
├── context.md                 THIS FILE
├── environment.yml            conda env, name: jaldrishti
├── .gitignore
├── data/                      gitignored — DEMs, landcover, population
│   ├── dem/                   Copernicus mosaic cache (auto-created)
│   └── reference/malpasset/   literature notes
├── outputs/                   gitignored — simulation results
│   ├── validation/            the four validation charts
│   └── terrain/               DEM GeoTIFFs
└── backend/
    ├── conftest.py            pytest setup + chart_dir fixture
    ├── jaldrishti/
    │   ├── __init__.py        EMPTY
    │   ├── config.py          study areas, dam specs, provenance   ✅ 630 lines
    │   ├── solver/
    │   │   ├── __init__.py    exports GRAVITY, NG, RunStats, SWE2D
    │   │   ├── swe2d.py       the solver                            ✅ 921 lines
    │   │   ├── flux.py        HLLC + wave speeds                    ✅ 157 lines
    │   │   └── reconstruct.py MUSCL limiters                        ✅ 116 lines
    │   ├── validation/
    │   │   ├── __init__.py    exports ritter, stoker, …
    │   │   └── analytical.py  Ritter + Stoker exact solutions       ✅ 176 lines
    │   ├── terrain/
    │   │   ├── __init__.py    package exports
    │   │   └── dem.py         DEM fetch + conditioning              ✅ 611 lines
    │   ├── analysis/__init__.py   EMPTY  ❌ arrival time, hazard, exposure
    │   ├── export/__init__.py     EMPTY  ❌ GeoTIFF, COG, shp, kml, PDF
    │   ├── scenario/__init__.py   EMPTY  ❌ breach + run orchestration
    │   ├── gee/__init__.py        EMPTY  ❌ Sentinel-1 SAR
    │   └── api/                   DOES NOT EXIST  ❌ FastAPI
    ├── scripts/
    │   └── check_terrain.py   build check for the DEM pipeline
    └── tests/
        ├── test_lake_at_rest.py   rung 1                            ✅ 251 lines
        ├── test_ritter.py         rung 2                            ✅ 440 lines
        ├── test_stoker.py         rung 3                            ✅ 523 lines
        └── reference/malpasset/   3 CSVs + README                   ✅ data ready
```

Also missing: `frontend/` (Next.js + deck.gl) does not exist yet.

### `SWE2D` public API — what you actually call

```python
from jaldrishti.solver import SWE2D, RunStats, GRAVITY, NG

s = SWE2D(z, dx, dy=None, manning=0.033, *,
          g=9.81, h_min=1e-3, cfl=0.4,
          limiter="mc",                       # 'none' | 'minmod' | 'mc'
          bc=("open", "open", "open", "open") # (west, east, south, north), 'wall'|'open'
)

# initial conditions
s.set_depth(h)                    # set depth directly
s.set_surface(eta, where=None)    # fill to a water-surface ELEVATION; h = max(0, eta - z)
                                  # `where` = boolean mask → this is how a dam-break
                                  # initial condition is set (reservoir wet, downstream dry)

# stepping
dt = s.compute_dt(dt_max=None)    # CFL-limited
s.step(dt=None, dt_max=None)      # one SSP-RK2 step
stats = s.run(t_end, *, dt_max=None, callback=None, callback_every=None,
              log_every=None, max_steps=10_000_000)
              # callback(solver) fires every callback_every SECONDS OF MODEL TIME —
              # this is the hook for arrival-time accumulation and frame saving

# state — READ-ONLY-ish properties returning INTERIOR views
s.z, s.h, s.hu, s.hv, s.manning   # (ny, nx)
s.eta                             # h + z
s.u, s.v, s.speed                 # desingularized velocities
s.wet                             # boolean mask
s.t                               # model time
s.volume()                        # total m³
s.stats                           # RunStats
```

> ⚠️ **`SWE2D.h` and friends expose the INTERIOR field only**, shape `(ny, nx)`.
> Ghost cells (`NG = 2` per side) are internal and never surface. **Do not slice
> `[ng:-ng]`** — that was an actual bug that cost a debugging cycle.

`RunStats` fields: `steps`, `t`, `volume_initial`, `volume_final`, `mass_clipped`,
`dt_min`, `dt_max`, `history` (list of `(t, volume, dt)`), and property
`volume_error` (relative).

---

## 9. The validation ladder — measured results

**Build the ladder before trusting anything.** Four rungs:
lake-at-rest → Ritter (dry bed) → Stoker (wet bed) → Malpasset (real event).

**Status: rungs 1–3 complete and green. 54 tests passing, ~26–31 s. Rung 4 not started.**

Every rung produces a chart in `outputs/validation/`, because a passing assertion
convinces a developer and a chart convinces a jury — and we need both.

### Rung 1 — Lake at rest (well-balancedness) · `tests/test_lake_at_rest.py`

Put still water over uneven terrain, take 200 steps, and require that **nothing
happens** — not "almost nothing", nothing to machine precision.

Six beds × three limiters. The beds run from flat to a random rough bed. **The
random bed matters most**: on a flat or linear bed a broken scheme can pass by
accident because errors cancel by symmetry. Random terrain removes that luck — and
it is also what a real DEM looks like. One bed (`island`) has a bump piercing the
surface, so there is a genuine **shoreline** and the wet/dry fallback is exercised.

| Metric | Result |
|---|---|
| Worst spurious velocity, 6 beds × 3 limiters | **1.554 × 10⁻¹³ m/s** |
| In human terms | ~5 micrometres per year |
| Margin below "physically negligible" (1e-3 m/s) | ~10 orders of magnitude |
| Flat bed | **exactly 0** |
| Tolerances | velocity < 1e-9 m/s · surface < 1e-9 m · mass < 1e-12 relative |

Both `wall` and `open` boundary conditions are separately tested on a sloping bed,
because a boundary leak is easy to dismiss as "just a boundary effect" instead of
the bug it is.

**Chart:** `outputs/validation/01_lake_at_rest.png`

### Rung 2 — Ritter (1892), dry bed · `tests/test_ritter.py`

Instantaneous full-width dam removal, flat frictionless bed, nothing downstream.
Exact solution known since 1892. Setup: `h0 = 10 m`, domain 1000 m, dam at 500 m,
`t_end = 20 s`, Manning n = 0 (Ritter assumes frictionless — leaving friction on
means comparing against the wrong problem).

This is the closest analytical problem to what the whole project is for. It
exercises the dry-bed wave speeds, the wetting/drying logic continuously, and the
rarefaction structure all at once.

| Metric | Result |
|---|---|
| Front position @ 0.1 m (reported threshold), dx=2 m | 833.0 m vs exact 835.0 m → **−2.0 m** (1 cell) |
| Front error vs resolution @ 0.1 m | dx=4 → −8.0 m · dx=2 → −2.0 m · dx=1 → −2.0 m |
| Depth at the dam | matches `(4/9)·h₀ = 4.444 m` to < 2% |
| Velocity at the dam | matches `(2/3)·√(gh₀) = 6.603 m/s` to < 2% |
| Peak velocity | 18.79 m/s = **95%** of theoretical `2√(gh₀) = 19.81 m/s`, approached **from below** |
| L1 depth error | dx=4 → 0.0123 m · dx=2 → 0.0060 m · dx=1 → 0.0030 m |
| Observed convergence order | **1.03, 1.03** |
| Mass error | **−3.64 × 10⁻¹⁶** over 499 steps |

**On the convergence order:** the exact solution has kinks in its derivative at the
rarefaction head and the wetting front, so a second-order scheme *cannot* achieve
second-order convergence on it globally. Published MUSCL results on Ritter converge
at roughly first order. We **measure and report** the observed order rather than
asserting 2.0 — claiming second-order convergence on a problem that cannot deliver
it would be exactly the kind of overclaim this project avoids.

**Documented limitation, measured not hidden:** Ritter's exact solution has a
vanishingly thin tongue at the leading edge (11 mm deep 20 m behind the tip, 0.1 mm
deep 2 m behind it). No grid scheme tracks that; ours reports the 1 cm contour
**−18.0 m** short. Two assertions make this a limitation rather than a bug: (1) it
does **not** scale with `h_min` — measured lag is essentially identical for `h_min`
from 1e-3 down to 1e-6, so an arbitrary solver parameter is not controlling the
physics; (2) it is confined to the film — at 0.1 m the same run is within one cell,
at 0.5 m it is exact.

Peak velocity is bounded on **both** sides deliberately: too low means momentum is
being destroyed at the wetting front (retards arrival time); too high means an
unguarded `hu/h` is manufacturing velocity (inflates hazard, since hazard scales
with depth × velocity, and eventually breaks CFL).

**Chart:** `outputs/validation/02_ritter_dry_bed.png`

### Rung 3 — Stoker (1957), wet bed · `tests/test_stoker.py`

Dam break onto a **wet** bed: a rarefaction matched to a **shock**. Tailwaters
tested: 5.0, 1.0, 0.1 m against `hl = 10 m`.

**This matters directly for Malpasset**, because the Reyran carried baseflow — so
the 1959 event propagated as a **bore**, not a dry-bed front. It is also the only
rung that exercises shock capturing at all.

| Metric | Result |
|---|---|
| Bore position error (hl:hr = 10:1, bore travelled 196.4 m) | dx=4 → **−0.008 m** · dx=2 → **−0.015 m** · dx=1 → **+0.013 m** |
| As a fraction of distance travelled | **0.008%** |
| Middle state | `hm = 3.9617 m`, `um = 7.3408 m/s` |
| Bore speed (Rankine–Hugoniot) | **9.8193 m/s** |
| Bore captured in | **2 cells** at dx=2 m (HLLC+MUSCL should give 2–4 — genuinely upwinding, not diffusing) |
| Monotonicity: overshoot above `hl` | **0.00 × 10⁰ m** (all three limiters) |
| Monotonicity: undershoot below `hr` | **0.00 × 10⁰ m** (all three limiters) |
| L1 depth error | dx=4 → 0.0130 m · dx=2 → 0.0067 m · dx=1 → 0.0036 m |
| Observed convergence order | **0.97, 0.88** — first order, which is *correct* for a shock |
| Mass error | **−9.92 × 10⁻¹⁶** over 497 steps |

**Hand-verified against theory:** `cm = √(9.81 × 3.9617) = 6.2341`, and
`2(cl − cm) = 7.3410` ✓ matches `um = 7.3408`. Bore speed
`hm·um/(hm − hr) = 29.081/2.9617 = 9.8190` ✓ matches 9.8193. Textbook values.

**The three failure modes this rung targets**, and why each is dangerous:

1. **Wrong bore speed** — error grows *linearly in time*, so every arrival time is
   progressively more wrong the further downstream you look.
2. **Smeared bore** — makes arrival time depend on which depth contour you pick,
   destroying the reproducibility of the headline number.
3. **Oscillation** — produces a **phantom wave arriving BEFORE the real flood.**
   This is the most dangerous possible error in an early-warning tool: it would
   trigger evacuation at the wrong time and destroy trust in every subsequent
   warning. The monotonicity test is flagged in-file as **"THE MOST
   SAFETY-CRITICAL TEST IN THE VALIDATION LADDER"** and asserts global bounds plus
   a separate "no ripple 15 cells ahead of the bore" check.

**A measurement trap that was caught and fixed** — worth knowing about, because the
same trap exists for any front-position measurement: `_shock_position` originally
returned the nearest cell **face**, which quantised the answer to `dx`. The exact
bore sits at 696.386 m, and 696 is divisible by 4, 2 **and** 1 — so all three
resolutions reported the *same* −0.4 m error and the measurement looked
grid-independent when it was really just rounding to the same place. Fixed by
interpolating the half-height crossing sub-cell. Errors became −0.008 / −0.015 /
+0.013 m and tolerances were tightened (position 2.0·dx → 1.0·dx, speed 3% → 1%).

**Chart:** `outputs/validation/03_stoker_wet_bed.png`

### Rung 4 — Malpasset · NOT STARTED

Reference data is in the repo (§5A). **The blocker is bathymetry**: we need the
Reyran valley bed registered to the **EDF local planimetric frame** that the
reference CSVs use, and no EPSG code exists for that frame.

Two candidate routes:

1. **Obtain the openTELEMAC `malpasset` case geometry** (mesh or node x,y,z),
   which is already in the local frame. Cleanest if available.
2. **Fit an affine transform** from the local frame to a real-world CRS using known
   correspondences, then sample Copernicus DEM over the Reyran valley. Note
   `transformers_abc.csv` carries an `x_telemac_m` column, which is a hint that
   such a registration exists in the literature.

⚠️ This is the one genuinely open-ended research task remaining and it is **not on
the critical path to Monday's screenshots.** Time-box it.

---

## 10. The terrain pipeline

`backend/jaldrishti/terrain/dem.py` — **built and working.**

### Data source: Copernicus DEM GLO-30

30 m global DEM from TanDEM-X radar interferometry, distributed as **Cloud-Optimized
GeoTIFF on AWS open data with NO authentication required.**

That last property decided it. Every alternative gates on approval we do not have
and cannot wait for: NASA Earthdata (registration), OpenTopography (API key),
Google Earth Engine (approval can take days). **This finding removed the NASA
Earthdata and OpenTopography dependencies from the critical path entirely.**

It is also the better DEM: TanDEM-X has far fewer voids than SRTM and no
SRTM-style radar shadow gaps in steep Himalayan terrain — which is exactly where
our domains are.

| Property | Value |
|---|---|
| URL pattern | `https://copernicus-dem-30m.s3.amazonaws.com/{TILE}/{TILE}.tif` |
| Tile naming | `Copernicus_DSM_COG_10_N30_00_E078_00_DEM` (named by SW corner; `10` = GLO-30, `30` = GLO-90) |
| Format | Tiled COG, 1024×1024 blocks, overviews [2,4,8], float32, EPSG:4326, 1 arcsec |
| Auth | None — HTTP 206 range requests work anonymously |
| Vertical accuracy | better than 4 m (90% linear error) |
| Acquisition | 2011–2015 |

Required GDAL env (set as module-level side effects in `dem.py`, because forgetting
them produces a confusing 403 rather than an obvious error):

```
AWS_NO_SIGN_REQUEST=YES
GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR
CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif
GDAL_HTTP_MULTIPLEX=YES · GDAL_HTTP_VERSION=2 · VSI_CACHE=TRUE · VSI_CACHE_SIZE=100000000
```

### ⚠️ The limitation that shapes the architecture

**Radar does not penetrate water.** The DEM was acquired 2011–2015; Tehri was
commissioned in 2006. So for Tehri the DEM records the **reservoir water surface as
a flat plateau**, not the valley floor beneath it. **The bathymetry is simply
absent.**

Two consequences, neither optional:

1. A reservoir volume computed by integrating `(FRL − DEM)` is a **lower bound**,
   and a bad one. The released volume **must** come from the published gross storage
   figure (CWC / NRLD), not from the terrain.
2. Initialising the reservoir with `set_surface(FRL)` over the DEM would give almost
   **zero depth**, because the DEM surface already *is* the water. The reservoir
   would appear empty.

**Therefore: we do not resolve the reservoir on the grid at all.** The far-field
domain starts at the dam, and the breach enters as an **inflow hydrograph** derived
from the published storage–elevation relationship (or from the SPH near-field
model). The DEM is used only for downstream routing, which is what it can actually
support.

This is not a weakness in the submission. Every serious dam-break study handles
reservoir volume this way, and *"where did you get the bathymetry?"* is the right
question for a jury to ask — we should have the answer ready rather than a filled
contour that quietly assumes it away.

### Other stated limitations

- **GLO-30 is a DSM, not a DTM** — it includes vegetation and buildings. In a
  forested Himalayan valley the apparent bed sits above the true bed by roughly the
  canopy height, and depths are biased accordingly.
- **A 30 m cell cannot resolve a gorge narrower than ~90 m.** The Bhagirathi is
  locally narrower, so the modelled channel is wider and shallower than the real
  one, which spreads and slows the wave.
- Flood depths below the 4 m vertical accuracy are not individually meaningful —
  this is the quantitative reason the arrival-time threshold is 0.1 m rather than
  1 mm.

### Pipeline API

```python
from jaldrishti.terrain import prepare_terrain, metric_extent_for, TerrainGrid

grid = prepare_terrain(
    dst_crs="EPSG:32644", dx=90.0,
    points=[(lat, lon), ...],   # domain must contain these
    margin_km=8.0,
    cache_dir=DATA_DIR / "dem",
    max_fill_m=2.0,
)
# → TerrainGrid(.z, .dx, .crs, .transform, .mask_valid, .source, .conditioning)
#   .shape · .bounds · .summary() · .to_geotiff(path, array=None)
```

Stages: `fetch_dem` → `to_metric_grid` → `fill_voids` → `fill_depressions`.

**Extent-first design.** We define the output rectangle *first* and fetch terrain to
fill it, rather than reprojecting a lat/lon box and accepting whatever falls out.
The difference is not cosmetic: a lat/lon rectangle maps to a **curved
quadrilateral** in UTM, so the bounding box around it has empty corners. Filling
those by interpolation invents terrain and inflated the void count from the true
0.05% to **4.5%** — which would have made the interpolated-cell flag useless.
`geographic_bounds_for` uses `transform_bounds(..., densify_pts=64)` because the
edges bow outward: the extreme latitude of a UTM rectangle's northern edge is at
its *middle*, not at either corner.

Snapping to whole multiples of `dx` means the 30 m and 90 m grids are **nested and
directly comparable**, so a resolution-sensitivity figure is like-for-like.

**Depression filling is deliberately less aggressive than in a normal hydrology
pipeline.** Classic D8 flow routing cannot tolerate a single pit, so hydrology
pipelines fill everything. A shallow water solver has no such problem: water that
runs into a real depression fills it and stops, which is what real water does.
Over-filling would **destroy information** — a filled depression cannot store water,
so the flood arrives downstream too early and too large. What we *do* need to remove
are the spurious one- and two-cell pits radar DEMs produce as speckle noise, of
which there are thousands at 30 m. Hence `max_fill_m` caps depression depth
(default 2.0 m), applied **all-or-nothing per connected depression** — partially
filling one would leave an unphysical shelf part-way up its side.

Void filling is **nearest-neighbour** on purpose: with voids this sparse, a fancier
interpolant would imply precision we do not have. `mask_valid` is preserved through
every stage so output can mark interpolated cells rather than presenting them as
measured.

### Measured results — Tehri domain

Domain derived from the dam + 4 downstream POIs with an 8 km margin.
UTM 44N extent: `xmin=218280, ymin=3308130, xmax=276660, ymax=3371310`
(≈ 58.4 × 63.2 km).

| | 90 m | 30 m |
|---|---|---|
| Grid | 649 × 702 | 1946 × 2106 |
| Cells | 455,598 | **4,098,276** |
| Voids after reprojection | 214 (**0.047%**) | 2,006 (**0.049%**) |
| Depression cells filled (2 m cap) | 2,743 | 46,925 |
| Storage removed by filling | 12.9 × 10⁶ m³ | 19.0 × 10⁶ m³ |
| Elevation range | 261 – 2752 m | 261.0 – 2764.1 m |
| Wall time (cold, incl. network) | 23.9 s | 21.0 s |

**Cross-validation that the whole chain is correct:** DEM bed at the dam reads
**830.3 m** (90 m grid) / **827.4 m** (30 m) against a published FRL of **830.0 m**.
The 5×5 window around it shows the dam itself — reservoir surface at 814–820 m to
the north, a crest ridge at 827–833 m, then a fast drop to 754–808 m to the south.
This simultaneously confirms the dam lat/lon in `config.py`, the reprojection, and
the DEM. It also confirms the bathymetry limitation directly: the reservoir reads as
a **flat surface below FRL**, i.e. we are seeing water, not bed.

### ⚠️ Feasibility problem: 4.1 M cells at 30 m

`CLAUDE.md` claims the 30 m precomputed run takes 15–30 min. At 4.1 M cells a
3-hour flood needs roughly 33,000 timesteps, which realistically lands at
**50–120 min**, not 15–30.

**Most of that box is ridgeline that never gets wet.** So the DEM-derived valley
mask is **not cosmetic — it is what makes the 30 m run feasible.** Building it is a
prerequisite for the high-res deliverable, not a nice-to-have.

---

## 11. The provenance system in `config.py`

**The problem this solves:** get the full reservoir level wrong by 5 m on Tehri and
the released volume — and therefore every downstream depth, arrival time and
exposure count — is wrong, **with no symptom anywhere in the output.** A number
cited from memory looks exactly like a number read off a CWC gazette.

So every slide-facing physical quantity carries machine-checkable provenance:

```python
@dataclass(frozen=True)
class Source:
    citation: str
    verified: bool = False
    note: str = ""
    def __str__(self):
        mark = "verified" if self.verified else "UNVERIFIED"
        return f"[{mark}] {self.citation}" + (f" ({self.note})" if self.note else "")
```

This lets the export layer **refuse to present unchecked figures as fact.**

Dataclasses: `Source` · `DamSpec` · `BreachSpec` · `Blockage` · `Domain` ·
`PointOfInterest` · `StudyArea`.

`Domain` carries both resolutions (`dx_interactive_m`, `dx_highres_m`) plus
`.shape(dx)` and `.cost_estimate(dx)` — so a bad resolution choice is caught
*before* a run rather than after twenty minutes of waiting.

Constants: `WGS84="EPSG:4326"` · `UTM44N="EPSG:32644"` (Uttarakhand) ·
`UTM43N="EPSG:32643"` · `REPO_ROOT` · `DATA_DIR` · `OUTPUT_DIR` · `REFERENCE_DIR`.

API: `get(key)` · `unverified(prefix=None)` · `provenance_report(key=None)` · plus a
`__main__` block.

```bash
python -m jaldrishti.config
```

lists all currently-unverified quantities. **There are 18.**

> ⚠️ **Standing rule from `CLAUDE.md`:** dam specifications must be verified against
> CWC / National Register of Large Dams sources **before they appear on any slide.**

---

## 12. Build state: what is done, what is not

**≈ 31% complete, weighted by effort.**

| Component | Weight | Done | Notes |
|---|---|---|---|
| SWE solver core | 25% | **85%** | Validated rungs 1–3. Missing rung 4 (Malpasset) |
| Terrain pipeline | 10% | **70%** | DEM fetch/reproject/condition done. Missing Manning-*n* from landcover, **valley mask** |
| `config.py` + provenance | 3% | **90%** | 18 numbers unverified; 1 bad POI coordinate |
| Breach + reservoir drawdown + scenario runner | 8% | 0% | — |
| **Analysis: arrival time, hazard, exposure, damage** | 12% | 0% | **The differentiator** |
| **Export: GeoTIFF/COG, .shp, .kml, PDF** | 8% | 0% | **PS-mandated** |
| Frontend (Next.js + deck.gl) | 15% | 0% | Directory does not exist |
| SPH near-field | 6% | 0% | Cut candidate #2 |
| FastAPI | 5% | 0% | — |
| Delft3D adapter | 4% | 0% | Authorised; specs research was in flight |
| GEE Sentinel-1 | 2% | 0% | Cut candidate #1 |
| Deck / PPT | 2% | 0% | **Hard deadline** |

**Honest framing: it is ~30% of the work but the *riskiest* 30%.** A wrong Riemann
solver is unrecoverable in six days; a missing KML export is two hours. Everything
remaining is assembly and presentation — which plays to the builder's strengths.

### Agreed working order (descending completion %)

1. **`config.py` 90% → 100%** — verify the 18 quantities against CWC/NRLD, fix the Koteshwar coordinate
2. **Solver 85% → 100%** — rung 4, Malpasset ⚠️ *time-box; open-ended and off the critical path*
3. **Terrain 70% → 100%** — Manning *n* from landcover, valley mask
4. Then the 0% items, critical-path first (§13)

---

## 13. Critical path and schedule

**Today: Saturday 29 August 2026. Final deadline: ~Friday 4 September 2026.**

### 🔴 Monday 31 August — PPT screenshots

From `CLAUDE.md`: *"Screenshots for the PPT must exist by Day 3 (Mon 31 Aug) — get
an ugly-but-real inundation map early. The deck is the hard deadline; polish is
negotiable."*

**Minimum viable path to that screenshot — nothing else is on it:**

```
breach hydrograph  →  scenario runner  →  arrival-time array  →  one PNG
```

Concretely:
1. `jaldrishti/scenario/breach.py` — parametric breach + reservoir drawdown → outflow hydrograph `Q(t)`
2. `jaldrishti/scenario/run.py` — glue terrain + hydrograph + `SWE2D`, inject inflow at the dam cell, run with a `callback` accumulating max-depth / max-velocity / first-arrival
3. `jaldrishti/analysis/arrival.py` — arrival time at the 0.1 m threshold
4. Render one map. Ugly is fine.

SPH, GEE, Delft3D and the frontend are **all off this path** and are the designated
cut order anyway.

### After Monday

5. Export layer — GeoTIFF/COG, **Shapefile**, **KML** (PS-mandated), PDF report
6. Exposure + damage (population raster zonal stats, ₹ estimates)
7. FastAPI + Next.js/deck.gl dashboard (Indian-flag chrome)
8. Malpasset rung 4 if not already done
9. SPH near-field · Delft3D adapter · GEE — in that order, cut from the bottom

---

## 14. Environment and how to run things

**Conda env name: `jaldrishti`.** Miniforge is an **all-users install under
`C:\Users\Public`** and **conda is NOT on PATH.** Always invoke by full path:

```bash
/c/Users/Public/miniforge3/Scripts/conda.exe run -n jaldrishti --no-capture-output python -m pytest tests/ -q
```

> ⚠️ **Do not use `conda run python -c "..."`** — nested quoting with f-string
> escapes crashes conda itself and produces a conda error report rather than
> running your code. **Write the script to a file and run the file.**

### Installed and verified

scipy 1.17.1 · scikit-image 0.26.0 · numba 0.67.0 · rasterio 1.4.4 · pyproj 3.7.2 ·
geopandas 1.1.4 · shapely 2.1.2 · fiona 1.10.1 · matplotlib 3.11.1 ·
simplekml 1.3.2 · reportlab 5.0.1 · xarray 2026.7.0 · netCDF4 1.7.4 · pandas 3.0.5

`skimage.morphology.reconstruction` is the fast route to depression filling (already
used). `netCDF4` will be needed by the Delft3D FM output writer.

**Absent:** `earthengine-api` (install only if Phase 7 / GEE survives the cut).
**Not installed:** QGIS — needed for the field-dump debugging protocol and as the
verification path for the Delft3D FM output writer.

### `environment.yml` design rule

There is deliberately **no `pip:` section.** Any genuinely pip-only package must be
installed with `--no-deps` so pip cannot overwrite conda's compiled geospatial
stack. Do not pip-install GDAL/rasterio/geopandas on Windows under any
circumstances.

### Common commands

```bash
# full test suite
/c/Users/Public/miniforge3/Scripts/conda.exe run -n jaldrishti --no-capture-output python -m pytest tests/ -q
```

```bash
# regenerate the validation charts and print the headline numbers
/c/Users/Public/miniforge3/Scripts/conda.exe run -n jaldrishti --no-capture-output python -m pytest tests/ -q -s -k chart
```

```bash
# list all unverified physical quantities
/c/Users/Public/miniforge3/Scripts/conda.exe run -n jaldrishti --no-capture-output python -m jaldrishti.config
```

```bash
# terrain pipeline build check on Tehri
/c/Users/Public/miniforge3/Scripts/conda.exe run -n jaldrishti --no-capture-output python scripts/check_terrain.py
```

### Git

Branch **`master`** (the only branch — it is the default of this solo repo). Last
commit `3b055fe` "Add 2D SWE solver core and validation ladder rungs 1-3".

`.gitignore` excludes `data/`, `outputs/`, `.env`, `*.credentials`,
`service-account*.json`, `*-privatekey.json`, `.venv/`.

---

## 15. Known bugs, open questions, and traps

### 🐛 Confirmed bugs

**1. `Koteshwar Dam` POI coordinate is wrong.** `config.py` has
`(30.2620, 78.4650)`, which the DEM reads as bed **963.8 m** (90 m grid) / 950.5 m
(30 m). Koteshwar is *downstream* of Tehri with an FRL around 612 m — it cannot be
350 m above Tehri's reservoir. The coordinate is on a hillside, not in the valley.
Devprayag (467 m), Rishikesh (363 m) and Haridwar (292 m) are all plausible.

> **Cross-checking POI elevations against the DEM is now a cheap standing check and
> should be run on every new POI.** This is exactly the class of error that would
> silently corrupt the arrival-time table with no visible symptom.

**2. 18 unverified physical quantities.** `python -m jaldrishti.config` lists them.
Blocks any slide use.

### 📌 Open questions

- **Malpasset local-frame registration** (§9 rung 4). The only open-ended research
  task left.
- **Valley mask algorithm.** Needed for 30 m feasibility. Likely: flow accumulation
  from the conditioned DEM, or a simple elevation-band buffer around the channel
  centreline. Must not clip the flood.
- **Manning *n* from landcover.** Source not yet chosen (ESA WorldCover is the
  obvious candidate, also on AWS open data without auth).
- **Population raster** for exposure. WorldPop or GHSL; neither yet wired in.
- **Delft3D adapter specs.** A background research workflow (`wf6d0w2f3`) was in
  flight and never reported. Re-run or research fresh. Once specs are in hand:
  write the modules, round-trip tests, and an explicit *"not validated against a
  real Delft3D binary"* flag.

### ⚠️ Stale documentation

- **`PLAN.md:19`** — "GEE approval takes days" is known wrong, and the matching
  risk-register row needs removing.
- **The entire DEM-acquisition risk row in `PLAN.md`** is obsolete — Copernicus is
  auth-free (§10).
- **`PLAN.md` schedule section** needs replacing to match the phase-based plan.
- **`CLAUDE.md`** claims the 30 m run takes 15–30 min; realistic is 50–120 min
  without a valley mask (§10).
- **`backend/requirements.txt`** (pip, for Render/Linux deployment) does not exist
  yet and must be kept in version-sync with `environment.yml`.

### 🪤 Traps — mistakes already made once

| Trap | What happens |
|---|---|
| Slicing `s.h[ng:-ng, ng:-ng]` | `SWE2D.h` is **already** the interior field. Slicing gives a zero-size array and `ValueError: zero-size array to reduction operation maximum` |
| Enabling `fastmath` | Silently destroys well-balancedness. Rung 1 catches it; nothing else will |
| Measuring a front at cell faces | Quantises to `dx` and can produce fake grid-independence when the exact answer happens to sit on a common divisor. Interpolate sub-cell |
| `conda run python -c "..."` | Crashes conda on nested quotes. Use a script file |
| Filling all depressions | Destroys real valley storage → flood arrives too early and too large |
| Reprojecting a lat/lon box and keeping the bbox | Empty corners → 4.5% fake voids. Use `metric_extent_for` |
| Initialising the reservoir with `set_surface(FRL)` | The DEM surface **is** the water. Gives ~zero depth. Use a hydrograph |
| Claiming we ran Delft3D | Absolutely prohibited. Adapter only |
| Implying the model is 3D | It is 2D depth-averaged. Only the *rendering* is 3D |

### 🚫 Never-overclaim rules

The PS says "probable" and "confidence-based" repeatedly. Accordingly:

- Report uncertainty. Show breach formation time as a **range**, not one flattering number.
- Flag resolution limits explicitly on every map.
- State that Chamoli was a **debris flow**, which SWE only approximates via bulking
  factor and elevated roughness.
- State that Malpasset's Manning *n* is **calibrated, not measured**.
- State that reservoir volume comes from published storage figures, **not** from
  DEM bathymetry (which does not exist).
- Never claim we ran Delft3D.
- Never imply 3D hydrodynamics.

**Volunteering understood limitations is what makes a jury trust the rest.** It is a
scoring strategy, not modesty.

### GEE-specific constraint

`gee/flood_observe.py` must use `ee.batch.Export.image.toDrive()`, **never**
`toCloudStorage()` — the GEE Community tier has no billing account attached.

---

## 16. Update protocol

When you change the build state, update these sections of this file — in this
order, so the header stays trustworthy:

1. **Header block** — `Last updated`, `Commit at time of writing`, `Build state %`
2. **§8** file inventory — new files, line counts, ✅/❌ status
3. **§9** if a validation rung moved — paste the **actually measured** numbers, do
   not write them from memory. Regenerate with the `-k chart` command in §14
4. **§12** the weighted table — adjust `Done %` and the working order
5. **§13** if the critical path changed or a deadline moved
6. **§15** — add new bugs and traps; **delete** entries that are fixed
7. **§14** if a package was installed or a command changed

**Verify, do not recall.** Every number in §9, §10 and §12 was produced by running
something. If you cannot re-derive a number, mark it as unverified rather than
carrying it forward. That rule is the same one `config.py` enforces on physical
quantities, and it applies to this document too.

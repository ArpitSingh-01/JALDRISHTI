"""
Scenario orchestration — one real place, one hypothetical failure, one bundle.

This is the module that turns the library into a product. Everything it calls is
already written and tested in isolation; the value here is the WIRING, and in
particular the handful of physical decisions that only exist once terrain, a
reservoir, a breach model and a solver have to agree with each other. Those
decisions are recorded below rather than buried at the call site, because each
one is a question a jury can reasonably ask.


DECISION 1 — THE RESERVOIR IS INITIALISED AT THE DEM'S OWN WATER SURFACE,
             NOT AT THE PUBLISHED FULL RESERVOIR LEVEL
-------------------------------------------------------------------------------
Copernicus DEM renders standing water as a flat plateau at whatever the water
surface was on the acquisition date. At Tehri that plateau reads 814.0 m, against
a published FRL of 830.0 m. Two ways to put a reservoir in the model:

  (a) initialise live water up to 830.0 m, or
  (b) initialise live water at the 814.0 m surface the DEM actually shows.

We do (b). (a) fails for a concrete reason, not a stylistic one: at dx = 90 m the
DEM's dam crest has cells at 829.8 m and 828.6 m — BELOW 830.0 m — so a pool
initialised at FRL spills over the crest on the first timestep and the model
invents a dam failure that was never requested. The same setup holds at dx = 30 m
(crest 834.7 m). A setup whose behaviour changes with dx is a silent trap, and
the only way to make (a) work at both resolutions is to burn a synthetic crest
into the DEM — i.e. to invent terrain. We would rather show a lake 16 m low and
say why.

The lake is therefore STATIC and contributes NO mass to the flood. It exists so
that (i) the reservoir appears on the map as water rather than as dry ground,
(ii) `initially_wet` is populated so hazard/arrival can separate NEW flooding
from water that was always there, and (iii) `total_wetted_area_km2` is
meaningful. It is a lake at rest on real terrain, which is exactly what
validation rung 1 (well-balanced, residual 2e-14 m/s) certifies the solver can
hold without drifting.


DECISION 2 — BREACH MASS COMES FROM THE LUMPED RESERVOIR MODEL, INJECTED BELOW
             THE DAM
-------------------------------------------------------------------------------
All the water that floods downstream comes from `breach.simulate_breach`, which
drains a lumped storage curve A(h) built from the PUBLISHED gross storage at the
PUBLISHED FRL. So the released volume is right even though the 2D lake is low.
Q(t) and the matching weir velocity U(t) are injected at a single cell in the
channel immediately downstream of the dam.

DECISION 3 — AND THEREFORE THE TWO ARE DISJOINT, WHICH IS THE POINT
-------------------------------------------------------------------------------
Decisions 1 and 2 touch different water. The static lake is upstream of the
crest and never moves; the injected hydrograph appears downstream of it. Nothing
is counted twice. Initialising live water at FRL *and* injecting Q(t) would
double-count the reservoir, and it is the single easiest way to produce a flood
that is roughly twice as large as reality while looking entirely plausible.


DECISION 4 — BOUNDARIES THE RESERVOIR TOUCHES ARE WALLED
-------------------------------------------------------------------------------
The Tehri domain is sized from the dam plus the downstream towns, so it extends
only ~8 km upstream of the dam while the real reservoir is ~45 km long. The pool
is therefore cut off by the domain edge. Against an OPEN boundary a static lake
drains straight out of the model — silently, and at a rate that looks like a
plausible flood. Any array edge the pool touches is switched to WALL, and which
ones is recorded. This is sound precisely because the lake carries no mass: a
wall upstream of a reservoir that never moves removes nothing real.

A trap worth stating once: `SWE2D`'s `bc` tuple is (west, east, south, north) in
INDEX space, and `_fill_ghosts` applies `bc_s` at j = 0. In a north-up raster
row 0 is the geographic NORTH edge, so the solver's "south" is the map's north.
We therefore key the wall logic off ARRAY edges (j0/jmax/i0/imax), never off
compass names, and use the transform only to label things for humans.


DECISION 5 — SNAP SUSPICION IS PROPAGATED, NEVER SWALLOWED
-------------------------------------------------------------------------------
The injection cell has to sit in the river, not on the valley wall, so it is
snapped to the channel by contributing area. `HydroGrid.snap_to_stream` sets
`info["suspect"]` when a much larger channel sits just outside the search radius
— which is a known live defect at Tehri (ROADMAP B4). When that fires, the run
still completes, but the flag lands in the summary's `unverified_inputs` and
`limitations`, so the number carries its own warning. Until B4 is fixed, NO
Tehri depth/velocity/arrival/exposure figure is presentable as fact.


DECISION 6 — AN IMPOSSIBLE BREACH GEOMETRY IS CLAMPED LOUDLY
-------------------------------------------------------------------------------
`BreachGeometry.check_fits` raises rather than clamps, on the grounds that
clamping the TOP width would leave `weir_outflow` integrating a trapezoid the
geometry no longer matches. Tehri's configured breach (600 m bottom width, 230 m
deep, 1:1 sides) has a top width of 1060 m in a 575 m crest, so it would raise.
We clamp the BOTTOM width via `max_bottom_width` and rebuild the geometry, which
keeps the trapezoid exactly self-consistent, and we record the clamp in
`breach_provenance` and in the limitations. The config value is not silently
overwritten and it is not allowed to crash the run either.


DECISION 7 — DAMAGE IS OPT-IN
-------------------------------------------------------------------------------
`ScenarioSummary.is_presentable()` returns False permanently once damage figures
exist, and every entry in `DAMAGE_SOURCES` is `verified=False`. So a run WITHOUT
damage can still be presentable, and a run with it cannot. Damage is therefore
off by default and turned on deliberately, per `damage=True`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..analysis import (
    ScenarioSummary,
    analyse_arrival,
    analyse_exposure,
    classify_hazard,
    resample_population,
)
from ..config import DATA_DIR, OUTPUT_DIR, STUDY_AREAS
from ..solver.swe2d import OPEN_BC_INFLUENCE_CELLS, SWE2D
from ..terrain import analyse_flow, prepare_terrain, roughness_for
from .breach import (
    BreachGeometry,
    ReservoirStorage,
    froehlich_peak_outflow,
    max_bottom_width,
    mlm_peak_outflow,
    simulate_breach,
    usbr_peak_outflow,
)

# The depth that counts as flooded. Used in exactly three places — the solver's
# accumulator, the hazard classifier and the arrival analysis — and they MUST
# agree, or "flooded area" and "area with an arrival time" describe different
# sets of cells and no one notices.
WET_THRESHOLD_M = 0.1

# Default population raster. WorldPop constrained, 2020, India.
DEFAULT_POPULATION = DATA_DIR / "population" / "ind_ppp_2020_constrained.tif"

# Array edge -> index into SWE2D's (west, east, south, north) bc tuple.
# See DECISION 4: the solver's "south" is applied at j = 0, which in a north-up
# raster is the geographic north edge. Keyed off array edges on purpose.
_EDGE_TO_BC_INDEX = {"i0": 0, "imax": 1, "j0": 2, "jmax": 3}


def _val(x):
    """Unwrap a config `Source(value=..., ...)` wrapper into a plain float."""
    return float(x.value) if hasattr(x, "value") else float(x)


def _maybe(x):
    """`_val` that tolerates None."""
    return None if x is None else _val(x)


# ---------------------------------------------------------------------------
# reservoir detection
# ---------------------------------------------------------------------------

@dataclass
class Pool:
    """The reservoir as the DEM actually shows it — measured, not assumed."""
    mask: np.ndarray
    level_m: float
    area_km2: float
    seed: tuple[int, int]
    touches: tuple[str, ...]          # array edges: 'j0' | 'jmax' | 'i0' | 'imax'
    suspect: bool = False
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        edges = ", ".join(self.touches) if self.touches else "none"
        return (f"pool: level {self.level_m:.1f} m, area {self.area_km2:.1f} km2, "
                f"{int(self.mask.sum()):,} cells, touches edges [{edges}]"
                f"{'  SUSPECT' if self.suspect else ''}")


def detect_pool(z, *, near_jj, near_ii, dx, search_cells=30, flat_tol=0.01,
                min_flat_cells=25, published_area_m2=None, verbose=True):
    """
    Find the reservoir as the largest FLAT region near the dam, then fill to it.

    Copernicus DEM renders standing water as a plateau at the water-surface
    elevation on the acquisition date. That artefact is the most useful thing in
    the dataset for this purpose: it means the reservoir does not have to be
    guessed at from the published FRL, it can be MEASURED off the DEM. The
    measured level is what we can defend; the published level is what we cannot
    reconcile with the DEM's own crest (see DECISION 1).

    Two stages:

      1. Flat detection. A cell is flat if it equals all four neighbours within
         `flat_tol`. Connected components of flat cells that come within
         `search_cells` of the dam are candidates; the largest wins. Depression
         filling (`max_fill_m = 2.0`) also creates flats, which is why the
         largest component is taken and a minimum size is enforced — a filled
         speckle pit is a handful of cells, a reservoir is thousands.

      2. Fill to level. The pool is the 4-connected component of
         `z <= level` containing the flat seed. This picks up the shoreline
         cells that sit just below the water surface but are not themselves
         flat.

    Returns None if no plausible flat water body is found, which is the correct
    answer for a blockage scenario with no impoundment yet.
    """
    from scipy import ndimage

    z = np.asarray(z, dtype=np.float64)
    ny, nx = z.shape

    # --- stage 1: flat regions ------------------------------------------------
    flat = np.zeros((ny, nx), dtype=bool)
    c = z[1:-1, 1:-1]
    flat[1:-1, 1:-1] = (
        (np.abs(c - z[:-2, 1:-1]) <= flat_tol)
        & (np.abs(c - z[2:, 1:-1]) <= flat_tol)
        & (np.abs(c - z[1:-1, :-2]) <= flat_tol)
        & (np.abs(c - z[1:-1, 2:]) <= flat_tol)
    )
    if not flat.any():
        return None

    # 4-connectivity: diagonal-only touching is not the same water body.
    struct4 = ndimage.generate_binary_structure(2, 1)
    lab, n = ndimage.label(flat, structure=struct4)
    if n == 0:
        return None

    # Candidates are components with a cell inside the search window.
    j0 = max(0, near_jj - search_cells)
    j1 = min(ny, near_jj + search_cells + 1)
    i0 = max(0, near_ii - search_cells)
    i1 = min(nx, near_ii + search_cells + 1)
    near_labels = np.unique(lab[j0:j1, i0:i1])
    near_labels = near_labels[near_labels > 0]
    if near_labels.size == 0:
        return None

    sizes = ndimage.sum(flat, lab, index=near_labels).astype(np.int64)
    best = int(near_labels[int(np.argmax(sizes))])
    best_size = int(sizes.max())
    if best_size < min_flat_cells:
        if verbose:
            print(f"  no flat water body >= {min_flat_cells} cells near the dam "
                  f"(largest was {best_size}) — treating as no reservoir")
        return None

    seed_mask = lab == best
    level = float(np.median(z[seed_mask]))
    sj, si = (int(a[0]) for a in np.where(seed_mask))

    # --- stage 2: fill to that level ------------------------------------------
    below = z <= level + 1e-6
    lab2, _ = ndimage.label(below, structure=struct4)
    comp = int(lab2[sj, si])
    pool = lab2 == comp if comp > 0 else seed_mask

    cell_km2 = (float(dx) ** 2) / 1.0e6
    area_km2 = float(pool.sum()) * cell_km2

    touches = []
    if pool[0, :].any():
        touches.append("j0")
    if pool[-1, :].any():
        touches.append("jmax")
    if pool[:, 0].any():
        touches.append("i0")
    if pool[:, -1].any():
        touches.append("imax")

    notes = []
    suspect = False
    if published_area_m2 is not None:
        pub_km2 = float(published_area_m2) / 1.0e6
        # LARGER than published is the leak test. The fill can escape over a
        # saddle into a neighbouring drainage, and area is how that shows up.
        # SMALLER is expected and not a fault: the level is below FRL and the
        # domain truncates the reservoir upstream.
        if area_km2 > pub_km2 * 1.05:
            suspect = True
            notes.append(
                f"Detected pool area {area_km2:.1f} km2 EXCEEDS the published "
                f"water spread at FRL ({pub_km2:.1f} km2) even though the "
                f"detected level ({level:.1f} m) is below FRL. The fill has "
                f"probably escaped over a saddle into an adjoining valley. "
                f"Treat the reservoir footprint as unverified.")
        else:
            notes.append(
                f"Detected pool: {area_km2:.1f} km2 at {level:.1f} m, against a "
                f"published spread of {pub_km2:.1f} km2 at FRL. Smaller is "
                f"expected — the DEM surface is below FRL and the domain "
                f"truncates the reservoir upstream.")

    if touches:
        notes.append(
            f"The reservoir reaches the domain edge ({', '.join(touches)}). "
            f"Those boundaries are walled so the static lake cannot drain out "
            f"of the model. Valid because the lake carries no mass, but it does "
            f"mean the modelled reservoir is truncated, not complete.")

    res = Pool(mask=pool, level_m=level, area_km2=area_km2, seed=(sj, si),
               touches=tuple(touches), suspect=suspect, notes=notes)
    if verbose:
        print(f"  {res.summary()}")
    return res


# ---------------------------------------------------------------------------
# run result
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    """Everything a caller might want, not just what the API serialises."""
    summary: ScenarioSummary | None
    exports: dict = field(default_factory=dict)
    run_dir: Path | None = None
    grid: object = None
    hydro: object = None
    roughness: object = None
    pool: Pool | None = None
    hydrograph: object = None
    solver: object = None
    setup: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# the orchestrator
# ---------------------------------------------------------------------------

def run_scenario(
    area,
    *,
    dx=None,
    duration_s=6 * 3600.0,
    out_dir=None,
    run_id=None,
    resolution="30m",
    margin_km=8.0,
    max_fill_m=2.0,
    stream_threshold_km2=1.0,
    snap_radius_m=2500.0,
    reservoir=True,
    crest_m=None,
    failure_mode="breach",
    release_head_m=15.0,
    release_width_m=80.0,
    release_formation_s=600.0,
    population=DEFAULT_POPULATION,
    exposure=True,
    damage=False,
    export_bundle=True,
    setup_only=False,
    log_every_s=200.0,
    verbose=True,
):
    """
    Run one scenario end to end and write an export bundle.

    Parameters
    ----------
    area        : StudyArea, or a key in STUDY_AREAS ('tehri', 'malpasset',
                  'rishi_ganga').
    dx          : grid resolution, m. Defaults to the domain's interactive
                  resolution.
    duration_s  : simulated time. NOT wall time.
    setup_only    : build terrain, reservoir, breach and solver, report the
                    setup, and stop before stepping. Use this to check a
                    configuration cheaply — the setup is where scenarios go
                    wrong, and it costs seconds instead of minutes.
    log_every_s   : how often, in SECONDS OF MODEL TIME (not steps), to record a
                    (t, volume, dt, Q_in) row into `stats.history`. That history
                    is what makes mass conservation plottable rather than merely
                    asserted.
    """
    if isinstance(area, str):
        if area not in STUDY_AREAS:
            raise KeyError(f"unknown study area {area!r}; "
                           f"have {sorted(STUDY_AREAS)}")
        area = STUDY_AREAS[area]

    dx = float(dx if dx is not None else area.domain.dx_interactive_m)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = run_id or f"{area.key}_{dx:g}m_{stamp}"
    out_dir = Path(out_dir) if out_dir is not None else OUTPUT_DIR / "runs" / run_id

    limitations: list[str] = []
    unverified: list[str] = []
    setup: dict = {"run_id": run_id, "dx_m": dx, "duration_s": duration_s}

    def say(msg):
        if verbose:
            print(msg)

    say(f"\n{'=' * 74}\n{area.title}  —  run {run_id}\n{'=' * 74}")
    say(f"scenario kind : {area.scenario_kind}")
    say(f"grid          : {area.domain.cost_estimate(dx)}")
    say(f"duration      : {duration_s / 3600.0:.2f} h simulated")

    t_wall = time.perf_counter()

    # -- 1. terrain -----------------------------------------------------------
    say("\n[1/7] terrain")
    focus = area.dam if area.dam is not None else area.blockage
    if focus is None:
        raise ValueError(f"{area.key}: needs either a dam or a blockage")
    pts = [(focus.lat, focus.lon)] + [(p.lat, p.lon) for p in area.downstream]
    grid = prepare_terrain(
        points=pts, dst_crs=area.domain.crs, dx=dx, margin_km=margin_km,
        resolution=resolution, cache_dir=DATA_DIR / "dem",
        max_fill_m=max_fill_m, verbose=verbose)
    ny, nx = grid.shape
    say(f"  {nx} x {ny} cells, source {grid.source}")

    from pyproj import Transformer
    from rasterio.transform import rowcol
    to_grid = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)

    def cell_of(lat, lon):
        xm, ym = to_grid.transform(lon, lat)
        r, c = rowcol(grid.transform, xm, ym)
        return int(r), int(c)

    fj, fi = cell_of(focus.lat, focus.lon)
    if not (0 <= fj < ny and 0 <= fi < nx):
        raise ValueError(f"{focus.name} at ({fj}, {fi}) is outside the grid")
    say(f"  {focus.name}: cell ({fj}, {fi}), bed {grid.z[fj, fi]:.1f} m")
    setup["dam_cell"] = [int(fj), int(fi)]

    # -- 2. roughness ---------------------------------------------------------
    say("\n[2/7] roughness")
    debris = bool(area.blockage is not None and area.blockage.debris_flow)
    rough = roughness_for(
        grid, cache_dir=DATA_DIR / "landcover", debris_flow=debris,
        uniform_n=area.manning_default, verbose=verbose)
    cover = ", ".join(f"{k}:{v * 100:.0f}%" for k, v in
                      sorted(rough.fraction.items(), key=lambda kv: -kv[1])[:4])
    say(f"  n in [{rough.n.min():.3f}, {rough.n.max():.3f}], "
        f"area mean {rough.n.mean():.3f}")
    say(f"  cover: {cover or 'unknown'}")
    say(f"  roughness sensitivity ratio: {rough.sensitivity_ratio:.2f}x")
    # Roughness is the one input whose uncertainty we can actually bound, so it
    # gets reported as a band rather than swallowed. Celerity in the friction-
    # dominated limit goes roughly as n^-0.5, so a ratio near 2 is a substantial
    # arrival-time uncertainty and the report must not imply otherwise.
    if rough.sensitivity_ratio > 1.2:
        limitations.append(
            f"Manning's n is a land-cover lookup, not a calibration. The "
            f"published ranges for this domain's cover classes span a factor of "
            f"{rough.sensitivity_ratio:.2f} in area-mean n. Arrival times carry "
            f"that uncertainty: rougher terrain slows the wave roughly as "
            f"n^-0.5, so the reported times should be read as a band, not a "
            f"schedule.")
    limitations.extend(rough.notes)
    if debris:
        limitations.append(
            "This is a DEBRIS FLOW, not a clearwater flood. The shallow water "
            "equations are being used outside their strict validity; the "
            "approximation is a bulking factor on volume plus an elevated "
            "Manning n. Depths are indicative of scale, not of rheology.")

    # -- 3. hydrology ---------------------------------------------------------
    say("\n[3/7] hydrology")
    hydro = analyse_flow(grid, stream_threshold_km2=stream_threshold_km2,
                         verbose=verbose)

    # -- 4. reservoir ---------------------------------------------------------
    say("\n[4/7] reservoir")
    pool = None
    bc = ["open", "open", "open", "open"]
    if reservoir:
        pub_area = _maybe(getattr(area.dam, "reservoir_area_m2", None)) \
            if area.dam is not None else None
        pool = detect_pool(grid.z, near_jj=fj, near_ii=fi, dx=dx,
                           published_area_m2=pub_area, verbose=verbose)
    if pool is None:
        say("  no reservoir initialised (dry start)")
    else:
        for edge in pool.touches:
            bc[_EDGE_TO_BC_INDEX[edge]] = "wall"
        limitations.extend(pool.notes)
        if pool.suspect:
            unverified.append(
                "Reservoir footprint: the detected pool is larger than the "
                "published water spread, which indicates the fill leaked into "
                "an adjoining valley. See limitations.")
        setup["pool"] = {
            "level_m": pool.level_m, "area_km2": pool.area_km2,
            "cells": int(pool.mask.sum()), "touches": list(pool.touches),
            "walled_bc": list(bc), "suspect": pool.suspect,
        }
        limitations.append(
            f"The reservoir is initialised at the DEM's own water surface "
            f"({pool.level_m:.1f} m), not at the published FRL. It is held "
            f"STATIC and contributes no mass to the flood; all flood water "
            f"comes from the lumped breach model, which uses the published "
            f"storage at the published FRL. Rendering the pool at FRL would "
            f"require inventing a dam crest, because at dx = {dx:g} m the DEM's "
            f"crest is locally below FRL.")

    say(f"  boundary conditions (west, east, south, north) = {tuple(bc)}")
    say("  NB: 'south' is applied at j=0, the raster's north edge — index "
        "space, not compass.")

    # -- 5. breach ------------------------------------------------------------
    say("\n[5/7] breach")
    hyd = None
    inflow_cells = None
    breach_prov: dict = {}
    if failure_mode == "water_release":
        hyd, inflow_cells, bprov, blims, bunv = _build_release(
            area, grid, hydro, pool, fj, fi, dx=dx,
            snap_radius_m=snap_radius_m, crest_m=crest_m,
            release_head_m=release_head_m, release_width_m=release_width_m,
            formation_time_s=release_formation_s, verbose=verbose)
        breach_prov = bprov
        limitations.extend(blims)
        unverified.extend(bunv)
        setup["release"] = bprov
    elif area.dam is not None and area.breach is not None:
        hyd, inflow_cells, bprov, blims, bunv = _build_breach(
            area, grid, hydro, pool, fj, fi, dx=dx,
            snap_radius_m=snap_radius_m, crest_m=crest_m, verbose=verbose)
        breach_prov = bprov
        limitations.extend(blims)
        unverified.extend(bunv)
        if bprov.get("snap_suspect"):
            unverified.append(
                "Breach injection point: a much larger channel sits just "
                "outside the search radius (ROADMAP B4). The hydrograph may be "
                "entering a tributary rather than the trunk river. Every "
                "downstream figure inherits this doubt.")
        setup["breach"] = bprov
    elif area.dam is None and area.blockage is not None \
            and area.breach is not None:
        hyd, inflow_cells, bprov, blims, bunv = _build_blockage(
            area, grid, hydro, pool, fj, fi, dx=dx,
            snap_radius_m=snap_radius_m, verbose=verbose)
        breach_prov = bprov
        limitations.extend(blims)
        unverified.extend(bunv)
        setup["blockage"] = bprov
    else:
        limitations.append(
            "No dam-breach hydrograph was applied: this study area has no "
            "verified dam and breach specification.")
        say("  no dam/breach spec — nothing injected")

    # -- 6. solver ------------------------------------------------------------
    say("\n[6/7] solver")
    solver = SWE2D(grid.z, dx, manning=rough.n, cfl=0.4, bc=tuple(bc))
    if pool is not None:
        eta = np.full(grid.shape, pool.level_m, dtype=np.float64)
        solver.set_surface(eta, where=pool.mask)
    initially_wet = None
    if pool is not None:
        # What counts as pre-existing water is the SAME threshold everything
        # else uses, so the masks are consistent by construction.
        initially_wet = pool.mask & (pool.level_m - grid.z > WET_THRESHOLD_M)
    if hyd is not None and inflow_cells is not None:
        solver.add_inflow(
            inflow_cells,
            hyd.q_at,
            direction=breach_prov.get("direction"),
            speed=hyd.u_at,
            label="breach")
    acc = solver.track_maxima(threshold=WET_THRESHOLD_M)

    solver_settings = {
        "solver": "JALDRISHTI SWE2D (finite volume, HLLC, MUSCL, "
                  "well-balanced bed slope)",
        "cfl": 0.4, "h_min": 1.0e-3, "limiter": "mc",
        "bc": list(bc), "dx_m": dx,
        "wet_threshold_m": WET_THRESHOLD_M,
        "open_bc_influence_cells": OPEN_BC_INFLUENCE_CELLS,
    }
    setup["solver"] = dict(solver_settings)

    if setup_only:
        say("\nsetup_only=True — stopping before the first timestep.")
        return RunResult(summary=None, setup=setup, grid=grid, hydro=hydro,
                         roughness=rough, pool=pool, hydrograph=hyd,
                         solver=solver)

    t0 = time.perf_counter()
    stats = solver.run(duration_s, log_every=log_every_s)
    wall = time.perf_counter() - t0
    vol_err = float(stats.volume_error)
    steps = int(stats.steps)
    say(f"  {steps:,} steps in {wall:.1f} s wall "
        f"({steps / max(wall, 1e-9):.0f} steps/s)")
    say(f"  dt in [{stats.dt_min:.3f}, {stats.dt_max:.3f}] s, "
        f"injected {stats.volume_injected / 1e9:.3f} km3, "
        f"clipped {stats.mass_clipped / 1e9:.3e} km3")
    say(f"  volume error {vol_err:+.3e}")

    # Mass conservation is asserted, not hoped for — but the test has to be
    # ONE-SIDED here. `RunStats.volume_error` is documented as a lower bound
    # rather than a test whenever a boundary is open, because water leaving the
    # domain is legitimate and shows up as a NEGATIVE error. So:
    #
    #   error > 0  water appeared from nowhere. Always a bug. Fatal.
    #   error < 0  water left through an open boundary. Expected, and at Tehri
    #              it is the correct behaviour — the flood is meant to exit the
    #              far end of the domain.
    #
    # A symmetric |error| > tol check would flag every routing run we ever do.
    any_open = "open" in bc
    if vol_err > 1.0e-6:
        limitations.append(
            f"MASS CONSERVATION FAILED: relative volume error {vol_err:+.3e} is "
            f"POSITIVE, meaning the model finished with more water than was "
            f"initialised plus injected. Water cannot appear from nowhere. This "
            f"run is diagnostic only and must not be reported.")
        unverified.append(
            f"Mass balance: spurious volume gain {vol_err:+.3e}.")
    elif vol_err < -1.0e-6 and not any_open:
        limitations.append(
            f"MASS CONSERVATION FAILED: relative volume error {vol_err:+.3e} on "
            f"a fully WALLED domain, where no water can leave. This run is "
            f"diagnostic only and must not be reported.")
        unverified.append(f"Mass balance: volume loss {vol_err:+.3e} with no "
                          f"open boundary to lose it through.")
    elif vol_err < -1.0e-6:
        say(f"  (negative error is outflow through the open boundaries — "
            f"{-vol_err * 100.0:.1f}% of throughput left the domain)")
    if stats.mass_clipped > 0.0:
        frac = stats.mass_clipped / max(
            stats.volume_initial + stats.volume_injected, 1e-30)
        if frac > 1.0e-4:
            limitations.append(
                f"The wetting/drying threshold discarded {frac * 100.0:.3f}% of "
                f"total water as negative-depth clipping. Below ~0.01% this is "
                f"normal housekeeping at the flood edge; above it, the depth "
                f"threshold is interfering with the solution.")

    # -- 7. analysis ----------------------------------------------------------
    say("\n[7/7] analysis")
    hazard = classify_hazard(
        solver.max_depth, solver.max_speed, solver.max_dv, dx=dx,
        wet_threshold=WET_THRESHOLD_M, initially_wet=initially_wet)
    arrival = analyse_arrival(
        solver.arrival_time, dx=dx, threshold_m=WET_THRESHOLD_M,
        run_duration_s=duration_s,
        open_bc_cells=OPEN_BC_INFLUENCE_CELLS,
        initially_wet=initially_wet)

    exp_result = None
    if exposure:
        exp_result = _build_exposure(
            grid, hazard, arrival, population=population, verbose=verbose)
        if exp_result is None:
            limitations.append(
                "No exposure analysis: the population raster was unavailable, "
                "so no population figure is reported. Absence of a number is "
                "not a finding of zero exposure.")

    dmg_result = None
    if damage:
        dmg_result = _build_damage(solver.max_depth, hazard, exp_result, dx=dx)

    settlements = _settlement_frame(area, grid.crs)

    # Which flooded cells may be quoted. The near-field breach source and the
    # open-boundary buffer both produce depths and speeds that describe the
    # model setup, not the flood, and both are disclaimed in the limitations —
    # so the reported peak must not be drawn from them. See DECISION 7b below.
    reportable = _reportable_mask(
        grid.shape, bc, inflow_cells, dx,
        near_field_m=breach_prov.get("breach_top_width_m"),
        verbose=verbose)
    if reportable is not None:
        n_excl = int((~reportable).sum())
        limitations.append(
            f"The reported peak depth and speed EXCLUDE the near-field breach "
            f"source and the open-boundary buffer ({n_excl:,} cells, "
            f"{n_excl * dx * dx / 1e6:.2f} km2). Peaks taken over those zones "
            f"reflect how the hydrograph is injected and how the domain edge is "
            f"closed, not the terrain; the raw near-field peak is reported "
            f"separately and must not be quoted as a flood depth.")

    # Resolution disclosure: at 90 m the confined gorge is unresolved, so quoted
    # depths are upper bounds. Sized/justified by scripts/diag_nearfield.py; we
    # DISCLOSE rather than mask-tune because no radius separates artifact from
    # flood and shrinking extent would corrupt arrival/exposure. See DECISION 7c.
    depth_note = _depth_resolution_note(
        solver.max_depth, reportable, dx, WET_THRESHOLD_M)
    if depth_note:
        limitations.append(depth_note)

    summary = ScenarioSummary(
        run_id=run_id,
        study_area=area.key,
        scenario=_scenario_label(area, breach_prov),
        transform=grid.transform, crs=grid.crs, dx=dx, shape=grid.shape,
        max_depth=solver.max_depth, max_speed=solver.max_speed,
        max_dv=solver.max_dv,
        hazard=hazard, arrival=arrival, exposure=exp_result, damage=dmg_result,
        duration_s=duration_s, wall_time_s=wall, steps=steps,
        volume_error=vol_err, dem_valid_mask=grid.mask_valid,
        reportable_mask=reportable,
        solver_settings=solver_settings,
        terrain_provenance={
            "source": grid.source, "dx_m": dx, "crs": grid.crs,
            "conditioning": grid.conditioning,
            "resolution_product": resolution,
            "margin_km": margin_km,
            "roughness_source": getattr(rough, "source", None),
            "roughness_cover_fraction": {int(k): float(v)
                                         for k, v in rough.fraction.items()},
            "roughness_n_mean": float(rough.n.mean()),
            "roughness_sensitivity_ratio": float(rough.sensitivity_ratio),
        },
        breach_provenance=breach_prov,
        extra_limitations=limitations,
        extra_unverified=unverified + list(_config_unverified(area)),
    )

    say("")
    say(summary.headline() if hasattr(summary, "headline") else "")
    say(f"presentable as fact: {summary.is_presentable()}")

    exports = {}
    if export_bundle:
        from .. import export as export_mod
        say(f"\nexporting -> {out_dir}")
        exports = export_mod.write_all(
            summary, out_dir, settlements=settlements,
            domain_mask=grid.mask_valid)
        say(f"  {len(exports)} artefacts")

    say(f"\ntotal wall time {time.perf_counter() - t_wall:.1f} s")

    return RunResult(summary=summary, exports=exports, run_dir=out_dir,
                     grid=grid, hydro=hydro, roughness=rough, pool=pool,
                     hydrograph=hyd, solver=solver, setup=setup)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _build_breach(area, grid, hydro, pool, fj, fi, *, dx, snap_radius_m,
                  crest_m, verbose):
    """
    Build Q(t) from the lumped reservoir and find the cells to inject it into.

    Returns (hydrograph, cells, provenance, limitations, unverified).
    """
    dam, spec = area.dam, area.breach
    prov: dict = {}
    lims: list[str] = []
    unverified: list[str] = []

    frl = _val(dam.frl_m)
    mwl = _maybe(dam.mwl_m)
    height = _val(dam.height_m)
    crest_len = _maybe(dam.crest_length_m)
    gross = _val(dam.gross_storage_m3)
    res_area = _maybe(dam.reservoir_area_m2)

    # Crest datum. Published FRL cannot be the crest (a crest at FRL has no
    # freeboard), so MWL is used when available and the assumption is recorded.
    if crest_m is None:
        crest_m = mwl if mwl is not None else frl + 5.0
        prov["crest_source"] = ("published MWL" if mwl is not None
                                else "FRL + 5 m assumed freeboard")
    else:
        prov["crest_source"] = "caller-supplied"
    crest_m = float(crest_m)
    if mwl is None:
        lims.append(
            f"The dam crest elevation is not in the verified specification. "
            f"{crest_m:.1f} m was assumed as FRL plus 5 m of freeboard. The "
            f"crest sets the breach invert and the weir datum, so this is a "
            f"real assumption, not a formality.")

    bed_m = crest_m - height
    depth = _maybe(spec.breach_depth_m) or (crest_m - bed_m)
    invert = crest_m - depth
    if invert < bed_m:
        invert = bed_m
        lims.append(
            "The requested breach depth would erode below the original "
            "streambed. The invert was floored at the streambed, which is the "
            "physically defensible limit — a breach rarely scours deeper.")

    side = float(spec.side_slope)
    want_bottom = _maybe(spec.breach_width_m) or 0.0
    head = crest_m - invert
    bottom = want_bottom
    if crest_len is not None:
        fits = max_bottom_width(crest_len, head, side)
        if want_bottom > fits:
            bottom = fits
            prov["bottom_width_clamped_from_m"] = want_bottom
            lims.append(
                f"CONFIGURED BREACH GEOMETRY DOES NOT FIT THE DAM. A "
                f"{want_bottom:.0f} m bottom width with 1:{side:g} sides over a "
                f"{head:.0f} m head implies a {want_bottom + 2 * side * head:.0f} m "
                f"opening in a {crest_len:.0f} m crest. The bottom width was "
                f"clamped to {bottom:.0f} m so the fully-developed breach "
                f"exactly spans the crest. The configured value in config.py is "
                f"geometrically impossible and should be corrected there.")
        if bottom <= 0.0:
            raise ValueError(
                f"{area.key}: side slope {side:g} over a {head:.0f} m head "
                f"consumes the entire {crest_len:.0f} m crest — no breach of "
                f"this depth and side slope can exist. Reduce side_slope or "
                f"breach_depth_m in config.py.")

    growth = "instant" if spec.mode == "instantaneous" else "linear"
    t_form = 0.0 if spec.mode == "instantaneous" else \
        float(spec.formation_time_s or 3600.0)
    geom = BreachGeometry(
        bottom_width_m=bottom, invert_m=invert, side_slope=side,
        formation_time_s=t_form, growth=growth, crest_length_m=crest_len)
    geom.check_fits(crest_m)

    storage = ReservoirStorage.power_law(
        bed_m=bed_m, full_level_m=frl, volume_m3=gross, area_m2=res_area)
    hyd = simulate_breach(
        crest_m=crest_m, initial_level_m=frl, geom=geom, storage=storage,
        reservoir_area_m2=res_area, bed_m=bed_m)

    if verbose:
        print(f"  crest {crest_m:.1f} m ({prov['crest_source']}), "
              f"invert {invert:.1f} m, bed {bed_m:.1f} m")
        print(f"  breach {bottom:.0f} m bottom x {head:.0f} m head, "
              f"1:{side:g} sides, {growth} over {t_form:.0f} s")
        print(f"  peak Q {hyd.peak_q:,.0f} m3/s at t = "
              f"{hyd.t_peak / 60.0:.1f} min, released "
              f"{hyd.released_volume_m3 / 1e9:.3f} km3 "
              f"(gross storage {gross / 1e9:.3f} km3)")
        print(f"  peak outlet velocity {hyd.peak_velocity:.1f} m/s")

    prov.update({
        "mode": spec.mode,
        "crest_m": crest_m, "invert_m": invert, "bed_m": bed_m,
        "bottom_width_m": bottom, "side_slope": side,
        "formation_time_s": t_form, "growth": growth,
        "initial_level_m": frl,
        "gross_storage_m3": gross,
        "peak_q_m3s": float(hyd.peak_q),
        "t_peak_s": float(hyd.t_peak),
        "released_volume_m3": float(hyd.released_volume_m3),
        "peak_outlet_velocity_ms": float(hyd.peak_velocity),
        "tailwater": "none (free discharge assumed)",
        "reservoir_inflow_m3s": 0.0,
    })
    lims.append(
        f"The breach is an ASSUMPTION, not a measurement: a {bottom:.0f} m "
        f"bottom-width trapezoid forming over {t_form / 60.0:.0f} minutes. "
        f"Formation time is the parameter that most changes the peak; the "
        f"configured plausible range is "
        f"{tuple(spec.formation_time_range_s or ())} s.")
    lims.append(
        "Breach outflow is computed for free discharge with no tailwater "
        "submergence and no reservoir inflow during the failure. Both make the "
        "peak slightly conservative (higher).")

    # -- cross-check the routed peak against the published regressions --------
    # The weir routing and the empirical regressions are independent estimates
    # of the same quantity, so disagreement is information. This is exactly the
    # check a jury asks for, and all three functions already exist.
    head_at_frl = frl - invert
    emp = {
        "froehlich": float(froehlich_peak_outflow(gross, head_at_frl)),
        "usbr": float(usbr_peak_outflow(head_at_frl)),
        "mlm": float(mlm_peak_outflow(gross, head_at_frl)),
    }
    lo, hi = min(emp.values()), max(emp.values())
    routed = float(hyd.peak_q)
    prov["empirical_peak_q_m3s"] = emp
    prov["routed_over_empirical_max"] = routed / hi if hi > 0 else float("nan")
    if verbose:
        print(f"  empirical peak checks (head {head_at_frl:.0f} m): "
              + ", ".join(f"{k} {v:,.0f}" for k, v in emp.items()))
        print(f"  routed / empirical max = {routed / hi:.2f}x")
    if routed > hi * 1.5 or routed < lo / 1.5:
        lims.append(
            f"PEAK OUTFLOW DISAGREES WITH THE PUBLISHED REGRESSIONS. The routed "
            f"weir solution peaks at {routed:,.0f} m3/s; the Froehlich, USBR and "
            f"MLM regressions give {lo:,.0f}-{hi:,.0f} m3/s for the same volume "
            f"and head ({routed / hi:.1f}x the highest). The routing is "
            f"internally consistent — it is a full-height breach of a 260 m dam, "
            f"and the weir formula at a {head_at_frl:.0f} m head gives a very "
            f"large discharge — but the regressions are fitted to embankment "
            f"dams far smaller than Tehri, so neither estimate is authoritative "
            f"here. Report the peak as a bracket spanning both, never as the "
            f"routed value alone.")
        unverified.append(
            f"Peak breach outflow: routed {routed:,.0f} m3/s vs empirical "
            f"{lo:,.0f}-{hi:,.0f} m3/s. Unreconciled.")

    # -- where to inject ------------------------------------------------------
    radius = max(8, int(round(snap_radius_m / dx)))
    sj, si, inj_info = _find_injection_cell(
        grid, hydro, pool, fj, fi, radius_cells=radius, verbose=verbose)
    prov["injection"] = inj_info
    prov["snap_suspect"] = bool(inj_info.get("suspect", False))
    prov["inflow_cell"] = [int(sj), int(si)]

    if inj_info.get("suspect"):
        lims.append(
            f"INJECTION POINT UNVERIFIED (ROADMAP B4). The chosen channel below "
            f"the dam drains {inj_info['area_km2']:.1f} km2, but a channel "
            f"draining {inj_info['best_area_wide_km2']:.1f} km2 sits just "
            f"outside the {radius}-cell search radius. The hydrograph may be "
            f"entering a tributary rather than the trunk river, which would put "
            f"the flood in the wrong valley. No depth, velocity, arrival time "
            f"or exposure figure from this run is presentable as fact.")

    # -- spread the hydrograph over a footprint, not a point ------------------
    # A 1.2e6 m3/s point source in one 90 m cell is 150 m of depth per second.
    # That is not a discretisation of a dam breach, it is a numerical explosion
    # with a physical-looking label. The real breach discharges through an
    # opening ~575 m wide into a valley reach of comparable length, so the source
    # is spread over the channel cells along that reach. The count is derived
    # from the breach geometry rather than picked: at dx = 90 m a 575 m opening
    # is ~6 cells, and pretending otherwise is what makes the point source look
    # defensible.
    top_width = bottom + 2.0 * side * head
    n_cells = max(1, int(round(top_width / dx)))
    cells, reach_m = _injection_footprint(hydro, pool, sj, si, n_cells, dx=dx)
    prov["inflow_cells"] = [[int(a), int(b)] for a, b in cells]
    prov["inflow_cell_count"] = len(cells)
    prov["inflow_reach_m"] = reach_m
    prov["breach_top_width_m"] = top_width
    peak_rate = routed / (len(cells) * dx * dx)
    prov["peak_source_depth_rate_ms"] = peak_rate
    if verbose:
        print(f"  injecting over {len(cells)} cells "
              f"({reach_m:.0f} m reach) for a {top_width:.0f} m breach opening")
        print(f"  peak source intensity {peak_rate:.2f} m/s of depth per cell")
    lims.append(
        f"The breach hydrograph is injected over {len(cells)} cells "
        f"({reach_m:.0f} m of channel) rather than at a point, because a "
        f"{top_width:.0f} m breach opening cannot be represented by one "
        f"{dx:g} m cell. Depths and velocities within roughly {reach_m:.0f} m of "
        f"the dam are a property of that source treatment, not of the terrain, "
        f"and must not be quoted.")
    if peak_rate > 5.0:
        lims.append(
            f"Peak source intensity is {peak_rate:.1f} m of depth per second per "
            f"cell. Above a few m/s the near-field solution is dominated by how "
            f"the source is spread. This is the near-field limitation that the "
            f"SPH breach model is intended to remove.")

    if grid.z[sj, si] > grid.z[fj, fi] + 5.0:
        lims.append(
            f"The breach injection cell sits {grid.z[sj, si] - grid.z[fj, fi]:.1f} m "
            f"ABOVE the dam reference cell, which is not what a tailrace should "
            f"look like. The search may have climbed a tributary.")

    # Flow direction, in INDEX space, from the D8 path. Index space is the only
    # frame the solver knows: hu is momentum in +i, hv in +j. Deriving the
    # direction from compass names would invite the row-order inversion.
    direction = None
    try:
        js, is_, _ = hydro.trace_downstream(sj, si, max_len=2)
        if len(js) >= 2:
            dj, di = int(js[1]) - sj, int(is_[1]) - si
            norm = float(np.hypot(di, dj))
            if norm > 0:
                direction = (di / norm, dj / norm)
    except Exception:
        direction = None
    if direction is None:
        lims.append(
            "The downstream flow direction at the injection cell could not be "
            "determined, so the breach hydrograph is injected as mass only "
            "(no momentum). The wave will take slightly longer to organise, "
            "making early arrival times marginally late.")
    prov["direction"] = direction
    if verbose:
        print(f"  inject direction (di, dj) = {direction}")

    return hyd, cells, prov, lims, unverified


def _build_release(area, grid, hydro, pool, fj, fi, *, dx, snap_radius_m,
                   crest_m, release_head_m, release_width_m,
                   formation_time_s, verbose):
    """
    Build Q(t) for a WATER RELEASE scenario (the PS's "water release" case,
    distinct from dam break).

    Representation: a weir-equivalent gated spillway release. The gates open
    over `formation_time_s`, spilling over an effective width
    `release_width_m` under an acting head `release_head_m` below the crest,
    while the reservoir draws down through the same storage curve the breach
    uses. This is NOT a breach: the dam stands, the invert stays high, and the
    hydrograph ends when the level reaches the gate sill.

    Gate operations are dam-specific; the numbers here are a scenario
    generator, not an operational schedule, and the limitations block says
    so. The stored water released is a small fraction of the reservoir, so
    the constant-area bias discussed in `simulate_breach` is negligible here.
    """
    dam = area.dam
    prov: dict = {}
    lims: list[str] = []
    unverified: list[str] = []

    frl = _val(dam.frl_m)
    height = _val(dam.height_m)
    gross = _val(dam.gross_storage_m3)
    res_area = _maybe(dam.reservoir_area_m2)
    if crest_m is None:
        crest_m = frl + 5.0
        prov["crest_source"] = "FRL + 5 m assumed freeboard"
    crest_m = float(crest_m)
    bed_m = crest_m - height
    # Gate sill: `release_head_m` below the operating level, but never below
    # the original streambed.
    invert = max(crest_m - float(release_head_m), bed_m)
    acting_head = crest_m - invert
    bottom = float(release_width_m)

    geom = BreachGeometry(
        bottom_width_m=bottom, invert_m=invert, side_slope=0.0,
        formation_time_s=float(formation_time_s), growth="linear",
        crest_length_m=None)
    storage = ReservoirStorage.power_law(
        bed_m=bed_m, full_level_m=frl, volume_m3=gross, area_m2=res_area)
    hyd = simulate_breach(
        crest_m=crest_m, initial_level_m=frl, geom=geom, storage=storage,
        bed_m=bed_m, t_max=12 * 3600.0)

    radius = max(8, int(round(snap_radius_m / dx)))
    sj, si, inj_info = _find_injection_cell(
        grid, hydro, pool, fj, fi, radius_cells=radius, verbose=verbose)
    prov["injection"] = inj_info
    prov["inflow_cell"] = [int(sj), int(si)]
    n_cells = max(1, int(round(bottom / dx)))
    cells, reach_m = _injection_footprint(hydro, pool, sj, si, n_cells, dx=dx)
    prov["inflow_cells"] = [[int(a), int(b)] for a, b in cells]
    prov["inflow_cell_count"] = len(cells)
    prov["inflow_reach_m"] = reach_m

    prov.update({
        "mode": "water_release",
        "crest_m": crest_m, "invert_m": invert, "bed_m": bed_m,
        "acting_head_m": acting_head,
        "release_width_m": bottom,
        "formation_time_s": float(formation_time_s),
        "initial_level_m": frl,
        "peak_q_m3s": float(hyd.peak_q),
        "t_peak_s": float(hyd.t_peak),
        "released_volume_m3": float(hyd.released_volume_m3),
        "peak_outlet_velocity_ms": float(hyd.peak_velocity),
    })

    lims.append(
        f"WATER RELEASE SCENARIO: a gated spillway release modelled as weir "
        f"flow over a {bottom:.0f} m effective width under {acting_head:.0f} m "
        f"of head, gates opening over {formation_time_s / 60:.0f} minutes. "
        f"Gate operations are dam-specific; this is a scenario generator, not "
        f"an operational schedule, and the hydrograph shape depends on those "
        f"three assumptions.")
    if verbose:
        print(f"  release: {bottom:.0f} m width, {acting_head:.0f} m head, "
              f"gates over {formation_time_s / 60:.0f} min")
        print(f"  peak Q {hyd.peak_q:,.0f} m3/s at t = "
              f"{hyd.t_peak / 60:.1f} min, released "
              f"{hyd.released_volume_m3 / 1e6:.1f} x 10^6 m3")

    direction = None
    try:
        js, is_, _ = hydro.trace_downstream(sj, si, max_len=2)
        if len(js) >= 2:
            dj, di = int(js[1]) - sj, int(is_[1]) - si
            norm = float(np.hypot(di, dj))
            if norm > 0:
                direction = (di / norm, dj / norm)
    except Exception:
        direction = None
    prov["direction"] = direction

    return hyd, cells, prov, lims, unverified


def _valley_width_m(grid, fj, fi, *, dx, relief_m=25.0, half_span_cells=40):
    """
    Measure the valley-floor width on an east-west transect through row `fj`.

    The floor is the contiguous run of cells around the transect minimum whose
    elevation is within `relief_m` of that minimum. A transect through a
    Himalayan gorge crosses the valley cleanly, so this is a direct DEM
    measurement rather than an assumption; if the transect is ambiguous (flat
    plateau, minimum on the window edge) the function returns None and the
    caller falls back to a flagged default.
    """
    j = int(np.clip(fj, 0, grid.shape[0] - 1))
    i0 = max(0, fi - half_span_cells)
    i1 = min(grid.shape[1], fi + half_span_cells + 1)
    transect = grid.z[j, i0:i1]
    if transect.size < 5:
        return None
    i_min = int(np.argmin(transect))
    if i_min == 0 or i_min == transect.size - 1:
        return None  # minimum on the window edge: transect did not cross
    floor = transect < (transect[i_min] + relief_m)
    # contiguous run containing the minimum
    left = i_min
    while left > 0 and floor[left - 1]:
        left -= 1
    right = i_min
    while right < floor.size - 1 and floor[right + 1]:
        right += 1
    return (right - left + 1) * dx


def _build_blockage(area, grid, hydro, pool, fj, fi, *, dx, snap_radius_m,
                    verbose):
    """
    Build Q(t) for a RIVER BLOCKAGE scenario (the Chamoli requirement).

    The physical sequence modelled — stated plainly, because it is NOT a
    reproduction of the 2021 hydrograph (see config.trigger_note):

      1. A debris deposit of volume V_d (blockage.source_volume_m3) dams the
         valley. The deposit's cross-section area follows from V_d spread over
         the observed ~700 m impoundment length (Shugar et al. 2021).
      2. The deposit height follows from that cross-section area and the
         valley-floor width MEASURED off the DEM transect at the site
         (trapezoidal section, 0.3W bottom to W top).
      3. The river impounds behind the deposit to the crest (overtopping
         failure, per BreachSpec.mode). The impounded volume is the lake
         geometry estimate: surface area W x L, mean depth 0.4 h.
      4. The breach is routed with the same weir + storage machinery as a dam
         break (`simulate_breach`), with a debris-typical side slope and a
         fast formation time. Both are assumptions and are flagged.

    The debris-flow rheology caveat is inherited from config.limitations and
    is NOT repeated numerically here: this module releases clear water through
    a weir, which approximates the water-led phase of the event only.
    """
    blk = area.blockage
    spec = area.breach
    prov: dict = {}
    lims: list[str] = []
    unverified: list[str] = []

    v_deposit = float(blk.source_volume_m3)
    dam_length_m = 700.0   # Shugar et al. 2021: ~700 m impoundment behind the deposit
    x_sec = v_deposit / dam_length_m

    w_valley = _valley_width_m(grid, fj, fi, dx=dx)
    if w_valley is None or w_valley < 3 * dx:
        w_valley = max(300.0, 4 * dx)
        unverified.append(
            f"Blockage valley width: the DEM transect at the deposit was "
            f"ambiguous, so {w_valley:.0f} m was assumed. Every breach "
            f"geometry figure inherits this.")
    else:
        prov["valley_width_source"] = "DEM transect at the deposit"

    z_bed = float(grid.z[fj, fi])
    # Trapezoidal deposit cross-section: 0.3W bottom, W top.
    h_dam = x_sec / (0.65 * w_valley)
    crest_m = z_bed + h_dam

    # Impoundment to the crest (overtopping trigger).
    v_impound = 0.4 * h_dam * w_valley * dam_length_m
    area_lake = w_valley * dam_length_m

    # Breach geometry: debris-typical side slope, fast failure.
    side = 1.5
    t_form = 600.0
    bottom = max_bottom_width(w_valley, h_dam, side)
    geom = BreachGeometry(
        bottom_width_m=0.3 * w_valley, invert_m=z_bed, side_slope=side,
        formation_time_s=t_form, growth="linear", crest_length_m=w_valley)
    try:
        geom.check_fits(crest_m)
    except ValueError as e:
        lims.append(f"Blockage breach geometry clamped: {e}")
        geom = BreachGeometry(
            bottom_width_m=bottom, invert_m=z_bed, side_slope=side,
            formation_time_s=t_form, growth="linear",
            crest_length_m=w_valley)

    storage = ReservoirStorage.power_law(
        bed_m=z_bed, full_level_m=crest_m, volume_m3=v_impound,
        area_m2=area_lake)
    hyd = simulate_breach(
        crest_m=crest_m, initial_level_m=crest_m, geom=geom,
        storage=storage, bed_m=z_bed, t_max=4 * 3600.0)

    # Injection cells: same channel-snapping and footprint treatment as a dam
    # breach, so the two scenario kinds are comparable.
    radius = max(8, int(round(snap_radius_m / dx)))
    sj, si, inj_info = _find_injection_cell(
        grid, hydro, pool, fj, fi, radius_cells=radius, verbose=verbose)
    prov["injection"] = inj_info
    prov["inflow_cell"] = [int(sj), int(si)]

    top_width = 0.3 * w_valley + 2.0 * side * h_dam
    n_cells = max(1, int(round(top_width / dx)))
    cells, reach_m = _injection_footprint(hydro, pool, sj, si, n_cells, dx=dx)
    prov["inflow_cells"] = [[int(a), int(b)] for a, b in cells]
    prov["inflow_cell_count"] = len(cells)
    prov["inflow_reach_m"] = reach_m

    prov.update({
        "mode": "blockage-overtopping",
        "deposit_volume_m3": v_deposit,
        "impoundment_length_m": dam_length_m,
        "valley_width_m": w_valley,
        "deposit_height_m": h_dam,
        "crest_m": crest_m, "bed_m": z_bed, "invert_m": z_bed,
        "impounded_volume_m3": v_impound,
        "impounded_area_m2": area_lake,
        "bottom_width_m": float(geom.bottom_width_m),
        "side_slope": side,
        "formation_time_s": t_form, "growth": "linear",
        "peak_q_m3s": float(hyd.peak_q),
        "t_peak_s": float(hyd.t_peak),
        "released_volume_m3": float(hyd.released_volume_m3),
        "peak_outlet_velocity_ms": float(hyd.peak_velocity),
    })

    lims.append(
        f"BLOCKAGE SCENARIO, NOT A RECONSTRUCTION. The 2021 Chamoli event was "
        f"a direct rock-ice avalanche into the channel, not the breach of a "
        f"long-lived lake. This run models the generic blockage-and-breach "
        f"sequence the problem statement asks for: a {v_deposit / 1e6:.1f} "
        f"x 10^6 m3 deposit dams a {w_valley:.0f} m valley to {h_dam:.0f} m "
        f"high, the river impounds behind it, and the overtopping breach "
        f"releases an estimated {v_impound / 1e6:.1f} x 10^6 m3. Compare with "
        f"the observed 8,000-14,000 m3/s at Raini as an order-of-magnitude "
        f"check only.")
    lims.append(
        f"The breach formation time ({t_form / 60:.0f} min) and side slope "
        f"(1:{side}) are assumptions typical of debris dams; no site-specific "
        f"value exists. Formation time is the parameter that most changes "
        f"the peak.")
    unverified.append(
        "Blockage impounded volume: estimated from lake geometry (area W x L, "
        "mean depth 0.4 h), not measured. The DEM shows the post-event terrain, "
        "so no impoundment exists in it to measure.")

    if verbose:
        print(f"  deposit {v_deposit / 1e6:.1f} x 10^6 m3 over "
              f"{dam_length_m:.0f} m -> {h_dam:.0f} m high in a "
              f"{w_valley:.0f} m valley")
        print(f"  impounded ~{v_impound / 1e6:.1f} x 10^6 m3 to crest "
              f"{crest_m:.0f} m")
        print(f"  peak Q {hyd.peak_q:,.0f} m3/s at t = "
              f"{hyd.t_peak / 60:.1f} min, released "
              f"{hyd.released_volume_m3 / 1e6:.1f} x 10^6 m3")

    # Flow direction at the injection cell, same as the dam-breach path.
    direction = None
    try:
        js, is_, _ = hydro.trace_downstream(sj, si, max_len=2)
        if len(js) >= 2:
            dj, di = int(js[1]) - sj, int(is_[1]) - si
            norm = float(np.hypot(di, dj))
            if norm > 0:
                direction = (di / norm, dj / norm)
    except Exception:
        direction = None
    prov["direction"] = direction

    return hyd, cells, prov, lims, unverified


def _find_injection_cell(grid, hydro, pool, fj, fi, *, radius_cells,
                         trunk_fraction=0.5, suspect_ratio=5.0, verbose=True):
    """
    The channel cell immediately DOWNSTREAM of the barrier.

    `HydroGrid.snap_to_stream` cannot be used here, and the reason is worth
    recording. The NRLD dam coordinate lands on the reservoir side of the
    structure, which after depression filling is a large FLAT. Drainage inside a
    flat is degenerate, so contributing area there is ~0, and a snap that
    maximises area then minimises distance walks UPSTREAM into the reservoir. At
    Tehri, dx = 90 m, it moved (89, 439) -> (80, 450): 1.3 km north, into the
    pool, with 0.0 km2 of catchment. Injecting a dam-break hydrograph there
    would fill the reservoir instead of flooding the valley, and the map would
    show an almost empty downstream channel — a failure that looks like a
    modelling result.

    So the search is constrained by the two things that actually define a
    tailrace:

      1. NOT in the reservoir pool. The outflow appears below the barrier.
      2. At or below the dam reference cell's elevation. The downstream side.

    Among the cells that qualify, the trunk is the one with the largest
    contributing area (it drains everything upstream, including the reservoir),
    and ties within `trunk_fraction` of the best go to the nearest — area first,
    distance second, the same two-step ordering `snap_to_stream` uses and for the
    same reason: bare nearest-distance slides the point onto whatever gully is
    closest.
    """
    ny, nx = grid.shape
    r = int(radius_cells)
    area = hydro.contributing_area_km2

    def window(rad):
        j0, j1 = max(0, fj - rad), min(ny, fj + rad + 1)
        i0, i1 = max(0, fi - rad), min(nx, fi + rad + 1)
        ok = np.ones((j1 - j0, i1 - i0), dtype=bool)
        if pool is not None:
            ok &= ~pool.mask[j0:j1, i0:i1]
        ok &= grid.z[j0:j1, i0:i1] <= grid.z[fj, fi]
        return j0, j1, i0, i1, ok

    j0, j1, i0, i1, ok = window(r)
    if not ok.any():
        raise ValueError(
            f"no cell within {r} cells of ({fj}, {fi}) is both outside the "
            f"reservoir and below the dam. The barrier location or the pool "
            f"detection is wrong; inspect the DEM before going further.")

    a = np.where(ok, area[j0:j1, i0:i1], -1.0)
    best = float(a.max())
    if best <= 0.0:
        raise ValueError(
            f"every candidate cell below the dam has zero contributing area. "
            f"Flow routing has not produced a channel here; check that "
            f"analyse_flow ran on a void-free grid.")

    cand = a >= best * trunk_fraction
    jj, ii = np.where(cand)
    d2 = (jj + j0 - fj) ** 2 + (ii + i0 - fi) ** 2
    k = int(np.argmin(d2))
    sj, si = int(jj[k] + j0), int(ii[k] + i0)

    # Is there a much bigger channel just outside the radius? That is the B4
    # signature, and it is reported rather than silently resolved.
    j0w, j1w, i0w, i1w, okw = window(r * 2)
    aw = np.where(okw, area[j0w:j1w, i0w:i1w], -1.0)
    best_wide = float(aw.max())
    chosen = float(area[sj, si])
    suspect = best_wide > chosen * suspect_ratio

    info = {
        "from": [int(fj), int(fi)],
        "to": [sj, si],
        "moved_m": float(np.hypot(sj - fj, si - fi) * grid.dx),
        "area_km2": chosen,
        "best_area_in_radius_km2": best,
        "best_area_wide_km2": best_wide,
        "search_radius_cells": r,
        "suspect": bool(suspect),
        "z_dam_m": float(grid.z[fj, fi]),
        "z_inject_m": float(grid.z[sj, si]),
        "method": "pool-aware downstream trunk search",
    }
    if verbose:
        print(f"  inject at ({sj}, {si}), {info['moved_m']:.0f} m from the dam, "
              f"catchment {chosen:.1f} km2, bed {info['z_inject_m']:.1f} m"
              f"{'  SUSPECT' if suspect else ''}")
    return sj, si, info


def _injection_footprint(hydro, pool, sj, si, n_cells, *, dx):
    """
    Spread the source along the channel downstream of the injection cell.

    The D8 downstream path is used rather than a disc, because a disc of cells
    around a channel in a steep Himalayan valley puts most of the source on the
    valley WALLS, where it becomes a sheet of water running down a hillside. The
    path stays in the channel by construction.
    """
    cells = [(int(sj), int(si))]
    reach_m = 0.0
    try:
        js, is_, dist = hydro.trace_downstream(sj, si, max_len=n_cells)
        for k in range(len(js)):
            t = (int(js[k]), int(is_[k]))
            if pool is not None and pool.mask[t]:
                continue
            if t not in cells:
                cells.append(t)
                reach_m = float(dist[k])
            if len(cells) >= n_cells:
                break
    except Exception:
        pass
    return np.array(cells, dtype=np.int64), reach_m


def _reportable_mask(shape, bc, inflow_cells, dx, *, near_field_m, verbose):
    """
    True where a depth or velocity may be quoted as a flood result.

    Two zones are set to False:

      * the NEAR-FIELD around the breach injection footprint, out to the breach
        opening width. A hydrograph forced into a handful of cells piles water
        up locally — at Tehri to a surface above the dam crest — and that peak
        is a property of the source, not the flood.
      * the OPEN-BOUNDARY buffer, OPEN_BC_INFLUENCE_CELLS deep along every edge
        with an 'open' condition, where the transmissive outflow perturbs the
        solution.

    Returns None when there is nothing to exclude (no breach and no open edge),
    so the summary falls back to quoting the whole flood mask unchanged.
    """
    ny, nx = shape
    excl = np.zeros(shape, dtype=bool)

    # -- open-boundary buffer -------------------------------------------------
    # bc is (west, east, south, north) in INDEX space: south -> j=0, north ->
    # j=ny-1, west -> i=0, east -> i=nx-1. Keyed off array edges, never compass.
    d = int(OPEN_BC_INFLUENCE_CELLS)
    edge_open = {"j0": bc[2], "jmax": bc[3], "i0": bc[0], "imax": bc[1]}
    if edge_open["j0"] == "open":
        excl[:d, :] = True
    if edge_open["jmax"] == "open":
        excl[ny - d:, :] = True
    if edge_open["i0"] == "open":
        excl[:, :d] = True
    if edge_open["imax"] == "open":
        excl[:, nx - d:] = True

    # -- near-field breach source --------------------------------------------
    if inflow_cells is not None and len(inflow_cells) and near_field_m:
        from scipy import ndimage
        seed = np.zeros(shape, dtype=bool)
        cc = np.asarray(inflow_cells, dtype=np.int64).reshape(-1, 2)
        seed[cc[:, 0], cc[:, 1]] = True
        r = max(1, int(round(float(near_field_m) / dx)))
        near = ndimage.binary_dilation(seed, iterations=r)
        excl |= near

    if not excl.any():
        return None
    if verbose:
        print(f"  reportable mask: {int((~excl).sum()):,} of {excl.size:,} "
              f"cells quotable ({int(excl.sum()):,} excluded)")
    return ~excl


def _depth_resolution_note(max_depth, reportable, dx, wet_threshold):
    """
    Quantified disclosure that confined-reach depths are resolution-limited
    UPPER BOUNDS, not survey depths. Returns a limitation string, or None.

    Sizing diagnostic (scripts/diag_nearfield.py, Tehri 90 m) established the
    physics we must disclose rather than mask away: at 90 m the Bhagirathi gorge
    is resolved as only 1-2 cells wide, so continuity forces depth up to ~230 m
    along the confined reach; 99% of cells deeper than 150 m sit in the 1.5 km
    reach just below the breach, and the peak-beyond-radius curve has NO knee
    (still 208 m at a 3.6 km exclusion). No exclusion radius cleanly separates
    the source pileup from the flood, and shrinking the wetted extent to lower a
    number would corrupt the arrival-time and exposure products that ARE the
    deliverable. So the peak is kept and framed honestly instead.

    Local channel width is estimated from the distance transform of the wetted
    mask: at a wet cell, edt is the number of cells to the nearest dry cell, so
    2*edt*dx is the local width. edt < 1.5 flags a channel the grid renders
    narrower than three cells -- i.e. an unresolved reach.
    """
    from scipy import ndimage

    wet = np.asarray(max_depth) > wet_threshold
    n_wet = int(wet.sum())
    if n_wet == 0:
        return None
    quotable = (wet & reportable) if reportable is not None else wet
    if not quotable.any():
        return None
    peak = float(np.asarray(max_depth)[quotable].max())

    edt = ndimage.distance_transform_edt(wet)
    conf_frac = float((wet & (edt < 1.5)).sum()) / n_wet

    return (
        f"DEPTH IS RESOLUTION-LIMITED. At {dx:.0f} m the confined valley is "
        f"resolved as only 1-2 cells wide, so modelled depths in confined "
        f"reaches are UPPER BOUNDS set by channel width at grid scale, not "
        f"survey depths. About {conf_frac:.0%} of the flooded area lies in "
        f"channels the grid renders narrower than {3 * dx:.0f} m, and the peak "
        f"reportable depth ({peak:.0f} m) occurs in the steep reach just below "
        f"the breach. Treat depth qualitatively at this resolution; quantitative "
        f"depth requires the 30 m product. Arrival time and exposure are the "
        f"primary, resolution-robust outputs.")


def _build_exposure(grid, hazard, arrival, *, population, verbose):
    """Resample the population raster onto the grid and cross-tabulate."""
    path = Path(population) if population else None
    if path is None or not path.exists():
        if verbose:
            print(f"  population raster not found ({path}) — skipping exposure")
        return None
    pop, report = resample_population(
        path, dst_transform=grid.transform, dst_crs=grid.crs,
        dst_shape=grid.shape, dst_dx=grid.dx)
    result = analyse_exposure(pop, hazard, arrival, resample_report=report)
    if verbose:
        print(f"  population on grid: {float(np.nansum(pop)):,.0f} total")
    return result


def _build_damage(max_depth, hazard, exp_result, *, dx):
    """
    Assemble a DamageResult by hand — `damage.py` has no single entry point,
    deliberately, because which categories apply is a scenario question.
    """
    from ..analysis.damage import (
        DamageResult,
        area_damage,
        standard_limitations,
    )
    by_cat = {"agriculture / land": area_damage(max_depth, dx=dx,
                                                curve="agriculture")}
    h56 = 0.0
    if hasattr(hazard, "aidr_class"):
        cls = np.asarray(hazard.aidr_class)
        h56 = float(np.count_nonzero(cls >= 5))
    return DamageResult(
        by_category=by_cat,
        structural_failure_buildings=0,
        structural_failure_population=h56,
        limitations=standard_limitations() + [
            "Only area-based (land) damage is computed. Building and road "
            "damage require OpenStreetMap footprints, which were not fetched "
            "for this run, so the total is an UNDERCOUNT of physical damage.",
        ],
    )


def _settlement_frame(area, crs):
    """A GeoDataFrame of the reported places, for the settlements-at-risk layer."""
    if not area.downstream:
        return None
    try:
        import geopandas as gpd
        from shapely.geometry import Point
    except Exception:
        return None
    rows = [p for p in area.downstream]
    gdf = gpd.GeoDataFrame(
        {"name": [p.name for p in rows],
         "kind": [p.kind for p in rows],
         "population": [p.population for p in rows],
         "geometry": [Point(p.lon, p.lat) for p in rows]},
        crs="EPSG:4326")
    return gdf.to_crs(crs)


def _scenario_label(area, breach_prov):
    if not breach_prov:
        return f"{area.scenario_kind} (no breach hydrograph)"
    mode = breach_prov.get("mode", "parametric")
    t = breach_prov.get("formation_time_s", 0.0)
    w = breach_prov.get("bottom_width_m", 0.0)
    if mode == "instantaneous":
        return "instantaneous full breach"
    return (f"{mode} breach, {w:.0f} m bottom width, "
            f"{t / 60.0:.0f} min formation")


def _config_unverified(area):
    """
    Surface every `verified=False` source in the study area's own specification.

    A run does not get to look more certain than its inputs. ROADMAP B1 is 11
    unverified entries in config.py; while that stands, they belong in the
    summary.
    """
    out = []
    for owner in (area.dam, area.blockage, area.breach):
        if owner is None:
            continue
        for name in vars(owner):
            v = getattr(owner, name)
            if hasattr(v, "verified") and not v.verified:
                out.append(f"{type(owner).__name__}.{name}: "
                           f"{getattr(v, 'citation', 'unverified')}")
    return out


__all__ = ["Pool", "RunResult", "detect_pool", "run_scenario",
           "WET_THRESHOLD_M"]

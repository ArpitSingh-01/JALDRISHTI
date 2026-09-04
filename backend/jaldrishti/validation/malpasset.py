"""
Validation rung 4: MALPASSET (1959) — the real dam break.

This is the top of the ladder. Rungs 1-3 (lake-at-rest, Ritter, Stoker) compare
the solver against *analytical* solutions on flat, frictionless beds: they prove
the hyperbolic core, the dry-bed front speed and the shock speed are right in
isolation. Malpasset is the first rung with none of those simplifications — real
terrain, real friction, a real breach, and, crucially, real *field* data to
compare against. It is the case that turns "the maths is correct" into "the model
is right about the world."

WHY MALPASSET AND NOTHING ELSE
------------------------------
It is the only full-scale real dam break for which three *independent* families
of observation survive, which is what makes it the universal benchmark in
shallow-water modelling:

    police high-water marks   17 surveyed max water-SURFACE ELEVATIONS   (field)
    transformer shutdowns      3 wave ARRIVAL TIMES                      (field)
    LNH-EDF 1:400 scale model  9 gauges: arrival time + max WS elevation (lab)

Two of those three measure ARRIVAL TIME directly — the headline output of this
whole project. A blue inundation blob can be faked; an arrival time at a named
place, matched against a transformer that physically shut down at a known second,
cannot.

THE INITIAL CONDITION, IN ONE SENTENCE
--------------------------------------
Fill every cell on the reservoir side of the dam line to a water-surface
elevation of 100.0 m (`h = 100 - z_bed`, so the lake takes the shape of its
valley), leave everything downstream dry, and release. The "reservoir side" is a
signed point-to-line half-plane test against the straight dam line
(4701.183, 4143.407) -> (4655.553, 4392.104); one small disconnected pocket at
(4500, 5350) is forced dry because it is on the reservoir side of the infinite
line but is not part of the actual lake. This is exactly the IC in the official
openTELEMAC case (`user_fortran/distan.f`, subroutine CORSUI).

WHAT "GOOD" LOOKS LIKE (set an honest bar before running)
---------------------------------------------------------
Kim, Sanders et al. (2014), Adv. Water Resour. 68:42-61, Table 7, swept meshes
from coarse to 2.07 million cells. Reported errors span ~0.7-2.9 m on maximum
water height and ~15-225 s on arrival time; even their finest grid lands ~2.8 m
off on max height. Nobody matches Malpasset to the metre. If we reach a few
metres on max water level and tens of seconds on arrival, we are at
published-literature quality and can say so with a citation.

CAVEATS TO STATE ON THE SLIDE (volunteering these is what earns a jury's trust)
-------------------------------------------------------------------------------
  * The terrain was digitised from 1931 maps; the field data were collected after
    a flood that violently reshaped the valley. Some mismatch is terrain error,
    not solver error.
  * Transformer times are electrical shutdown times. Only A (valley bottom, just
    below the dam) is a clean arrival time; B and C lie between arrival and peak,
    so we validate on the RELATIVE times (B-A = 1140 s, C-A = 1320 s), as the
    official TELEMAC case does.
  * G6-G14 are laboratory (1:400 model) truth, not field truth.
  * The bed dataset is clipped at +100 m; terrain above the reservoir level is
    irrelevant to the flood and is not resolved.

REFERENCES
----------
Biscarini, Di Francesco, Ridolfi & Manciola (2016). On the Simulation of Floods
    in a Narrow Bending Valley: The Malpasset Dam Break Case Study. Water
    8(11):545. doi:10.3390/w8110545 (CC-BY) — the observation tables.
Hervouet, J.-M. (2007). Hydrodynamics of Free Surface Flows. Wiley, pp. 281-288.
Kim, B., Sanders, B.F. et al. (2014). Adv. Water Resour. 68:42-61 — error band.
openTELEMAC examples/telemac2d/malpasset — executable EDF-authored case.
"""
from __future__ import annotations

import csv
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from ..solver import SWE2D

# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
# backend/jaldrishti/validation/malpasset.py
#   parents[0]=validation  [1]=jaldrishti  [2]=backend  [3]=repo root
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[3]

BED_PATH = _REPO_ROOT / "data" / "reference" / "malpasset" / "malpasset_bed_20m.npy"
REFERENCE_DIR = _BACKEND_DIR / "tests" / "reference" / "malpasset"

# --------------------------------------------------------------------------- #
# case constants (all cross-checked across TELEMAC + Biscarini 2016; see README)
# --------------------------------------------------------------------------- #
RESERVOIR_LEVEL_M = 100.0
DAM_LINE = ((4701.183, 4143.407), (4655.553, 4392.104))
FORCED_DRY_CENTRE = (4500.0, 5350.0)
FORCED_DRY_RADIUS_M = 200.0
MANNING_N = 0.033          # = Strickler K = 30
DURATION_S = 4000.0

# Native bed grid geometry (from malpasset_bed_20m.README.txt).
BED_DX_M = 20.0
BED_X0_M = 536.0           # x of column j=0 (cell-centre coordinate)
BED_Y0_M = -2344.0         # y of row i=0; row 0 = ymin (south-up array order)

# NaN outside the mesh footprint is replaced by a bed high enough that water can
# never climb onto it, turning "outside the domain" into an impassable dry wall.
# 200 m sits well above both the 100 m reservoir and the +111 m valley rim, so
# the well-balanced scheme keeps those cells dry to machine precision (the same
# guarantee the lake-at-rest rung verifies).
OUTSIDE_MESH_BED_M = 200.0

# Published quality band, Kim et al. (2014) Table 7.
PUBLISHED_MAXWS_L1_M = (0.7, 2.9)
PUBLISHED_ARRIVAL_S = (15.0, 225.0)


# --------------------------------------------------------------------------- #
# terrain
# --------------------------------------------------------------------------- #
@dataclass
class Bed:
    """A (possibly coarsened) Malpasset bed on a regular grid.

    `z` is solver-ready (NaN replaced by OUTSIDE_MESH_BED_M). `valid` marks the
    cells that were inside the mesh, kept for masking figures and for an honest
    "in the model domain" test on the observation points. Cell (i, j) has centre
    (x0 + dx*j, y0 + dx*i); row 0 is the southernmost.
    """
    z: np.ndarray
    valid: np.ndarray
    x0: float
    y0: float
    dx: float

    @property
    def shape(self) -> tuple[int, int]:
        return self.z.shape

    def ij(self, x: float, y: float) -> tuple[int, int]:
        """Nearest cell (i, j) to a point, clipped to the grid."""
        j = int(round((x - self.x0) / self.dx))
        i = int(round((y - self.y0) / self.dx))
        ny, nx = self.z.shape
        return min(max(i, 0), ny - 1), min(max(j, 0), nx - 1)

    def xcoords(self) -> np.ndarray:
        return self.x0 + self.dx * np.arange(self.z.shape[1])

    def ycoords(self) -> np.ndarray:
        return self.y0 + self.dx * np.arange(self.z.shape[0])

    def extent(self) -> tuple[float, float, float, float]:
        """(xmin, xmax, ymin, ymax) of cell centres — for imshow(origin='lower')."""
        xs, ys = self.xcoords(), self.ycoords()
        return float(xs[0]), float(xs[-1]), float(ys[0]), float(ys[-1])


def load_bed(coarsen: int = 1, path: Optional[Path] = None) -> Bed:
    """
    Load the 20 m EDF bed, optionally block-averaging by an integer factor.

    Coarsening exists for the fast pytest rung: the full 20 m grid (863 x 461
    cells, ~40 000 timesteps to 4000 s) is a ~45-minute run, far too slow for the
    test suite. Block-averaging to 60-100 m brings it into a minute or two while
    still exercising the whole IC-build/run/sample/score path on real terrain. It
    also, honestly, degrades accuracy: averaging bed cells across a gorge that is
    only 1-2 cells wide widens and raises the channel floor, slowing the wave.
    That degradation is the price of a fast test; the quotable numbers come from
    the full-resolution script run.

    Averaging is NaN-aware: a coarse cell is `valid` only where at least one of
    its fine cells was inside the mesh; an all-NaN block becomes outside-mesh.
    """
    p = Path(path) if path is not None else BED_PATH
    if not p.is_file():
        raise FileNotFoundError(
            f"Malpasset bed not found at {p}. It is a large binary kept out of "
            f"git under data/reference/ (see the reference README)."
        )
    z_raw = np.load(p).astype(np.float64)   # (ny, nx), NaN outside the mesh
    if coarsen <= 1:
        valid = np.isfinite(z_raw)
        z = np.where(valid, z_raw, OUTSIDE_MESH_BED_M)
        return Bed(z=z, valid=valid, x0=BED_X0_M, y0=BED_Y0_M, dx=BED_DX_M)

    f = int(coarsen)
    ny, nx = z_raw.shape
    ny2, nx2 = ny // f, nx // f
    # Crop the few leftover cells off the north/east edges (outside-mesh anyway).
    cropped = z_raw[: ny2 * f, : nx2 * f].reshape(ny2, f, nx2, f)
    with warnings.catch_warnings():
        # An all-NaN block warns "Mean of empty slice"; we handle it explicitly.
        warnings.simplefilter("ignore", category=RuntimeWarning)
        z_mean = np.nanmean(cropped, axis=(1, 3))
    valid = np.isfinite(z_mean)
    z = np.where(valid, z_mean, OUTSIDE_MESH_BED_M)
    # Cell-centre of a block is the mean of its fine centres: origin shifts by
    # (f-1)/2 fine cells, spacing scales by f.
    x0 = BED_X0_M + BED_DX_M * (f - 1) / 2.0
    y0 = BED_Y0_M + BED_DX_M * (f - 1) / 2.0
    return Bed(z=z, valid=valid, x0=x0, y0=y0, dx=BED_DX_M * f)


# --------------------------------------------------------------------------- #
# initial condition
# --------------------------------------------------------------------------- #
def _signed_distance(bed: Bed, p1, p2) -> np.ndarray:
    """
    Signed perpendicular distance from every cell centre to the infinite line
    through p1->p2, metres. Positive on the reservoir (upstream) side.

    Sign convention is fixed empirically by the geometry, not guessed: the cross
    product (p2-p1) x (Q-p1) is negative for transformer A, which sits just BELOW
    the dam (downstream, dry at t=0), so the reservoir is the side where the cross
    product is positive. `reservoir_mask` asserts every observation point ends up
    on the dry side, which catches a flipped sign immediately.
    """
    (x1, y1), (x2, y2) = p1, p2
    dx, dy = x2 - x1, y2 - y1
    length = float(np.hypot(dx, dy))
    xs = bed.xcoords()[None, :]
    ys = bed.ycoords()[:, None]
    cross = dx * (ys - y1) - dy * (xs - x1)      # (ny, nx) by broadcasting
    return cross / length


def reservoir_mask(bed: Bed) -> np.ndarray:
    """
    Boolean mask of cells initially filled with reservoir water.

    Reservoir side of the dam line AND terrain below the 100 m level AND inside
    the mesh, minus the forced-dry pocket at (4500, 5350). The terrain and mesh
    conditions are redundant with `set_surface` (which fills h = max(0, 100 - z),
    zero where z >= 100 or z = 200 outside the mesh) but make the mask itself an
    honest picture of the lake for the figures.
    """
    sd = _signed_distance(bed, *DAM_LINE)
    mask = (sd > 0.001) & bed.valid & (bed.z < RESERVOIR_LEVEL_M)

    cx, cy = FORCED_DRY_CENTRE
    xs = bed.xcoords()[None, :]
    ys = bed.ycoords()[:, None]
    pocket = (xs - cx) ** 2 + (ys - cy) ** 2 <= FORCED_DRY_RADIUS_M ** 2
    mask &= ~pocket
    return mask


def build_solver(bed: Bed, *, manning: float = MANNING_N, cfl: float = 0.4,
                 limiter: str = "mc") -> tuple[SWE2D, np.ndarray]:
    """
    Construct the solver with the Malpasset IC ready to run.

    Boundaries are solid walls on all four sides, matching the openTELEMAC case
    (`the sea boundary is slip too`). A welcome consequence: with no inflow and no
    open boundary, total water volume is conserved to machine precision, so a mass
    drift in this run points at a solver bug, not at legitimate outflow.

    Returns the solver (with track_maxima already armed, so the reservoir reports
    arrival time 0) and the reservoir mask (for figures).
    """
    s = SWE2D(bed.z, bed.dx, manning=manning, cfl=cfl, limiter=limiter,
              bc=("wall", "wall", "wall", "wall"))
    mask = reservoir_mask(bed)
    s.set_surface(RESERVOIR_LEVEL_M, where=mask)
    s.track_maxima(threshold=0.1)
    return s, mask


# --------------------------------------------------------------------------- #
# observations
# --------------------------------------------------------------------------- #
@dataclass
class Observation:
    name: str
    x: float
    y: float
    ws_obs_m: Optional[float] = None      # max water-surface elevation, m
    at_obs_s: Optional[float] = None      # arrival time, s
    kind: str = "gauge"                   # 'police' | 'transformer' | 'gauge'


def _read_csv_rows(name: str) -> list[dict]:
    path = REFERENCE_DIR / name
    with open(path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.reader(f) if r and not r[0].lstrip().startswith("#")]
    header, *body = rows
    header = [h.strip() for h in header]
    return [dict(zip(header, r)) for r in body]


def load_observations() -> dict[str, list[Observation]]:
    """The three observation families, keyed by kind."""
    police = [
        Observation(r["point"], float(r["x_m"]), float(r["y_m"]),
                    ws_obs_m=float(r["ws_obs_m"]), kind="police")
        for r in _read_csv_rows("police_survey_p1_p17.csv")
    ]
    transformers = [
        Observation(r["transformer"], float(r["x_m"]), float(r["y_m"]),
                    at_obs_s=float(r["at_obs_s"]), kind="transformer")
        for r in _read_csv_rows("transformers_abc.csv")
    ]
    gauges = [
        Observation(r["gauge"], float(r["x_m"]), float(r["y_m"]),
                    ws_obs_m=float(r["ws_lab_m"]), at_obs_s=float(r["at_lab_s"]),
                    kind="gauge")
        for r in _read_csv_rows("gauges_g6_g14.csv")
    ]
    return {"police": police, "transformer": transformers, "gauge": gauges}


# --------------------------------------------------------------------------- #
# sampling
# --------------------------------------------------------------------------- #
def _disk(bed: Bed, x: float, y: float, radius_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Row/col indices of cells whose centre lies within radius_m of (x, y)."""
    i0, j0 = bed.ij(x, y)
    r = int(np.ceil(radius_m / bed.dx))
    ny, nx = bed.z.shape
    ii, jj = np.mgrid[max(0, i0 - r): min(ny, i0 + r + 1),
                      max(0, j0 - r): min(nx, j0 + r + 1)]
    xs = bed.x0 + bed.dx * jj
    ys = bed.y0 + bed.dx * ii
    within = (xs - x) ** 2 + (ys - y) ** 2 <= radius_m ** 2
    return ii[within], jj[within]


def sample_max_ws(bed: Bed, max_depth: np.ndarray, obs: Observation,
                  *, radius_m: float, wet_threshold: float = 0.1) -> Optional[float]:
    """
    Modelled maximum water-surface elevation at an observation point, metres.

    WS elevation = bed + max depth, taken as the MAXIMUM over wet cells within
    `radius_m`. The neighbourhood matters for bank marks: the README documents
    three police points (P13, P14, P16) that sit marginally *below* the
    interpolated 1931 bed, so a single-nearest-cell sample reports them
    permanently dry and manufactures a huge spurious error. Taking the wettest
    cell within ~one cell radius is the standard fix and is stated in the methods.
    Only cells that actually flooded (max depth > threshold) count; otherwise a
    dry bank cell's bed elevation would masquerade as a water level.

    Returns None if no cell in the neighbourhood flooded (a genuine model dry).
    """
    ii, jj = _disk(bed, obs.x, obs.y, radius_m)
    if ii.size == 0:
        return None
    d = max_depth[ii, jj]
    wetted = d > wet_threshold
    if not np.any(wetted):
        return None
    ws = bed.z[ii, jj][wetted] + d[wetted]
    return float(np.max(ws))


def sample_arrival(bed: Bed, arrival: np.ndarray, obs: Observation,
                   *, radius_m: float) -> Optional[float]:
    """
    Modelled first-arrival time at an observation point, seconds.

    The EARLIEST arrival among cells within `radius_m` (the wave front is a line;
    the nearest cell to a bank point may be a metre inside the channel and arrive
    a step sooner). `arrival` is NaN where the water never came. Returns None if
    every cell in the neighbourhood stayed dry.
    """
    ii, jj = _disk(bed, obs.x, obs.y, radius_m)
    if ii.size == 0:
        return None
    a = arrival[ii, jj]
    a = a[np.isfinite(a)]
    if a.size == 0:
        return None
    return float(np.min(a))


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
@dataclass
class PointResult:
    name: str
    kind: str
    x: float
    y: float
    obs_ws: Optional[float] = None
    mod_ws: Optional[float] = None
    obs_at: Optional[float] = None
    mod_at: Optional[float] = None

    @property
    def ws_err(self) -> Optional[float]:
        if self.obs_ws is None or self.mod_ws is None:
            return None
        return self.mod_ws - self.obs_ws

    @property
    def at_err(self) -> Optional[float]:
        if self.obs_at is None or self.mod_at is None:
            return None
        return self.mod_at - self.obs_at


def _norms(errs: list[float]) -> dict[str, float]:
    if not errs:
        return {"n": 0, "l1": float("nan"), "l2": float("nan"),
                "linf": float("nan"), "bias": float("nan")}
    a = np.asarray(errs, dtype=float)
    return {
        "n": int(a.size),
        "l1": float(np.mean(np.abs(a))),
        "l2": float(np.sqrt(np.mean(a ** 2))),
        "linf": float(np.max(np.abs(a))),
        "bias": float(np.mean(a)),
    }


def sample_all(bed: Bed, s: SWE2D, obs: dict[str, list[Observation]],
               *, bank_radius_m: float = 30.0,
               channel_radius_m: float = 0.0) -> list[PointResult]:
    """
    Sample the modelled fields at every observation point.

    Bank marks (police) and transformers are sampled over a ~one-cell-radius disk
    (`bank_radius_m`); the physical-model channel gauges G6-G14 sit in the channel
    and are sampled at the nearest cell (`channel_radius_m = 0`), as the README's
    terrain check found no wet/dry-edge problem there.
    """
    max_depth = np.asarray(s.max_depth)
    arrival = np.asarray(s.arrival_time)
    results: list[PointResult] = []
    for family in obs.values():
        for o in family:
            radius = channel_radius_m if o.kind == "gauge" else bank_radius_m
            # A radius of 0 still needs to hit the nearest cell.
            r = max(radius, bed.dx * 0.5)
            pr = PointResult(o.name, o.kind, o.x, o.y,
                             obs_ws=o.ws_obs_m, obs_at=o.at_obs_s)
            if o.ws_obs_m is not None:
                pr.mod_ws = sample_max_ws(bed, max_depth, o, radius_m=r)
            if o.at_obs_s is not None:
                pr.mod_at = sample_arrival(bed, arrival, o, radius_m=r)
            results.append(pr)
    return results


def score(results: list[PointResult]) -> dict:
    """
    Reduce sampled points to the reportable error metrics.

    Max WS elevation: L1/L2/Linf over all police + gauge points that flooded in
    the model. Arrival time: L1 over the physical-model gauges (the clean arrival
    dataset). Transformers: RELATIVE times B-A and C-A, because the absolute
    shutdown times carry an unknown datum offset and B, C are upper bounds.
    """
    ws_errs = [r.ws_err for r in results if r.ws_err is not None]
    gauge_at_errs = [r.at_err for r in results
                     if r.kind == "gauge" and r.at_err is not None]

    out: dict = {
        "max_ws": _norms(ws_errs),
        "gauge_arrival": _norms(gauge_at_errs),
        "n_points_total": len(results),
        "n_dry_in_model": sum(
            1 for r in results if r.obs_ws is not None and r.mod_ws is None
        ),
    }

    # Relative transformer times.
    tf = {r.name: r for r in results if r.kind == "transformer"}
    rel = {}
    if "A" in tf and tf["A"].mod_at is not None:
        a_mod, a_obs = tf["A"].mod_at, tf["A"].obs_at
        for name, obs_rel in (("B", 1140.0), ("C", 1320.0)):
            r = tf.get(name)
            if r is not None and r.mod_at is not None:
                mod_rel = r.mod_at - a_mod
                rel[name] = {
                    "obs_rel_s": obs_rel,
                    "mod_rel_s": mod_rel,
                    "err_s": mod_rel - obs_rel,
                }
    out["transformer_rel"] = rel
    return out

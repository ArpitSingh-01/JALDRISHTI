"""
Arrival time — the number this whole platform exists to report.

WHY THIS IS THE PRODUCT
-----------------------
Every team attempting this problem statement will render an inundation extent. A
blue polygon tells a district officer that a place will flood. It does not tell
them whether to move people, and it does not tell them in what order. "Water
reaches Ghansali in 47 minutes; 12,400 people are inside the 60-minute band" is
an operational instruction. That sentence is what this module produces.

The solver already does the hard part. `SWE2D.arrival_time` is a first-crossing
time accumulated inside the timestep loop, so it is exact to the timestep rather
than quantised to an output-frame interval. This module's job is to turn that
raster of seconds into the three things a response plan needs:

  1. minutes, masked honestly where water never arrived;
  2. isochrone BANDS — the 0-15, 15-30, 30-60, 60-120 minute rings that a
     staged evacuation is actually organised around;
  3. isochrone POLYGONS, so the bands can be shipped as Shapefile and KML and
     opened in whatever GIS the district office already runs.

WHY BANDS AND NOT A CONTINUOUS SURFACE
--------------------------------------
A continuous arrival surface implies a precision the model does not have. Arrival
time inherits every uncertainty in the chain — breach formation time, Manning n
(a factor-of-two spread on its own), DEM vintage, the 90 m cell. Reporting "47.3
minutes" would be dishonest. Reporting "inside the 30-60 minute band" is a claim
the model can support, and it is also the form an evacuation order takes.

The band edges are a response-planning choice, not a physical one, so they are a
parameter with a documented default rather than a constant.

WHY THE RESERVOIR MUST BE MASKED OUT
------------------------------------
The solver's arrival raster records zero for every cell that was already wet at
t=0 — the reservoir, and the river channel downstream. That is literally true and
operationally useless. Left in, it makes `first_arrival_minutes()` return 0.0 for
every dam-break run ("first arrival 0 minutes after failure"), and it folds tens
of square kilometres of pre-existing lake into the 0-15 minute band, so the
population count for "under 15 minutes to evacuate" includes everyone the
population raster thinks is standing in the water. Pass `initially_wet` to
`analyse()`. If you do not, the result says so in its own limitations list.

WHAT ARRIVAL TIME IS NOT
------------------------
It is not warning time. Warning time is arrival time minus detection, decision
and dissemination delay, and those are institutional quantities this model knows
nothing about. `ArrivalResult.limitations` says so explicitly, because the
difference is the difference between a useful tool and a dangerous one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Default isochrone edges in minutes. Chosen to match how a staged evacuation is
# organised rather than to make round numbers on a chart:
#   15 min  — no time for anything but vertical evacuation in place
#   30 min  — on foot, immediate neighbourhood only
#   60 min  — organised movement with vehicles
#   120 min — full planned evacuation of a settlement
DEFAULT_BANDS_MIN = (15.0, 30.0, 60.0, 120.0)

# Sequential blue ramp — fastest arrival darkest, because on a map the eye should
# go first to the places with least time. Deliberately NOT the hazard ramp: the
# two quantities must never be confused on the same figure.
#
# The lightest step is #bdd7e7, not the near-white #f7fbff that a nine-step Blues
# ramp would give. On a map, unflooded land is rendered as neutral grey, and a
# near-white ">120 min" class is invisible against it — the least urgent band
# would silently disappear rather than reading as "flooded, but late". A class
# that cannot be seen is a class the reader concludes is empty.
BAND_COLOURS = (
    "#08306b", "#2171b5", "#4292c6", "#7fb8d9", "#bdd7e7",
)

# Pre-existing water — the reservoir and the river channel — is deliberately OFF
# the blue urgency ramp. A desaturated slate cannot be misread as "an isochrone
# band I can't quite place on the legend", which is exactly what happens when the
# lake is drawn in a pale blue that sits between two band colours.
PRE_EXISTING_WATER_COLOUR = "#8c96a8"


def to_minutes(arrival_seconds):
    """
    Seconds -> minutes, preserving NaN for "never arrived".

    NaN is load-bearing here. A cell the water never reached must not appear as
    a very large arrival time, because every downstream consumer — band edges,
    zonal statistics, the colour ramp — would silently treat it as flooded-late
    rather than dry.
    """
    a = np.asarray(arrival_seconds, dtype=np.float64)
    return a / 60.0


# Sentinel values in the band raster. Both are negative so that every consumer
# which iterates `enumerate(band_labels())` skips them without having to know
# they exist — but they are distinct, because "dry land the wave never reached"
# and "the reservoir, which was already water before the dam failed" are
# completely different statements and must never be summed together.
NEVER_FLOODED = -1
INITIALLY_WET = -2


def band_index(arrival_minutes, bands=DEFAULT_BANDS_MIN, *, initially_wet=None):
    """
    Bin arrival minutes into 0..len(bands), with negative sentinels for the two
    kinds of cell that have no meaningful arrival time.

    Band k covers [bands[k-1], bands[k]) — closed below, open above, matching
    `np.digitize`'s default — and the final index is everything at or later than
    the last edge. Cells the water never reached get NEVER_FLOODED.

    `initially_wet` is the reservoir (and the pre-existing river channel). Those
    cells have arrival time zero, which is true and useless: they were water
    before the failure. Left in band 0 they inflate the 0-15 minute area and
    population with the reservoir's own surface, so the headline "N people have
    under 15 minutes" would silently include everyone the model thinks is
    standing in the lake. They get INITIALLY_WET instead.
    """
    a = np.asarray(arrival_minutes, dtype=np.float64)
    never = ~np.isfinite(a)
    idx = np.digitize(np.where(never, 0.0, a), np.asarray(bands, dtype=float))
    out = np.where(never, np.int8(NEVER_FLOODED), idx.astype(np.int8))
    if initially_wet is not None:
        out = np.where(np.asarray(initially_wet, dtype=bool),
                       np.int8(INITIALLY_WET), out)
    return out.astype(np.int8)


def band_labels(bands=DEFAULT_BANDS_MIN) -> list[str]:
    """Human-readable labels, in band-index order."""
    edges = list(bands)
    out = [f"0-{edges[0]:.0f} min"]
    for lo, hi in zip(edges, edges[1:]):
        out.append(f"{lo:.0f}-{hi:.0f} min")
    out.append(f">{edges[-1]:.0f} min")
    return out


def front_speed(arrival_seconds, dx):
    """
    Apparent speed of the flood front, m/s, from the gradient of arrival time.

    |grad t| has units s/m, so the front speed is its reciprocal. Useful as a
    diagnostic rather than a deliverable: a front speed exceeding the local
    gravity wave speed sqrt(g*h) by a wide margin means the arrival field is
    being set by numerical noise in a thin film, not by a physical wave.

    Returned as NaN wherever arrival time is undefined or the gradient vanishes.
    """
    t = np.asarray(arrival_seconds, dtype=np.float64)
    filled = np.where(np.isfinite(t), t, np.nan)
    gy, gx = np.gradient(filled, float(dx))
    grad = np.hypot(gy, gx)
    with np.errstate(divide="ignore", invalid="ignore"):
        speed = np.where(grad > 0, 1.0 / grad, np.nan)
    return speed


def isochrone_polygons(band_idx, transform, crs, bands=DEFAULT_BANDS_MIN,
                       *, simplify_m=None):
    """
    Dissolve the band raster into one polygon per isochrone band.

    Returns a GeoDataFrame with columns: band (int), label (str), min_minutes,
    max_minutes, area_km2 — ready for `export/vector.py` to write as Shapefile
    and KML.

    Uses `rasterio.features.shapes`, which traces exact cell boundaries, so the
    polygons are blocky at the cell scale. That is deliberate and honest: a
    smoothed contour would imply sub-cell precision the model does not have. Pass
    `simplify_m` only for cartographic output, never for anything that gets
    measured.
    """
    import geopandas as gpd
    from rasterio import features
    from shapely.geometry import shape

    band_idx = np.asarray(band_idx)
    labels = band_labels(bands)
    edges = [0.0, *bands, np.inf]

    records = []
    for idx, label in enumerate(labels):
        mask = band_idx == idx
        if not mask.any():
            continue
        geoms = [
            shape(geom)
            for geom, val in features.shapes(
                mask.astype(np.uint8), mask=mask, transform=transform)
            if val == 1
        ]
        if not geoms:
            continue
        from shapely.ops import unary_union
        merged = unary_union(geoms)
        if simplify_m:
            merged = merged.simplify(simplify_m, preserve_topology=True)
        records.append({
            "band": idx,
            "label": label,
            "min_minutes": float(edges[idx]),
            "max_minutes": float(edges[idx + 1]),
            "geometry": merged,
        })

    gdf = gpd.GeoDataFrame(records, crs=crs)
    if len(gdf):
        gdf["area_km2"] = gdf.geometry.area / 1.0e6
    return gdf


@dataclass
class ArrivalResult:
    """
    The arrival-time product: rasters, bands, and the caveats that must travel
    with them.

    `limitations` is a field rather than a docstring because this is the output
    most likely to be quoted out of context. Anyone rendering the arrival map is
    expected to render these strings too.
    """
    seconds: np.ndarray                 # NaN where never flooded
    minutes: np.ndarray
    band: np.ndarray                    # int8, -1 = never, -2 = already wet
    bands_min: tuple
    cell_area_m2: float
    threshold_m: float
    initially_wet: np.ndarray | None = None
    limitations: list[str] = field(default_factory=list)

    @property
    def ever_flooded(self) -> np.ndarray:
        """Cells that hold water at some point — including the reservoir."""
        return np.isfinite(self.seconds)

    @property
    def newly_flooded(self) -> np.ndarray:
        """
        Cells the wave reached that were dry before the failure.

        This, not `ever_flooded`, is the inundation caused by the dam break. The
        difference is the reservoir surface, which is large.
        """
        wet = self.ever_flooded
        if self.initially_wet is None:
            return wet
        return wet & ~np.asarray(self.initially_wet, dtype=bool)

    @property
    def flooded_area_km2(self) -> float:
        """Newly inundated area — the reservoir is not flooding."""
        return int(self.newly_flooded.sum()) * self.cell_area_m2 / 1.0e6

    def area_by_band_km2(self) -> dict[str, float]:
        out = {}
        for idx, label in enumerate(band_labels(self.bands_min)):
            n = int((self.band == idx).sum())
            out[label] = n * self.cell_area_m2 / 1.0e6
        return out

    def first_arrival_minutes(self) -> float:
        """
        Earliest arrival outside the initially-wet region.

        Excluding the reservoir is the whole point. Include it and this returns
        0.0 for every dam-break run, because the reservoir is wet at t=0 — and
        "first arrival 0 min after failure" is the kind of sentence that ends up
        on a slide and destroys the credibility of everything next to it.
        """
        m = np.where(self.newly_flooded, self.minutes, np.nan)
        finite = m[np.isfinite(m)]
        return float(finite.min()) if finite.size else float("nan")

    def last_arrival_minutes(self) -> float:
        m = np.where(self.newly_flooded, self.minutes, np.nan)
        finite = m[np.isfinite(m)]
        return float(finite.max()) if finite.size else float("nan")

    def sample(self, rows, cols) -> np.ndarray:
        """
        Arrival minutes at specific cell indices — the per-settlement table.

        Returns NaN for locations the water never reached, which the report must
        print as "not reached" rather than omitting the row: a settlement absent
        from a table looks like an oversight, whereas "not reached in this
        scenario" is information.
        """
        return self.minutes[np.asarray(rows), np.asarray(cols)]

    def summary(self) -> str:
        lines = [
            f"newly flooded  : {self.flooded_area_km2:.2f} km^2",
            f"first arrival  : {self.first_arrival_minutes():.1f} min",
            f"last arrival   : {self.last_arrival_minutes():.1f} min",
            "area by band:",
        ]
        for label, km2 in self.area_by_band_km2().items():
            lines.append(f"  {label:<14} {km2:8.2f} km^2")
        if self.initially_wet is not None:
            n = int(np.asarray(self.initially_wet, dtype=bool).sum())
            lines.append(
                f"  ({n:,} cells were already water before failure and are "
                f"excluded from every figure above)")
        if self.limitations:
            lines.append("limitations:")
            lines += [f"  - {t}" for t in self.limitations]
        return "\n".join(lines)


def analyse(arrival_seconds, *, dx, bands=DEFAULT_BANDS_MIN,
            threshold_m=0.1, run_duration_s=None,
            open_bc_cells=None, initially_wet=None) -> ArrivalResult:
    """
    Turn `SWE2D.arrival_time` into the reportable arrival product.

    `initially_wet` is the reservoir and pre-existing channel — pass the depth
    field at t=0 thresholded at `threshold_m`. Omitting it does not crash
    anything; it silently reports first arrival as 0 minutes and folds the
    reservoir surface into the 0-15 minute band. See `band_index`.

    `run_duration_s` matters: a cell that had not flooded by the end of a
    truncated run is indistinguishable in the raster from one that never floods
    at all. If the simulation stopped before the wave left the domain, that has
    to be stated, not inferred.

    `open_bc_cells` should be `swe2d.OPEN_BC_INFLUENCE_CELLS` when any boundary is
    open. Results within that many cells of an open boundary are contaminated by
    the transmissive condition and must not be quoted.
    """
    seconds = np.asarray(arrival_seconds, dtype=np.float64)
    minutes = to_minutes(seconds)
    if initially_wet is not None:
        initially_wet = np.asarray(initially_wet, dtype=bool)
        if initially_wet.shape != seconds.shape:
            raise ValueError(
                f"initially_wet {initially_wet.shape} must match the arrival "
                f"raster {seconds.shape}")
    idx = band_index(minutes, bands, initially_wet=initially_wet)

    limitations = [
        f"Arrival time is the first moment depth exceeded {threshold_m:.2f} m in "
        f"a {dx:.0f} m cell. It is a neighbourhood-scale figure, not a "
        f"doorstep-scale one.",
        "Arrival time is NOT warning time. Warning time is arrival time minus "
        "detection, decision and dissemination delay, none of which this model "
        "represents.",
        "Reported as bands rather than exact minutes because the underlying "
        "uncertainty — breach formation time, Manning n, DEM vintage — is far "
        "wider than the difference between adjacent minutes.",
    ]

    if initially_wet is None:
        limitations.append(
            "No initially-wet mask was supplied, so the reservoir and the "
            "pre-existing river channel are counted as flooded at t=0. First "
            "arrival and the earliest band are NOT trustworthy in this run.")

    if run_duration_s is not None:
        never = ~np.isfinite(seconds)
        limitations.append(
            f"The simulation covered {run_duration_s / 60.0:.0f} min. "
            f"{int(never.sum()):,} cells had not flooded by then; they are "
            f"reported as not reached, which for cells near the downstream "
            f"boundary may mean 'not yet' rather than 'never'."
        )

    if open_bc_cells:
        limitations.append(
            f"Cells within {open_bc_cells} of an open boundary "
            f"({open_bc_cells * dx / 1000.0:.1f} km) are affected by the "
            f"transmissive outflow condition and must not be quoted."
        )

    return ArrivalResult(
        seconds=seconds,
        minutes=minutes,
        band=idx,
        bands_min=tuple(bands),
        cell_area_m2=float(dx) * float(dx),
        threshold_m=float(threshold_m),
        initially_wet=initially_wet,
        limitations=limitations,
    )

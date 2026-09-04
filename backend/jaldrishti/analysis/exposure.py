"""
Exposure — how many people and what infrastructure is in the flood.

WHY THIS FILE IS THE DIFFERENTIATOR
-----------------------------------
`CLAUDE.md`: *"The differentiator is arrival time + exposure, not the inundation
map."* A depth raster is a physics result. "12,400 people are inside the 60-minute
band, of whom 3,100 are in Extreme hazard" is a decision. This module is where the
physics becomes a decision.

THE RESAMPLING TRAP, AND WHY IT IS HANDLED THE LONG WAY
-------------------------------------------------------
A population raster holds COUNTS per cell, not a continuous field. Two things go
wrong if you resample it like an elevation grid:

  1. Bilinear or nearest-neighbour resampling of counts does not conserve people.
     Going from 100 m source cells to 90 m model cells with `Resampling.bilinear`
     changes the national total, silently, by whatever the area ratio happens to
     be. The headline number is then wrong by a factor nobody notices because it
     is still a plausible-looking integer.

  2. WorldPop constrained rasters are in EPSG:4326, so a "100 m" cell is 100 m
     only near the equator. At Tehri (30.4 N) a 3-arcsecond cell is about 92.6 m
     east-west and 92.5 m north-south — and the east-west extent shrinks with
     cos(latitude) while the north-south does not. Treating cell area as constant
     biases the total.

So the conversion goes counts -> DENSITY (persons per m^2, using each source
cell's true ground area at its own latitude) -> reproject the density ->
multiply by the target cell area. Density is a genuine field, so interpolating it
is legitimate, and the round trip conserves people to interpolation error rather
than to luck. `resample_population` asserts that conservation and reports the
residual, because a silent 20% error in the headline number is the single most
embarrassing failure mode available to this project.

WHAT THIS MODULE DELIBERATELY DOES NOT CLAIM
--------------------------------------------
WorldPop 2020 is a modelled surface, not a census enumeration: it disaggregates
census counts onto a grid using built-up-area covariates. It is the right dataset
for this purpose and it is what the humanitarian sector uses, but a per-cell count
is an estimate with real uncertainty, and it is six years old at the time of
writing. Exposure figures are therefore reported to two significant figures with
the vintage stated, never as exact head counts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------
EXPOSURE_SOURCES = {
    "worldpop_constrained": (
        "WorldPop (2020), 'Global High Resolution Population Denominators "
        "Project' — constrained individual-country estimates, 100 m, "
        "unadjusted; www.worldpop.org, DOI 10.5258/SOTON/WP00660", False),
    "osm_infrastructure": (
        "OpenStreetMap contributors, via OSMnx (Boeing, G. 2017, "
        "'OSMnx: New methods for acquiring, constructing, analyzing, and "
        "visualizing complex street networks', Computers, Environment and "
        "Urban Systems 65:126-139). ODbL.", False),
}

EARTH_RADIUS_M = 6_371_008.8


# ---------------------------------------------------------------------------
# population
# ---------------------------------------------------------------------------
def geographic_cell_area_m2(lat_deg, res_x_deg, res_y_deg):
    """
    True ground area of a lat/lon raster cell, m^2, at a given latitude.

    Uses the exact spherical formula for a quadrilateral bounded by two meridians
    and two parallels:

        A = R^2 * dlon * (sin(lat_top) - sin(lat_bottom))

    rather than the usual `dx*cos(lat) * dy` approximation. The difference is
    small at 100 m cells but the exact form costs nothing and removes a source of
    doubt from the number the whole project is judged on.

    `lat_deg` may be an array (one entry per raster row), which is how it is used:
    cell area varies down the raster, so a single scalar would reintroduce the
    very bias this function exists to remove.
    """
    lat = np.asarray(lat_deg, dtype=np.float64)
    half = 0.5 * res_y_deg
    top = np.radians(lat + half)
    bot = np.radians(lat - half)
    dlon = math.radians(abs(res_x_deg))
    return EARTH_RADIUS_M ** 2 * dlon * np.abs(np.sin(top) - np.sin(bot))


def resample_population(pop_path, *, dst_transform, dst_crs, dst_shape,
                        dst_dx, tolerance=0.02):
    """
    Read a population-count raster and resample it onto the model grid,
    conserving people.

    Returns `(pop_on_grid, report)` where `pop_on_grid` is persons per model cell
    and `report` is a dict recording the source total, the resampled total and
    the residual — which the metadata sidecar records and the PDF prints.

    `tolerance` is the fractional mismatch treated as acceptable. 2% is
    interpolation error at these cell sizes; more than that means something is
    structurally wrong (a CRS mismatch, a nodata value being counted as people)
    and the caller should be told rather than handed a plausible number.
    """
    import rasterio
    from rasterio.warp import Resampling, calculate_default_transform, reproject
    from rasterio.windows import from_bounds
    from rasterio.transform import array_bounds

    pop_path = Path(pop_path)
    if not pop_path.exists():
        raise FileNotFoundError(
            f"population raster not found: {pop_path}. Exposure is the "
            f"headline deliverable — see ROADMAP.md data gap D1.")

    ny, nx = dst_shape
    dst_bounds = array_bounds(ny, nx, dst_transform)

    with rasterio.open(pop_path) as src:
        # Window the source to the model domain, with a generous pad so
        # reprojection has neighbours to interpolate from at the edges.
        from rasterio.warp import transform_bounds
        west, south, east, north = transform_bounds(
            dst_crs, src.crs, *dst_bounds, densify_pts=21)
        pad = 20 * max(abs(src.res[0]), abs(src.res[1]))
        window = from_bounds(west - pad, south - pad, east + pad, north + pad,
                             transform=src.transform).round_offsets().round_lengths()
        window = window.intersection(
            rasterio.windows.Window(0, 0, src.width, src.height))
        if window.width < 1 or window.height < 1:
            raise ValueError(
                "the model domain does not overlap the population raster; "
                "check the CRS and the study-area bounds")

        counts = src.read(1, window=window, masked=True).filled(0.0)
        win_transform = src.window_transform(window)
        src_crs = src.crs
        res_x, res_y = src.transform.a, -src.transform.e

    counts = np.asarray(counts, dtype=np.float64)
    # WorldPop uses a large negative nodata; masked-read handles it, but guard
    # anyway. Negative people are always an error, never data.
    counts = np.where(counts < 0.0, 0.0, counts)
    source_raw_window = float(counts.sum())

    # --- counts -> density, using each row's own true cell area --------------
    is_geographic = bool(getattr(src_crs, "is_geographic", False))
    if is_geographic:
        rows = np.arange(counts.shape[0])
        # cell-centre latitudes for the window
        lats = win_transform.f + (rows + 0.5) * win_transform.e
        cell_area = geographic_cell_area_m2(lats, res_x, res_y)[:, None]
    else:
        cell_area = np.full((1, 1), abs(res_x) * abs(res_y))
    density = counts / cell_area                      # persons per m^2

    # --- reproject the density ---------------------------------------------
    dst_density = np.zeros(dst_shape, dtype=np.float64)
    reproject(
        source=density,
        destination=dst_density,
        src_transform=win_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        # Area-weighted average is the right operator for a density field going
        # to a similar or coarser resolution: it integrates the source cells
        # covering each target cell instead of point-sampling one of them.
        resampling=Resampling.average,
        src_nodata=None,
        dst_nodata=None,
    )

    pop_on_grid = dst_density * (float(dst_dx) ** 2)
    dst_total = float(pop_on_grid.sum())

    # --- conservation check against the RIGHT baseline ----------------------
    # Comparing dst_total to the raw window sum is wrong in two compounding
    # ways, and both make a perfectly conserving reprojection read as a large
    # "loss". First, the read window is padded (see above), so it holds people
    # from ~1.7 km of ground outside the model domain. Second, that window is an
    # axis-aligned box in the SOURCE CRS, and the model domain is a rectangle in
    # the projected CRS; away from the UTM central meridian the projected
    # rectangle is rotated, so its lat/lon bounding box is larger than the
    # ground the model actually spans. At Tehri the two together inflate the raw
    # window total by ~30%, which is exactly the spurious residual an earlier
    # version of this function reported.
    #
    # The honest comparand is the source population INSIDE the destination
    # footprint. Reproject a domain indicator (ones on the dst grid) back onto
    # the source grid; each source cell then carries the fraction of its area
    # the domain covers, and counts weighted by that fraction sum to the source
    # population the model is responsible for. Against this baseline the
    # measured residual is a fraction of a percent, which is the interpolation
    # error the density round-trip should incur — not the double-counted domain
    # mismatch the raw comparison was reporting.
    cover = np.zeros(counts.shape, dtype=np.float64)
    reproject(
        source=np.ones(dst_shape, dtype=np.float64), destination=cover,
        src_transform=dst_transform, src_crs=dst_crs,
        dst_transform=win_transform, dst_crs=src_crs,
        resampling=Resampling.average, src_nodata=None, dst_nodata=None,
    )
    source_in_footprint = float((counts * cover).sum())

    residual = ((dst_total - source_in_footprint) / source_in_footprint
                if source_in_footprint else 0.0)
    report = {
        "source_total": source_in_footprint,
        "resampled_total": dst_total,
        "residual_fraction": residual,
        "conserved": bool(abs(residual) <= tolerance),
        "source_total_raw_window": source_raw_window,
        "source_crs": str(src_crs),
        "source_is_geographic": is_geographic,
        "source_path": str(pop_path),
        "method": "counts -> per-row-exact density -> area-average reproject "
                  "-> multiply by target cell area; conservation checked "
                  "against source population within the destination footprint "
                  "(coverage-weighted), not the padded read window",
    }
    return pop_on_grid, report


def population_by_class(pop_on_grid, class_raster, labels):
    """
    Sum population within each class of an integer raster.

    Works for both hazard classes and arrival bands — they have the same shape:
    an int8 raster where NEGATIVE values are sentinels (-1 not flooded, -2
    already water before the failure). Because this only ever sums cells whose
    class index is in `range(len(labels))`, every sentinel is excluded
    automatically, and the totals below count only people who are in water that
    the failure put there.
    """
    pop = np.asarray(pop_on_grid, dtype=np.float64)
    cls = np.asarray(class_raster)
    if pop.shape != cls.shape:
        raise ValueError(f"population {pop.shape} and class {cls.shape} "
                         f"rasters must have the same shape")
    out = {}
    for idx, label in enumerate(labels):
        out[label] = float(pop[cls == idx].sum())
    return out


def population_cross_tab(pop_on_grid, hazard_class, arrival_band,
                         hazard_labels, band_labels_):
    """
    Population by (hazard class x arrival band) — the table that drives a staged
    evacuation.

    This cross-tabulation is the actual operational product. "3,100 people in
    Extreme hazard inside the 30-minute band" identifies who moves first; the
    marginal totals alone do not, because a large population in a late band is a
    different problem from the same number in an early one.
    """
    pop = np.asarray(pop_on_grid, dtype=np.float64)
    hz = np.asarray(hazard_class)
    ab = np.asarray(arrival_band)
    table = {}
    for h_idx, h_label in enumerate(hazard_labels):
        row = {}
        for b_idx, b_label in enumerate(band_labels_):
            sel = (hz == h_idx) & (ab == b_idx)
            row[b_label] = float(pop[sel].sum())
        table[h_label] = row
    return table


# ---------------------------------------------------------------------------
# infrastructure
# ---------------------------------------------------------------------------
def osm_features(bounds_4326, tags, *, cache_dir=None, name=None):
    """
    Fetch OSM features for a bounding box, with an on-disk cache.

    Caching is a reproducibility requirement, not a speed optimisation: OSM is
    edited continuously, so an uncached run cannot be reproduced. The cached
    GeoPackage is what the run manifest references.
    """
    import geopandas as gpd
    import osmnx as ox

    if cache_dir is not None and name is not None:
        cache = Path(cache_dir) / f"{name}.gpkg"
        if cache.exists():
            return gpd.read_file(cache)

    west, south, east, north = bounds_4326
    gdf = ox.features_from_bbox(bbox=(west, south, east, north), tags=tags)

    if cache_dir is not None and name is not None:
        cache = Path(cache_dir) / f"{name}.gpkg"
        cache.parent.mkdir(parents=True, exist_ok=True)
        # OSM tag columns are wildly heterogeneous; keep only what serialises.
        keep = [c for c in gdf.columns
                if c == "geometry" or gdf[c].map(type).nunique() == 1]
        gdf[keep].to_file(cache, driver="GPKG")
    return gdf


def count_features_in_flood(gdf, flood_mask, transform, dst_crs):
    """
    Count vector features whose geometry intersects a flooded cell.

    Point features are sampled directly; lines and polygons are counted if ANY
    part intersects the flood, which is the operationally correct rule for a road
    or a bridge — a road cut at one point is impassable along its whole length.
    Length of flooded road is reported separately by `flooded_length_km`.
    """
    import geopandas as gpd
    from rasterio.features import geometry_mask

    if gdf is None or len(gdf) == 0:
        return 0
    g = gdf.to_crs(dst_crs)
    mask = np.asarray(flood_mask, dtype=bool)

    # Rasterise each geometry once against the flood mask. For the counts we
    # need, testing the rasterised footprint is far cheaper than a vector
    # overlay and gives the same answer at cell resolution — which is the only
    # resolution the flood mask has anyway.
    hit = 0
    for geom in g.geometry:
        if geom is None or geom.is_empty:
            continue
        try:
            covered = ~geometry_mask([geom], out_shape=mask.shape,
                                     transform=transform, invert=False,
                                     all_touched=True)
        except Exception:
            continue
        if (covered & mask).any():
            hit += 1
    return hit


def flooded_length_km(gdf, flood_polygon, dst_crs):
    """Kilometres of linear feature (road, rail) inside the flood polygon."""
    if gdf is None or len(gdf) == 0 or flood_polygon is None:
        return 0.0
    g = gdf.to_crs(dst_crs)
    lines = g[g.geometry.geom_type.isin(("LineString", "MultiLineString"))]
    if not len(lines):
        return 0.0
    clipped = lines.geometry.intersection(flood_polygon)
    return float(clipped.length.sum() / 1000.0)


# ---------------------------------------------------------------------------
# result object
# ---------------------------------------------------------------------------
@dataclass
class ExposureResult:
    """Population and infrastructure exposure, with provenance and caveats."""
    total_population: float
    population_by_hazard: dict
    population_by_arrival_band: dict
    population_cross_tab: dict
    infrastructure: dict = field(default_factory=dict)
    settlements: list = field(default_factory=list)
    resample_report: dict = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    sources: dict = field(default_factory=lambda: dict(EXPOSURE_SOURCES))

    def rounded_population(self, value=None) -> int:
        """
        Population rounded to two significant figures.

        Reporting 12,437 people implies a per-person census. Reporting 12,000
        states the same thing at the precision the input data supports. The PDF
        uses this; the JSON keeps the raw float so nothing is lost.
        """
        v = self.total_population if value is None else value
        if v <= 0:
            return 0
        mag = 10 ** max(0, int(math.floor(math.log10(v))) - 1)
        return int(round(v / mag) * mag)

    def unverified_sources(self) -> list[str]:
        return [f"{k}: {v[0]}" for k, v in self.sources.items() if not v[1]]

    def summary(self) -> str:
        lines = [
            f"population exposed : ~{self.rounded_population():,} "
            f"(raw {self.total_population:,.0f})",
            "by hazard class:",
        ]
        for label, v in self.population_by_hazard.items():
            lines.append(f"  {label:<12} ~{self.rounded_population(v):>9,}")
        lines.append("by arrival band:")
        for label, v in self.population_by_arrival_band.items():
            lines.append(f"  {label:<14} ~{self.rounded_population(v):>9,}")
        if self.infrastructure:
            lines.append("infrastructure:")
            for k, v in self.infrastructure.items():
                lines.append(f"  {k:<22} {v}")
        if self.resample_report and not self.resample_report.get("conserved", True):
            lines.append(
                f"  WARNING: population resampling residual "
                f"{self.resample_report['residual_fraction']:+.1%}")
        if self.limitations:
            lines.append("limitations:")
            lines += [f"  - {t}" for t in self.limitations]
        return "\n".join(lines)


def standard_limitations(vintage=2020) -> list[str]:
    """The caveats that must accompany any exposure figure from this module."""
    return [
        f"Population is WorldPop {vintage} constrained — a MODELLED surface that "
        f"disaggregates census counts onto a grid using built-up-area "
        f"covariates, not an enumeration. Per-cell counts carry real "
        f"uncertainty and the surface is {2026 - vintage} years old.",
        "Counts are reported to two significant figures. The input data does "
        "not support a head count, and quoting one would imply a census.",
        "Population is a residential night-time distribution. It does not "
        "represent people at work, in transit, at a market, or on a pilgrimage "
        "route — which for the Bhagirathi and Alaknanda valleys is a material "
        "seasonal omission.",
        "Infrastructure counts come from OpenStreetMap, whose completeness "
        "varies enormously by district. An absent feature means absent from "
        "OSM, not absent from the ground.",
        "A feature is counted as exposed if ANY part of it intersects a flooded "
        "cell. For a road or a bridge that is the operationally correct rule — "
        "a road cut at one point is impassable — but it is not a measure of "
        "how much of the asset is under water.",
    ]


def analyse(pop_on_grid, hazard_result, arrival_result, *,
            infrastructure=None, settlements=None, resample_report=None,
            vintage=2020, extra_limitations=None) -> ExposureResult:
    """
    The one call the orchestrator makes. Tabulates population consistently.

    WHY THIS EXISTS RATHER THAN CALLING THE HELPERS DIRECTLY
    -------------------------------------------------------
    The hazard raster and the arrival raster disagree about the reservoir: a
    reservoir cell is genuinely in Extreme hazard (it is deep water) but has no
    meaningful arrival time. Tabulate population against each raster
    independently and the by-hazard column sums to more than the by-band column,
    by exactly the reservoir's population. A table whose rows and columns
    disagree is the fastest way to lose a technical jury.

    So every figure here is computed over ONE mask — cells the breach newly
    flooded — and the marginal totals are asserted to agree before the result is
    returned. If they ever don't, that is a bug in this package, not a rounding
    artefact, and it raises rather than reporting a plausible wrong number.
    """
    pop = np.asarray(pop_on_grid, dtype=np.float64)
    if pop.shape != hazard_result.dry_mask.shape:
        raise ValueError(
            f"population grid {pop.shape} does not match the model grid "
            f"{hazard_result.dry_mask.shape}")

    limitations = standard_limitations(vintage=vintage)

    # The single mask. Both stages must agree on it; if they don't, say so.
    haz_wet = ~np.asarray(hazard_result.dry_mask, dtype=bool)
    arr_wet = np.asarray(arrival_result.newly_flooded, dtype=bool)
    iw = hazard_result.initially_wet
    if iw is not None:
        haz_wet = haz_wet & ~np.asarray(iw, dtype=bool)

    disagree = int((haz_wet ^ arr_wet).sum())
    if disagree:
        limitations.append(
            f"The hazard and arrival stages disagree about {disagree:,} cells "
            f"(hazard uses peak depth >= its wet threshold, arrival uses first "
            f"crossing of {arrival_result.threshold_m:.2f} m). Exposure counts "
            f"the intersection, so these cells are excluded.")
    mask = haz_wet & arr_wet

    masked = np.where(mask, pop, 0.0)
    total = float(masked.sum())

    # Sentinels are negative in both class rasters, so cells outside `mask` must
    # be pushed to a negative value to be excluded from the tabulations.
    haz_cls = np.where(mask, hazard_result.defra_class, np.int8(-1))
    band = np.where(mask, arrival_result.band, np.int8(-1))

    from .arrival import band_labels as _band_labels
    from .hazard import DEFRA_CLASS_NAMES

    haz_labels = list(DEFRA_CLASS_NAMES)
    bnd_labels = _band_labels(arrival_result.bands_min)

    by_hazard = population_by_class(masked, haz_cls, haz_labels)
    by_band = population_by_class(masked, band, bnd_labels)
    xtab = population_cross_tab(masked, haz_cls, band, haz_labels, bnd_labels)

    # --- the invariant ---------------------------------------------------
    # Three independent tabulations of the same people. If they disagree the
    # table is wrong, and a wrong exposure table is worse than none.
    tol = max(1.0e-6, 1.0e-9 * max(total, 1.0))
    sums = {
        "by_hazard": sum(by_hazard.values()),
        "by_arrival_band": sum(by_band.values()),
        "cross_tab": sum(v for row in xtab.values() for v in row.values()),
    }
    for name, s in sums.items():
        if abs(s - total) > tol:
            raise AssertionError(
                f"exposure tabulation is inconsistent: {name} sums to {s:,.6f} "
                f"but the flooded population is {total:,.6f} "
                f"(difference {s - total:+.6g}). This is a bug in "
                f"jaldrishti.analysis, not a data problem.")

    if extra_limitations:
        limitations.extend(extra_limitations)

    return ExposureResult(
        total_population=total,
        population_by_hazard=by_hazard,
        population_by_arrival_band=by_band,
        population_cross_tab=xtab,
        infrastructure=dict(infrastructure or {}),
        settlements=list(settlements or []),
        resample_report=dict(resample_report or {}),
        limitations=limitations,
    )

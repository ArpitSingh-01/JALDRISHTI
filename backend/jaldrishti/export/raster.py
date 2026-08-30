"""
Raster export — GeoTIFF and Cloud-Optimised GeoTIFF.

WHAT THE PROBLEM STATEMENT ACTUALLY DEMANDS
-------------------------------------------
PS 26161 names its deliverable formats explicitly: GeoTIFF, Shapefile and KML.
That is not a stylistic preference. A district emergency operations centre runs
whatever GIS it already has — usually QGIS, sometimes ArcGIS, often just Google
Earth on a laptop — and a result it cannot open is a result it does not have.
This module and `vector.py` exist to make the output portable to those tools with
no conversion step in between.

WHY EVERY RASTER CARRIES A NODATA VALUE AND A MASK
--------------------------------------------------
Depth zero and depth unknown are different statements, and a single float32 band
cannot hold both unless one of them is nodata. Writing 0.0 for "dry" and 0.0 for
"outside the domain" makes the flood extent look larger than it is when someone
styles the layer with a "> 0" rule. So:

  * dry cells inside the domain are written as 0.0 — a measurement;
  * cells outside the computed domain are written as nodata — an absence;
  * arrival time, which is NaN where water never came, is written with nodata
    rather than a large number, because a large number sorts as "flooded late".

WHY COG
-------
A Cloud-Optimised GeoTIFF is an ordinary GeoTIFF with its tiles and overviews
arranged so a client can fetch a window over HTTP without downloading the file.
The frontend needs this — a 30 m Tehri domain is a large raster and deck.gl
should not be pulling all of it to draw a zoomed-out view. It costs one extra
build step and nothing in compatibility: every reader that opens a GeoTIFF opens
a COG.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Written into every file's GeoTIFF metadata. The PS asks for a "confidence-
# based" product; a raster that leaves the machine without provenance attached
# cannot be one, because the tags are the only thing that travels with a file
# once it has been emailed to a district office.
DEFAULT_TAGS = {
    "GENERATOR": "JALDRISHTI (SIH 2026, PS 26161)",
    "SOLVER": "jaldrishti 2D SWE — finite volume, HLLC, MUSCL, "
              "well-balanced bed slope",
    "DISCLAIMER": "Simulation output. Not a survey. Not an official flood "
                  "hazard map. See the accompanying provenance JSON for "
                  "limitations and unverified inputs.",
}

# Float rasters use a large negative sentinel; integer class rasters use -1,
# which is already the "dry" sentinel the analysis package assigns, so the two
# meanings coincide and no translation is needed.
FLOAT_NODATA = -9999.0
INT_NODATA = -1


@dataclass
class RasterSpec:
    """One band to write: what it is called, what it holds, and how to read it."""
    name: str
    array: np.ndarray
    dtype: str
    nodata: float
    description: str
    units: str = ""
    colour_ramp: str = ""
    # True for quantities that have no meaning over water that existed before
    # the failure. See `raster_specs` for why this is per-band and not global:
    # depth over the reservoir is a real 40 m of water, but arrival time there is
    # 0.0, which is not an arrival, and hazard there is not a hazard anyone was
    # exposed to.
    mask_initially_wet: bool = False


def _write(path, array, *, transform, crs, dtype, nodata, tags=None,
           description="", cog=False):
    import rasterio

    a = np.asarray(array)
    if dtype.startswith("float"):
        a = np.where(np.isfinite(a), a, nodata).astype(dtype)
    else:
        a = a.astype(dtype)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    profile = dict(
        driver="GTiff", height=a.shape[0], width=a.shape[1], count=1,
        dtype=dtype, crs=crs, transform=transform, nodata=nodata,
        compress="deflate", predictor=2 if dtype.startswith("float") else 1,
        tiled=True, blockxsize=512, blockysize=512,
    )
    if cog:
        # A COG needs its overviews written before the image data is finalised,
        # which rasterio handles via the COG driver when available. Falling back
        # to a tiled GTiff with overviews is not bit-identical to a COG but is
        # readable by every client that reads a COG, so the fallback degrades
        # capability rather than correctness.
        try:
            profile["driver"] = "COG"
            profile.pop("tiled")
            profile.pop("blockxsize")
            profile.pop("blockysize")
            profile["blocksize"] = 512
            profile["overviews"] = "AUTO"
        except Exception:                                  # pragma: no cover
            profile["driver"] = "GTiff"

    all_tags = dict(DEFAULT_TAGS)
    all_tags.update(tags or {})

    def _do_write(prof):
        with rasterio.open(path, "w", **prof) as dst:
            dst.write(a, 1)
            dst.update_tags(**{k: str(v) for k, v in all_tags.items()})
            if description:
                dst.set_band_description(1, description)
            dst.update_tags(1, DESCRIPTION=description)

    if cog:
        cog_profile = dict(profile)
        cog_profile["driver"] = "COG"
        for k in ("tiled", "blockxsize", "blockysize", "predictor"):
            cog_profile.pop(k, None)
        cog_profile["blocksize"] = 512
        cog_profile["overviews"] = "AUTO"
        try:
            _do_write(cog_profile)
            return path
        except Exception:
            # The COG driver arrived in GDAL 3.1 and is not guaranteed present in
            # every conda build. Falling back to a tiled GTiff with overviews
            # loses HTTP range-request efficiency and nothing else — every reader
            # that opens a COG opens this. Degrading capability beats failing the
            # export, so the fallback is silent in the file and recorded in the
            # tag below.
            all_tags["COG"] = "false — COG driver unavailable, wrote tiled GTiff"
            cog = False

    _do_write(profile)

    # Only reached on the plain-GTiff path (either cog=False was requested, or
    # the COG driver was unavailable and we fell through). A COG already has its
    # overviews, built by the driver.
    if max(a.shape) > 1024:
        # Overviews for anything big enough that a viewer would otherwise
        # decimate it on the fly. Average resampling, not nearest: a decimated
        # depth field should show the mean depth of the cells it covers.
        from rasterio.enums import Resampling
        with rasterio.open(path, "r+") as dst:
            factors = [f for f in (2, 4, 8, 16) if max(a.shape) // f >= 256]
            if factors:
                dst.build_overviews(factors, Resampling.average)
                dst.update_tags(ns="rio_overview", resampling="average")
    return path


def raster_specs(summary) -> list[RasterSpec]:
    """
    The standard band set for a scenario, in the order a responder needs them.

    Arrival time comes first deliberately. It is the differentiating product, and
    a directory listing is a user interface.

    WHICH BANDS ARE MASKED OVER PRE-EXISTING WATER, AND WHY IT DIFFERS PER BAND
    --------------------------------------------------------------------------
    The solver records arrival time 0 for every cell already wet at t=0. In the
    band raster that is handled by the -2 sentinel, but a continuous float raster
    has no sentinel, so `arrival_time_min.tif` would hand anyone who opens it 0.0
    across the whole reservoir. Styled with the obvious "0 = most urgent" ramp,
    the lake becomes the most alarming thing on the map, and `min()` over the
    raster returns 0 — the same defect that made `first_arrival_minutes()` report
    "0 min after failure" before it was fixed, reappearing one layer down in a
    file that leaves the machine.

    So arrival time is masked to nodata there. Depth and speed are NOT: 40 m of
    reservoir is a true depth and a legitimate thing to render.

    The hazard bands are masked too, for a different reason — consistency. The
    hazard schemes have no notion of "already wet", and `vector.hazard_zones`
    already drops the reservoir from the polygons. An unmasked hazard raster
    would disagree with the Shapefile built from the same run, and a deliverable
    set whose own layers contradict each other is worse than one layer fewer.
    """
    specs = [
        RasterSpec(
            "arrival_time_min", summary.arrival.minutes, "float32",
            FLOAT_NODATA,
            "Minutes from failure until depth first exceeded "
            f"{summary.arrival.threshold_m:.2f} m. NODATA = water never "
            "arrived within the simulated period, OR the cell was already water "
            "before the failure (see arrival_band, value -2, to tell the two "
            "apart).",
            "minutes", "sequential blue, fastest darkest",
            mask_initially_wet=True),
        RasterSpec(
            "arrival_band", summary.arrival.band, "int16", INT_NODATA,
            "Isochrone band index. -1 never flooded, -2 already water before "
            "failure. Labels: " + ", ".join(
                f"{i}={lab}" for i, lab in enumerate(_band_labels(summary))),
            "class", "sequential blue"),
        RasterSpec(
            "max_depth_m", summary.max_depth, "float32", FLOAT_NODATA,
            "Maximum water depth reached at any time during the simulation. "
            "Includes pre-existing water bodies, whose depth is real — use "
            "arrival_band == -2 to exclude the reservoir.",
            "metres", "sequential blue"),
        RasterSpec(
            "max_speed_ms", summary.max_speed, "float32", FLOAT_NODATA,
            "Maximum flow speed reached at any time.", "m/s",
            "sequential viridis"),
        RasterSpec(
            "max_depth_velocity", summary.max_dv, "float32", FLOAT_NODATA,
            "Running maximum of depth x speed — the hazard product. NOT "
            "max_depth x max_speed, which multiplies two peaks occurring at "
            "different times and overstates hazard.",
            "m^2/s", "sequential"),
        RasterSpec(
            "hazard_rating", summary.hazard.rating, "float32", FLOAT_NODATA,
            "Defra/EA flood hazard rating HR = d(v + 0.5) + DF. NODATA over "
            "water that existed before the failure, matching hazard_zones.shp.",
            "HR", "yellow to dark red", mask_initially_wet=True),
        RasterSpec(
            "hazard_class_defra", summary.hazard.defra_class, "int16",
            INT_NODATA,
            "Defra hazard band. -1 dry or pre-existing water, 0=Low, "
            "1=Moderate, 2=Significant, 3=Extreme.", "class",
            "yellow to dark red", mask_initially_wet=True),
        RasterSpec(
            "hazard_class_aidr", summary.hazard.aidr_class, "int16", INT_NODATA,
            "AIDR combined hazard class. -1 dry or pre-existing water, "
            "0=H1 ... 5=H6.", "class", "yellow to dark red",
            mask_initially_wet=True),
    ]
    if summary.dem_valid_mask is not None:
        specs.append(RasterSpec(
            "dem_valid", np.asarray(summary.dem_valid_mask, dtype=np.int16),
            "int16", INT_NODATA,
            "1 where the DEM had real data, 0 where elevation was interpolated "
            "across a void. Depths over 0 cells are weaker evidence.",
            "flag", "binary"))
    return specs


def _band_labels(summary):
    from ..analysis.arrival import band_labels
    return band_labels(summary.arrival.bands_min)


def write_scenario_rasters(summary, out_dir, *, cog=True,
                           domain_mask=None) -> dict[str, Path]:
    """
    Write the full band set for a scenario. Returns {name: path}.

    `domain_mask` is True inside the computed domain. Cells outside it are
    written as nodata rather than zero, so "we did not model here" never renders
    as "we modelled here and found nothing" — the distinction that makes an
    inundation extent honest at its edges.
    """
    out_dir = Path(out_dir)
    written = {}
    initially_wet = summary.hazard.initially_wet
    if initially_wet is not None:
        initially_wet = np.asarray(initially_wet, dtype=bool)
    tags = {
        "RUN_ID": summary.run_id,
        "STUDY_AREA": summary.study_area,
        "SCENARIO": summary.scenario,
        "RESOLUTION_M": f"{summary.dx:g}",
        "SIMULATED_DURATION_S": f"{summary.duration_s:g}",
        "MASS_CONSERVATION_ERROR": f"{summary.volume_error:+.3e}",
        "PRESENTABLE_AS_FACT": str(summary.is_presentable()[0]),
        "UNVERIFIED_INPUT_COUNT": str(len(summary.unverified_inputs)),
    }

    for spec in raster_specs(summary):
        a = np.asarray(spec.array)
        if spec.mask_initially_wet and initially_wet is not None:
            a = np.where(initially_wet, spec.nodata, a)
        if domain_mask is not None:
            a = np.where(np.asarray(domain_mask, dtype=bool), a, spec.nodata)
        # Keys are filenames, not band names, so the returned manifest can be
        # zipped or served without the caller reconstructing extensions.
        written[f"{spec.name}.tif"] = _write(
            out_dir / f"{spec.name}.tif", a,
            transform=summary.transform, crs=summary.crs,
            dtype=spec.dtype, nodata=spec.nodata,
            tags={**tags, "UNITS": spec.units,
                  "COLOUR_RAMP": spec.colour_ramp,
                  "MASKED_OVER_PRE_EXISTING_WATER":
                      str(bool(spec.mask_initially_wet))},
            description=spec.description, cog=cog)
    return written


def write_qgis_style(spec: RasterSpec, path) -> Path:
    """
    Write a QGIS `.qml` layer style beside a class raster.

    Worth the twenty lines: a district GIS operator who opens
    `hazard_class_defra.tif` without a style sees a grey ramp from -1 to 3 and
    has to be told what the numbers mean. With the .qml alongside, QGIS loads
    the colours and the class names automatically and the map is legible on
    first open. This is the difference between shipping data and shipping a
    product.
    """
    from ..analysis.hazard import (AIDR_CLASSES, AIDR_CLASS_COLOURS,
                                  DEFRA_CLASS_COLOURS, DEFRA_CLASS_MEANING,
                                  DEFRA_CLASS_NAMES)
    from ..analysis.arrival import BAND_COLOURS

    if spec.name == "hazard_class_defra":
        entries = [(i, DEFRA_CLASS_COLOURS[i],
                    f"{DEFRA_CLASS_NAMES[i]} — {DEFRA_CLASS_MEANING[i]}")
                   for i in range(len(DEFRA_CLASS_NAMES))]
    elif spec.name == "hazard_class_aidr":
        entries = [(i, AIDR_CLASS_COLOURS[i], f"{c[0]} — {c[4]}")
                   for i, c in enumerate(AIDR_CLASSES)]
    elif spec.name == "arrival_band":
        labels = spec.description.split("Labels: ")[-1].split(", ")
        entries = [(i, BAND_COLOURS[i % len(BAND_COLOURS)],
                    lab.split("=", 1)[-1])
                   for i, lab in enumerate(labels)]
    else:
        raise ValueError(f"no discrete style defined for {spec.name!r}")

    items = "\n".join(
        f'          <paletteEntry value="{v}" color="{c}" label="{lab}" '
        f'alpha="255"/>' for v, c, lab in entries)
    qml = f"""<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="AllStyleCategories">
  <pipe>
    <rasterrenderer type="paletted" band="1" opacity="0.8" alphaBand="-1">
      <rasterTransparency/>
      <colorPalette>
{items}
      </colorPalette>
    </rasterrenderer>
  </pipe>
  <blendMode>0</blendMode>
</qgis>
"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(qml, encoding="utf-8")
    return path

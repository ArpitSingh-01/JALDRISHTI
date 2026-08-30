"""
Export — turning a `ScenarioSummary` into files a district office can use.

PS 26161 names its deliverable formats: GeoTIFF, Shapefile, KML. This package
produces those plus the two things that make them trustworthy rather than merely
openable — a provenance JSON recording every input and every unverified figure,
and a PDF briefing whose limitations page is page 2 rather than an appendix.

    raster.py     GeoTIFF / COG, one band per quantity, plus QGIS .qml styles
    vector.py     Shapefile (zipped) and KMZ — extent, isochrones, hazard zones
    metadata.py   provenance JSON, SHA-256 manifest, plain-text README
    report.py     the PDF, with an UNVERIFIED watermark when the gate says so

`write_all()` is the single entry point. It writes a complete, self-describing
run directory and returns the manifest of what it wrote.

WHY THE OUTPUT IS A DIRECTORY AND NOT A FILE
--------------------------------------------
A flood result is not one artefact. It is eight rasters, four vector layers in
two formats each, a PDF and its figures, and the record of how they were made.
Emitting them into one directory per run — with a MANIFEST that hashes every file
— means the whole thing can be zipped, emailed, and verified as a unit. Emitting
them individually invites the failure this project most needs to avoid: a depth
raster arriving somewhere without its caveats.

Nothing here is imported at module scope beyond the standard library and numpy.
rasterio, geopandas, simplekml, reportlab and matplotlib are all imported inside
the functions that use them, so `import jaldrishti.export` is cheap and the API
process does not pay for reportlab on startup.
"""

from __future__ import annotations

from pathlib import Path

from .metadata import (
    METADATA_SCHEMA_VERSION,
    MODEL_DISCLAIMER,
    SOLVER_ATTRIBUTION,
    build_metadata,
    environment_record,
    git_record,
    sha256_of,
    write_manifest,
    write_metadata,
    write_readme,
)
from .raster import (
    DEFAULT_TAGS,
    FLOAT_NODATA,
    INT_NODATA,
    RasterSpec,
    raster_specs,
    write_qgis_style,
    write_scenario_rasters,
)
from .report import (
    render_arrival_map,
    render_hazard_map,
    write_report,
)
from .vector import (
    KML_DISCLAIMER,
    arrival_isochrones,
    hazard_zones,
    inundation_extent,
    settlements_at_risk,
    write_kml,
    write_kmz,
    write_shapefile,
    write_scenario_vectors,
)

__all__ = [
    # raster
    "DEFAULT_TAGS", "FLOAT_NODATA", "INT_NODATA", "RasterSpec", "raster_specs",
    "write_qgis_style", "write_scenario_rasters",
    # vector
    "KML_DISCLAIMER", "arrival_isochrones", "hazard_zones",
    "inundation_extent", "settlements_at_risk", "write_kml", "write_kmz",
    "write_shapefile", "write_scenario_vectors",
    # metadata
    "METADATA_SCHEMA_VERSION", "MODEL_DISCLAIMER", "SOLVER_ATTRIBUTION",
    "build_metadata", "environment_record", "git_record", "sha256_of",
    "write_manifest", "write_metadata", "write_readme",
    # report
    "render_arrival_map", "render_hazard_map", "write_report",
    # bundle
    "write_all",
]


def write_all(summary, out_dir, *, settlements=None, cog=True,
              simplify_m=None, include_maps=True, hillshade=None,
              domain_mask=None, hash_files=True,
              extra_metadata=None) -> dict[str, Path]:
    """
    Write the complete deliverable set for one scenario. Returns {name: path}.

    Every key is the path of the file as actually written, relative to `out_dir`
    and POSIX-separated — `"arrival_time_min.tif"`, `"shapefile/hazard_zones_defra.zip"`.
    So the return value can be zipped, served or bundled directly, with no caller
    reconstructing extensions and no key that disagrees with what is on disk.

    Order matters and is not arbitrary:

      1. rasters, vectors, styles — the data;
      2. README and provenance JSON — how to read the data;
      3. PDF — the briefing, which reads the same `summary` and therefore cannot
         disagree with the data;
      4. MANIFEST last, because it hashes everything above it.

    A failure in any one stage is caught and recorded in the returned manifest
    under `errors` rather than aborting the export. A run that produces eight
    rasters and no PDF is still useful; a run that produces nothing because
    reportlab was unhappy is not.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    errors: dict[str, str] = {}

    def _stage(name, fn):
        try:
            result = fn()
        except Exception as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"
            return None
        return result

    rasters = _stage("rasters", lambda: write_scenario_rasters(
        summary, out_dir, cog=cog, domain_mask=domain_mask))
    if rasters:
        written.update(rasters)
        # QGIS styles for the three discrete rasters. Cheap, and the difference
        # between a legible map on first open and a grey ramp of integers.
        for spec in raster_specs(summary):
            if spec.name in ("hazard_class_defra", "hazard_class_aidr",
                             "arrival_band"):
                q = _stage(f"style:{spec.name}", lambda s=spec: write_qgis_style(
                    s, out_dir / f"{s.name}.qml"))
                if q:
                    written[f"{spec.name}.qml"] = q

    vectors = _stage("vectors", lambda: write_scenario_vectors(
        summary, out_dir, settlements=settlements, simplify_m=simplify_m))
    if vectors:
        written.update(vectors)

    r = _stage("readme", lambda: write_readme(summary, out_dir / "README.txt"))
    if r:
        written["README.txt"] = r

    m = _stage("metadata", lambda: write_metadata(
        summary, out_dir / "metadata.json", extra=extra_metadata))
    if m:
        written["metadata.json"] = m

    p = _stage("report", lambda: write_report(
        summary, out_dir / "report.pdf",
        figures_dir=out_dir / "figures", include_maps=include_maps,
        hillshade=hillshade))
    if p:
        written["report.pdf"] = p

    if errors:
        # Visible, in the run directory, next to the output it explains. An
        # export that partially failed must not look like one that succeeded.
        import json
        efile = out_dir / "EXPORT_ERRORS.json"
        efile.write_text(json.dumps(errors, indent=2), encoding="utf-8")
        written["EXPORT_ERRORS.json"] = efile

    man = _stage("manifest", lambda: write_manifest(
        out_dir, hash_files=hash_files))
    if man:
        written["MANIFEST.json"] = man

    return written

"""
Vector export — Shapefile and KML.

WHY BOTH, AND WHY THEY ARE NOT THE SAME FILE WITH A DIFFERENT EXTENSION
-----------------------------------------------------------------------
PS 26161 names Shapefile and KML explicitly. They serve different readers:

  * Shapefile is what a district GIS cell loads into QGIS/ArcGIS to intersect
    against its own ward boundaries, asset registers and voter rolls. It carries
    an attribute table, so it can be queried and joined.
  * KML is what a tehsildar with a laptop and no GIS training opens in Google
    Earth. It carries styling, so it draws itself correctly with no legend
    configuration.

The same geometry has to go out in both, and each format has a way of silently
corrupting it.

THE FOUR SILENT FAILURES THIS MODULE EXISTS TO PREVENT
-----------------------------------------------------
1. **Shapefile truncates attribute names to 10 characters.** The DBF format has
   no way to store a longer one. `population_at_risk` and `population_at_night`
   both become `population` — GDAL emits a warning to stderr that nobody reads
   and then writes one column where there were two. Every field written here has
   an explicit <=10 character name, and `_check_field_names` raises rather than
   letting the driver decide.

2. **KML is defined in WGS84 geographic coordinates only.** There is no CRS tag
   to set. Hand it a UTM easting of 500000 and Google Earth reads that as 500000
   degrees east, wraps it, and draws your flood somewhere in the Pacific. Every
   KML written here is reprojected to EPSG:4326 first, unconditionally, and the
   reprojection is asserted rather than assumed.

3. **KML colours are aabbggrr, not rrggbb.** Alpha first, then blue, green, red —
   the reverse of every other format. Pass a web hex straight through and the
   extreme-hazard dark red (#7f0000) renders as dark blue, which on a flood map
   reads as deep water rather than danger. `_kml_colour` does the swap.

4. **A <Folder> in a KML becomes a separate LAYER when the file is read back.**
   OGR maps one KML folder to one layer, so the natural-looking idea of grouping
   a multi-part band's pieces into a folder splits the file: single-part bands
   stay in the document root (the "default" layer) and every multi-part band
   becomes a layer of its own. `geopandas.read_file` then returns *only* the
   default layer and drops the rest, emitting nothing worse than a warning. The
   isochrone KMZ lost its ">120 min" band exactly this way. So `write_kml`
   writes ONE placemark per input row, always, using a <MultiGeometry> for
   multi-part geometry and never a folder — which makes "the KML has the same
   feature count as the GeoDataFrame" a property that can be, and is, tested.

WHY GEOMETRY IS NOT SMOOTHED
----------------------------
The polygons come from `rasterio.features.shapes`, which traces exact cell
boundaries, so they are blocky at 90 m or 30 m. That is honest: the model has no
sub-cell information and a smooth contour would imply it does. `simplify_m` is
available for cartographic output but defaults to off, and anything measured
(area, length) is computed before simplification.
"""

from __future__ import annotations

from pathlib import Path
import zipfile

import numpy as np

# Google Earth's own polygon fill is 50% by default and looks muddy over
# satellite imagery. 0.55 alpha keeps the terrain legible underneath while the
# extent still reads as a filled region.
KML_FILL_ALPHA = 0.55

# Shapefile DBF hard limit. Not a convention — the format cannot store more.
DBF_NAME_LIMIT = 10

# The disclaimer that travels inside every KML description balloon. A KML gets
# forwarded by email far more often than it gets opened next to its provenance
# JSON, so the caveat has to be in the file the user actually clicks.
KML_DISCLAIMER = (
    "JALDRISHTI simulation output — SIH 2026, PS 26161. This is a MODEL RESULT, "
    "not a survey and not an official flood hazard map. Arrival time is time "
    "from dam failure, NOT warning time. Cell resolution limits detail; "
    "see the accompanying provenance JSON for the full limitations list."
)


def _check_field_names(names) -> None:
    """
    Refuse to write a Shapefile whose field names the DBF format would mangle.

    GDAL's behaviour on an over-long name is to truncate and warn on stderr. In a
    pipeline that warning is invisible, and two fields that truncate to the same
    prefix collapse into one — losing a column without losing the file, which is
    the worst kind of failure because the output still looks valid.
    """
    bad = [n for n in names if n != "geometry" and len(n) > DBF_NAME_LIMIT]
    if bad:
        raise ValueError(
            f"Shapefile field name(s) exceed the {DBF_NAME_LIMIT}-character DBF "
            f"limit and would be silently truncated: {bad}. Rename them in the "
            f"layer builder, do not let the driver decide.")
    short = [n for n in names if n != "geometry"]
    dupes = {n for n in short if short.count(n) > 1}
    if dupes:
        raise ValueError(f"duplicate Shapefile field names: {sorted(dupes)}")


def _kml_colour(web_hex: str, alpha: float = 1.0) -> str:
    """
    Convert a web colour (#rrggbb) to KML's aabbggrr byte order.

    KML inherited its colour encoding from the original Keyhole binary format and
    it is little-endian: alpha, blue, green, red. Every other format the project
    touches — QGIS .qml, matplotlib, CSS, deck.gl — is rrggbb. Passing one
    straight through swaps red and blue, so #7f0000 (extreme hazard, dark red)
    renders as dark navy, which on a flood map reads as deep calm water. That is
    a legend inversion on the single most important class.
    """
    h = web_hex.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"expected #rrggbb, got {web_hex!r}")
    rr, gg, bb = h[0:2], h[2:4], h[4:6]
    aa = f"{int(round(max(0.0, min(1.0, alpha)) * 255)):02x}"
    return f"{aa}{bb}{gg}{rr}"


# --------------------------------------------------------------------------
# layer builders — geometry from rasters
# --------------------------------------------------------------------------
def _polygonise(mask, transform, crs, *, simplify_m=None):
    """Dissolve a boolean raster mask into a single (multi)polygon geometry."""
    from rasterio import features
    from shapely.geometry import shape
    from shapely.ops import unary_union

    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        return None
    geoms = [
        shape(g) for g, v in features.shapes(
            mask.astype(np.uint8), mask=mask, transform=transform) if v == 1
    ]
    if not geoms:
        return None
    merged = unary_union(geoms)
    if simplify_m:
        merged = merged.simplify(simplify_m, preserve_topology=True)
    return merged


def inundation_extent(summary, *, simplify_m=None):
    """
    The flood outline as a single feature — the layer most people will open first.

    Two rows, not one: the new inundation and the pre-existing water body. They
    are kept as separate features rather than merged because a single blue
    polygon covering reservoir and floodplain alike is exactly the misleading
    picture this project is trying not to produce. Anyone who wants the union can
    dissolve two rows; nobody can recover the split from one.
    """
    import geopandas as gpd

    rows = []
    new_geom = _polygonise(summary.new_flood_mask, summary.transform,
                           summary.crs, simplify_m=simplify_m)
    if new_geom is not None:
        rows.append({
            "kind": "new_flood",
            "label": "Newly inundated (caused by failure)",
            "area_km2": round(summary.flooded_area_km2, 4),
            "maxdepth_m": round(summary.peak_depth_m, 3),
            "maxspd_ms": round(summary.peak_speed_ms, 3),
            "geometry": new_geom,
        })

    iw = summary.hazard.initially_wet
    if iw is not None:
        pre_geom = _polygonise(iw, summary.transform, summary.crs,
                               simplify_m=simplify_m)
        if pre_geom is not None:
            n = int(np.asarray(iw, dtype=bool).sum())
            rows.append({
                "kind": "pre_water",
                "label": "Water present before failure (reservoir / channel)",
                "area_km2": round(n * summary.dx * summary.dx / 1.0e6, 4),
                "maxdepth_m": None,
                "maxspd_ms": None,
                "geometry": pre_geom,
            })

    gdf = gpd.GeoDataFrame(rows, crs=summary.crs)
    _check_field_names(list(gdf.columns))
    return gdf


def hazard_zones(summary, *, scheme="defra", simplify_m=None):
    """One polygon per hazard class, with the published plain-language meaning."""
    import geopandas as gpd

    from ..analysis.hazard import (AIDR_CLASSES, AIDR_CLASS_COLOURS,
                                   DEFRA_CLASS_COLOURS, DEFRA_CLASS_MEANING,
                                   DEFRA_CLASS_NAMES)

    if scheme == "defra":
        raster = summary.hazard.defra_class
        names = list(DEFRA_CLASS_NAMES)
        meanings = list(DEFRA_CLASS_MEANING)
        colours = list(DEFRA_CLASS_COLOURS)
    elif scheme == "aidr":
        raster = summary.hazard.aidr_class
        names = [c[0] for c in AIDR_CLASSES]
        meanings = [c[4] for c in AIDR_CLASSES]
        colours = list(AIDR_CLASS_COLOURS)
    else:
        raise ValueError(f"unknown hazard scheme {scheme!r}")

    raster = np.asarray(raster)
    iw = summary.hazard.initially_wet
    pre = np.asarray(iw, dtype=bool) if iw is not None else None

    rows = []
    for idx, name in enumerate(names):
        mask = raster == idx
        if pre is not None:
            # Hazard over the reservoir surface is not a hazard to anybody: it
            # was water before the failure and nobody was standing in it. Left
            # in, the deepest class is dominated by the lake and the legend
            # implies the reservoir is the most dangerous place in the domain.
            mask = mask & ~pre
        geom = _polygonise(mask, summary.transform, summary.crs,
                           simplify_m=simplify_m)
        if geom is None:
            continue
        rows.append({
            "class_id": idx,
            "class_name": name,
            "meaning": meanings[idx][:254],
            "colour": colours[idx],
            "area_km2": round(int(mask.sum()) * summary.dx * summary.dx / 1e6, 4),
            "geometry": geom,
        })

    gdf = gpd.GeoDataFrame(rows, crs=summary.crs)
    _check_field_names(list(gdf.columns))
    return gdf


def arrival_isochrones(summary, *, simplify_m=None):
    """
    The isochrone bands — the layer this platform is actually for.

    Field names are pre-shortened for the DBF: `min_min` / `max_min` rather than
    `minimum_minutes`. Ugly, and unavoidable at 10 characters.
    """
    from ..analysis.arrival import BAND_COLOURS, band_labels, isochrone_polygons

    gdf = isochrone_polygons(summary.arrival.band, summary.transform,
                             summary.crs, summary.arrival.bands_min,
                             simplify_m=simplify_m)

    if len(gdf):
        labels = band_labels(summary.arrival.bands_min)
        gdf = gdf.rename(columns={"min_minutes": "min_min",
                                  "max_minutes": "max_min"})
        gdf["colour"] = [BAND_COLOURS[int(b) % len(BAND_COLOURS)]
                         for b in gdf["band"]]
        gdf["action"] = [_evacuation_action(int(b), labels) for b in gdf["band"]]
        # max_min is +inf for the final open-ended band. Shapefile's DBF cannot
        # represent infinity; it writes it as a huge float or as 0 depending on
        # the driver. -1 is used as the documented "no upper bound" sentinel.
        gdf["max_min"] = [(-1.0 if not np.isfinite(v) else float(v))
                          for v in gdf["max_min"]]
        gdf["area_km2"] = gdf["area_km2"].round(4)
    _check_field_names(list(gdf.columns))
    return gdf


def _evacuation_action(band, labels):
    """
    The operational reading of each isochrone band.

    This is the sentence a district officer needs and the model cannot supply on
    its own: the bands were chosen (see `arrival.DEFAULT_BANDS_MIN`) to match
    these actions, so the mapping belongs beside them rather than in a slide.
    Truncated to 254 characters for the DBF.
    """
    table = {
        0: "No time to move — vertical evacuation in place only",
        1: "On foot, immediate neighbourhood only",
        2: "Organised movement with vehicles feasible",
        3: "Full planned evacuation of settlement feasible",
    }
    return table.get(band, "Beyond the last isochrone — lowest priority")[:254]


def settlements_at_risk(summary, settlements, *, name_field="name"):
    """
    Point layer: one row per settlement, with arrival time and hazard class.

    This is the table that turns a raster into an order. Settlements the water
    never reaches are KEPT, with arrival -1, because a village missing from the
    list looks like an oversight whereas "not reached in this scenario" is
    information a planner can act on.
    """
    import geopandas as gpd
    from rasterio.transform import rowcol

    gdf = settlements.to_crs(summary.crs).copy()
    xs = gdf.geometry.x.to_numpy()
    ys = gdf.geometry.y.to_numpy()
    rows, cols = rowcol(summary.transform, xs, ys)
    rows = np.clip(np.asarray(rows), 0, summary.shape[0] - 1)
    cols = np.clip(np.asarray(cols), 0, summary.shape[1] - 1)

    arr = summary.arrival.minutes[rows, cols]
    newly = summary.new_flood_mask[rows, cols]
    # A settlement centroid inside the reservoir footprint has arrival 0, which
    # is not an arrival. Only newly-flooded cells get a time.
    arrival = np.where(newly & np.isfinite(arr), arr, -1.0)

    if name_field in gdf.columns:
        names = [str(v)[:60] for v in gdf[name_field]]
    else:
        # Unnamed settlements still have to appear — a point with a location and
        # an arrival time is actionable even without a gazetteer name, and
        # dropping it would understate exposure.
        names = [f"unnamed_{i}" for i in range(len(gdf))]

    out = gpd.GeoDataFrame({
        "name": names,
        "arr_min": np.round(arrival, 1),
        "flooded": newly.astype(np.int16),
        "depth_m": np.round(np.where(newly, summary.max_depth[rows, cols],
                                     0.0), 2),
        "speed_ms": np.round(np.where(newly, summary.max_speed[rows, cols],
                                      0.0), 2),
        "haz_class": np.where(newly, summary.hazard.defra_class[rows, cols],
                              -1).astype(np.int16),
        "band": np.where(newly, summary.arrival.band[rows, cols],
                         -1).astype(np.int16),
        "geometry": gdf.geometry.values,
    }, crs=summary.crs)
    if "population" in gdf.columns:
        out["pop"] = gdf["population"].to_numpy()
    _check_field_names(list(out.columns))
    # Sorted by urgency: the top of the file is the top of the response
    # priority list. -1 (never reached) sorts last, not first.
    key = np.where(out["arr_min"] < 0, np.inf, out["arr_min"])
    return out.iloc[np.argsort(key, kind="stable")].reset_index(drop=True)


# --------------------------------------------------------------------------
# writers
# --------------------------------------------------------------------------
def write_shapefile(gdf, path, *, zip_it=True) -> Path:
    """
    Write one Shapefile, optionally zipped.

    A "Shapefile" is at minimum four files — .shp geometry, .shx index, .dbf
    attributes, .prj coordinate system — and loses its coordinate system the
    moment someone emails the .shp alone. That happens constantly. Zipping by
    default makes the set atomic; QGIS and ArcGIS both open a zipped Shapefile
    directly.

    When zipping, the loose sidecars are REMOVED once they are safely inside the
    archive. Leaving them defeats the point: "atomic" is not true if an openable
    loose copy is sitting in the same directory, where it can be picked up
    instead of the zip and then drift away from it. It also doubles the size of
    the vector output, and the loose files evade the `*.zip` ignore rule so a
    run directory leaks its Shapefiles into version control. `write_kmz` has
    always unlinked its intermediate .kml; this is the same contract.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not len(gdf):
        # An empty Shapefile is a valid and meaningful artefact — "we looked and
        # this class does not occur" — but most drivers refuse to infer a
        # geometry type from zero rows. Skip rather than crash the export, and
        # let the caller see the missing entry in the returned manifest.
        return None
    _check_field_names(list(gdf.columns))
    gdf.to_file(path, driver="ESRI Shapefile", engine="pyogrio")

    if not zip_it:
        return path
    zpath = path.with_suffix(".zip")
    packed = []
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
            side = path.with_suffix(ext)
            if side.exists():
                zf.write(side, side.name)
                packed.append(side)
    # Only after the archive is closed and flushed, and only the files actually
    # written into it. If zipping raised, the exception propagates with every
    # sidecar still on disk — losing the data would be far worse than leaving a
    # partial export to be diagnosed.
    for side in packed:
        side.unlink()
    return zpath


def write_kml(gdf, path, *, name, colour_field="colour", label_field="label",
              description_fields=(), fill_alpha=KML_FILL_ALPHA,
              extrude_field=None) -> Path:
    """
    Write a styled KML — one placemark per input row.

    Reprojects to EPSG:4326 unconditionally. KML has no CRS declaration — the
    specification fixes it at WGS84 geographic — so a projected geometry written
    verbatim is not "wrong CRS", it is nonsense coordinates that Google Earth
    still renders, somewhere in the ocean, without complaint.

    Multi-part geometry becomes a <MultiGeometry> in a single placemark, never a
    <Folder>. OGR reads one folder as one layer, which splits the file and costs
    a reader every band that is not in the default layer. The row-for-row
    invariant is what makes the KML comparable to the Shapefile written from the
    same GeoDataFrame.
    """
    import simplekml

    gdf = gdf.to_crs("EPSG:4326")
    # Assert rather than trust: a GeoDataFrame with crs=None passes through
    # `to_crs` unchanged in some geopandas versions instead of raising, and the
    # failure downstream is a map of the Gulf of Guinea.
    xmin, ymin, xmax, ymax = gdf.total_bounds
    if not (-180.0 <= xmin <= 180.0 and -90.0 <= ymin <= 90.0
            and -180.0 <= xmax <= 180.0 and -90.0 <= ymax <= 90.0):
        raise ValueError(
            f"KML geometry is not in geographic coordinates "
            f"(bounds {xmin:.1f},{ymin:.1f},{xmax:.1f},{ymax:.1f}). KML is "
            f"WGS84-only; check the source CRS is set.")

    kml = simplekml.Kml(name=name)
    kml.document.description = KML_DISCLAIMER

    for _, row in gdf.iterrows():
        label = str(row.get(label_field, name))
        desc_parts = [f"{f}: {row[f]}" for f in description_fields
                      if f in row and row[f] is not None]
        desc_parts.append("")
        desc_parts.append(KML_DISCLAIMER)
        desc = "\n".join(desc_parts)
        web = row.get(colour_field, "#2171b5") if colour_field else "#2171b5"

        geom = row.geometry
        if geom is None or geom.is_empty:
            continue

        if geom.geom_type == "Point":
            pnt = kml.newpoint(name=label, description=desc,
                               coords=[(geom.x, geom.y)])
            pnt.style.iconstyle.color = _kml_colour(web, 1.0)
            pnt.style.labelstyle.scale = 0.8
            continue

        polys = [g for g in (geom.geoms if geom.geom_type.startswith("Multi")
                             else [geom])
                 if g is not None and not g.is_empty]
        if not polys:
            continue

        # ONE placemark per input row, always. A multi-part band goes into a
        # <MultiGeometry> inside that single placemark, NOT into a <Folder>:
        # OGR maps every folder to a separate layer, so a folder here means
        # `read_file` silently returns only the default layer and drops whole
        # bands. See failure 4 in the module docstring.
        multi = len(polys) > 1
        if multi:
            holder = kml.newmultigeometry(name=label, description=desc)
            sub_kw: dict = {}
        else:
            holder = kml
            sub_kw = {"name": label, "description": desc}

        made = []
        for poly in polys:
            if poly.geom_type in ("LineString", "LinearRing"):
                made.append(holder.newlinestring(
                    coords=list(poly.coords), **sub_kw))
                continue
            pol = holder.newpolygon(
                outerboundaryis=list(poly.exterior.coords),
                innerboundaryis=[list(r.coords) for r in poly.interiors],
                **sub_kw)
            if extrude_field and row.get(extrude_field):
                # Extruding by depth gives Google Earth a 3D water column, which
                # is the single most legible way to show depth to a
                # non-technical viewer. Clamped so a bad value cannot produce a
                # kilometre-high wall.
                pol.extrude = 1
                pol.altitudemode = simplekml.AltitudeMode.relativetoground
                h = float(min(max(row[extrude_field], 0.0), 200.0))
                pol.outerboundaryis = [
                    (x, y, h) for x, y, *_ in poly.exterior.coords]
            made.append(pol)

        # Style once at the placemark level for a MultiGeometry — styling each
        # child instead would emit a duplicate <Style> block per part, bloating
        # the file that KMZ exists to keep small.
        lines_only = all(o.__class__.__name__ == "LineString" for o in made)
        for obj in ([holder] if multi else made):
            obj.style.linestyle.color = _kml_colour(web, 1.0)
            obj.style.linestyle.width = 2 if lines_only else 1
            if not lines_only:
                obj.style.polystyle.color = _kml_colour(web, fill_alpha)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    kml.save(str(path))
    return path


def write_kmz(gdf, path, **kwargs) -> Path:
    """
    KMZ — a zipped KML. Same content, roughly a tenth the size.

    Matters for email: a 30 m Tehri isochrone KML runs to tens of megabytes of
    coordinate text and bounces off government mail servers with attachment
    limits. KMZ is what actually gets delivered.
    """
    path = Path(path)
    tmp = path.with_suffix(".kml")
    write_kml(gdf, tmp, **kwargs)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(tmp, "doc.kml")
    tmp.unlink()
    return path


def write_scenario_vectors(summary, out_dir, *, settlements=None,
                           simplify_m=None, kmz=True) -> dict[str, Path]:
    """
    Write the whole vector deliverable set. Returns {relative path: path}.

    Every layer goes out in both formats. The Shapefile is for the GIS cell, the
    KML for everyone else, and neither is treated as the authoritative one.

    Keys are the path each file was actually written to, relative to `out_dir` —
    NOT `f"{layer}.shp"`. A Shapefile is six sidecar files, so `write_shapefile`
    zips it by default and returns a `.zip`; a key that hardcoded `.shp` would
    name a zip archive `inundation_extent.shp`, and a caller that trusted the key
    to serve or bundle the file would hand a district GIS cell something no GIS
    will open. Deriving the key from the returned path also survives `zip=False`,
    where `.shp` is once again correct, without a second branch to keep in sync.
    """
    out_dir = Path(out_dir)
    shp_dir = out_dir / "shapefile"
    kml_dir = out_dir / "kml"
    written: dict[str, Path] = {}

    def _key(p: Path) -> str:
        return p.relative_to(out_dir).as_posix()

    layers = [
        ("inundation_extent", inundation_extent(summary, simplify_m=simplify_m),
         "kind", ("area_km2", "maxdepth_m", "maxspd_ms"), "maxdepth_m"),
        ("arrival_isochrones", arrival_isochrones(summary,
                                                  simplify_m=simplify_m),
         "label", ("min_min", "max_min", "area_km2", "action"), None),
        ("hazard_zones_defra", hazard_zones(summary, scheme="defra",
                                            simplify_m=simplify_m),
         "class_name", ("meaning", "area_km2"), None),
        ("hazard_zones_aidr", hazard_zones(summary, scheme="aidr",
                                           simplify_m=simplify_m),
         "class_name", ("meaning", "area_km2"), None),
    ]
    if settlements is not None and len(settlements):
        layers.append(
            ("settlements_at_risk", settlements_at_risk(summary, settlements),
             "name", ("arr_min", "depth_m", "speed_ms", "haz_class"), None))

    for layer_name, gdf, label_field, desc_fields, extrude in layers:
        if gdf is None or not len(gdf):
            continue
        # Colour is a KML styling attribute, not data. It is dropped from the
        # Shapefile so the attribute table stays a table of measurements.
        shp_gdf = gdf.drop(columns=[c for c in ("colour",) if c in gdf.columns])
        p = write_shapefile(shp_gdf, shp_dir / f"{layer_name}.shp")
        if p is not None:
            written[_key(p)] = p

        kml_kw = dict(name=f"{summary.study_area} — {layer_name}",
                      label_field=label_field,
                      description_fields=desc_fields,
                      colour_field="colour" if "colour" in gdf.columns else None,
                      extrude_field=extrude)
        if kmz:
            k = write_kmz(gdf, kml_dir / f"{layer_name}.kmz", **kml_kw)
        else:
            k = write_kml(gdf, kml_dir / f"{layer_name}.kml", **kml_kw)
        written[_key(k)] = k

    return written

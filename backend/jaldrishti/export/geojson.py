"""
GeoJSON views over a run bundle, for the dashboard's map layer.

Two derivations, both read REAL run artefacts — nothing here is mock data:

1. ISOCHRONES. The bundle's `arrival_band.tif` is a categorical raster of
   arrival bands (0 = dry/never, 1..5 = the bands in the metadata's
   `area_by_arrival_band_km2` keys, in order). Polygonising it gives the
   isochrone map: "floodwater arrived here within 15 minutes," etc. This is
   the SAME raster the KMZ exporter uses, so the map and the KML deliverable
   can never disagree.

2. SETTLEMENTS AT RISK. The named downstream points of interest configured
   for the study area (real villages and projects — Koteshwar, Devprayag,
   Rishikesh, Haridwar for Tehri; Raini, Tapovan, Joshimath for Chamoli),
   with arrival time / peak depth / speed SAMPLED from the bundle's rasters
   at each point's cell. The names are geography; the numbers are the model.
   A settlement the wave never reaches reports arrival = null — shown, not
   hidden, because "never arrived" is itself a response-relevant answer.

Both outputs are reprojected to WGS84 (EPSG:4326) because the browser map
works in lon/lat; the run rasters live in the study area's UTM frame.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

BAND_LABELS_DEFAULT = ["0-15 min", "15-30 min", "30-60 min", "60-120 min",
                       ">120 min"]


def _grid_from_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    grid = meta["scenario"]["grid"]
    return {
        "crs": grid["crs"],
        "dx_m": float(grid["dx_m"]),
        "shape": tuple(grid["shape"]),
        # GDAL-style affine: [a, b, c(x0), d, e, f(y0)] as stored by the
        # export writer. rasterio wants (a, b, c, d, e, f) with e NEGATIVE
        # row step; the stored transform is the rasterio Affine tuple already.
        "transform": tuple(grid["transform"]),
    }


def _to_4326(geom: dict, src_crs: str) -> dict:
    from rasterio.warp import transform_geom

    return transform_geom(src_crs, "EPSG:4326", geom)


def isochrones_fc(bundle: Path) -> dict[str, Any]:
    """
    Polygonise arrival_band.tif into a WGS84 FeatureCollection of isochrone
    polygons, labelled by their arrival band. Raises FileNotFoundError when
    the bundle lacks the raster (e.g. a setup-only run).
    """
    import rasterio
    from rasterio import features
    import shapely.geometry as sgeom

    tif = Path(bundle) / "arrival_band.tif"
    if not tif.is_file():
        raise FileNotFoundError(f"no arrival_band.tif in {bundle}")
    meta_path = Path(bundle) / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    grid = _grid_from_metadata(meta)
    labels = list(
        meta["scenario"]["results"].get("area_by_arrival_band_km2", {}).keys()
    ) or BAND_LABELS_DEFAULT

    with rasterio.open(tif) as src:
        band = src.read(1)
        transform = src.transform
        crs = src.crs

    features_out: list[dict] = []
    for value in sorted(set(np.unique(band)) - {0}):
        mask = band == value
        if not mask.any():
            continue
        label = labels[int(value) - 1] if int(value) - 1 < len(labels) \
            else f"band {int(value)}"
        shapes = features.shapes(
            mask.astype(np.uint8), mask=mask, transform=transform)
        for geom, _val in shapes:
            poly = sgeom.shape(geom)
            # Simplify at half a cell so the browser gets a lean payload
            # without changing what the raster says.
            poly = poly.simplify(grid["dx_m"] / 2.0, preserve_topology=True)
            if poly.is_empty:
                continue
            features_out.append({
                "type": "Feature",
                "properties": {"band": int(value), "label": label},
                "geometry": _to_4326(poly.__geo_interface__, str(crs)),
            })

    return {"type": "FeatureCollection", "features": features_out}


def settlements_fc(bundle: Path, area: Any) -> dict[str, Any]:
    """
    Named downstream settlements with modelled arrival/depth/speed sampled
    from the bundle rasters. `area` is the StudyArea from config (its
    `downstream` POIs are the source of names and coordinates).
    """
    import rasterio
    from pyproj import Transformer

    bundle = Path(bundle)
    meta = json.loads((bundle / "metadata.json").read_text(encoding="utf-8"))
    grid = _grid_from_metadata(meta)

    rasters = {}
    for name in ("arrival_time_min", "max_depth_m", "max_speed_ms"):
        p = bundle / f"{name}.tif"
        if p.is_file():
            rasters[name] = rasterio.open(p)

    to_utm = Transformer.from_crs("EPSG:4326", grid["crs"], always_xy=True)

    features_out: list[dict] = []
    for poi in getattr(area, "downstream", []) or []:
        xm, ym = to_utm.transform(poi.lon, poi.lat)

        props: dict[str, Any] = {
            "name": poi.name,
            "kind": getattr(poi, "kind", "settlement"),
            "flooded": False,
            "arr_min": None,
            "depth_m": None,
            "speed_ms": None,
        }
        if "arrival_time_min" in rasters:
            src = rasters["arrival_time_min"]
            row, col = (int(v) for v in src.index(xm, ym))
            if 0 <= row < src.height and 0 <= col < src.width:
                arr = float(src.read(1)[row, col])
                # nodata / never-arrived convention: negative in the raster
                if arr >= 0:
                    props["flooded"] = True
                    props["arr_min"] = round(arr, 1)
                    if "max_depth_m" in rasters:
                        dsrc = rasters["max_depth_m"]
                        drow, dcol = (int(v) for v in dsrc.index(xm, ym))
                        if 0 <= drow < dsrc.height and 0 <= dcol < dsrc.width:
                            d = float(dsrc.read(1)[drow, dcol])
                            props["depth_m"] = round(d, 2) if d > 0 else None
                    if "max_speed_ms" in rasters:
                        ssrc = rasters["max_speed_ms"]
                        srow, scol = (int(v) for v in ssrc.index(xm, ym))
                        if 0 <= srow < ssrc.height and 0 <= scol < ssrc.width:
                            s = float(ssrc.read(1)[srow, scol])
                            props["speed_ms"] = round(s, 2) if s > 0 else None
        features_out.append({
            "type": "Feature",
            "properties": props,
            "geometry": {"type": "Point",
                         "coordinates": [float(poi.lon), float(poi.lat)]},
        })

    for r in rasters.values():
        r.close()
    return {"type": "FeatureCollection", "features": features_out}

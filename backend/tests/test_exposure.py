"""
Population resampling must conserve people, and the conservation CHECK must
measure against the right baseline.

`resample_population` is the headline pipeline — the exposure count comes straight
out of it. An earlier version compared the resampled domain total against a padded
read window in the SOURCE CRS. That window overcounts the source by ~30% at Tehri
(padding + a rotated-UTM footprint whose lat/lon bounding box is larger than the
ground the model spans), so a perfectly conserving resample reported a spurious
23% "loss" and was gated non-presentable. These tests lock in the fix: the residual
is measured against the source population INSIDE the destination footprint, and a
genuinely conserving resample reads as conserved.

Note on tolerances: the footprint baseline is itself computed by reprojecting a
domain indicator back onto the source grid, so it carries a perimeter-scaled edge
error. On the real Tehri grid (649x704) that is -0.4%; on the deliberately tiny
synthetic grids here it is 1-2%. The rigorous conservation proof in each test is
therefore `pop.sum() == expected` (the forward operator is exact for a uniform
density); the residual_fraction assertions only confirm the report's own flag.
"""
from __future__ import annotations

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds

from jaldrishti.analysis.exposure import resample_population

UTM44N = "EPSG:32644"
WGS84 = "EPSG:4326"


def _write_raster(path, data, transform, crs):
    data = np.asarray(data, dtype=np.float32)
    with rasterio.open(
        path, "w", driver="GTiff",
        height=data.shape[0], width=data.shape[1], count=1,
        dtype="float32", transform=transform, crs=crs, nodata=-99999.0,
    ) as dst:
        dst.write(data, 1)


def test_resample_conserves_utm_to_utm(tmp_path):
    # Uniform counts on a 30 m UTM grid downsampled to 90 m — the real WorldPop
    # regime (source finer than the model grid). Equal-area cells give a uniform
    # density, for which area-average reprojection is exact, so the forward
    # operator conserves people to machine precision. The footprint baseline
    # carries ~1% edge noise on a grid this small, so residual_fraction is only
    # asserted under the 2% operating tolerance.
    src = tmp_path / "pop_utm.tif"
    ny, nx = 300, 300
    counts = np.full((ny, nx), 5.0, dtype=np.float32)
    src_dx = 30.0
    ox, oy = 300_000.0, 3_360_000.0
    _write_raster(src, counts, from_origin(ox, oy, src_dx, src_dx), UTM44N)

    # dst 90 m grid fully inside the source extent
    dst_dx = 90.0
    dny, dnx = 50, 60
    dst_transform = from_origin(ox + 1_000.0, oy - 1_000.0, dst_dx, dst_dx)

    pop, rep = resample_population(
        src, dst_transform=dst_transform, dst_crs=UTM44N,
        dst_shape=(dny, dnx), dst_dx=dst_dx)

    # rigorous conservation: dst fully inside a uniform source, so the grid holds
    # 5 people / 30 m cell rescaled to the 90 m cell area, exactly.
    expected = (5.0 / (src_dx ** 2)) * (dst_dx ** 2) * dny * dnx
    assert pop.sum() == pytest.approx(expected, rel=0.005)

    assert rep["conserved"] is True
    assert abs(rep["residual_fraction"]) < 0.02

    # the footprint baseline must never exceed the raw padded window — the
    # padded window is a superset of the domain footprint by construction.
    assert rep["source_total"] <= rep["source_total_raw_window"] + 1e-6


def test_resample_conserves_geographic_to_utm(tmp_path):
    # Geographic source (cell area varies with latitude) -> UTM. Exercises the
    # cos(lat) area path and the cross-CRS footprint coverage. Uniform counts
    # here mean a NON-uniform density, so a few percent of edge interpolation
    # error is expected on a small grid; the point is that it conserves.
    src = tmp_path / "pop_geo.tif"
    ny, nx = 120, 120
    counts = np.full((ny, nx), 8.0, dtype=np.float32)
    res = 3.0 / 3600.0  # 3 arcsec, ~80-90 m at this latitude
    west, north = 78.30, 30.55
    _write_raster(src, counts, from_origin(west, north, res, res), WGS84)

    # derive a UTM dst box from a sub-window well inside the source footprint
    dst_dx = 90.0
    sub_w, sub_e = west + 20 * res, west + 90 * res
    sub_s, sub_n = north - 90 * res, north - 20 * res
    umin, vmin, umax, vmax = transform_bounds(
        WGS84, UTM44N, sub_w, sub_s, sub_e, sub_n)
    dnx = int((umax - umin) // dst_dx)
    dny = int((vmax - vmin) // dst_dx)
    assert dnx > 0 and dny > 0
    dst_transform = from_origin(umin, vmin + dny * dst_dx, dst_dx, dst_dx)

    pop, rep = resample_population(
        src, dst_transform=dst_transform, dst_crs=UTM44N,
        dst_shape=(dny, dnx), dst_dx=dst_dx, tolerance=0.05)

    assert rep["source_is_geographic"] is True
    assert rep["conserved"] is True
    assert abs(rep["residual_fraction"]) < 0.05
    assert pop.sum() > 0.0


def test_padded_window_would_overstate_the_loss(tmp_path):
    # Regression guard for the actual bug: a dst grid that sits deep in the
    # interior of a fully-populated source. The raw padded window necessarily
    # holds far more people than the domain footprint, so had we kept comparing
    # against it the residual would read ~-50% even though the resample conserves.
    src = tmp_path / "pop_pad.tif"
    ny, nx = 300, 300
    counts = np.full((ny, nx), 3.0, dtype=np.float32)
    src_dx = 30.0
    ox, oy = 300_000.0, 3_400_000.0
    _write_raster(src, counts, from_origin(ox, oy, src_dx, src_dx), UTM44N)

    # a small 30x30 @ 90 m window (2.7 km) deep inside the source. The tiny grid
    # maximises the raw-window overcount (the point of the test) but also pushes
    # the footprint baseline's edge noise to ~2%, so we run at the 3% tolerance.
    dst_dx = 90.0
    dny, dnx = 30, 30
    dst_transform = from_origin(ox + 5_000.0, oy - 5_000.0, dst_dx, dst_dx)

    pop, rep = resample_population(
        src, dst_transform=dst_transform, dst_crs=UTM44N,
        dst_shape=(dny, dnx), dst_dx=dst_dx, tolerance=0.03)

    # forward operator is exact regardless of the baseline: uniform density.
    expected = (3.0 / (src_dx ** 2)) * (dst_dx ** 2) * dny * dnx
    assert pop.sum() == pytest.approx(expected, rel=0.01)

    assert rep["conserved"] is True

    # the raw window carries far more people than the footprint here...
    raw_residual = ((rep["resampled_total"] - rep["source_total_raw_window"])
                    / rep["source_total_raw_window"])
    assert raw_residual < -0.3
    # ...but the footprint-based residual, the one that gates presentation, is
    # an order of magnitude smaller.
    assert abs(rep["residual_fraction"]) < abs(raw_residual) / 5

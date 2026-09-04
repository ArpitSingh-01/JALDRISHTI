"""
Diagnose the population-resampling residual for the Tehri 90 m run.

resample_population() reported residual -23.1% / conserved=false. How much of that
is a real Resampling.average mass loss, and how much is an artifact of comparing
the DOMAIN against a source total taken over a PADDED window (+20 source pixels)?

This reads the destination grid straight from the run's max_depth GeoTIFF (its
exact transform / CRS / shape) and the WorldPop raster, then tries several
resampling strategies. For each it prints the resampled total and the residual
against BOTH the padded source window (what the code compares to now) and the
tight domain window. No solver, no JIT — just rasterio.

    conda run -n jaldrishti python scripts/diag_resample.py
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio import Affine
from rasterio.transform import array_bounds
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.windows import Window, from_bounds

ROOT = Path(__file__).resolve().parents[1]          # backend/
PROJ = ROOT.parent                                  # project root
DST_TIF = PROJ / "outputs/runs/tehri_90m_20260902T041110Z/max_depth_m.tif"
POP = PROJ / "data/population/ind_ppp_2020_constrained.tif"

EARTH_R = 6_371_008.8


def geo_cell_area(lats, rx, ry):
    lat = np.asarray(lats, dtype=np.float64)
    half = 0.5 * ry
    top = np.radians(lat + half)
    bot = np.radians(lat - half)
    dlon = math.radians(abs(rx))
    return EARTH_R ** 2 * dlon * np.abs(np.sin(top) - np.sin(bot))


def read_counts_density(win, src):
    counts = src.read(1, window=win, masked=True).filled(0.0)
    counts = np.asarray(counts, dtype=np.float64)
    counts = np.where(counts < 0.0, 0.0, counts)
    wt = src.window_transform(win)
    rx, ry = src.transform.a, -src.transform.e
    if bool(getattr(src.crs, "is_geographic", False)):
        rows = np.arange(counts.shape[0])
        lats = wt.f + (rows + 0.5) * wt.e
        area = geo_cell_area(lats, rx, ry)[:, None]
    else:
        area = np.full((1, 1), abs(rx) * abs(ry))
    return counts, counts / area, wt


def reproj_density(density, wt, src_crs, dst_transform, dst_crs, shape, how):
    out = np.zeros(shape, dtype=np.float64)
    reproject(
        source=density, destination=out,
        src_transform=wt, src_crs=src_crs,
        dst_transform=dst_transform, dst_crs=dst_crs,
        resampling=how, src_nodata=None, dst_nodata=None,
    )
    return out


def main():
    with rasterio.open(DST_TIF) as d:
        dst_transform = d.transform
        dst_crs = d.crs
        ny, nx = d.height, d.width
        dst_dx = abs(d.transform.a)
    dst_shape = (ny, nx)
    dst_area = float(dst_dx) ** 2
    dst_bounds = array_bounds(ny, nx, dst_transform)
    print(f"dst grid {nx} x {ny} @ {dst_dx:g} m   {dst_crs}")

    with rasterio.open(POP) as src:
        src_crs = src.crs
        w, s, e, n = transform_bounds(dst_crs, src_crs, *dst_bounds,
                                      densify_pts=21)
        tight = from_bounds(w, s, e, n, transform=src.transform)
        tight = tight.round_offsets().round_lengths()
        tight = tight.intersection(Window(0, 0, src.width, src.height))

        pad = 20 * max(abs(src.res[0]), abs(src.res[1]))
        padded = from_bounds(w - pad, s - pad, e + pad, n + pad,
                             transform=src.transform)
        padded = padded.round_offsets().round_lengths()
        padded = padded.intersection(Window(0, 0, src.width, src.height))

        c_tight, _, _ = read_counts_density(tight, src)
        src_tight = float(c_tight.sum())
        _, density_p, wt_p = read_counts_density(padded, src)
        c_pad, _, _ = read_counts_density(padded, src)
        src_pad = float(c_pad.sum())
        srx = abs(src.res[0])

    print(f"source total  padded window : {src_pad:>12,.0f}")
    print(f"source total  tight  window : {src_tight:>12,.0f}")
    print(f"  padding inflates the source baseline by "
          f"{100.0 * (src_pad - src_tight) / src_tight:+.1f}%")
    print(f"  effective source cell ~ {srx * 111_320 * math.cos(math.radians(30.4)):.1f} m "
          f"E-W  (dst {dst_dx:g} m)")
    print()
    print(f"{'strategy':40s} {'total':>12s}  {'vs padded':>10s}  {'vs tight':>10s}")

    def report(name, grid):
        tot = float(grid.sum())
        print(f"{name:40s} {tot:>12,.0f}  "
              f"{(tot - src_pad) / src_pad:>+9.1%}  "
              f"{(tot - src_tight) / src_tight:>+9.1%}")
        return tot

    # 1. current: area-average on density
    dd = reproj_density(density_p, wt_p, src_crs, dst_transform, dst_crs,
                        dst_shape, Resampling.average)
    report("1 average(density) x area  [CURRENT]", dd * dst_area)

    # 2. bilinear on density
    dd2 = reproj_density(density_p, wt_p, src_crs, dst_transform, dst_crs,
                         dst_shape, Resampling.bilinear)
    report("2 bilinear(density) x area", dd2 * dst_area)

    # 3. nearest on density
    dd3 = reproj_density(density_p, wt_p, src_crs, dst_transform, dst_crs,
                         dst_shape, Resampling.nearest)
    report("3 nearest(density) x area", dd3 * dst_area)

    # 4/5. oversample density to a fine grid, x fine area, block-sum to dst.
    for F, how, tag in ((5, Resampling.bilinear, "bilinear"),
                        (5, Resampling.nearest, "nearest")):
        fine_transform = dst_transform * Affine.scale(1.0 / F, 1.0 / F)
        fine_shape = (ny * F, nx * F)
        fine_area = (dst_dx / F) ** 2
        fd = reproj_density(density_p, wt_p, src_crs, fine_transform, dst_crs,
                            fine_shape, how)
        fine_counts = fd * fine_area
        block = fine_counts.reshape(ny, F, nx, F).sum(axis=(1, 3))
        report(f"4 oversample x{F} {tag} + blocksum", block)

    # 6. normalise the current result to the tight source total
    cur_tot = float((dd * dst_area).sum())
    if cur_tot > 0:
        report("5 average x area, normalised to tight",
               dd * dst_area * (src_tight / cur_tot))

    # --- the rigorous baseline: source population INSIDE the dst footprint ---
    # Reproject a domain indicator (ones on the dst grid) back onto the source
    # grid; each source cell then carries the fraction of its area covered by
    # the domain. counts x fraction, summed, is the exact in-footprint total.
    cover = np.zeros(density_p.shape, dtype=np.float64)
    reproject(
        source=np.ones(dst_shape, dtype=np.float64), destination=cover,
        src_transform=dst_transform, src_crs=dst_crs,
        dst_transform=wt_p, dst_crs=src_crs,
        resampling=Resampling.average, src_nodata=None, dst_nodata=None,
    )
    src_footprint = float((c_pad * cover).sum())
    print()
    print(f"source total IN dst footprint (coverage-weighted): "
          f"{src_footprint:>12,.0f}")
    print(f"  footprint vs tight bbox: "
          f"{(src_footprint - src_tight) / src_tight:+.1%}  "
          f"(bbox overcounts the true domain)")
    print(f"  CURRENT resampled total {cur_tot:,.0f} vs footprint: "
          f"{(cur_tot - src_footprint) / src_footprint:+.2%}  <-- the honest residual")


if __name__ == "__main__":
    main()

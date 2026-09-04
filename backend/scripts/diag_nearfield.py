"""
Localize the near-dam resolution artifact so the reportable-mask exclusion
radius can be SIZED from data instead of guessed.

The Tehri 90 m run injects the breach hydrograph into a 6-cell footprint in a
gorge the grid resolves as ~1-2 cells wide. Continuity then piles water to ~230 m
for some distance downstream until the valley widens enough for 90 m to resolve
it. The current mask excludes only round(575/90)=6 cells, and the reported peak
(233 m) still sits right at that boundary -> the artifact extends further.

This reads the run's max_depth GeoTIFF and the injection cells from metadata,
computes each wet cell's distance (in cells) to the nearest injection cell, and
prints, for each candidate exclusion radius r, the peak depth that would REMAIN
reportable beyond r. The knee where that peak stops dropping steeply is where the
resolution artifact ends and the real flood begins. No solver, no re-run.

    conda run -n jaldrishti python scripts/diag_nearfield.py
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import rasterio
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]          # backend/
PROJ = ROOT.parent
RUN = PROJ / "outputs/runs/tehri_90m_20260902T041110Z"
DEPTH = RUN / "max_depth_m.tif"
META = RUN / "metadata.json"


def main():
    meta = json.load(io.open(META, encoding="utf-8"))
    breach = meta["scenario"]["provenance"]["breach"]
    cells = np.asarray(breach["inflow_cells"], dtype=np.int64).reshape(-1, 2)
    dx = float(meta["scenario"]["grid"]["dx_m"])
    top_w = float(breach.get("breach_top_width_m", 0.0))

    with rasterio.open(DEPTH) as d:
        depth = d.read(1, masked=True).filled(0.0).astype(np.float64)
    depth = np.where(depth < 0.0, 0.0, depth)
    wet = depth > 0.1
    ny, nx = depth.shape

    seed = np.zeros(depth.shape, dtype=bool)
    seed[cells[:, 0], cells[:, 1]] = True
    # distance (in cells) from every cell to the nearest injection cell
    dist = ndimage.distance_transform_edt(~seed)

    print(f"grid {nx}x{ny} @ {dx:g} m   wet cells {int(wet.sum()):,}")
    print(f"injection footprint {len(cells)} cells   breach_top_width {top_w:g} m "
          f"-> current radius {max(1, round(top_w / dx))} cells "
          f"({max(1, round(top_w / dx)) * dx:g} m)")
    print(f"global peak depth {depth.max():.1f} m   "
          f"near-field peak (<=6 cells) {depth[wet & (dist <= 6)].max():.1f} m")

    # far-field reference: plausible flood depth well away from the source
    far = depth[wet & (dist > 40)]
    if far.size:
        print(f"far-field (>40 cells) depth  median {np.median(far):.1f}  "
              f"p95 {np.percentile(far, 95):.1f}  max {far.max():.1f} m")
    print()
    print("A) peak depth remaining beyond an exclusion RADIUS from the source")
    print(f"{'radius':>6} {'metres':>7} {'peak_beyond':>12} {'excl_cells':>11} "
          f"{'excl_km2':>9}")
    prev = None
    for r in (0, 6, 10, 20, 30, 40):
        beyond = wet & (dist > r)
        peak = depth[beyond].max() if beyond.any() else 0.0
        n_excl = int((wet & (dist <= r)).sum())
        drop = "" if prev is None else f"  ({peak - prev:+.1f})"
        print(f"{r:>6} {r * dx:>7.0f} {peak:>12.1f} {n_excl:>11,} "
              f"{n_excl * dx * dx / 1e6:>9.3f}{drop}")
        prev = peak

    # -- B) the physical discriminator: local channel WIDTH -------------------
    # distance_transform_edt on the wet mask gives, at each wet cell, the number
    # of cells to the nearest dry cell -> the local half-width. 2*edt*dx is the
    # local channel width. A gorge the grid renders 1-2 cells wide (edt ~ 0.5-1)
    # is unresolved; a wide valley reach (edt >= 2) is resolved.
    edt = ndimage.distance_transform_edt(wet)
    print()
    print("B) depth vs local channel width (2*edt*dx). The artifact hypothesis:")
    print("   deep water lives in NARROW (unresolved) reaches.")
    print(f"{'min_halfwidth':>14} {'~width_m':>9} {'peak':>7} {'median':>7} "
          f"{'cells':>7} {'km2':>7}")
    for w in (0.0, 1.0, 1.5, 2.0, 2.5, 3.0):
        sel = wet & (edt >= w)
        if not sel.any():
            continue
        dd = depth[sel]
        print(f"{w:>14.1f} {2 * w * dx:>9.0f} {dd.max():>7.1f} "
              f"{np.median(dd):>7.1f} {sel.sum():>7,} "
              f"{sel.sum() * dx * dx / 1e6:>7.3f}")
    print()
    # confined-reach share: cells narrower than a 3-cell (edt<1.5) channel
    confined = wet & (edt < 1.5)
    resolved = wet & (edt >= 1.5)
    print(f"confined reach (channel < 3 cells wide): {int(confined.sum()):,} cells "
          f"({100 * confined.sum() / wet.sum():.0f}% of flood), "
          f"peak {depth[confined].max():.1f} m")
    if resolved.any():
        print(f"resolved reach (>= 3 cells wide)       : {int(resolved.sum()):,} cells "
              f"({100 * resolved.sum() / wet.sum():.0f}% of flood), "
              f"peak {depth[resolved].max():.1f} m  <- honest quotable peak")

    # -- C) WHERE is the deep water? reservoir (upstream, wide) vs gorge -------
    inj_row = int(np.median(cells[:, 0]))
    inj_col = int(np.median(cells[:, 1]))
    print()
    print(f"injection median cell (row,col) = ({inj_row},{inj_col})")
    print(f"{'rank':>4} {'row':>5} {'col':>5} {'depth':>7} {'edt':>5} "
          f"{'dist_inj':>8} {'d_row':>6}")
    flat = np.argsort(depth, axis=None)[::-1][:12]
    for i, idx in enumerate(flat):
        r, c = np.unravel_index(idx, depth.shape)
        print(f"{i:>4} {r:>5} {c:>5} {depth[r, c]:>7.1f} {edt[r, c]:>5.1f} "
              f"{dist[r, c]:>8.1f} {r - inj_row:>+6}")
    # rows < inj_row are upstream (toward the dam/reservoir) given e < 0
    deep = wet & (depth > 150.0)
    up = deep & (np.arange(ny)[:, None] < inj_row)
    print(f"cells >150 m: {int(deep.sum()):,}  of which upstream of injection "
          f"(toward reservoir): {int(up.sum()):,} "
          f"({100 * up.sum() / max(1, deep.sum()):.0f}%)")


if __name__ == "__main__":
    main()

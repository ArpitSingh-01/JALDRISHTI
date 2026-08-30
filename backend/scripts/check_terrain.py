"""
Run the terrain pipeline on the Tehri domain and report what came back.

Not a test — a build check. Run it to confirm the DEM path works end to end and to
get the numbers needed to replace the placeholder domain bounds in config.py.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from jaldrishti.config import DATA_DIR, OUTPUT_DIR, TEHRI
from jaldrishti.terrain import metric_extent_for, prepare_terrain

# Domain from the dam plus every place we have to report on, so it cannot silently
# exclude one of them.
pts = [(TEHRI.dam.lat, TEHRI.dam.lon)] + [(p.lat, p.lon) for p in TEHRI.downstream]
print("domain must contain:")
print(f"  {TEHRI.dam.name:28s} {TEHRI.dam.lat:.4f} N  {TEHRI.dam.lon:.4f} E")
for p in TEHRI.downstream:
    print(f"  {p.name:28s} {p.lat:.4f} N  {p.lon:.4f} E")

for dx in (90.0, 30.0):
    print(f"\n{'=' * 72}\ndx = {dx:g} m\n{'=' * 72}")
    t0 = time.perf_counter()
    grid = prepare_terrain(
        points=pts, dst_crs=TEHRI.domain.crs, dx=dx, margin_km=8.0,
        cache_dir=DATA_DIR / "dem", max_fill_m=2.0)
    print(f"\n{grid.summary()}")
    print(f"elapsed: {time.perf_counter() - t0:.1f} s")

    out = OUTPUT_DIR / "terrain" / f"tehri_dem_{int(dx)}m.tif"
    grid.to_geotiff(out)
    print(f"wrote {out}")

    # Sanity: every reported location must sit inside the grid, and the elevation
    # at the dam must be plausible against the published FRL. If this is wrong,
    # everything downstream is wrong and no other output would reveal it.
    from pyproj import Transformer
    from rasterio.transform import rowcol
    tr = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
    ny, nx = grid.shape
    print(f"\n{'location':28s} {'row':>6s} {'col':>6s}  {'bed m':>8s}  inside?")
    for name, lat, lon in ([(TEHRI.dam.name, TEHRI.dam.lat, TEHRI.dam.lon)]
                           + [(p.name, p.lat, p.lon) for p in TEHRI.downstream]):
        xm, ym = tr.transform(lon, lat)
        r, c = rowcol(grid.transform, xm, ym)
        ok = 0 <= r < ny and 0 <= c < nx
        bed = grid.z[r, c] if ok else float("nan")
        print(f"{name:28s} {r:6d} {c:6d}  {bed:8.1f}  {'yes' if ok else 'NO'}")

    xm, ym = tr.transform(TEHRI.dam.lon, TEHRI.dam.lat)
    r, c = rowcol(grid.transform, xm, ym)
    frl = TEHRI.dam.frl_m
    frl = frl.value if hasattr(frl, "value") else frl
    print(f"\ndam bed {grid.z[r, c]:.1f} m vs published FRL {frl} m")
    print(f"5x5 window about the dam (north at top):\n"
          f"{np.round(grid.z[r-2:r+3, c-2:c+3], 1)}")

    e = metric_extent_for(pts, TEHRI.domain.crs, dx, margin_km=8.0)
    print(f"\nconfig.py Domain bounds at dx={dx:g}: "
          f"xmin={e[0]:.0f}, ymin={e[1]:.0f}, xmax={e[2]:.0f}, ymax={e[3]:.0f}")

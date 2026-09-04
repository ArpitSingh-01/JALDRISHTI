"""Quick, throwaway bed-datum check for the Malpasset case.

Prints the elevation distribution of the raw bed .npy and, crucially, the bed
elevations INSIDE the reservoir mask plus the resulting initial water depths.
If the reservoir floor near the dam is ~20-30 m (crest ~100 m) we expect a max
initial depth of ~70-80 m; a much shallower max means the bed datum is biased
high and every water-surface comparison is off by construction.
"""
from __future__ import annotations

import numpy as np

from jaldrishti.validation import malpasset as M

bed = M.load_bed(coarsen=1)  # native 20 m
z = bed.z
valid = bed.valid
zin = z[valid]

print("RAW BED (native 20 m)")
print(f"  shape {bed.shape}  dx {bed.dx:.0f} m  origin ({bed.x0:.0f}, {bed.y0:.0f})")
print(f"  valid cells {valid.sum():,} / {z.size:,}")
print(f"  in-mesh elevation  min {zin.min():8.2f}  max {zin.max():8.2f} m")
for p in (0.1, 1, 5, 25, 50, 75, 95, 99):
    print(f"    p{p:<4} = {np.percentile(zin, p):8.2f} m")

s, mask = M.build_solver(bed)
h0 = np.asarray(s.h)
zres = z[mask]
hres = h0[mask]
print("\nRESERVOIR (mask cells)")
print(f"  cells {int(mask.sum()):,}")
print(f"  bed elevation   min {zres.min():7.2f}  mean {zres.mean():7.2f}  "
      f"max {zres.max():7.2f} m")
print(f"  initial depth   min {hres.min():7.2f}  mean {hres.mean():7.2f}  "
      f"max {hres.max():7.2f} m")
print(f"  volume          {float(s.volume())/1e6:7.2f} x10^6 m^3")

# Hypsometry: what fill level reproduces the historical ~55e6 m^3?
# Fill the reservoir footprint's terrain to a sweep of levels and integrate.
print("\nHYPSOMETRY over the reservoir footprint (fill level -> volume):")
cell_area = bed.dx * bed.dx
zfoot = z[mask]  # terrain inside the connected reservoir footprint
for level in (85, 90, 95, 98, 100, 102, 105):
    depth = np.clip(level - zfoot, 0.0, None)
    vol = float(depth.sum() * cell_area)
    print(f"  WS = {level:3d} m  ->  {vol/1e6:7.2f} x10^6 m^3  "
          f"(wet cells {(depth>0).sum():,})")

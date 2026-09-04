"""
Diagnostic: does the flow routing actually carry the reservoir's drainage
through the cell we inject the breach into?

Not a test. This answers ROADMAP B4's real question, which is not "did the snap
move" but "is the hydrograph entering the trunk river". Run it, read it, then
decide. It prints:

  1. the largest contributing areas in the domain and where they are
  2. where the reservoir pool drains to, by tracing from its lowest cell
  3. the contributing area profile along the trunk downstream of the dam
  4. whether the injection cell lies on the pool's own outflow path

    python scripts/diag_injection.py --dx 90
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jaldrishti.scenario.run import detect_pool, run_scenario

p = argparse.ArgumentParser()
p.add_argument("--area", default="tehri")
p.add_argument("--dx", type=float, default=90.0)
a = p.parse_args()

res = run_scenario(a.area, dx=a.dx, setup_only=True, export_bundle=False,
                   exposure=False, verbose=False)
grid, hydro, pool = res.grid, res.hydro, res.pool
area = hydro.contributing_area_km2
ny, nx = grid.shape
fj, fi = res.setup["dam_cell"]
sj, si = res.setup["breach"]["inflow_cell"]

print("=" * 74)
print(f"{a.area} at dx = {a.dx:g} m   grid {nx} x {ny}")
print("=" * 74)
print(f"dam cell        ({fj}, {fi})  bed {grid.z[fj, fi]:.1f} m  "
      f"area {area[fj, fi]:.2f} km2")
print(f"injection cell  ({sj}, {si})  bed {grid.z[sj, si]:.1f} m  "
      f"area {area[sj, si]:.2f} km2")
print(f"pool            level {pool.level_m:.1f} m  {pool.area_km2:.1f} km2  "
      f"{int(pool.mask.sum()):,} cells")

# ---- 1. the biggest catchments in the domain -------------------------------
print("\n[1] largest contributing areas in the domain")
flat = np.argsort(area.ravel())[::-1][:400]
seen = []
for k in flat:
    j, i = int(k // nx), int(k % nx)
    if any(abs(j - pj) < 15 and abs(i - pi) < 15 for pj, pi in seen):
        continue
    seen.append((j, i))
    edge = ""
    if j < 2 or j > ny - 3 or i < 2 or i > nx - 3:
        edge = "  [ON EDGE — outlet]"
    print(f"    ({j:4d}, {i:4d})  {area[j, i]:9.1f} km2  bed "
          f"{grid.z[j, i]:7.1f} m{edge}")
    if len(seen) >= 8:
        break

# ---- 2. where does the pool drain? -----------------------------------------
print("\n[2] the pool's own outflow path")
pj, pi = np.where(pool.mask)
zp = grid.z[pj, pi]
low = int(np.argmin(zp))
lj, li = int(pj[low]), int(pi[low])
print(f"    lowest pool cell ({lj}, {li}) at {grid.z[lj, li]:.1f} m, "
      f"area {area[lj, li]:.2f} km2")
# highest-area pool cell is the one the routing funnels the lake through
hi = int(np.argmax(area[pj, pi]))
hj, hi_i = int(pj[hi]), int(pi[hi])
print(f"    pool cell with most area ({hj}, {hi_i}) "
      f"area {area[hj, hi_i]:.2f} km2 at {grid.z[hj, hi_i]:.1f} m")
js, is_, dist = hydro.trace_downstream(hj, hi_i)
print(f"    trace from there: {len(js)} cells, {dist[-1] / 1000:.1f} km to edge")
on_path = [(int(js[k]), int(is_[k])) for k in range(len(js))]
print(f"    first 12 cells:")
for k in range(min(12, len(js))):
    j, i = int(js[k]), int(is_[k])
    mark = ""
    if (j, i) == (sj, si):
        mark = "   <-- INJECTION CELL"
    if (j, i) == (fj, fi):
        mark = "   <-- dam cell"
    print(f"       {k:3d}  ({j:4d}, {i:4d})  {dist[k] / 1000:6.2f} km  "
          f"bed {grid.z[j, i]:7.1f} m  area {area[j, i]:8.2f} km2{mark}")
print(f"    injection cell on the pool's outflow path: "
      f"{(sj, si) in on_path}")
if (sj, si) in on_path:
    print(f"      at index {on_path.index((sj, si))} of {len(on_path)}")

# ---- 3. area profile along the trunk downstream of the injection ----------
print("\n[3] area profile downstream of the injection cell")
js, is_, dist = hydro.trace_downstream(sj, si)
print(f"    {len(js)} cells, {dist[-1] / 1000:.1f} km to the domain edge")
step = max(1, len(js) // 20)
prev = None
for k in range(0, len(js), step):
    j, i = int(js[k]), int(is_[k])
    jump = ""
    if prev is not None and area[j, i] > prev * 1.6:
        jump = f"   <-- area x{area[j, i] / prev:.1f} (confluence)"
    prev = float(area[j, i])
    print(f"       ({j:4d}, {i:4d})  {dist[k] / 1000:6.2f} km  bed "
          f"{grid.z[j, i]:7.1f} m  area {area[j, i]:8.2f} km2{jump}")

# ---- 4. what the dam cell's neighbourhood looks like ----------------------
print("\n[4] contributing area within 6 cells of the dam "
      "(pool cells marked *)")
r = 6
for j in range(max(0, fj - r), min(ny, fj + r + 1)):
    row = []
    for i in range(max(0, fi - r), min(nx, fi + r + 1)):
        s = f"{area[j, i]:7.1f}"
        if pool.mask[j, i]:
            s = f"{area[j, i]:6.1f}*"
        if (j, i) == (fj, fi):
            s = f"[{area[j, i]:5.1f}]"
        if (j, i) == (sj, si):
            s = f"<{area[j, i]:5.1f}>"
        row.append(s)
    print(f"    j={j:4d} " + " ".join(row))

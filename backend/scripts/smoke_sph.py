"""Smoke test: 20 steps of the SPH solver with visible timing per stage."""
import time

import numpy as np

from jaldrishti.solver.sph2d import DamBreakSPH

t0 = time.perf_counter()
sim = DamBreakSPH(1.0, 0.5, 4.0, 0.02)
print(f"build: {time.perf_counter() - t0:.1f}s  "
      f"particles={sim.x.shape[0]} fluid={int(sim.fluid.sum())}")

sim.set_gauge(1.2)
for i in range(20):
    t1 = time.perf_counter()
    dt = sim.step()
    if i < 5 or i % 5 == 0:
        v = float(np.linalg.norm(sim.v[sim.fluid], axis=1).max())
        print(f"step {i:3d}  dt={dt:.3e}  t={sim.stats.t:.4f}  "
              f"vmax={v:.3f}  front={sim.front_position():.3f}  "
              f"({time.perf_counter() - t1:.3f}s)")
print("OK")

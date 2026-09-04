"""Diagnostic: run the Martin-Moyce front scenario with dt/velocity telemetry."""
import math
import time

import numpy as np

from jaldrishti.solver.sph2d import DamBreakSPH, GRAVITY

a = 0.5
t_scale = math.sqrt(a / GRAVITY)
t_end = 3.44 * t_scale
print(f"t_end = {t_end:.3f} s")

sim = DamBreakSPH(2 * a, a, 8 * a, a / 25)
sim.set_gauge(2.0 * a)
t0 = time.perf_counter()
last = t0
while sim.stats.t < t_end:
    dt = sim.step()
    if sim.stats.steps % 200 == 0:
        now = time.perf_counter()
        v = float(np.linalg.norm(sim.v[sim.fluid], axis=1).max())
        print(f"step {sim.stats.steps:5d} t={sim.stats.t:.3f} dt={dt:.2e} "
              f"vmax={v:9.2f} front={sim.front_position():.2f} "
              f"({now - last:.1f}s for 200 steps, "
              f"total {now - t0:.0f}s)")
        last = now
print(f"done in {time.perf_counter() - t0:.0f}s, steps={sim.stats.steps}")

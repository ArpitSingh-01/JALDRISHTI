"""Probe: front detection sensitivity + profile snapshots."""
import math

import numpy as np

from jaldrishti.solver.sph2d import DamBreakSPH, GRAVITY

a = 0.5
t_scale = math.sqrt(a / GRAVITY)
sim = DamBreakSPH(2 * a, a, 8 * a, a / 25,
                  viscosity_alpha=0.25, viscosity_beta=0.5)

targets = [1.22, 1.89, 2.56, 3.44]
ti = 0
while ti < len(targets) and sim.stats.t < targets[-1] * t_scale:
    sim.step()
    if ti < len(targets) and sim.stats.t >= targets[ti] * t_scale:
        T = sim.stats.t / t_scale
        fl = sim.fluid
        x_fl = sim.x[fl, 0]
        z_fl = sim.x[fl, 1]
        front_bed = x_fl[z_fl < 0.04].max() if (z_fl < 0.04).any() else 0
        front_all = x_fl.max()
        # profile in the leading 2 m
        prof = []
        for x0 in np.arange(1.0, 3.5, 0.25):
            sel = (x_fl >= x0) & (x_fl < x0 + 0.25)
            prof.append(f"{x0:.2f}:{z_fl[sel].max():.2f}" if sel.any()
                        else f"{x0:.2f}:-")
        print(f"T={T:.2f} front_bed={front_bed:.2f} front_all={front_all:.2f} "
              f"Z_bed={(front_bed - 1.0):.2f} Z_all={(front_all - 1.0):.2f}")
        print("   profile:", " ".join(prof))
        ti += 1

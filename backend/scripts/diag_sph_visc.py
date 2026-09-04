"""Probe: front travel vs viscosity settings at fixed resolution."""
import math
import sys

import numpy as np

from jaldrishti.solver.sph2d import DamBreakSPH, GRAVITY

a = 0.5
t_scale = math.sqrt(a / GRAVITY)
t_end = 3.44 * t_scale
cases = [
    (0.05, 0.1, 1.3),
    (0.02, 0.05, 1.3),
    (0.1, 0.2, 1.3),
]
for alpha, beta, hf in cases:
    sim = DamBreakSPH(2 * a, a, 8 * a, a / 25,
                      viscosity_alpha=alpha, viscosity_beta=beta,
                      h_factor=hf)
    sim.run(t_end, callback_every=1000, shepard_every=40)
    T = sim.stats.t / t_scale
    travel = sim.front_position() - 2 * a
    Z = travel / (2 * a)
    vol_err = sim.stats.volume_error
    print(f"alpha={alpha} beta={beta} h={hf}:  T={T:.2f} Z={Z:.2f} "
          f"(obs 2.25)  vol_err={vol_err:.4f} steps={sim.stats.steps}")

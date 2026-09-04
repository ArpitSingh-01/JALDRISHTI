"""Diagnostic: find the pressure/density spike source in the SPH startup."""
import numpy as np

from jaldrishti.solver.sph2d import DamBreakSPH, _forces, _boundary_density, _density_rate

sim = DamBreakSPH(1.0, 0.5, 4.0, 0.02)
sim.set_gauge(1.2)

cells = sim._rebuild_cells()
_boundary_density(sim.x, sim.m, sim.rho, sim.fluid, sim.h_s, *cells)
sim._update_pressure()
print("after boundary density:")
print("  boundary rho range:", sim.rho[~sim.fluid].min(), sim.rho[~sim.fluid].max())
print("  fluid rho:", sim.rho[sim.fluid].min(), sim.rho[sim.fluid].max())

_forces(sim.x, sim.v, sim.rho, sim.p, sim.m, sim.h_s, *cells,
        sim.alpha, sim.beta, sim.c0, sim.fluid, sim.ax, sim.az)
fl = sim.fluid
a = np.abs(sim.ax[fl])
print("  fluid ax range:", sim.ax[fl].min(), sim.ax[fl].max())
print("  fluid az range:", sim.az[fl].min(), sim.az[fl].max())
worst = np.argmax(np.abs(sim.ax[fl]))
idx = np.where(fl)[0][worst]
print("  worst ax particle: pos", sim.x[idx], "rho", sim.rho[idx],
      "p", sim.p[idx])

_density_rate(sim.x, sim.v, sim.m, sim.h_s, *cells, sim.drho, sim.fluid)
print("  drho range:", sim.drho[fl].min(), sim.drho[fl].max())

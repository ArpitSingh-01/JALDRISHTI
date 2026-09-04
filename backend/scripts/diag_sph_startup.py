"""Fine-grained startup diagnostic: find the first bad step."""
import numpy as np

from jaldrishti.solver.sph2d import DamBreakSPH

sim = DamBreakSPH(1.0, 0.5, 4.0, 0.02)
sim.set_gauge(1.2)

for i in range(60):
    dt = sim.step()
    fl = sim.fluid
    vmax = float(np.linalg.norm(sim.v[fl], axis=1).max())
    pmax = float(sim.p[fl].max())
    rmin = float(sim.rho[fl].min())
    rmax = float(sim.rho[fl].max())
    if i >= 20 or vmax > 1.0:
        print(f"step {i:3d} dt={dt:.2e} vmax={vmax:.3e} pmax={pmax:.3e} "
              f"rho=[{rmin:.1f},{rmax:.1f}]")
    if vmax > 1e3:
        # locate the bad particle
        k = int(np.argmax(np.linalg.norm(sim.v[fl], axis=1)))
        idx = np.where(fl)[0][k]
        print("   bad particle:", sim.x[idx], "v", sim.v[idx],
              "rho", sim.rho[idx], "fluid neighbors:",
              int(((np.abs(sim.x[:, 0] - sim.x[idx, 0]) < 0.06) &
                   (np.abs(sim.x[:, 1] - sim.x[idx, 1]) < 0.06)).sum()))
        break

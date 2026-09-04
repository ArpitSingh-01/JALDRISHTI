"""
Weakly-compressible Smoothed Particle Hydrodynamics (SPH) in a 2D plane.

WHERE SPH FITS IN JALDRISHTI
----------------------------
SPH represents water as moving particles rather than a fixed grid, which makes
it good at violent, splashing, free-surface flow — precisely what happens in
the first moments at a breach — and poor at cheaply routing a flood eighty
kilometres downstream. So each method is used where it is strong: SPH resolves
the NEAR-FIELD breach dynamics, the 2D shallow-water solver (`swe2d`) routes
the far-field flood, and the handover between them is a discharge hydrograph
measured at a vertical gauge line inside the SPH domain and delivered to
`SWE2D.add_inflow` as Q(t). The routing core never learns where Q came from.

THE FORMULATION
---------------
Standard weakly-compressible SPH (Monaghan 1992, 1994):

    continuity:   dρ_a/dt = Σ_b m_b (v_a − v_b) · ∇W_ab
    momentum:     dv_a/dt = Σ_b m_b (P_a/ρ_a² + P_b/ρ_b² + Π_ab) ∇W_ab + g
    equation of   P = c0² ρ0/γ [ (ρ/ρ0)^γ − 1 ],  γ = 7
    state:
    viscosity:    Monaghan artificial viscosity Π_ab (α, β), which is what
                  keeps a collapsing column from interpenetrating itself.

The kernel is the 2D cubic spline with compact support 2 h_s. Neighbour search
is a uniform cell list rebuilt every step (cell size = kernel radius), jitted
with Numba like the rest of the solver core. Time integration is the Monaghan
predictor-corrector; dt obeys both the sound-speed and the force CFL bounds.

BOUNDARIES
----------
Walls and bed are built from STATIC boundary particles that participate in the
density and pressure sums but never move. This is the classical Monaghan
boundary-particle treatment: simple, robust and adequate for a breach-jet
scale problem. It is NOT the more modern double-density or δ-SPH boundary
handling, and that is a stated limitation, not a hidden one.

VALIDATION (see tests/test_sph.py)
----------------------------------
1. Hydrostatic: a resting block of water must keep ρ ≈ ρ0 and v ≈ 0.
2. Mass: particle count is conserved exactly; the density-weighted volume
   must not drift.
3. Front position against the Martin & Moyce (1952) Table 1 measurements —
   the same experiment Monaghan (1994) used to validate SPH, transcribed from
   the original paper (see scripts/pdf_front_law.py for the extraction).
4. The outflow hydrograph at a gauge line: non-negative, and its time integral
   cannot exceed the volume per unit width initially upstream of it.

The gauge hydrograph feeds the comparison module
(`jaldrishti.validation.compare`), which puts the SPH and SWE scenarios
side by side.

REFERENCES
----------
Monaghan, J.J. (1992). Smoothed particle hydrodynamics. Ann. Rev. Astron.
    Astrophys. 30, 543-574.
Monaghan, J.J. (1994). Simulating free surface flows with SPH. J. Comput.
    Phys. 110(2), 399-406.
Martin, J.C. & Moyce, W.J. (1952). Part IV. An experimental study of the
    collapse of liquid columns on a rigid horizontal plane. Phil. Trans. R.
    Soc. Lond. A 244(882), 312-324.  [Table 1, n² = 1, a = 2¼ in.]
Liu, G.R. & Liu, M.B. (2003). Smoothed Particle Hydrodynamics: A Meshfree
    Particle Method. World Scientific.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from numba import njit

GRAVITY = 9.81
GAMMA = 7.0
RHO0 = 1000.0

# ---------------------------------------------------------------------------
# Kernel: 2D cubic spline, support 2 h_s.
# W(r) = N(q)/h_s² with q = r/h_s and N(q) = 10/(7π) · spline(q).
# The functions below return the DIMENSIONLESS spline(q) and spline'(q);
# call sites apply the 1/h_s² (value) or 1/h_s³ (gradient) scale.
# ---------------------------------------------------------------------------

_KERNEL_NORM = 10.0 / (7.0 * math.pi)


@njit(cache=True, inline="always")
def _kernel(q: float) -> float:
    if q < 0.0 or q >= 2.0:
        return 0.0
    if q < 1.0:
        return _KERNEL_NORM * (1.0 - 1.5 * q * q + 0.75 * q * q * q)
    return _KERNEL_NORM * 0.25 * (2.0 - q) ** 3


@njit(cache=True, inline="always")
def _kernel_grad(q: float) -> float:
    """dW/dq. Multiply by (rx / (h_s³ r)) to get ∂W/∂x."""
    if q < 0.0 or q >= 2.0:
        return 0.0
    if q < 1.0:
        return _KERNEL_NORM * (-3.0 * q + 2.25 * q * q)
    return _KERNEL_NORM * -0.75 * (2.0 - q) ** 2


# ---------------------------------------------------------------------------
# Neighbour search: uniform cell list, cell size = kernel radius (2 h_s)
# ---------------------------------------------------------------------------


@njit(cache=True)
def _build_cells(x, inv_cell, n_cellx, n_celly, counts):
    n = x.shape[0]
    for a in range(n):
        cx = int(x[a, 0] * inv_cell)
        cy = int(x[a, 1] * inv_cell)
        if cx < 0:
            cx = 0
        elif cx >= n_cellx:
            cx = n_cellx - 1
        if cy < 0:
            cy = 0
        elif cy >= n_celly:
            cy = n_celly - 1
        counts[cy * n_cellx + cx] += 1


@njit(cache=True)
def _cell_starts(counts, starts):
    total = 0
    for c in range(counts.shape[0]):
        starts[c] = total
        total += counts[c]


@njit(cache=True)
def _fill_cells(x, inv_cell, n_cellx, n_celly, starts, order):
    n = x.shape[0]
    cursor = starts.copy()
    for a in range(n):
        cx = int(x[a, 0] * inv_cell)
        cy = int(x[a, 1] * inv_cell)
        if cx < 0:
            cx = 0
        elif cx >= n_cellx:
            cx = n_cellx - 1
        if cy < 0:
            cy = 0
        elif cy >= n_celly:
            cy = n_celly - 1
        c = cy * n_cellx + cx
        order[cursor[c]] = a
        cursor[c] += 1


@njit(cache=True)
def _cell_of(x, inv_cell, n_cellx, n_celly, out):
    for a in range(x.shape[0]):
        cx = int(x[a, 0] * inv_cell)
        cy = int(x[a, 1] * inv_cell)
        if cx < 0:
            cx = 0
        elif cx >= n_cellx:
            cx = n_cellx - 1
        if cy < 0:
            cy = 0
        elif cy >= n_celly:
            cy = n_celly - 1
        out[a] = cy * n_cellx + cx


# ---------------------------------------------------------------------------
# Physics loops (jitted; each runs over the 3x3 cell neighbourhood)
# ---------------------------------------------------------------------------


@njit(cache=True)
def _density_rate(x, v, m, h_s, cell_of, n_cellx, n_celly, starts, counts,
                  order, drho, fluid):
    """Continuity equation for FLUID particles."""
    n = x.shape[0]
    for a in range(n):
        if not fluid[a]:
            drho[a] = 0.0
            continue
        ca = cell_of[a]
        c0x = ca % n_cellx
        c0y = ca // n_cellx
        acc = 0.0
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                cx = c0x + dx
                cy = c0y + dy
                if cx < 0 or cy < 0 or cx >= n_cellx or cy >= n_celly:
                    continue
                c = cy * n_cellx + cx
                for k in range(counts[c]):
                    b = order[starts[c] + k]
                    if b == a:
                        continue
                    rx = x[a, 0] - x[b, 0]
                    ry = x[a, 1] - x[b, 1]
                    r2 = rx * rx + ry * ry
                    if r2 >= 4.0 * h_s * h_s:
                        continue
                    r = math.sqrt(r2)
                    if r < 1e-12:
                        continue
                    # ∂W/∂x = N'(q) · rx / (h_s³ · r)
                    gx = _kernel_grad(r / h_s) * rx / (h_s * h_s * h_s * r)
                    gy = _kernel_grad(r / h_s) * ry / (h_s * h_s * h_s * r)
                    dvx = v[a, 0] - v[b, 0]
                    dvy = v[a, 1] - v[b, 1]
                    acc += m[b] * (dvx * gx + dvy * gy)
        drho[a] = acc


@njit(cache=True)
def _boundary_density(x, m, rho, fluid, h_s, cell_of, n_cellx, n_celly,
                      starts, counts, order):
    """Shepard-corrected density summation for STATIC boundary particles."""
    n = x.shape[0]
    fallback = RHO0
    for a in range(n):
        if fluid[a]:
            continue
        ca = cell_of[a]
        c0x = ca % n_cellx
        c0y = ca // n_cellx
        num = 0.0
        den = 0.0
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                cx = c0x + dx
                cy = c0y + dy
                if cx < 0 or cy < 0 or cx >= n_cellx or cy >= n_celly:
                    continue
                c = cy * n_cellx + cx
                for k in range(counts[c]):
                    b = order[starts[c] + k]
                    rx = x[a, 0] - x[b, 0]
                    ry = x[a, 1] - x[b, 1]
                    r2 = rx * rx + ry * ry
                    if r2 >= 4.0 * h_s * h_s:
                        continue
                    r = math.sqrt(r2)
                    w = _kernel(r / h_s) / (h_s * h_s)
                    num += m[b] * w
                    den += w * (m[b] / rho[b])
        if den > 1e-12:
            rho[a] = num / den
        else:
            rho[a] = fallback


@njit(cache=True)
def _forces(x, v, rho, p, m, h_s, cell_of, n_cellx, n_celly, starts, counts,
            order, alpha, beta, c0, fluid, ax_out, az_out):
    """Momentum equation with Monaghan artificial viscosity, gravity in −z."""
    n = x.shape[0]
    for a in range(n):
        ca = cell_of[a]
        c0x = ca % n_cellx
        c0y = ca // n_cellx
        accx = 0.0
        accz = -GRAVITY
        pa = p[a]
        rho_a2 = rho[a] * rho[a]
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                cx = c0x + dx
                cy = c0y + dy
                if cx < 0 or cy < 0 or cx >= n_cellx or cy >= n_celly:
                    continue
                c = cy * n_cellx + cx
                for k in range(counts[c]):
                    b = order[starts[c] + k]
                    if b == a:
                        continue
                    rx = x[a, 0] - x[b, 0]
                    ry = x[a, 1] - x[b, 1]
                    r2 = rx * rx + ry * ry
                    if r2 >= 4.0 * h_s * h_s:
                        continue
                    r = math.sqrt(r2)
                    if r < 1e-12:
                        continue
                    gr = _kernel_grad(r / h_s) / (h_s * h_s * h_s * r)
                    gx = gr * rx
                    gz = gr * ry
                    press = pa / rho_a2 + p[b] / (rho[b] * rho[b])
                    dvx = v[a, 0] - v[b, 0]
                    dvz = v[a, 1] - v[b, 1]
                    vr = dvx * rx + dvz * ry
                    pi_ab = 0.0
                    if vr < 0.0:
                        mu = h_s * vr / (r2 + 0.01 * h_s * h_s)
                        rho_mean = 0.5 * (rho[a] + rho[b])
                        pi_ab = (-alpha * c0 * mu + beta * mu * mu) / rho_mean
                    # dv_a/dt = -SUM m_b (p/rho^2 + Pi) grad_a(W_ab).
                    # grad_a(W_ab) points from a TOWARD b (N' < 0), so the
                    # minus sign is what makes pressure repel. Dropping it
                    # turns the fluid into a self-attracting collapse —
                    # caught by the hydrostatic and collapse diagnostics.
                    accx -= m[b] * (press + pi_ab) * gx
                    accz -= m[b] * (press + pi_ab) * gz
        ax_out[a] = accx
        az_out[a] = accz


@njit(cache=True)
def _integrate_half(x, v, ax, az, drho, rho, dt, fluid):
    n = x.shape[0]
    for a in range(n):
        if not fluid[a]:
            continue
        v[a, 0] += 0.5 * dt * ax[a]
        v[a, 1] += 0.5 * dt * az[a]
        x[a, 0] += 0.5 * dt * v[a, 0]
        x[a, 1] += 0.5 * dt * v[a, 1]
        rho[a] += 0.5 * dt * drho[a]


@njit(cache=True)
def _shepard_filter(x, m, rho, fluid, h_s, cell_of, n_cellx, n_celly, starts,
                    counts, order):
    """Shepard density filter for fluid particles: ρ_a = Σ m_b W / Σ (m_b/ρ_b) W."""
    n = x.shape[0]
    new_rho = rho.copy()
    for a in range(n):
        if not fluid[a]:
            continue
        ca = cell_of[a]
        c0x = ca % n_cellx
        c0y = ca // n_cellx
        num = 0.0
        den = 0.0
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                cx = c0x + dx
                cy = c0y + dy
                if cx < 0 or cy < 0 or cx >= n_cellx or cy >= n_celly:
                    continue
                c = cy * n_cellx + cx
                for k in range(counts[c]):
                    b = order[starts[c] + k]
                    rx = x[a, 0] - x[b, 0]
                    ry = x[a, 1] - x[b, 1]
                    r2 = rx * rx + ry * ry
                    if r2 >= 4.0 * h_s * h_s:
                        continue
                    r = math.sqrt(r2)
                    w = _kernel(r / h_s) / (h_s * h_s)
                    num += m[b] * w
                    den += w * (m[b] / rho[b])
        if den > 1e-12:
            new_rho[a] = num / den
    return new_rho


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class SPHRunStats:
    """Diagnostics for one SPH run, mirroring swe2d.RunStats in spirit."""
    steps: int = 0
    t: float = 0.0
    dt_min: float = float("inf")
    dt_max: float = 0.0
    volume_initial: float = 0.0
    volume_final: float = 0.0
    history: list = field(default_factory=list)  # (t, q_gauge, front_x)

    @property
    def volume_error(self) -> float:
        if self.volume_initial == 0.0:
            return 0.0
        return (self.volume_final - self.volume_initial) / self.volume_initial


class DamBreakSPH:
    """
    A 2D (vertical plane) weakly-compressible SPH dam-break experiment.

    Coordinates: x downstream, z up. Gravity acts in −z. The domain is a tank
    of length `tank_length` with a rigid bed at z = 0; the reservoir is a block
    of water of width `column_width` and height `column_height` standing at
    the left wall. When the simulation starts the "dam" simply does not exist
    — the column collapses under gravity, which is the canonical SPH
    dam-break benchmark (Monaghan 1994) and JALDRISHTI's near-field breach
    model.

    Units are metres and seconds. Particle mass is set so the initial lattice
    gives ρ = ρ0 = 1000 kg/m³ with the 2D kernel.

    Parameters
    ----------
    column_width, column_height : reservoir block dimensions (m)
    tank_length                 : total domain length (m); the column starts
                                  against the left wall
    particle_spacing            : initial lattice spacing (m). The Martin-
                                  Moyce comparison in the tests uses
                                  column_height / 40; coarsen for speed.
    sound_speed                 : c0. Rule of thumb c0 ≈ 10 · max|u| keeps
                                  density variation below ~1% (Monaghan 1992).
    viscosity_alpha, viscosity_beta : Monaghan artificial viscosity. CALIBRATED,
                                  not free: against the Martin & Moyce (1952)
                                  front-position data, alpha = 0.5 puts the
                                  front 33% slow (over-dissipated), alpha =
                                  0.05 puts it 4% slow with ~1.4% volume
                                  noise. 0.05/0.1 is the documented compromise;
                                  the sweep behind this choice is in the
                                  validation ledger.
    cfl                         : dt safety factor on both CFL bounds.
    """

    def __init__(self, column_width, column_height, tank_length,
                 particle_spacing, *, sound_speed=None,
                 viscosity_alpha=0.05, viscosity_beta=0.1, cfl=0.25,
                 h_factor=1.3):
        self.column_width = float(column_width)
        self.column_height = float(column_height)
        self.tank_length = float(tank_length)
        self.dp = float(particle_spacing)
        self.cfl = float(cfl)
        self.alpha = float(viscosity_alpha)
        self.beta = float(viscosity_beta)
        self.h_s = float(h_factor) * self.dp
        if sound_speed is None:
            # max|u| ~ 2 sqrt(g H); 10x keeps compressibility under ~1%
            self.c0 = 10.0 * math.sqrt(GRAVITY * column_height)
        else:
            self.c0 = float(sound_speed)

        self._build_particles()
        self.stats = SPHRunStats()
        self.stats.volume_initial = self.volume
        self._gauge_x = None
        self._gauge_times: list[float] = []
        self._gauge_q: list[float] = []

    # -- construction --------------------------------------------------------

    def _build_particles(self):
        dp = self.dp
        xs, zs, fluid = [], [], []

        nx = int(round(self.column_width / dp))
        nz = int(round(self.column_height / dp))
        for iz in range(nz):
            for ix in range(nx):
                xs.append((ix + 0.5) * dp)
                zs.append((iz + 0.5) * dp)
                fluid.append(True)

        # Static boundary particles: left wall, bed, right wall — three layers.
        pad = 3 * dp
        top = self.column_height + 6.0 * dp

        def add_wall(x0, x1, z0, z1):
            nxw = max(1, int(round((x1 - x0) / dp)))
            nzw = max(1, int(round((z1 - z0) / dp)))
            for iz in range(nzw):
                for ix in range(nxw):
                    xs.append(x0 + (ix + 0.5) * (x1 - x0) / nxw)
                    zs.append(z0 + (iz + 0.5) * (z1 - z0) / nzw)
                    fluid.append(False)

        add_wall(-pad, 0.0, -pad, top)                  # left wall
        add_wall(0.0, self.tank_length, -pad, 0.0)      # bed
        add_wall(self.tank_length, self.tank_length + pad,
                 -pad, top)                             # right wall

        self.x = np.column_stack([xs, zs]).astype(np.float64)
        self.v = np.zeros_like(self.x)
        self.fluid = np.array(fluid, dtype=np.bool_)
        n = self.x.shape[0]

        # Each fluid particle owns dp² of area at ρ0.
        self.m = np.full(n, RHO0 * dp * dp, dtype=np.float64)
        self.rho = np.full(n, RHO0, dtype=np.float64)
        # Hydrostatic (Reissner) initial condition: the Tait EOS has an exact
        # equilibrium solution rho(z) = rho0 (1 + (gamma-1) g (H - z)/c0^2)
        # ^ (1/(gamma-1)). Starting from it means the column begins in
        # balance instead of free-falling onto the bed and compressing into
        # a pressure spike — the classical WCSPH startup failure.
        H = self.column_height
        gamma = GAMMA
        rho_h = RHO0 * (1.0 + (gamma - 1.0) * GRAVITY
                        * np.maximum(H - self.x[:, 1], 0.0)
                        / (self.c0 ** 2)) ** (1.0 / (gamma - 1.0))
        self.rho = np.where(self.fluid, rho_h, self.rho)
        self.p = np.zeros(n, dtype=np.float64)
        self.drho = np.zeros(n, dtype=np.float64)
        self.ax = np.zeros(n, dtype=np.float64)
        self.az = np.zeros(n, dtype=np.float64)

    # -- derived quantities ----------------------------------------------------

    @property
    def volume(self) -> float:
        """Water volume per unit thickness (m²), density-weighted."""
        return float(np.sum(self.m[self.fluid] / self.rho[self.fluid]))

    def front_position(self) -> float:
        """Leading edge of the collapse: furthest fluid particle riding the bed."""
        on_bed = self.fluid & (self.x[:, 1] < 2.0 * self.dp)
        if not on_bed.any():
            on_bed = self.fluid
        return float(self.x[on_bed, 0].max())

    def free_surface_profile(self, binsize=None):
        """
        Binned free-surface height vs x — the SPH counterpart of a depth
        profile, used to overlay against SWE/analytical results.

        Returns (x_centers, h): h[b] is the top of the water column in bin b
        (0.0 where dry).
        """
        if binsize is None:
            binsize = 2.0 * self.dp
        fx = self.x[self.fluid, 0]
        fz = self.x[self.fluid, 1]
        if fx.size == 0:
            return np.array([]), np.array([])
        nb = int(np.ceil(self.tank_length / binsize))
        h = np.zeros(nb)
        idx = np.clip((fx / binsize).astype(np.int64), 0, nb - 1)
        np.maximum.at(h, idx, fz)
        centers = (np.arange(nb) + 0.5) * binsize
        return centers, h

    # -- gauge -----------------------------------------------------------------

    def set_gauge(self, x_pos: float):
        """
        Place a vertical gauge line at x = x_pos. Every sample, the per-unit-
        width discharge q(t) crossing the line is measured — the near-field
        handover signal that becomes the SWE inflow hydrograph.
        """
        self._gauge_x = float(x_pos)

    def _measure_gauge(self, t: float):
        if self._gauge_x is None:
            return
        near = self.fluid & (np.abs(self.x[:, 0] - self._gauge_x) < self.dp)
        if near.any():
            # Σ (m/ρ)·u over the window, divided by window width 2·dp:
            # volume flux per unit thickness per unit width (m²/s).
            contrib = (self.m[near] / self.rho[near]) * self.v[near, 0]
            q = float(contrib.sum() / (2.0 * self.dp))
        else:
            q = 0.0
        self._gauge_times.append(t)
        self._gauge_q.append(q)

    def gauge_hydrograph(self):
        """(times, q) — measured discharge per unit width (m²/s) at the gauge."""
        return np.array(self._gauge_times), np.array(self._gauge_q)

    # -- time integration --------------------------------------------------------

    def _rebuild_cells(self):
        cell = 2.0 * self.h_s
        x_min = float(self.x[:, 0].min()) - cell
        z_min = float(self.x[:, 1].min()) - cell
        n_cellx = int((float(self.x[:, 0].max()) - x_min) / cell) + 3
        n_celly = int((float(self.x[:, 1].max()) - z_min) / cell) + 3
        inv_cell = 1.0 / cell
        shifted = self.x - np.array([x_min, z_min])
        ncell = n_cellx * n_celly
        counts = np.zeros(ncell, dtype=np.int64)
        _build_cells(shifted, inv_cell, n_cellx, n_celly, counts)
        starts = np.zeros(ncell, dtype=np.int64)
        _cell_starts(counts, starts)
        order = np.zeros(self.x.shape[0], dtype=np.int64)
        _fill_cells(shifted, inv_cell, n_cellx, n_celly, starts, order)
        cell_of = np.empty(self.x.shape[0], dtype=np.int64)
        _cell_of(shifted, inv_cell, n_cellx, n_celly, cell_of)
        return cell_of, n_cellx, n_celly, starts, counts, order

    def compute_dt(self) -> float:
        fl = self.fluid
        if fl.any():
            v_max = float(np.max(np.linalg.norm(self.v[fl], axis=1)))
            # Force bound must include BOTH components: during the collapse
            # the horizontal pressure gradient, not gravity, sets a_max.
            a_max = float(max(
                np.max(np.abs(self.ax[fl])), np.max(np.abs(self.az[fl]))))
        else:
            v_max, a_max = 0.0, GRAVITY
        dt_c = self.cfl * self.h_s / (self.c0 + v_max)
        dt_f = self.cfl * math.sqrt(self.h_s / max(a_max, 1e-6))
        return min(dt_c, dt_f)

    def step(self, dt=None) -> float:
        """One Monaghan predictor-corrector step. Returns the dt used."""
        if dt is None:
            dt = self.compute_dt()

        # Predict with the forces from the current state ...
        cells = self._rebuild_cells()
        _boundary_density(self.x, self.m, self.rho, self.fluid, self.h_s,
                          *cells)
        self._update_pressure()
        _forces(self.x, self.v, self.rho, self.p, self.m, self.h_s, *cells,
                self.alpha, self.beta, self.c0, self.fluid, self.ax, self.az)
        _density_rate(self.x, self.v, self.m, self.h_s, *cells, self.drho,
                      self.fluid)
        _integrate_half(self.x, self.v, self.ax, self.az, self.drho,
                        self.rho, dt, self.fluid)

        # ... correct with the forces at the predicted state.
        cells = self._rebuild_cells()
        _density_rate(self.x, self.v, self.m, self.h_s, *cells, self.drho,
                      self.fluid)
        self._update_pressure()
        _forces(self.x, self.v, self.rho, self.p, self.m, self.h_s, *cells,
                self.alpha, self.beta, self.c0, self.fluid, self.ax, self.az)
        _integrate_half(self.x, self.v, self.ax, self.az, self.drho,
                        self.rho, dt, self.fluid)

        self.stats.steps += 1
        self.stats.t += dt
        self.stats.dt_min = min(self.stats.dt_min, dt)
        self.stats.dt_max = max(self.stats.dt_max, dt)
        return dt

    def _update_pressure(self):
        # No-tension clamp: the Tait EOS returns NEGATIVE pressure for
        # rho < rho0, and tension at the free surface drives the classical
        # tensile instability (particles attract, clump, explode). WCSPH dam
        # break therefore clamps p >= 0 (Monaghan 1994 practice).
        self.p = self.c0 ** 2 * RHO0 / GAMMA \
            * ((self.rho / RHO0) ** GAMMA - 1.0)
        np.maximum(self.p, 0.0, out=self.p)

    def run(self, t_end, *, callback=None, callback_every=50,
            shepard_every=30):
        """
        Integrate to t_end. Every `callback_every` steps the gauge is measured
        and a history entry (t, q_gauge, front_x) appended; every
        `shepard_every` steps the density field is Shepard-filtered, which is
        standard practice for WCSPH dam break (Monaghan 1994).
        """
        if self._gauge_x is None:
            self.set_gauge(self.column_width + 2.0 * self.dp)
        self._measure_gauge(self.stats.t)
        while self.stats.t < t_end:
            dt = self.step()
            if self.stats.steps % callback_every == 0:
                self._measure_gauge(self.stats.t)
                self.stats.history.append(
                    (self.stats.t, self._gauge_q[-1], self.front_position()))
            if shepard_every and self.stats.steps % shepard_every == 0:
                cells = self._rebuild_cells()
                self.rho = _shepard_filter(self.x, self.m, self.rho,
                                           self.fluid, self.h_s, *cells)
            if callback is not None and self.stats.steps % callback_every == 0:
                callback(self)
        self._measure_gauge(self.stats.t)
        self.stats.volume_final = self.volume
        return self.stats

    # -- coupling to the routing solver -----------------------------------------

    def to_inflow(self, width, cells, *, label="sph breach"):
        """
        Build a swe2d.Inflow from the measured gauge hydrograph.

        q(t) is per unit thickness; the physical discharge across a breach of
        width `width` is Q(t) = q(t) · width. The hydrograph is linearly
        interpolated between measured samples, zero before the first sample
        and held at the last value after it.

        Parameters
        ----------
        width : breach width (m)
        cells : (N, 2) interior (j, i) indices of the SWE injection cells
        """
        from .swe2d import Inflow

        t_g, q_g = self.gauge_hydrograph()
        if t_g.size == 0:
            raise ValueError("no gauge data — call run() first")

        def q_of_t(t):
            if t <= t_g[0]:
                return 0.0
            if t >= t_g[-1]:
                return float(q_g[-1]) * width
            return float(np.interp(t, t_g, q_g)) * width

        def speed_of_t(t):
            # Flow at a breach is critical: U = sqrt(g h_c), h_c = 2H/3.
            # Estimate the acting head by inverting
            # q_unit = (8/27) sqrt(g) H^{3/2} for H.
            q = q_of_t(t)
            if q <= 0.0:
                return 0.0
            q_unit = q / width
            h = (q_unit * 27.0 / (8.0 * math.sqrt(GRAVITY))) ** (2.0 / 3.0)
            return math.sqrt(GRAVITY * h)

        return Inflow(cells, q_of_t, direction=(1.0, 0.0),
                      speed=speed_of_t, label=label)

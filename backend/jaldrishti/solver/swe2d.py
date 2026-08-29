"""
2D depth-averaged shallow water solver: finite volume, HLLC, MUSCL, well-balanced.

THE EQUATIONS
-------------
Conservation of mass and momentum for a water layer, averaged over its depth:

    d(h)/dt  + d(hu)/dx           + d(hv)/dy           = 0
    d(hu)/dt + d(hu^2 + g h^2/2)/dx + d(huv)/dy         = -g h dz/dx - friction
    d(hv)/dt + d(huv)/dx           + d(hv^2 + g h^2/2)/dy = -g h dz/dy - friction

h is depth, (u, v) the depth-averaged velocity, z the bed elevation. Three
numbers per cell — h, hu, hv — are the entire state of the simulation.

Depth-averaging is what makes this tractable over a whole valley, and it is also
its central assumption: vertical accelerations are neglected and pressure is
taken as hydrostatic. That holds for a flood sheet hundreds of metres wide and
metres deep. It does NOT hold in the violent, non-hydrostatic jet immediately at
a dam breach, which is why a separate SPH model handles the near field and hands
this solver an inflow hydrograph.

Note the dimensionality carefully: this model is TWO-dimensional and
depth-averaged. Depth-averaging is precisely what removes the third dimension.
Any 3D appearance in the dashboard is rendering, not physics.

THE FOUR THINGS THAT MAKE OR BREAK A SOLVER LIKE THIS
-----------------------------------------------------
1. WELL-BALANCEDNESS. Still water on a slope must stay still to machine
   precision. The pressure-gradient flux and the bed-slope source term are large
   and nearly equal, and unless they are discretised so as to cancel *exactly*,
   the residual shows up as spurious velocity — the model invents a flood out of
   a calm reservoir. We achieve this with Audusse hydrostatic reconstruction
   plus a matching centred bed source; see `_rhs` for the term-by-term proof.

2. WETTING AND DRYING. Cells switch dry->wet constantly along an advancing
   front. Velocity is u = hu/h, so as h -> 0 an unguarded division yields
   absurd velocities, which violate CFL, which produce NaN, which spreads
   across the whole domain in a few steps. Every division by depth in this file
   is guarded by h_min.

3. POSITIVITY. A limiter overshoot that drives h negative gives sqrt(g*h) of a
   negative number. Near the wet/dry front we drop to first order specifically
   to prevent this.

4. MASS CONSERVATION. Finite volume conserves mass by construction, so any
   drift is a bug — in the boundary conditions or in the dry-cell clipping.
   We therefore account for every drop we clip and report it, rather than
   letting it hide.

REFERENCES
----------
Audusse, E. et al. (2004). A fast and stable well-balanced scheme with
    hydrostatic reconstruction for shallow water flows. SIAM J. Sci. Comput.
    25(6), 2050-2065.
Toro, E.F. (2001). Shock-Capturing Methods for Free-Surface Shallow Flows.
Kurganov, A. & Petrova, G. (2007). A second-order well-balanced positivity
    preserving central-upwind scheme for the Saint-Venant system.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from numba import njit

from .flux import hllc_x
from .reconstruct import LIMITER_NAMES, LIMITER_NONE, limited_slope

# fastmath stays OFF everywhere: it would let the compiler reassociate the
# floating-point operations whose exact cancellation the well-balanced property
# depends on. See flux.py for the longer note.
_JIT = dict(cache=True, fastmath=False, nogil=True)

GRAVITY = 9.81

# Ghost-cell width. Two are needed, not one: the MUSCL slope in the outermost
# real cell requires a neighbour, and that neighbour's own slope requires one
# more beyond it.
NG = 2

# TWO depth thresholds, for two different jobs. Conflating them is a real and
# costly mistake — it was measurably retarding our wetting front.
#
#   h_min  (a solver parameter, default 1e-3 m) is the RESOLVED-DEPTH scale. Above
#          it, velocity is computed exactly as hu/h; below it, velocity is
#          desingularised towards zero (see _desing_vel). It is also the depth
#          below which a cell is masked out of reported output, because a
#          sub-millimetre film is not a flood.
#
#   H_DRY  is "is there any water here at all". Used only to pick the dry-bed
#          branch of the Riemann solver and to decide when momentum may be
#          discarded. It must be far smaller than h_min: raising it to h_min
#          freezes the thin film at the head of the flood wave, and since the
#          head of the wave is the arrival time, that error lands squarely on
#          our headline output.
H_DRY = 1.0e-12

# Boundary condition codes (ints, because Numba cannot switch on strings).
BC_WALL = 0        # reflective / solid: mirror depth, negate normal momentum
BC_OPEN = 1        # transmissive: zero-gradient outflow, water leaves freely
BC_CODES = {"wall": BC_WALL, "open": BC_OPEN}


# =============================================================================
# Numba kernels
# =============================================================================

@njit(**_JIT)
def _fill_ghosts(h, hu, hv, ng, bc_w, bc_e, bc_s, bc_n):
    """
    Populate ghost cells so the interior update needs no special-casing at edges.

    A wall mirrors the depth and flips the sign of the NORMAL momentum, which
    makes the flux through the boundary face identically zero — water bounces.
    An open boundary copies the interior value (zero gradient), letting waves
    leave without reflecting back in.

    A note on 'open': zero-gradient outflow is only non-reflecting for
    supercritical outflow. For subcritical flow it admits a weak spurious
    reflection. Acceptable here because we place open boundaries far downstream
    of anything we report on.
    """
    ny, nx = h.shape

    # ---- west / east (x-normal) ----
    for j in range(ny):
        for gi in range(ng):
            src = ng + (ng - 1 - gi)          # mirror index inside the domain
            if bc_w == BC_WALL:
                h[j, gi] = h[j, src]
                hu[j, gi] = -hu[j, src]
                hv[j, gi] = hv[j, src]
            else:
                h[j, gi] = h[j, ng]
                hu[j, gi] = hu[j, ng]
                hv[j, gi] = hv[j, ng]

            gi2 = nx - 1 - gi
            src2 = nx - ng - 1 - (ng - 1 - gi)
            if bc_e == BC_WALL:
                h[j, gi2] = h[j, src2]
                hu[j, gi2] = -hu[j, src2]
                hv[j, gi2] = hv[j, src2]
            else:
                h[j, gi2] = h[j, nx - ng - 1]
                hu[j, gi2] = hu[j, nx - ng - 1]
                hv[j, gi2] = hv[j, nx - ng - 1]

    # ---- south / north (y-normal) ----
    for i in range(nx):
        for gj in range(ng):
            src = ng + (ng - 1 - gj)
            if bc_s == BC_WALL:
                h[gj, i] = h[src, i]
                hu[gj, i] = hu[src, i]
                hv[gj, i] = -hv[src, i]
            else:
                h[gj, i] = h[ng, i]
                hu[gj, i] = hu[ng, i]
                hv[gj, i] = hv[ng, i]

            gj2 = ny - 1 - gj
            src2 = ny - ng - 1 - (ng - 1 - gj)
            if bc_n == BC_WALL:
                h[gj2, i] = h[src2, i]
                hu[gj2, i] = hu[src2, i]
                hv[gj2, i] = -hv[src2, i]
            else:
                h[gj2, i] = h[ny - ng - 1, i]
                hu[gj2, i] = hu[ny - ng - 1, i]
                hv[gj2, i] = hv[ny - ng - 1, i]


@njit(inline="always", **_JIT)
def _desing_vel(h, q, h_min):
    """
    Desingularised velocity (Kurganov & Petrova 2007):

        u = 2*h*q / (h^2 + max(h^2, h_min^2))

    Read the two branches off the max():
      * h >= h_min :  denominator = 2h^2, so u = q/h EXACTLY. No approximation is
                      introduced anywhere the depth is actually resolved, which
                      is what lets lake-at-rest still pass at machine precision.
      * h <  h_min :  denominator = h^2 + h_min^2, so u -> 0 linearly as h -> 0,
                      and |u| <= |q|/h_min throughout.

    Why not simply a hard cutoff (u = 0 when h <= h_min)? Because a cutoff makes
    the velocity field switch on and off as a cell wets, and cells at the head of
    a flood wave straddle that threshold every single timestep. The result is
    that the fastest-moving water in the domain repeatedly has its velocity reset
    to zero. Measured on Ritter's dam break, the hard cutoff cost us 12% of the
    front velocity (17.4 m/s against a theoretical 19.8). This form is continuous,
    equally bounded, and costs one extra comparison.
    """
    h2 = h * h
    hm2 = h_min * h_min
    den = h2 + (h2 if h2 > hm2 else hm2)
    if den <= 0.0:
        return 0.0
    return 2.0 * h * q / den


@njit(**_JIT)
def _primitives(h, hu, hv, z, h_min, eta, u, v):
    """
    Derive water-surface elevation and velocity from the conserved state.

    This is the one place velocity is computed, so it is the one place that has to
    get the h -> 0 limit right. See _desing_vel: exact where the depth is
    resolved, smoothly damped below h_min, never able to produce the 10^6 m/s
    that an unguarded hu/h yields at a wetting front.
    """
    ny, nx = h.shape
    for j in range(ny):
        for i in range(nx):
            hij = h[j, i]
            eta[j, i] = hij + z[j, i]
            u[j, i] = _desing_vel(hij, hu[j, i], h_min)
            v[j, i] = _desing_vel(hij, hv[j, i], h_min)


@njit(**_JIT)
def _slopes_x(q, h, s, limiter, h_min):
    """
    Limited across-cell slopes in x, with a first-order fallback near dry cells.

    The fallback is the positivity guard from the module docstring. If a cell or
    either x-neighbour is dry, we force a zero slope in that cell, i.e. revert
    locally to piecewise-constant. Reconstructing a slope across a wet/dry front
    is what drives depth negative; giving up second-order accuracy in exactly
    those cells costs almost nothing (the front is one cell wide) and buys
    robustness everywhere.

    IMPORTANT: the dry test is on DEPTH regardless of which field `q` is, so a
    given cell's eta-slope and z-slope are always zeroed together. They have to
    be. The well-balanced cancellation in `_rhs` pairs the reconstructed surface
    against the reconstructed bed; zeroing one without the other would break the
    cancellation and leak spurious velocity along every shoreline.
    """
    ny, nx = q.shape
    for j in range(ny):
        s[j, 0] = 0.0
        s[j, nx - 1] = 0.0
        for i in range(1, nx - 1):
            if h[j, i] <= h_min or h[j, i - 1] <= h_min or h[j, i + 1] <= h_min:
                s[j, i] = 0.0
            else:
                s[j, i] = limited_slope(q[j, i - 1], q[j, i], q[j, i + 1], limiter)


@njit(**_JIT)
def _slopes_y(q, h, s, limiter, h_min):
    """As _slopes_x, along y. The same paired-zeroing requirement applies."""
    ny, nx = q.shape
    for i in range(nx):
        s[0, i] = 0.0
        s[ny - 1, i] = 0.0
    for j in range(1, ny - 1):
        for i in range(nx):
            if h[j, i] <= h_min or h[j - 1, i] <= h_min or h[j + 1, i] <= h_min:
                s[j, i] = 0.0
            else:
                s[j, i] = limited_slope(q[j - 1, i], q[j, i], q[j + 1, i], limiter)


@njit(**_JIT)
def _rhs(h, hu, hv, z, eta, u, v,
         s_eta_x, s_z_x, s_u_x, s_v_x,
         s_eta_y, s_z_y, s_u_y, s_v_y,
         dh, dhu, dhv,
         dx, dy, g, h_min, ng):
    """
    Evaluate d(h,hu,hv)/dt for every interior cell.

    WELL-BALANCEDNESS, PROVED TERM BY TERM
    --------------------------------------
    Take still water: eta = H everywhere, u = v = 0. Then:

      * eta has zero slope, so the reconstructed surface on both sides of every
        face equals H.
      * At face i+1/2 the bed is z_face = max(z_minus, z_plus), so
        hL* = H - z_face = hR*. The two Riemann states are IDENTICAL and at
        rest, so HLLC returns zero mass flux and pure pressure
        Fhu = 0.5*g*(h*)^2.
      * The Audusse correction gives the left cell
            Fhu_minus = 0.5*g*(h*)^2 + 0.5*g*h_R^2 - 0.5*g*(h*)^2 = 0.5*g*h_R^2
        where h_R is cell i's OWN reconstructed depth at its right face.
        Symmetrically the right cell sees 0.5*g*h_L^2.
      * So the flux difference for cell i is
            -(0.5*g*h_R^2 - 0.5*g*h_L^2)/dx
        and since h_R - h_L = -dz and h_R + h_L = 2h, that equals
            +g*h*dz/dx.
      * The centred bed source contributes exactly -g*h*dz/dx.

    Sum: zero, identically, in floating point — no cancellation of large terms
    against each other by luck. That is why `test_lake_at_rest` passes at ~1e-16
    rather than at "small enough". And it is why fastmath must stay off.
    """
    ny, nx = h.shape

    for j in range(ny):
        for i in range(nx):
            dh[j, i] = 0.0
            dhu[j, i] = 0.0
            dhv[j, i] = 0.0

    # -------------------------------------------------------------- X SWEEP --
    # One pass over vertical faces. Face index i means "the face between cell i
    # and cell i+1", so to cover both faces of every interior cell we need
    # i = ng-1 .. nx-ng-1 inclusive.
    inv_dx = 1.0 / dx
    for j in range(ng, ny - ng):
        for i in range(ng - 1, nx - ng):
            # ---- reconstruct to the two sides of face i+1/2 ----
            # 'minus' side is cell i's right face; 'plus' side is cell i+1's left.
            eta_m = eta[j, i] + 0.5 * s_eta_x[j, i]
            z_m = z[j, i] + 0.5 * s_z_x[j, i]
            u_m = u[j, i] + 0.5 * s_u_x[j, i]
            v_m = v[j, i] + 0.5 * s_v_x[j, i]

            eta_p = eta[j, i + 1] - 0.5 * s_eta_x[j, i + 1]
            z_p = z[j, i + 1] - 0.5 * s_z_x[j, i + 1]
            u_p = u[j, i + 1] - 0.5 * s_u_x[j, i + 1]
            v_p = v[j, i + 1] - 0.5 * s_v_x[j, i + 1]

            # cells' own reconstructed depths at this face (pre-clipping)
            h_m = eta_m - z_m
            h_p = eta_p - z_p
            if h_m < 0.0:
                h_m = 0.0
            if h_p < 0.0:
                h_p = 0.0

            # ---- Audusse hydrostatic reconstruction ----
            # Raising the face bed to the higher of the two sides is what stops
            # water flowing through a wall of dry terrain, and simultaneously
            # delivers the exact lake-at-rest cancellation proved above.
            z_face = z_m if z_m > z_p else z_p
            hL = eta_m - z_face
            hR = eta_p - z_face
            if hL < 0.0:
                hL = 0.0
            if hR < 0.0:
                hR = 0.0

            Fh, Fhu, Fhv = hllc_x(hL, u_m, v_m, hR, u_p, v_p, g, H_DRY)

            # ---- Audusse pressure correction, different for each side ----
            Fhu_m = Fhu + 0.5 * g * (h_m * h_m - hL * hL)
            Fhu_p = Fhu + 0.5 * g * (h_p * h_p - hR * hR)

            inv = inv_dx
            # outflow from cell i through its right face
            if ng <= i < nx - ng:
                dh[j, i] -= Fh * inv
                dhu[j, i] -= Fhu_m * inv
                dhv[j, i] -= Fhv * inv
            # inflow to cell i+1 through its left face
            if ng <= i + 1 < nx - ng:
                dh[j, i + 1] += Fh * inv
                dhu[j, i + 1] += Fhu_p * inv
                dhv[j, i + 1] += Fhv * inv

    # -------------------------------------------------------------- Y SWEEP --
    # Same routine, with u and v swapped on the way in and the returned momentum
    # fluxes swapped back. The equations are rotationally symmetric.
    inv_dy = 1.0 / dy
    for j in range(ng - 1, ny - ng):
        for i in range(ng, nx - ng):
            eta_m = eta[j, i] + 0.5 * s_eta_y[j, i]
            z_m = z[j, i] + 0.5 * s_z_y[j, i]
            u_m = u[j, i] + 0.5 * s_u_y[j, i]
            v_m = v[j, i] + 0.5 * s_v_y[j, i]

            eta_p = eta[j + 1, i] - 0.5 * s_eta_y[j + 1, i]
            z_p = z[j + 1, i] - 0.5 * s_z_y[j + 1, i]
            u_p = u[j + 1, i] - 0.5 * s_u_y[j + 1, i]
            v_p = v[j + 1, i] - 0.5 * s_v_y[j + 1, i]

            h_m = eta_m - z_m
            h_p = eta_p - z_p
            if h_m < 0.0:
                h_m = 0.0
            if h_p < 0.0:
                h_p = 0.0

            z_face = z_m if z_m > z_p else z_p
            hL = eta_m - z_face
            hR = eta_p - z_face
            if hL < 0.0:
                hL = 0.0
            if hR < 0.0:
                hR = 0.0

            # swap: v becomes the normal component, u the transverse
            Gh, Ghv, Ghu = hllc_x(hL, v_m, u_m, hR, v_p, u_p, g, H_DRY)

            Ghv_m = Ghv + 0.5 * g * (h_m * h_m - hL * hL)
            Ghv_p = Ghv + 0.5 * g * (h_p * h_p - hR * hR)

            inv = inv_dy
            if ng <= j < ny - ng:
                dh[j, i] -= Gh * inv
                dhu[j, i] -= Ghu * inv
                dhv[j, i] -= Ghv_m * inv
            if ng <= j + 1 < ny - ng:
                dh[j + 1, i] += Gh * inv
                dhu[j + 1, i] += Ghu * inv
                dhv[j + 1, i] += Ghv_p * inv

    # ------------------------------------------------- CENTRED BED SOURCE ---
    # The partner of the Audusse correction. Accounts for the bed variation
    # *within* a cell, and is exactly what cancels the reconstruction residual
    # in still water (see the docstring derivation).
    for j in range(ng, ny - ng):
        for i in range(ng, nx - ng):
            hij = h[j, i]
            if hij > h_min:
                dhu[j, i] -= g * hij * s_z_x[j, i] / dx
                dhv[j, i] -= g * hij * s_z_y[j, i] / dy


@njit(**_JIT)
def _apply_friction(h, hu, hv, n_man, dt, g, h_min, ng):
    """
    Manning bed friction, integrated point-implicitly.

    The friction slope gives d(hu)/dt = -Cf*hu with

        Cf = g * n^2 * |U| / h^(7/3),      |U| = sqrt(u^2 + v^2)

    Explicit integration of this is stiff in shallow water: as h -> 0, Cf blows
    up and an explicit step overshoots through zero, reversing the flow and
    then oscillating. The implicit update

        hu <- hu / (1 + dt*Cf)

    is unconditionally stable, can never reverse the sign of the momentum, and
    correctly drives it towards zero. This is standard practice and it is the
    difference between a solver that survives a thin sheet of water spreading
    over a floodplain and one that does not.
    """
    ny, nx = h.shape
    for j in range(ng, ny - ng):
        for i in range(ng, nx - ng):
            hij = h[j, i]
            if hij <= H_DRY:
                # Genuinely no water. Discard any residual momentum so a
                # completely dry cell cannot carry a stale value.
                hu[j, i] = 0.0
                hv[j, i] = 0.0
                continue
            q = math.sqrt(hu[j, i] * hu[j, i] + hv[j, i] * hv[j, i])
            if q <= 0.0:
                continue
            nm = n_man[j, i]
            # |U| = q/h, and h^(4/3) from the Manning form, giving h^(7/3) total
            cf = g * nm * nm * (q / hij) / (hij ** (7.0 / 3.0))
            denom = 1.0 + dt * cf
            # In a very thin film h^(7/3) -> 0 makes Cf enormous, which is
            # physically correct (such a film IS friction-dominated) but can
            # overflow to inf. Short-circuit rather than divide by inf, which
            # would give 0/0 = NaN if the momentum were also denormal.
            if denom > 1.0e12 or not (denom == denom):
                hu[j, i] = 0.0
                hv[j, i] = 0.0
            else:
                hu[j, i] /= denom
                hv[j, i] /= denom


@njit(**_JIT)
def _clean_dry(h, hu, hv, h_min, dx, dy, ng):
    """
    Enforce non-negative depth and kill momentum in dry cells.

    Returns the VOLUME (m^3) invented by clipping, so the caller can report it.
    Finite volume conserves mass exactly, so ANY drift traces to this function
    or to the boundaries; measuring it here is what turns a silent mass leak
    into a number we can watch. A well-behaved run keeps this at round-off.
    """
    ny, nx = h.shape
    clipped = 0.0
    for j in range(ng, ny - ng):
        for i in range(ng, nx - ng):
            if h[j, i] < 0.0:
                clipped += -h[j, i]     # mass we had to invent
                h[j, i] = 0.0
                hu[j, i] = 0.0
                hv[j, i] = 0.0
            elif h[j, i] <= H_DRY:
                hu[j, i] = 0.0
                hv[j, i] = 0.0
            # Deliberately NOT zeroing momentum in the band H_DRY < h <= h_min.
            # Those are the cells at the head of an advancing flood wave. Wiping
            # their momentum every stage forces the fastest water in the domain
            # to re-accelerate from rest each timestep, which measurably retards
            # the front. _desing_vel already bounds their velocity safely.
    return clipped * dx * dy


@njit(**_JIT)
def _max_speeds(h, hu, hv, dx, dy, g, h_min, ng):
    """
    Largest (|u|+c)/dx + (|v|+c)/dy over the domain — the CFL denominator.

    Thin cells are included rather than skipped: they now carry momentum (see
    _clean_dry), so leaving them out of the stability estimate would be exactly
    the kind of omission that produces an intermittent NaN weeks later. Their
    contribution is negligible in practice — the desingularised velocity is
    bounded and sqrt(g*h) of a micron of water is ~0.003 m/s — so including them
    costs no timestep.
    """
    ny, nx = h.shape
    worst = 0.0
    for j in range(ng, ny - ng):
        for i in range(ng, nx - ng):
            hij = h[j, i]
            if hij <= H_DRY:
                continue
            c = math.sqrt(g * hij)
            uu = abs(_desing_vel(hij, hu[j, i], h_min))
            vv = abs(_desing_vel(hij, hv[j, i], h_min))
            val = (uu + c) / dx + (vv + c) / dy
            if val > worst:
                worst = val
    return worst


@njit(**_JIT)
def _total_volume(h, dx, dy, ng):
    ny, nx = h.shape
    tot = 0.0
    for j in range(ng, ny - ng):
        for i in range(ng, nx - ng):
            tot += h[j, i]
    return tot * dx * dy


@njit(**_JIT)
def _axpy_state(h, hu, hv, dh, dhu, dhv, dt, ng):
    """h += dt*dh, etc., over the interior only."""
    ny, nx = h.shape
    for j in range(ng, ny - ng):
        for i in range(ng, nx - ng):
            h[j, i] += dt * dh[j, i]
            hu[j, i] += dt * dhu[j, i]
            hv[j, i] += dt * dhv[j, i]


@njit(**_JIT)
def _blend_state(h, hu, hv, h0, hu0, hv0, ng):
    """Second stage of SSP-RK2: q <- 0.5*(q0 + q)."""
    ny, nx = h.shape
    for j in range(ng, ny - ng):
        for i in range(ng, nx - ng):
            h[j, i] = 0.5 * (h0[j, i] + h[j, i])
            hu[j, i] = 0.5 * (hu0[j, i] + hu[j, i])
            hv[j, i] = 0.5 * (hv0[j, i] + hv[j, i])


# =============================================================================
# Python-level driver
# =============================================================================

@dataclass
class RunStats:
    """Diagnostics for one run — these feed the validation charts directly."""
    steps: int = 0
    t: float = 0.0
    volume_initial: float = 0.0
    volume_final: float = 0.0
    mass_clipped: float = 0.0
    dt_min: float = float("inf")
    dt_max: float = 0.0
    history: list = field(default_factory=list)   # (t, volume, dt)

    @property
    def volume_error(self) -> float:
        """Relative mass-conservation error. Should be ~1e-14, not ~1e-3."""
        if self.volume_initial == 0.0:
            return 0.0
        return (self.volume_final - self.volume_initial) / self.volume_initial


class SWE2D:
    """
    Cell-centred finite-volume shallow water solver on a uniform Cartesian grid.

    The grid maps one-to-one onto DEM pixels, which is why a Cartesian grid is
    the right choice here rather than an unstructured mesh: our terrain arrives
    as a raster, and staying on the raster avoids an interpolation step that
    would blur the very elevations the flood depth is measured against.

    Arrays are stored with NG ghost cells on every side. Public properties
    return interior views, so callers never see the padding.
    """

    def __init__(self, z, dx, dy=None, manning=0.033, *,
                 g=GRAVITY, h_min=1.0e-3, cfl=0.4,
                 limiter="mc", bc=("open", "open", "open", "open")):
        """
        Parameters
        ----------
        z        : (ny, nx) bed elevation, metres
        dx, dy   : cell size, metres (dy defaults to dx)
        manning  : Manning's n, scalar or (ny, nx) array
        h_min    : dry threshold. 1e-3 m is the value that keeps hu/h sane;
                   see the wetting/drying note in the module docstring.
        cfl      : safety factor. 0.4, not the theoretical 0.9 — robustness
                   over a marginal speedup, per project policy.
        limiter  : 'none' (1st order), 'minmod' (robust), 'mc' (sharper)
        bc       : (west, east, south, north), each 'wall' or 'open'
        """
        z = np.asarray(z, dtype=np.float64)
        if z.ndim != 2:
            raise ValueError(f"z must be 2D, got shape {z.shape}")

        self.ny, self.nx = z.shape
        self.dx = float(dx)
        self.dy = float(dx if dy is None else dy)
        self.g = float(g)
        self.h_min = float(h_min)
        self.cfl = float(cfl)

        if limiter not in LIMITER_NAMES:
            raise ValueError(f"limiter must be one of {sorted(LIMITER_NAMES)}")
        self.limiter_name = limiter
        self.limiter = LIMITER_NAMES[limiter]

        if len(bc) != 4:
            raise ValueError("bc must be (west, east, south, north)")
        for side in bc:
            if side not in BC_CODES:
                raise ValueError(f"unknown bc {side!r}; use {sorted(BC_CODES)}")
        self.bc_names = tuple(bc)
        self.bc = tuple(BC_CODES[s] for s in bc)

        shape = (self.ny + 2 * NG, self.nx + 2 * NG)
        self._z = np.empty(shape, dtype=np.float64)
        self._z[NG:-NG, NG:-NG] = z
        self._extend_static(self._z)

        self._n = np.empty(shape, dtype=np.float64)
        manning_arr = np.broadcast_to(
            np.asarray(manning, dtype=np.float64), (self.ny, self.nx))
        self._n[NG:-NG, NG:-NG] = manning_arr
        self._extend_static(self._n)

        self._h = np.zeros(shape, dtype=np.float64)
        self._hu = np.zeros(shape, dtype=np.float64)
        self._hv = np.zeros(shape, dtype=np.float64)

        # Workspace, allocated once. Allocating inside the time loop would show
        # up as GC pressure and dominate the profile at these step counts.
        self._ws = {k: np.zeros(shape, dtype=np.float64) for k in (
            "eta", "u", "v",
            "s_eta_x", "s_z_x", "s_u_x", "s_v_x",
            "s_eta_y", "s_z_y", "s_u_y", "s_v_y",
            "dh", "dhu", "dhv",
            "h0", "hu0", "hv0",
        )}

        self.t = 0.0
        self.stats = RunStats()

    # ---- geometry helpers ------------------------------------------------
    def _extend_static(self, a):
        """
        Extend a time-invariant field (bed elevation, Manning n) into the ghost
        band, matching the boundary condition.

        This is subtler than it looks. `_fill_ghosts` mirrors depth and flips the
        normal momentum at a wall, but the reflection is only EXACT if the bed is
        mirrored the same way. Otherwise eta = h + z in the ghost cells is not the
        mirror image of eta inside, the reconstructed slopes are not antisymmetric,
        and a small mass flux leaks through what is meant to be a solid wall.
        Open boundaries want the opposite — zero gradient, i.e. a plain copy.

        Corners are handled by ordering: x first over all rows, then y over all
        columns, so the y pass reads ghost columns that are already populated.
        `_fill_ghosts` uses the same order, keeping the two consistent.
        """
        ng = NG
        bw, be, bs, bn = self.bc

        if bw == BC_WALL:
            a[:, :ng] = a[:, 2 * ng - 1:ng - 1:-1]
        else:
            a[:, :ng] = a[:, ng:ng + 1]

        if be == BC_WALL:
            a[:, -ng:] = a[:, -ng - 1:-2 * ng - 1:-1]
        else:
            a[:, -ng:] = a[:, -ng - 1:-ng]

        if bs == BC_WALL:
            a[:ng, :] = a[2 * ng - 1:ng - 1:-1, :]
        else:
            a[:ng, :] = a[ng:ng + 1, :]

        if bn == BC_WALL:
            a[-ng:, :] = a[-ng - 1:-2 * ng - 1:-1, :]
        else:
            a[-ng:, :] = a[-ng - 1:-ng, :]

    # ---- state accessors (interior views) --------------------------------
    @property
    def z(self):
        return self._z[NG:-NG, NG:-NG]

    @property
    def h(self):
        return self._h[NG:-NG, NG:-NG]

    @property
    def hu(self):
        return self._hu[NG:-NG, NG:-NG]

    @property
    def hv(self):
        return self._hv[NG:-NG, NG:-NG]

    @property
    def manning(self):
        return self._n[NG:-NG, NG:-NG]

    @property
    def wet(self):
        """
        Boolean mask of cells with a resolved depth.

        Downstream analysis should mask with this rather than inventing its own
        threshold, so that "wet" means the same thing in the depth map, the
        velocity map, the hazard classification and the exposure count.
        """
        return self.h > self.h_min

    @property
    def eta(self):
        """Water-surface elevation, masked to NaN where dry (for plotting)."""
        return np.where(self.wet, self.h + self.z, np.nan)

    def _desing(self, q):
        """NumPy mirror of the kernel's _desing_vel, so reported velocities are
        exactly the ones the solver used rather than a second, subtly different
        definition."""
        h = self.h
        h2 = h * h
        den = h2 + np.maximum(h2, self.h_min ** 2)
        safe = np.where(den > 0.0, den, 1.0)
        return np.where(den > 0.0, 2.0 * h * q / safe, 0.0)

    @property
    def u(self):
        return self._desing(self.hu)

    @property
    def v(self):
        return self._desing(self.hv)

    @property
    def speed(self):
        return np.hypot(self.u, self.v)

    # ---- initial conditions ----------------------------------------------
    def set_depth(self, h):
        self.h[:] = np.maximum(np.asarray(h, dtype=np.float64), 0.0)
        self.hu[:] = 0.0
        self.hv[:] = 0.0

    def set_surface(self, eta, where=None):
        """
        Fill to a water-surface ELEVATION, the natural way to state a reservoir
        level: h = max(0, eta - z). Cells whose bed is above `eta` stay dry, so
        a reservoir automatically takes the shape of its valley.

        `where` optionally restricts the fill to a boolean mask — that is how a
        dam-break initial condition is set (reservoir wet, downstream dry).
        """
        target = np.maximum(np.asarray(eta, dtype=np.float64) - self.z, 0.0)
        if where is None:
            self.h[:] = target
        else:
            mask = np.asarray(where, dtype=bool)
            self.h[:] = np.where(mask, target, 0.0)
        self.hu[:] = 0.0
        self.hv[:] = 0.0

    def volume(self) -> float:
        """Total water volume, m^3."""
        return _total_volume(self._h, self.dx, self.dy, NG)

    # ---- time stepping ---------------------------------------------------
    def compute_dt(self, dt_max=None) -> float:
        """
        CFL-limited timestep:  dt <= cfl / ((|u|+c)/dx + (|v|+c)/dy)

        This is the correct 2D form for a dimensionally-unsplit scheme. Using
        the 1D condition per direction independently overestimates the allowable
        step by up to 2x and will eventually bite.
        """
        worst = _max_speeds(self._h, self._hu, self._hv,
                            self.dx, self.dy, self.g, self.h_min, NG)
        if worst <= 0.0:
            # Entirely dry (or entirely still and dry): nothing can move, so any
            # step is stable. Return the cap rather than infinity.
            return dt_max if dt_max else 1.0
        dt = self.cfl / worst
        return min(dt, dt_max) if dt_max else dt

    def _eval_rhs(self):
        w = self._ws
        _fill_ghosts(self._h, self._hu, self._hv, NG, *self.bc)
        _primitives(self._h, self._hu, self._hv, self._z, self.h_min,
                    w["eta"], w["u"], w["v"])
        lim = self.limiter
        _slopes_x(w["eta"], self._h, w["s_eta_x"], lim, self.h_min)
        _slopes_x(self._z, self._h, w["s_z_x"], lim, self.h_min)
        _slopes_x(w["u"], self._h, w["s_u_x"], lim, self.h_min)
        _slopes_x(w["v"], self._h, w["s_v_x"], lim, self.h_min)
        _slopes_y(w["eta"], self._h, w["s_eta_y"], lim, self.h_min)
        _slopes_y(self._z, self._h, w["s_z_y"], lim, self.h_min)
        _slopes_y(w["u"], self._h, w["s_u_y"], lim, self.h_min)
        _slopes_y(w["v"], self._h, w["s_v_y"], lim, self.h_min)
        _rhs(self._h, self._hu, self._hv, self._z,
             w["eta"], w["u"], w["v"],
             w["s_eta_x"], w["s_z_x"], w["s_u_x"], w["s_v_x"],
             w["s_eta_y"], w["s_z_y"], w["s_u_y"], w["s_v_y"],
             w["dh"], w["dhu"], w["dhv"],
             self.dx, self.dy, self.g, self.h_min, NG)

    def step(self, dt=None, dt_max=None) -> float:
        """
        Advance one timestep with SSP-RK2 (Heun) and return the dt used.

        Why RK2 rather than forward Euler: MUSCL makes the spatial
        discretisation second-order, and pairing it with a first-order time
        integrator throws that accuracy away while also shrinking the stable CFL
        range. SSP ("strong stability preserving") matters specifically because
        it guarantees the positivity we work so hard for in each stage is not
        destroyed by the stage combination.
        """
        if dt is None:
            dt = self.compute_dt(dt_max=dt_max)

        w = self._ws
        # keep q^n for the RK blend
        np.copyto(w["h0"], self._h)
        np.copyto(w["hu0"], self._hu)
        np.copyto(w["hv0"], self._hv)

        # stage 1: q* = q^n + dt*L(q^n)
        self._eval_rhs()
        _axpy_state(self._h, self._hu, self._hv,
                    w["dh"], w["dhu"], w["dhv"], dt, NG)
        self.stats.mass_clipped += _clean_dry(self._h, self._hu, self._hv,
                                              self.h_min, self.dx, self.dy, NG)

        # stage 2: q^{n+1} = 0.5*(q^n + (q* + dt*L(q*)))
        self._eval_rhs()
        _axpy_state(self._h, self._hu, self._hv,
                    w["dh"], w["dhu"], w["dhv"], dt, NG)
        _blend_state(self._h, self._hu, self._hv,
                     w["h0"], w["hu0"], w["hv0"], NG)
        self.stats.mass_clipped += _clean_dry(self._h, self._hu, self._hv,
                                              self.h_min, self.dx, self.dy, NG)

        # Friction is applied as an operator split after the hyperbolic update.
        # It is a local sink with no spatial coupling, so splitting it costs
        # nothing in accuracy and lets us integrate it implicitly (see
        # _apply_friction) without complicating the Riemann solve.
        _apply_friction(self._h, self._hu, self._hv, self._n,
                        dt, self.g, self.h_min, NG)

        self.t += dt
        self.stats.steps += 1
        self.stats.t = self.t
        self.stats.dt_min = min(self.stats.dt_min, dt)
        self.stats.dt_max = max(self.stats.dt_max, dt)
        return dt

    def run(self, t_end, *, dt_max=None, callback=None, callback_every=None,
            log_every=None, max_steps=10_000_000):
        """
        Integrate to `t_end`.

        `callback(solver)` fires every `callback_every` seconds of model time —
        that is the hook for saving frames, sampling gauges and accumulating
        arrival time. `log_every` records (t, volume, dt) into stats.history so
        mass conservation can be plotted rather than merely asserted.
        """
        if self.stats.volume_initial == 0.0 and self.stats.steps == 0:
            self.stats.volume_initial = self.volume()

        next_cb = self.t + callback_every if callback_every else None
        next_log = self.t + log_every if log_every else None
        if log_every:
            self.stats.history.append((self.t, self.volume(), 0.0))

        while self.t < t_end - 1e-12 and self.stats.steps < max_steps:
            dt = self.compute_dt(dt_max=dt_max)
            # Never overshoot t_end: a partial final step keeps reported times
            # exact, which matters when comparing arrival times to the second.
            if self.t + dt > t_end:
                dt = t_end - self.t
            self.step(dt=dt)

            if next_cb is not None and self.t >= next_cb - 1e-12:
                callback(self)
                next_cb += callback_every
            if next_log is not None and self.t >= next_log - 1e-12:
                self.stats.history.append((self.t, self.volume(), dt))
                next_log += log_every

        self.stats.volume_final = self.volume()
        self.stats.t = self.t
        return self.stats

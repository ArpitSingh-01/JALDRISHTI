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

# How many cells inward from an OPEN boundary the transmissive condition
# measurably contaminates the solution. A zero-gradient outflow cannot be exact
# for both still water and uniform flow on a slope (see _extend_static for the
# derivation and the measurements); we choose the still-water-exact form, which
# leaves a backwater at the outflow decaying from +37% depth in the edge cell to
# under 1% by the eighth cell. Ten is that measured extent with margin.
#
# This is a REPORTING mask, not a solver parameter — nothing in the timestep
# reads it. Results within this many cells of an open boundary should not be
# quoted, and the domain must therefore extend at least this far beyond anything
# of interest: 900 m at 90 m resolution, 300 m at 30 m.
OPEN_BC_INFLUENCE_CELLS = 10


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

        Cf = g * n^2 * |U| / h^(4/3),      |U| = sqrt(u^2 + v^2)

    Note the exponent is 4/3 with |U| (a VELOCITY) in the numerator. Cf is a
    rate, so it must have units of 1/s: g*n^2*|U|/h^(4/3) does, and the same
    expression over h^(7/3) does not. The code below writes it over h^(7/3)
    because it uses the conserved momentum q = h*|U| in the numerator instead,
    which is algebraically identical -- see the comment at the cf assignment,
    which also records the bug this replaced.

    Explicit integration of this is stiff in shallow water: as h -> 0, Cf blows
    up and an explicit step overshoots through zero, reversing the flow and
    then oscillating. The implicit update

        hu <- hu / (1 + dt*Cf)

    is unconditionally stable, can never reverse the sign of the momentum, and
    correctly drives it towards zero. This is standard practice and it is the
    difference between a solver that survives a thin sheet of water spreading
    over a floodplain and one that does not.

    It is also better than merely stable: with h held fixed the substep is the
    EXACT solution of its own ODE. dU/dt = -k|U|U with k = g*n^2/h^(4/3) has the
    solution U(t) = U0 / (1 + k*|U0|*t), and evaluating Cf at U0 reproduces that
    at t = dt for ANY dt, not just small ones. Direction is preserved so |U|
    obeys the scalar ODE in 2D too. Consequence: the whole friction time-error
    budget lives in the operator split, not here. Because Cf is evaluated after
    the hyperbolic update rather than before, steady state lands slightly below
    Manning normal velocity,

        u_steady / u_normal = 1 - dt*g*S0 / (2*u_normal) + O(dt^2),

    which is sub-percent at the working timestep and biases arrival times LATE
    (the safe direction for an evacuation product). It grows as dt*g*S0/u, so
    shallow slow flow on a coarse grid is where it matters. Both properties are
    asserted in tests/test_friction.py.
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
            # Cf = g * n^2 * |U| / h^(4/3). Written in terms of the CONSERVED
            # momentum q = h*|U| this is g * n^2 * q / h^(7/3), which is the form
            # used here because q is what we already have.
            #
            # Do NOT also divide q by h. That was the original bug: it computed
            # g*n^2*|U|/h^(7/3), which has units of 1/(m*s) rather than 1/s and
            # is wrong by exactly a factor of h. It over-damped thin films by 10x
            # at 0.1 m and under-damped deep flow by 20x at 20 m, so a forested
            # gorge at n = 0.087 behaved like smooth concrete and every arrival
            # time came out far too early. Nothing caught it because Ritter,
            # Stoker and lake-at-rest are all frictionless. The check that pins
            # it down is Manning normal depth — see tests/test_friction.py.
            cf = g * nm * nm * q / (hij ** (7.0 / 3.0))
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


@njit(**_JIT)
def _add_source(dh, dhu, dhv, cj, ci, rate, mom_x, mom_y):
    """
    Inject a volumetric source into the right-hand side.

    `rate[k]` is Q_k/(dx*dy) in m/s — the rate at which depth grows in cell k.
    `mom_x/y[k]` is Q_k*U*e/(dx*dy) in m^2/s^2, the matching momentum influx.

    Because mass and momentum are added in a fixed ratio U, the injected water
    has velocity exactly U from the very first step: hu/h = (rate*U*dt)/(rate*dt).
    That self-consistency is what stops an inflow into a dry cell from producing
    a spurious velocity spike, which is the usual failure mode of a naive source
    term.

    Added to the RHS rather than applied as an operator split, so the source
    participates in both RK stages and is integrated to the same second-order
    accuracy as the fluxes. A hydrograph near its peak changes appreciably within
    one timestep, and splitting it would evaluate it at one time only.
    """
    for k in range(cj.size):
        j = cj[k]
        i = ci[k]
        dh[j, i] += rate[k]
        dhu[j, i] += mom_x[k]
        dhv[j, i] += mom_y[k]


@njit(**_JIT)
def _accumulate_fields(h, hu, hv, h_min, t, thresh,
                       h_max, speed_max, dv_max, t_arrival, ng):
    """
    Update the running maxima and first-arrival time over the whole domain.

    WHY THIS IS A KERNEL AND NOT A CALLBACK
    ---------------------------------------
    Arrival time is this project's headline output, and it is a FIRST-CROSSING
    time: sampling it every few seconds of model time would quantise it to the
    sampling interval and, worse, would miss the maximum depth entirely if the
    peak passed between samples. It has to be evaluated every step.

    A Python callback doing that on a million-cell array 20,000 times costs
    minutes. In Numba it costs a few percent of one flux evaluation, so there is
    no reason to compromise.

    `t_arrival` uses -1 as "never arrived" rather than NaN, because a NaN
    comparison is always false and the `< 0.0` test would then never fire, so the
    first arrival would never be recorded. The public accessor converts to NaN.
    """
    ny, nx = h.shape
    for j in range(ng, ny - ng):
        for i in range(ng, nx - ng):
            hij = h[j, i]
            if hij > h_max[j, i]:
                h_max[j, i] = hij
            if hij > h_min:
                u = _desing_vel(hij, hu[j, i], h_min)
                v = _desing_vel(hij, hv[j, i], h_min)
                s = math.sqrt(u * u + v * v)
                if s > speed_max[j, i]:
                    speed_max[j, i] = s
                # Depth x velocity: the standard hazard variable, because it is
                # proportional to the drag force per unit width on a person or
                # a wall. Tracked as its own maximum, NOT as h_max*speed_max,
                # which would multiply two peaks that occur at different times
                # and overstate the hazard.
                dv = hij * s
                if dv > dv_max[j, i]:
                    dv_max[j, i] = dv
            if hij >= thresh and t_arrival[j, i] < 0.0:
                t_arrival[j, i] = t


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
    volume_injected: float = 0.0
    mass_clipped: float = 0.0
    dt_min: float = float("inf")
    dt_max: float = 0.0
    history: list = field(default_factory=list)   # (t, volume, dt, Q_in)

    @property
    def volume_error(self) -> float:
        """
        Relative mass-conservation error. Should be ~1e-14, not ~1e-3.

        Injected volume is credited, so a run with an inflow hydrograph is held
        to the same standard as a closed one. With OPEN boundaries this becomes a
        lower bound on conservation rather than a test of it, because water is
        legitimately allowed to leave the domain — use walls when the intent is
        to verify conservation.
        """
        expected = self.volume_initial + self.volume_injected
        if expected == 0.0:
            return 0.0
        return (self.volume_final - expected) / expected


@dataclass
class Inflow:
    """
    A discharge hydrograph injected over a set of cells.

    This is the solver's interface to the outside world, and it is deliberately
    the ONLY one. A dam breach, an SPH near-field handover, a gauged tributary
    and a published design flood all arrive here as Q(t), so the routing core
    never learns which it was.

    Parameters
    ----------
    cells     : (N, 2) array of interior (j, i) indices to inject into
    q         : callable t -> TOTAL discharge across all cells, m^3/s
    direction : (ex, ey) unit vector for the momentum, or None for mass only
    speed     : callable t -> inflow speed (m/s), or a constant. Required when
                direction is set.
    weights   : per-cell share of the discharge; defaults to equal.

    MASS-ONLY VERSUS DIRECTED
    -------------------------
    With direction=None only mass is added and the water leaves the source cells
    under its own pressure gradient. That is the conservative default: it assumes
    nothing about the jet, and on the steep Himalayan gradients of our study
    reaches the terrain establishes the flow direction within a few cells anyway.

    Its weakness is at the very start, where a mound of water on a flat-ish reach
    spreads in all directions including upstream. Supplying direction and speed
    fixes that, and for a dam breach both are known rather than guessed: flow at
    a breach is critical, so U = sqrt(g*h_c) with h_c = 2H/3 — which is exactly
    the velocity `scenario.breach` reports alongside the discharge.
    """
    cells: np.ndarray
    q: object
    direction: tuple | None = None
    speed: object = None
    weights: np.ndarray | None = None
    label: str = "inflow"

    def __post_init__(self):
        cells = np.asarray(self.cells, dtype=np.int64)
        if cells.ndim == 1:
            cells = cells.reshape(1, 2)
        if cells.ndim != 2 or cells.shape[1] != 2:
            raise ValueError("cells must be an (N, 2) array of (j, i) indices")
        if cells.shape[0] == 0:
            raise ValueError("inflow has no cells")
        self.cells = cells

        if self.weights is None:
            w = np.full(cells.shape[0], 1.0 / cells.shape[0])
        else:
            w = np.asarray(self.weights, dtype=np.float64).ravel()
            if w.size != cells.shape[0]:
                raise ValueError("weights must have one entry per cell")
            if (w < 0).any():
                raise ValueError("weights must be non-negative")
            tot = w.sum()
            if tot <= 0:
                raise ValueError("weights sum to zero")
            w = w / tot
        self._w = w

        if self.direction is not None:
            ex, ey = self.direction
            norm = math.hypot(ex, ey)
            if norm <= 0:
                raise ValueError("direction must be a non-zero vector")
            self.direction = (ex / norm, ey / norm)
            if self.speed is None:
                raise ValueError(
                    "an inflow with a direction needs a speed; pass speed=, or "
                    "drop direction= for a mass-only source")

        # Ghost-offset index arrays and scratch, allocated once.
        self._cj = cells[:, 0] + NG
        self._ci = cells[:, 1] + NG
        self._rate = np.zeros(cells.shape[0], dtype=np.float64)
        self._mx = np.zeros(cells.shape[0], dtype=np.float64)
        self._my = np.zeros(cells.shape[0], dtype=np.float64)

    def discharge(self, t: float) -> float:
        return float(self.q(t)) if callable(self.q) else float(self.q)

    def inflow_speed(self, t: float) -> float:
        if self.speed is None:
            return 0.0
        return float(self.speed(t)) if callable(self.speed) else float(self.speed)


@dataclass
class FieldAccumulator:
    """
    Running maxima and first-arrival time, updated every timestep.

    These four arrays ARE the product's outputs. Everything the dashboard shows
    and everything the exposure analysis counts derives from them, so they are
    accumulated inside the time loop where they can be exact, rather than
    reconstructed afterwards from saved frames.

    Arrays are padded like the state arrays; use the solver's properties for
    interior views.
    """
    h_max: np.ndarray
    speed_max: np.ndarray
    dv_max: np.ndarray
    t_arrival: np.ndarray
    threshold: float

    @classmethod
    def zeros(cls, shape, threshold: float):
        return cls(
            h_max=np.zeros(shape, dtype=np.float64),
            speed_max=np.zeros(shape, dtype=np.float64),
            dv_max=np.zeros(shape, dtype=np.float64),
            # -1 = never arrived. See _accumulate_fields for why not NaN.
            t_arrival=np.full(shape, -1.0, dtype=np.float64),
            threshold=float(threshold),
        )


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
        self._inflows: list = []
        self._acc: FieldAccumulator | None = None
        self._q_in = 0.0        # total inflow discharge over the last step

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
        Open boundaries want the opposite -- zero gradient, i.e. a plain copy.

        Corners are handled by ordering: x first over all rows, then y over all
        columns, so the y pass reads ghost columns that are already populated.
        `_fill_ghosts` uses the same order, keeping the two consistent.

        THE FLAT COPY AT AN OPEN BOUNDARY IS A DELIBERATE TRADE-OFF
        ----------------------------------------------------------
        Copying the bed flat means the bed STOPS SLOPING at an open boundary. The
        limiter then sees the stencil (z_edge, z_edge, z_inner), whose one-sided
        differences have opposite signs, so it returns exactly zero: the last
        interior cell loses its bed-slope forcing entirely. On a sloping bed that
        produces a backwater at the outflow. Measured on a uniform channel
        (S0 = 0.002, n = 0.033, h = 2 m, dx = 100 m), depth above normal:

            edge cell  +36.9% | -1 +29.9% | -2 +22.3% | -3 +15.7%
            -4 +10.2%  | -6 +3.1% | -8 +0.5% | -12 and beyond  0.0%

        so the artefact is confined to roughly 8 cells and decays geometrically.
        See OPEN_BC_INFLUENCE_CELLS below.

        The obvious "fix" -- continuing the bed slope into the ghosts -- makes
        uniform flow EXACT (deviation 0.0, mass error 0.0) and is catastrophically
        wrong anyway, because it breaks lake-at-rest. With the bed continued, a
        zero-gradient copy of h gives a ghost eta that is no longer level with the
        interior, so still water on a slope accelerates. Measured on the same bed
        with all four boundaries open, 200 steps from rest:

            bed ghosts flat-copied :  max|u| = 2.2e-14 m/s, mass drift  0.0
            bed ghosts continued   :  max|u| = 1.63    m/s, mass drift -2.1%

        and the continued case is still accelerating at that point. Run to steady
        state (eta0 = 5 m, initial depth 5 -> 26 m) it converges to something
        unambiguous: depth uniform at 7.71 m, speed 5.275 m/s, which is Manning
        normal velocity for 7.71 m to within 0.2% -- with 54% of the water gone.

        The still lake has become a uniform-flow river. That is the failure mode
        the well-balanced property exists to prevent, and it is far worse than a
        bounded backwater: a spurious current appears everywhere there is water,
        not just near a boundary, and no grid refinement helps because it is not a
        discretisation error.

        The two conditions genuinely conflict. h-copy plus a continued bed is
        right for flowing water; h-copy plus a flat bed is right for still water.
        No zero-gradient transmissive boundary can be exact for both -- that needs
        a characteristic/radiation condition, which is a much larger change and
        buys nothing for this application. We keep the still-water-exact choice,
        because a model that invents flow in a reservoir is unusable, whereas a
        known artefact in the last few cells of the outflow is simply masked.

        Both halves are pinned in tests/test_boundaries.py so neither can
        regress silently.
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

    # ---- inflow sources --------------------------------------------------
    def add_inflow(self, cells, q, *, direction=None, speed=None,
                   weights=None, label="inflow") -> Inflow:
        """
        Register a discharge hydrograph Q(t) injected over `cells`.

        This is how a dam breach enters the simulation. `scenario.breach`
        produces Q(t) and the critical velocity U(t) at the breach; both are
        passed straight through, so the momentum of the incoming water is
        derived from weir hydraulics rather than assumed.

        Parameters
        ----------
        cells     : (N, 2) array of interior (j, i) indices, or a single (j, i)
        q         : float or callable t -> total discharge, m^3/s
        direction : (ex, ey) flow direction; None injects mass only
        speed     : float or callable t -> speed, m/s (required with direction)
        weights   : per-cell share of Q; defaults to equal split

        Returns the Inflow so the caller can keep a handle on it.
        """
        cells = np.asarray(cells, dtype=np.int64)
        if cells.ndim == 1:
            cells = cells.reshape(1, 2)
        if cells.size and (
                (cells[:, 0] < 0).any() or (cells[:, 0] >= self.ny).any()
                or (cells[:, 1] < 0).any() or (cells[:, 1] >= self.nx).any()):
            raise ValueError(
                "inflow cells fall outside the interior domain "
                f"(0..{self.ny - 1}, 0..{self.nx - 1})")
        inf = Inflow(cells=cells, q=q, direction=direction, speed=speed,
                     weights=weights, label=label)
        self._inflows.append(inf)
        return inf

    def _add_sources(self, t: float) -> float:
        """
        Add every registered inflow to the current RHS. Returns total Q at t.

        The source goes into the RHS rather than being operator-split onto the
        state, for a specific reason: a breach hydrograph near its peak changes
        appreciably within one timestep, and splitting would evaluate it at one
        instant only. Adding to dh/dhu/dhv lets it participate in both RK2
        stages and inherit the scheme's second-order accuracy in time.

        Mass goes in at Q/(dx*dy) per unit area and momentum at Q*U*e/(dx*dy),
        i.e. in fixed ratio U. That ratio is what keeps the scheme safe: the
        water accumulating in an initially dry cell has hu/h = U exactly from
        the first step, instead of arriving as mass first and being accelerated
        afterwards — which is the usual way a naive source term produces a
        spurious velocity spike and trips the CFL limit.
        """
        if not self._inflows:
            return 0.0
        w = self._ws
        cell_area = self.dx * self.dy
        q_total = 0.0
        for inf in self._inflows:
            q = inf.discharge(t)
            if q == 0.0:
                continue
            q_total += q
            # depth rate, m/s
            np.multiply(inf._w, q / cell_area, out=inf._rate)
            if inf.direction is None:
                inf._mx[:] = 0.0
                inf._my[:] = 0.0
            else:
                u = inf.inflow_speed(t)
                ex, ey = inf.direction
                np.multiply(inf._rate, u * ex, out=inf._mx)
                np.multiply(inf._rate, u * ey, out=inf._my)
            _add_source(w["dh"], w["dhu"], w["dhv"],
                        inf._cj, inf._ci, inf._rate, inf._mx, inf._my)
        return q_total

    # ---- output accumulation ---------------------------------------------
    def track_maxima(self, threshold=0.1) -> FieldAccumulator:
        """
        Start accumulating max depth, max speed, max depth*velocity and first
        arrival time, updated every timestep.

        `threshold` is the depth (m) that counts as "flooded" for arrival time.
        0.1 m is the usual choice: below roughly that, a DEM at 30-90 m cannot
        distinguish real sheet flow from interpolation noise, so a smaller
        threshold reports arrival times the terrain does not support.

        Arrival time MUST be accumulated in the time loop rather than sampled
        from saved frames. It is a first-crossing time, so sampling quantises it
        to the frame interval and a short-lived peak between frames is missed
        entirely — and arrival time is the number this whole product exists to
        report.
        """
        if threshold <= 0:
            raise ValueError("threshold must be positive")
        shape = self._h.shape
        self._acc = FieldAccumulator.zeros(shape, threshold)
        # Seed with the initial condition, so a cell that starts wet (the
        # reservoir) reports arrival time 0 rather than never arriving.
        self._accumulate()
        return self._acc

    def _accumulate(self):
        acc = self._acc
        if acc is None:
            return
        _accumulate_fields(self._h, self._hu, self._hv, self.h_min,
                           self.t, acc.threshold,
                           acc.h_max, acc.speed_max, acc.dv_max,
                           acc.t_arrival, NG)

    def _require_acc(self, what):
        if self._acc is None:
            raise RuntimeError(
                f"{what} needs track_maxima() to have been called before the run")
        return self._acc

    @property
    def max_depth(self):
        """Maximum depth reached in each cell over the run, m."""
        return self._require_acc("max_depth").h_max[NG:-NG, NG:-NG]

    @property
    def max_speed(self):
        """Maximum flow speed reached in each cell, m/s."""
        return self._require_acc("max_speed").speed_max[NG:-NG, NG:-NG]

    @property
    def max_dv(self):
        """
        Maximum depth*velocity, m^2/s — the standard hazard variable.

        Tracked as its own running maximum, NOT as max_depth * max_speed. The
        latter multiplies two peaks that generally occur at different times and
        overstates the hazard, sometimes badly: the leading edge of a dam-break
        wave is fast and shallow, the later body is deep and slow.
        """
        return self._require_acc("max_dv").dv_max[NG:-NG, NG:-NG]

    @property
    def arrival_time(self):
        """
        First time each cell exceeded the arrival threshold, seconds.

        NaN where the water never arrived. The internal sentinel is -1 because a
        NaN comparison is always false, so `t_arrival < 0` would never fire and
        arrival would never be recorded at all.
        """
        acc = self._require_acc("arrival_time")
        out = acc.t_arrival[NG:-NG, NG:-NG].copy()
        out[out < 0.0] = np.nan
        return out

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
            dt = dt_max if dt_max else 1.0
        else:
            dt = self.cfl / worst
            if dt_max:
                dt = min(dt, dt_max)
        if self._inflows:
            dt = self._inflow_dt_limit(self.t, dt)
        return dt

    def _inflow_dt_limit(self, t, dt_guess):
        """
        Cap dt so an injection into a dry cell cannot violate CFL.

        With a dry domain `_max_speeds` finds nothing to limit on and hands back
        the cap. A large hydrograph injected over that step then creates a deep,
        fast cell in one go — and the CFL limit for the step that just created it
        was computed from the state before it existed. So the source has to carry
        its own limit; this is the first thing that breaks when a real breach
        hydrograph meets a dry channel.

        The condition is implicit: the depth created depends on dt, and the wave
        speed depends on that depth. Iterating downwards from the current guess
        converges immediately and errs on the safe side, since each pass uses the
        larger depth estimate from the pass before.
        """
        dt = dt_guess
        area = self.dx * self.dy
        for _ in range(2):
            worst = 0.0
            for inf in self._inflows:
                q = inf.discharge(t)
                if q <= 0.0:
                    continue
                # Worst single cell, not the average: an inflow weighted onto
                # one cell of many is limited by that cell.
                rate = float(inf._w.max()) * q / area
                h = rate * dt
                if h <= self.h_min:
                    continue
                c = math.sqrt(self.g * h) + abs(inf.inflow_speed(t))
                worst = max(worst, c / self.dx + c / self.dy)
            if worst <= 0.0:
                break
            dt = min(dt, self.cfl / worst)
        return dt

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
        q1 = self._add_sources(self.t)
        _axpy_state(self._h, self._hu, self._hv,
                    w["dh"], w["dhu"], w["dhv"], dt, NG)
        self.stats.mass_clipped += _clean_dry(self._h, self._hu, self._hv,
                                              self.h_min, self.dx, self.dy, NG)

        # stage 2: q^{n+1} = 0.5*(q^n + (q* + dt*L(q*)))
        self._eval_rhs()
        q2 = self._add_sources(self.t + dt)
        _axpy_state(self._h, self._hu, self._hv,
                    w["dh"], w["dhu"], w["dhv"], dt, NG)
        _blend_state(self._h, self._hu, self._hv,
                     w["h0"], w["hu0"], w["hv0"], NG)
        self.stats.mass_clipped += _clean_dry(self._h, self._hu, self._hv,
                                              self.h_min, self.dx, self.dy, NG)

        # Heun applied to a source term is the trapezoidal rule, so this is not
        # an approximation of the injected volume — it is exactly what the two
        # stages above put into the domain, which is what makes the mass balance
        # a real check on an inflow run rather than a self-fulfilling one.
        if self._inflows:
            self.stats.volume_injected += 0.5 * (q1 + q2) * dt
        self._q_in = 0.5 * (q1 + q2)

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

        # Accumulate AFTER the state is final for this step, and at the new t,
        # so a reported arrival time is a time at which the depth genuinely
        # exceeded the threshold in the solution we keep.
        self._accumulate()
        return dt

    def run(self, t_end, *, dt_max=None, callback=None, callback_every=None,
            log_every=None, max_steps=10_000_000):
        """
        Integrate to `t_end`.

        `callback(solver)` fires every `callback_every` seconds of model time —
        that is the hook for saving frames and sampling gauges. Arrival time and
        the running maxima are NOT sampled here; call `track_maxima()` and they
        are accumulated every step instead. `log_every` records
        (t, volume, dt, Q_in) into stats.history so mass conservation can be
        plotted rather than merely asserted.
        """
        if self.stats.volume_initial == 0.0 and self.stats.steps == 0:
            self.stats.volume_initial = self.volume()

        next_cb = self.t + callback_every if callback_every else None
        next_log = self.t + log_every if log_every else None
        if log_every:
            self.stats.history.append((self.t, self.volume(), 0.0, self._q_in))

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
                self.stats.history.append(
                    (self.t, self.volume(), dt, self._q_in))
                next_log += log_every

        self.stats.volume_final = self.volume()
        self.stats.t = self.t
        return self.stats

"""
MUSCL slope reconstruction and TVD slope limiters.

THE PROBLEM
-----------
The cheapest finite-volume scheme treats each cell as a flat, constant block
(piecewise constant, first-order accurate). It is rock-solid stable, but
numerically diffusive: a sharp flood front spreads out over many cells as it
travels. Over 17 km of the Reyran valley a first-order scheme turns a wall of
water into a gentle ramp, which destroys exactly the quantity we care most about
— arrival time.

THE FIX
-------
MUSCL (Monotone Upstream-centred Scheme for Conservation Laws) fits a *linear*
profile inside each cell instead of a constant, using the neighbours to estimate
the slope. That makes the scheme second-order accurate and keeps fronts sharp.

THE CATCH
---------
A naive centred slope overshoots near a discontinuity, producing oscillations
that drive depth negative — and a negative depth is instant death: sqrt(g*h) of
a negative number is NaN, which spreads across the whole domain within a few
timesteps. A *limiter* clamps the slope so the reconstruction stays monotone
(the TVD property: total variation does not increase). This is not optional
polish; without it the solver does not survive a dam break.

WHAT WE RECONSTRUCT, AND WHY IT MATTERS
---------------------------------------
We reconstruct the water-surface elevation eta = h + z, NOT the depth h.

This is the single most important design decision in the file. Consider still
water on a slope: eta is exactly constant, so its slope is zero and the
reconstruction is trivially exact. The depth h, by contrast, varies strongly
from cell to cell (it mirrors the terrain), so reconstructing h would introduce
errors that manifest as fake velocities in standing water. Reconstructing eta is
half of what makes the scheme well-balanced; hydrostatic reconstruction in
swe2d.py is the other half.

Velocities u and v are reconstructed as primitives rather than as momenta hu,
hv. In very shallow water hu -> 0 while u stays finite, so limiting the momentum
produces erratic velocities right at the wet/dry front where we can least
afford them.
"""

from __future__ import annotations

from numba import njit

_JIT = dict(cache=True, fastmath=False, nogil=True)

# Limiter selection. Passed as an int because Numba cannot dispatch on strings
# inside a jitted kernel.
LIMITER_NONE = 0     # first order — piecewise constant, most diffusive, safest
LIMITER_MINMOD = 1   # most diffusive TVD limiter, very robust
LIMITER_MC = 2       # monotonized central — sharper fronts, still TVD

LIMITER_NAMES = {"none": LIMITER_NONE, "minmod": LIMITER_MINMOD, "mc": LIMITER_MC}


@njit(inline="always", **_JIT)
def minmod(a, b):
    """
    Least-magnitude slope, zero across an extremum.

    If the left and right differences disagree in sign we are at a local max or
    min, so the only monotone choice is a flat slope. Otherwise take whichever
    difference is smaller in magnitude — the conservative option.
    """
    if a * b <= 0.0:
        return 0.0
    return a if abs(a) < abs(b) else b


@njit(inline="always", **_JIT)
def mc_limiter(a, b):
    """
    Monotonized central-difference (van Leer) limiter.

    Uses the centred slope 0.5*(a+b) where the solution is smooth — which is
    more accurate than minmod — but clips it to twice the smaller one-sided
    difference near a discontinuity. Sharper fronts than minmod at equal
    stability, so it is the better default once the scheme is known to work.
    """
    if a * b <= 0.0:
        return 0.0
    centred = 0.5 * (a + b)
    lim = 2.0 * (a if abs(a) < abs(b) else b)
    # `lim` and `centred` share a sign here, so magnitude comparison is enough.
    if abs(centred) < abs(lim):
        return centred
    return lim


@njit(inline="always", **_JIT)
def limited_slope(qm, q0, qp, limiter):
    """
    Cell-centred limited slope from the three-point stencil (qm, q0, qp).

    Returns the total variation ACROSS the cell, i.e. q_right_face -
    q_left_face. The half-widths are applied by the caller:

        q_left  = q0 - 0.5 * slope
        q_right = q0 + 0.5 * slope

    Returning the across-cell difference rather than dq/dx keeps the caller free
    of dx factors, which in turn keeps the well-balanced cancellation in
    swe2d.py easy to verify by eye.
    """
    if limiter == LIMITER_NONE:
        return 0.0
    a = q0 - qm   # backward difference
    b = qp - q0   # forward difference
    if limiter == LIMITER_MINMOD:
        return minmod(a, b)
    return mc_limiter(a, b)

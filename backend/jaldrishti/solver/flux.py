"""
HLLC approximate Riemann solver for the 2D shallow water equations.

WHAT A RIEMANN SOLVER IS FOR
----------------------------
In a finite-volume scheme each cell stores *averages* of the conserved
quantities (h, hu, hv). At the face between two cells the left and right
averages generally disagree, so the local picture is a discontinuity — a
miniature dam break at every cell face, at every timestep. The Riemann problem
is: given the two states, what flux crosses the face? Solving it exactly for
the shallow water equations requires iteration, which is far too slow to do
millions of times per second, so we use an approximate solver.

WHY HLLC AND NOT HLL
--------------------
HLL approximates the solution with just two waves (left- and right-running)
and a single constant state between them. That is enough for depth and normal
momentum, but it completely misses the *contact wave* — the shear discontinuity
that carries the transverse (along-face) momentum. Physically, HLL smears
momentum sideways.

HLLC restores the contact wave: it upwinds the transverse momentum according to
which side of the contact the face sits on. That matters enormously for
Malpasset, where the flood wave slams into a sharp bend in the valley and
survives it only if lateral momentum is transported correctly. On a straight
channel you would barely notice the difference; on a bending valley HLL will
give you visibly wrong overtopping.

REFERENCES
----------
Toro, E.F. (2001). Shock-Capturing Methods for Free-Surface Shallow Flows. Wiley.
Fraccarollo, L. & Toro, E.F. (1995). Experimental and numerical assessment of
    the shallow water model for two-dimensional dam-break type problems.
    J. Hydraulic Research 33(6), 843-864.
"""

from __future__ import annotations

import math

from numba import njit

# NOTE ON fastmath: it is deliberately NOT enabled anywhere in this module or in
# swe2d.py. fastmath permits the compiler to reassociate floating-point
# operations, which destroys the *exact* cancellation that the well-balanced
# bed-slope discretisation depends on. With fastmath the lake-at-rest test stops
# passing at machine precision and starts leaking spurious velocities. The
# speedup is not worth an invented flood.
_JIT = dict(cache=True, fastmath=False, nogil=True)


@njit(inline="always", **_JIT)
def hllc_x(hL, uL, vL, hR, uR, vR, g, h_min):
    """
    HLLC flux across a face whose normal points in +x.

    Parameters
    ----------
    hL, uL, vL : left-side depth, normal velocity, transverse velocity
    hR, uR, vR : right-side equivalents
    g          : gravitational acceleration
    h_min      : dry-cell depth threshold

    Returns
    -------
    (Fh, Fhu, Fhv) : mass flux, normal-momentum flux, transverse-momentum flux

    For a y-face, call this with u and v swapped, then swap the returned
    momentum fluxes back. The equations are rotationally symmetric, so one
    routine covers both directions.
    """
    dryL = hL <= h_min
    dryR = hR <= h_min

    # Both sides dry: nothing crosses. Returning early also keeps the wave-speed
    # estimates below from dividing by zero.
    if dryL and dryR:
        return 0.0, 0.0, 0.0

    cL = math.sqrt(g * hL) if not dryL else 0.0
    cR = math.sqrt(g * hR) if not dryR else 0.0

    # ---- wave speed estimates -------------------------------------------------
    # The dry cases are not an optimisation, they are a correctness requirement.
    # The wet-wet estimate below assumes both sides support gravity waves; used
    # against a dry bed it produces speeds that are too slow and the advancing
    # front lags (or the scheme goes unstable).
    if dryL:
        # Dry left, wet right: right state expands leftwards into the dry bed.
        # The leading edge of a rarefaction into dry bed travels at u - 2c
        # (Ritter's solution), not u - c.
        sL = uR - 2.0 * cR
        sR = uR + cR
    elif dryR:
        # Wet left, dry right: mirror image. This is the wet/dry front of an
        # advancing flood wave, i.e. the case that matters most for us.
        sL = uL - cL
        sR = uL + 2.0 * cL
    else:
        # Two-rarefaction approximation (Toro). Cheap, and robust because it
        # never underestimates the fastest wave — which is what would break CFL.
        c_star = 0.5 * (cL + cR) + 0.25 * (uL - uR)
        u_star = 0.5 * (uL + uR) + cL - cR
        sL = min(uL - cL, u_star - c_star)
        sR = max(uR + cR, u_star + c_star)

    # ---- physical fluxes on each side ----------------------------------------
    FL_h = hL * uL
    FL_hu = hL * uL * uL + 0.5 * g * hL * hL   # advection + hydrostatic pressure
    FL_hv = hL * uL * vL

    FR_h = hR * uR
    FR_hu = hR * uR * uR + 0.5 * g * hR * hR
    FR_hv = hR * uR * vR

    # ---- supersonic cases: the whole fan travels one way, so pure upwinding --
    if sL >= 0.0:
        return FL_h, FL_hu, FL_hv
    if sR <= 0.0:
        return FR_h, FR_hu, FR_hv

    # ---- subsonic: face sits inside the wave fan ----------------------------
    # HLL average for mass and normal momentum.
    inv = 1.0 / (sR - sL)
    Fh = (sR * FL_h - sL * FR_h + sL * sR * (hR - hL)) * inv
    Fhu = (sR * FL_hu - sL * FR_hu + sL * sR * (hR * uR - hL * uL)) * inv

    # ---- the "C" in HLLC: contact wave speed --------------------------------
    # Transverse momentum is passively advected by the fluid, so it must be
    # upwinded by the sign of the contact speed, NOT averaged. Averaging it is
    # exactly the HLL defect described in the module docstring.
    den = hR * (uR - sR) - hL * (uL - sL)
    if abs(den) > 1.0e-12:
        s_star = (sL * hR * (uR - sR) - sR * hL * (uL - sL)) / den
    else:
        # Degenerate (near-identical states): fall back to the average velocity.
        s_star = 0.5 * (uL + uR)

    Fhv = Fh * vL if s_star >= 0.0 else Fh * vR

    return Fh, Fhu, Fhv


@njit(inline="always", **_JIT)
def max_wave_speed(h, u, v, g, h_min):
    """
    Largest signal speed in a cell, per direction — the input to the CFL limit.

    sqrt(g*h) is the gravity-wave celerity: the shallow-water analogue of the
    speed of sound. Information cannot travel faster than |velocity| + celerity,
    and an explicit scheme is only stable if no wave crosses more than a
    fraction of a cell per timestep.
    """
    if h <= h_min:
        return 0.0, 0.0
    c = math.sqrt(g * h)
    return abs(u) + c, abs(v) + c

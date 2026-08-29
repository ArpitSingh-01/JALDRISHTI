"""
Exact analytical solutions to the shallow water equations.

These are the rungs on the validation ladder between "the code runs" and "the
code is right". Each has a closed form, so agreement is a real measurement of
numerical error rather than a comparison against another approximate model.

    Ritter (1892)  — dam break onto a DRY bed. Exercises the Riemann solver's
                     dry-bed wave speeds and the wetting front. This is the
                     single most relevant test case for a dam-break tool.
    Stoker (1957)  — dam break onto a WET bed. Introduces a genuine shock, so it
                     tests whether the scheme captures a discontinuity at the
                     right speed rather than smearing it.

Both assume a frictionless horizontal bed and an instantaneous, full-width dam
removal, so a solver must be run with Manning n = 0 to be compared against them.
That is a feature: it isolates the hyperbolic core from the source terms.

REFERENCES
----------
Ritter, A. (1892). Die Fortpflanzung der Wasserwellen. Zeitschrift des Vereines
    Deutscher Ingenieure 36(33), 947-954.
Stoker, J.J. (1957). Water Waves: The Mathematical Theory with Applications.
Delestre, O. et al. (2013). SWASHES: a compilation of shallow water analytic
    solutions. Int. J. Numer. Meth. Fluids 72(3), 269-300.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import brentq

GRAVITY = 9.81


def ritter(x, t, h0, *, x0=0.0, g=GRAVITY):
    """
    Ritter's dry-bed dam-break solution.

    Initial condition: h = h0 for x < x0, h = 0 for x > x0, water at rest.

    The solution is a single rarefaction fan opening from the dam site. Three
    regions, separated by two characteristics:

        xi <= -c0        undisturbed reservoir
        -c0 < xi < 2*c0  rarefaction
        xi >= 2*c0       still dry

    where xi = (x - x0)/t and c0 = sqrt(g*h0).

    The factor of TWO on the downstream side is the physically interesting part
    and a sharp test of the solver: the wetting front outruns the gravity-wave
    speed of the reservoir by a factor of two, because the leading water is
    accelerating into a vacuum. A solver whose dry-bed wave speed estimate uses
    u + c instead of u + 2c gets a front that visibly lags — and since arrival
    time is our headline output, that error is not cosmetic.

    Returns
    -------
    (h, u) : arrays matching the shape of `x`
    """
    x = np.asarray(x, dtype=np.float64)
    if t <= 0.0:
        h = np.where(x < x0, h0, 0.0)
        return h, np.zeros_like(x)

    c0 = np.sqrt(g * h0)
    xi = (x - x0) / t

    h = np.zeros_like(x)
    u = np.zeros_like(x)

    upstream = xi <= -c0
    h[upstream] = h0
    u[upstream] = 0.0

    fan = (xi > -c0) & (xi < 2.0 * c0)
    h[fan] = (2.0 * c0 - xi[fan]) ** 2 / (9.0 * g)
    u[fan] = 2.0 / 3.0 * (xi[fan] + c0)

    # xi >= 2*c0 stays at the initialised zeros: dry, at rest.
    return h, u


def ritter_front_position(t, h0, *, x0=0.0, g=GRAVITY):
    """Position of the wetting front. The arrival-time check in one number."""
    return x0 + 2.0 * np.sqrt(g * h0) * t


def stoker_middle_state(hl, hr, *, g=GRAVITY):
    """
    Solve for the constant state between the rarefaction and the shock.

    Unlike Ritter, the wet-bed problem has no closed form for the intermediate
    depth: it comes from matching a rarefaction on the left to a shock on the
    right, which leaves one nonlinear equation in one unknown.

        rarefaction:  u2 = 2*(cl - cm)
        shock:        u2 = (hm - hr) * sqrt( (g/2) * (1/hm + 1/hr) )

    with hm = cm^2/g. Both branches are monotone in cm over (cr, cl), so a
    bracketed root find is guaranteed to converge — no initial guess needed.

    Returns
    -------
    (hm, u2, shock_speed)
    """
    if hr <= 0.0:
        raise ValueError("Stoker's solution requires a wet downstream bed; "
                         "use ritter() for hr = 0")
    if hl <= hr:
        raise ValueError("expected hl > hr for a dam-break configuration")

    cl = np.sqrt(g * hl)
    cr = np.sqrt(g * hr)

    def residual(cm):
        hm = cm * cm / g
        u_rare = 2.0 * (cl - cm)
        u_shock = (hm - hr) * np.sqrt(0.5 * g * (1.0 / hm + 1.0 / hr))
        return u_rare - u_shock

    # Bracket: cm = cr gives u_shock = 0 < u_rare, cm = cl gives u_rare = 0 < u_shock.
    cm = brentq(residual, cr, cl, xtol=1.0e-14, rtol=1.0e-15, maxiter=200)

    hm = cm * cm / g
    u2 = 2.0 * (cl - cm)
    # Mass conservation across the shock, in the shock's frame.
    shock_speed = hm * u2 / (hm - hr)
    return hm, u2, shock_speed


def stoker(x, t, hl, hr, *, x0=0.0, g=GRAVITY):
    """
    Stoker's wet-bed dam-break solution.

    Initial condition: h = hl for x < x0, h = hr > 0 for x > x0, water at rest.

    Four regions: undisturbed reservoir, rarefaction fan, constant middle state,
    and undisturbed downstream water, the last separated from the middle state by
    a SHOCK (a hydraulic bore). The shock is what makes this test worth running:
    a scheme without a proper Riemann solver will either smear the bore over many
    cells or place it at the wrong speed, and both errors show up immediately as
    a depth-profile mismatch.

    Returns
    -------
    (h, u) : arrays matching the shape of `x`
    """
    x = np.asarray(x, dtype=np.float64)
    if t <= 0.0:
        return np.where(x < x0, hl, hr), np.zeros_like(x)

    cl = np.sqrt(g * hl)
    hm, u2, s = stoker_middle_state(hl, hr, g=g)
    cm = np.sqrt(g * hm)

    xi = (x - x0) / t
    h = np.empty_like(x)
    u = np.empty_like(x)

    r1 = xi <= -cl                       # undisturbed reservoir
    r2 = (xi > -cl) & (xi <= u2 - cm)    # rarefaction fan
    r3 = (xi > u2 - cm) & (xi < s)       # constant middle state
    r4 = xi >= s                         # undisturbed tailwater

    h[r1] = hl
    u[r1] = 0.0
    h[r2] = (2.0 * cl - xi[r2]) ** 2 / (9.0 * g)
    u[r2] = 2.0 / 3.0 * (xi[r2] + cl)
    h[r3] = hm
    u[r3] = u2
    h[r4] = hr
    u[r4] = 0.0

    return h, u

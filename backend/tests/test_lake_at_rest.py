"""
Validation rung 1: LAKE AT REST (well-balancedness).

WHAT IS BEING TESTED
--------------------
Put still water over uneven terrain and leave it alone. Nothing should happen.
Not "almost nothing" — nothing, to machine precision.

WHY THIS IS THE FIRST TEST AND NOT AN AFTERTHOUGHT
--------------------------------------------------
In the momentum equation the pressure-gradient flux and the bed-slope source term
are individually large and, in still water, exactly equal and opposite. For a
100 m deep reservoir on a 1-in-10 slope both are on the order of g*h*dz/dx ~ 100
m^2/s^2. If the discretisation gets them right only to 1%, the residual is ~1
m^2/s^2 of unbalanced force applied every timestep — and the model will show a
calm reservoir spontaneously sloshing, or worse, quietly draining downstream and
"flooding" villages that were never at risk.

That failure is insidious because it looks plausible. A blue blob appears on the
map, it spreads downhill, and nothing in the output announces that it is an
artefact. This test is the only thing standing between us and that.

The scheme achieves exact balance through three co-operating choices, each of
which this test would catch the loss of:
  * reconstruct the water SURFACE eta = h+z, not the depth h  (reconstruct.py)
  * Audusse hydrostatic reconstruction at every face           (swe2d._rhs)
  * a matching CENTRED in-cell bed source term                 (swe2d._rhs)
and one restraint: fastmath stays off, so the compiler cannot reassociate the
arithmetic whose cancellation we depend on.

TERRAIN CASES
-------------
Six beds, from trivially symmetric to deliberately adversarial. The random bed
matters most: on a flat or linear bed a broken scheme can pass by accident
because errors cancel by symmetry. Random terrain removes that luck, and it is
also what a real DEM actually looks like.
"""

from __future__ import annotations

import numpy as np
import pytest

from jaldrishti.solver import SWE2D

# Well-balancedness is a machine-precision claim, so the threshold is set just
# above the round-off floor rather than at some comfortable engineering value.
# For reference, a physically negligible velocity would be ~1e-3 m/s; anything
# this test admits is at least six orders of magnitude below that.
VEL_TOL = 1.0e-9        # m/s
SURFACE_TOL = 1.0e-9    # m
MASS_TOL = 1.0e-12      # relative

NX, NY = 60, 40
DX = 25.0
WATER_LEVEL = 100.0


def _beds():
    """(name, bed elevation array, description) for each terrain case."""
    y, x = np.mgrid[0:NY, 0:NX]
    xm = x * DX
    ym = y * DX

    flat = np.full((NY, NX), 20.0)

    slope_x = 20.0 + 0.05 * xm                      # 1-in-20 down-valley slope
    slope_xy = 20.0 + 0.03 * xm + 0.02 * ym         # tilted in both directions

    cx, cy = NX * DX * 0.5, NY * DX * 0.5
    r2 = (xm - cx) ** 2 + (ym - cy) ** 2
    bump = 20.0 + 60.0 * np.exp(-r2 / (2.0 * (200.0 ** 2)))

    # Same bump, tall enough to break the surface: this case has a real shoreline
    # and therefore exercises the first-order fallback near dry cells.
    island = 20.0 + 130.0 * np.exp(-r2 / (2.0 * (200.0 ** 2)))

    rng = np.random.default_rng(20260828)
    rough = 20.0 + 50.0 * rng.random((NY, NX))

    return [
        ("flat", flat, "flat bed"),
        ("slope_x", slope_x, "uniform 1:20 slope in x"),
        ("slope_xy", slope_xy, "slope in x and y"),
        ("bump", bump, "submerged Gaussian bump"),
        ("island", island, "bump piercing the surface (shoreline present)"),
        ("rough", rough, "random rough bed (no helpful symmetry)"),
    ]


BEDS = _beds()
BED_IDS = [b[0] for b in BEDS]


def _run_case(bed, limiter, n_steps=200, bc="open"):
    """Fill to a level surface, take n_steps, report the worst residual motion."""
    s = SWE2D(bed, DX, manning=0.03, limiter=limiter, bc=(bc,) * 4)
    s.set_surface(WATER_LEVEL)
    v0 = s.volume()

    # A fixed dt taken from the initial state: with no flow, the CFL estimate is
    # driven purely by the gravity wave speed and would not change anyway, and
    # fixing it makes the test deterministic.
    dt = s.compute_dt()
    for _ in range(n_steps):
        s.step(dt=dt)

    wet = s.h > s.h_min
    max_speed = float(np.max(s.speed[wet])) if wet.any() else 0.0
    surf_err = (float(np.max(np.abs((s.h + s.z)[wet] - WATER_LEVEL)))
                if wet.any() else 0.0)
    mass_err = abs(s.volume() - v0) / v0
    return s, dt, max_speed, surf_err, mass_err


@pytest.mark.parametrize("limiter", ["none", "minmod", "mc"])
@pytest.mark.parametrize("bed", BEDS, ids=BED_IDS)
def test_lake_stays_at_rest(bed, limiter):
    """No spurious velocity, no surface distortion, no mass drift."""
    name, z, _desc = bed
    _s, _dt, max_speed, surf_err, mass_err = _run_case(z, limiter)

    assert np.isfinite(max_speed), f"{name}/{limiter}: NaN in the velocity field"
    assert max_speed < VEL_TOL, (
        f"{name}/{limiter}: spurious velocity {max_speed:.3e} m/s exceeds "
        f"{VEL_TOL:.0e}. The bed-slope source term and the pressure flux are no "
        f"longer cancelling — check hydrostatic reconstruction and the centred "
        f"source in _rhs, and confirm fastmath is still disabled."
    )
    assert surf_err < SURFACE_TOL, (
        f"{name}/{limiter}: water surface deviates {surf_err:.3e} m from level"
    )
    assert mass_err < MASS_TOL, (
        f"{name}/{limiter}: mass drifted by {mass_err:.3e} (relative)"
    )


@pytest.mark.parametrize("bc", ["wall", "open"])
def test_lake_at_rest_boundaries(bc):
    """
    Both boundary treatments must also be silent.

    A wall reflects, which is only exact if the bed is mirrored into the ghost
    cells the same way the depth is; an open boundary is zero-gradient. Either
    one done carelessly leaks water at the domain edge, and because that leak is
    at the edge it is easy to mistake for "just a boundary effect" instead of the
    bug it is.
    """
    _name, z, _desc = BEDS[1]      # sloping bed: the boundary sees a real gradient
    _s, _dt, max_speed, surf_err, mass_err = _run_case(z, "mc", bc=bc)
    assert max_speed < VEL_TOL, f"bc={bc}: spurious velocity {max_speed:.3e} m/s"
    assert surf_err < SURFACE_TOL, f"bc={bc}: surface error {surf_err:.3e} m"
    assert mass_err < MASS_TOL, f"bc={bc}: mass drift {mass_err:.3e}"


def test_lake_at_rest_chart(chart_dir):
    """
    Produce the deck figure: residual velocity per terrain case, log scale,
    against the double-precision round-off floor.

    This chart is the answer to the jury question "how do you know your model
    isn't just making the water up?" — and it is far more persuasive than a
    passing test, because it shows the margin rather than asserting a threshold.
    """
    import matplotlib.pyplot as plt

    limiters = ["none", "minmod", "mc"]
    results = {lim: [] for lim in limiters}
    for lim in limiters:
        for name, z, _desc in BEDS:
            _s, _dt, max_speed, _se, _me = _run_case(z, lim)
            results[lim].append(max(max_speed, 1.0e-18))   # floor for log plot

    fig, (ax, ax2) = plt.subplots(
        1, 2, figsize=(13, 4.6), gridspec_kw={"width_ratios": [1.6, 1]})

    labels = [b[0] for b in BEDS]
    xpos = np.arange(len(labels))
    width = 0.26
    for k, lim in enumerate(limiters):
        ax.bar(xpos + (k - 1) * width, results[lim], width,
               label=f"limiter = {lim}")

    ax.axhline(1.0e-3, color="crimson", ls="--", lw=1.2,
               label="1e-3 m/s (physically negligible)")
    ax.axhline(2.22e-16, color="grey", ls=":", lw=1.2,
               label="double-precision epsilon")

    # A flat bed cancels EXACTLY — zero, not small. A log axis cannot render
    # that, so it would otherwise read as missing data. Label it instead.
    for xi, label in zip(xpos, labels):
        if max(results[lim][xi] for lim in limiters) <= 1.0e-18:
            ax.annotate("exactly 0", (xi, 1.5e-17), rotation=90, ha="center",
                        va="bottom", fontsize=8, color="dimgrey")

    ax.set_yscale("log")
    # Two decades of headroom above the 1e-3 reference line so the headline box
    # can sit clear of it. The empty space is not wasted: it IS the margin.
    ax.set_ylim(1e-18, 1e1)
    ax.set_xticks(xpos)
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.set_ylabel("max spurious velocity  [m/s]")
    ax.set_title("Lake at rest: residual motion after 200 steps\n"
                 "(well-balanced scheme — lower is better)", fontsize=10)
    # Legend goes in the empty middle band. Upper-left is where the headline box
    # and the 1e-3 reference line are; lower-right sits on top of the island and
    # rough bars. The band between 1e-6 and 1e-12 is genuinely empty — that is the
    # whole point of the figure.
    ax.legend(fontsize=7.5, loc="center left", framealpha=0.95)
    ax.grid(axis="y", alpha=0.3)

    # The headline number, ON the chart. A jury reads the figure, not our console,
    # and "5 microns per year" lands in a way "1.6e-13 m/s" does not.
    worst_all = max(max(v) for v in results.values())
    per_year = worst_all * 3.156e7          # m/s -> m/year
    ax.text(0.02, 0.98,
            f"worst case over 6 beds x 3 limiters:  {worst_all:.2e} m/s\n"
            f"= {per_year * 1e6:.0f} micrometres per year  "
            f"(~{np.log10(1e-3 / worst_all):.0f} orders below negligible)",
            transform=ax.transAxes, fontsize=8, va="top",
            bbox=dict(boxstyle="round,pad=0.4", fc="#f1f8e9", ec="#33691e",
                      lw=0.8))

    # Cross-section through the shoreline case: proves the surface stays level
    # right across the wet/dry boundary, which is where naive schemes fail.
    _name, z_island, _d = BEDS[4]
    s, _dt, _ms, _se, _me = _run_case(z_island, "mc")
    jmid = NY // 2
    xs = np.arange(NX) * DX / 1000.0
    ax2.fill_between(xs, 0, s.z[jmid], color="#8d6e63", label="bed")
    eta_line = np.where(s.h[jmid] > s.h_min, s.h[jmid] + s.z[jmid], np.nan)
    ax2.plot(xs, eta_line, color="#1565c0", lw=2, label="water surface")
    ax2.axhline(WATER_LEVEL, color="#1565c0", ls=":", lw=1,
                label=f"initial level {WATER_LEVEL:.0f} m")
    ax2.set_xlabel("distance  [km]")
    ax2.set_ylabel("elevation  [m]")
    ax2.set_title("Shoreline case, mid-domain section", fontsize=10)
    ax2.legend(fontsize=8, loc="upper right")
    ax2.grid(alpha=0.3)

    fig.suptitle("JALDRISHTI solver validation 1/4 — well-balancedness",
                 fontsize=12, y=1.02)
    fig.tight_layout()
    out = chart_dir / "01_lake_at_rest.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)

    assert out.exists()
    worst = max(max(v) for v in results.values())
    print(f"\n[lake at rest] worst spurious velocity across all cases: "
          f"{worst:.3e} m/s   ->  {out}")

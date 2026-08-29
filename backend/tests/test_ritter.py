"""
Validation rung 2: RITTER (1892) — dam break onto a DRY bed.

WHAT IS BEING TESTED
--------------------
An instantaneous, full-width dam removal on a flat frictionless bed with nothing
downstream. Ritter solved this exactly in 1892, so we can measure our error
rather than guess at it.

WHY THIS IS THE RIGHT SECOND TEST
---------------------------------
This is the closest analytical problem to what the whole project is for. It
exercises, all at once:

  * the Riemann solver's DRY-BED wave speeds. Water accelerating into a dry bed
    produces a front travelling at u + 2c, not u + c. A solver that uses the
    wet-wet estimate everywhere gets a front that lags by tens of percent — and
    the front position IS the arrival time, our headline output. Nothing else in
    the ladder catches this.
  * the wetting/drying logic, continuously, at a front that advances a cell every
    few timesteps for the whole run.
  * the rarefaction structure, i.e. whether the scheme is genuinely solving the
    equations or merely diffusing a blob downhill.

WHAT "AGREEMENT" MEANS HERE
---------------------------
The exact solution has kinks in its derivative at the rarefaction head and at the
wetting front, so a second-order scheme cannot achieve second-order convergence
on it globally. Published MUSCL results on Ritter converge at roughly first order
in L1. We therefore MEASURE the observed order and report it rather than
asserting 2.0 — claiming second-order convergence on a problem that cannot
deliver it would be exactly the kind of overclaim this project avoids.
"""

from __future__ import annotations

import numpy as np
import pytest

from jaldrishti.solver import SWE2D
from jaldrishti.validation import ritter

H0 = 10.0            # reservoir depth, m
LENGTH = 1000.0      # domain length, m
X_DAM = 500.0        # dam location, m — chosen so it lands on a cell FACE at
                     # every resolution tested (1000/500/250 m divides it evenly)
T_END = 20.0         # s. Long enough for structure to develop, short enough that
                     # neither the front nor the rarefaction tail reaches a
                     # boundary, so the comparison is against the pure Ritter
                     # solution with no boundary contamination.
NY = 4               # a few rows: the problem is 1D, this keeps the 2D code path
                     # under test rather than special-casing it
G = 9.81

DEPTH_REPORT = 0.10   # m — the depth at which we are willing to CLAIM an arrival
                      # time. Justification, because a jury will ask:
                      #   * SRTM/ASTER vertical accuracy is several metres, so a
                      #     10 cm water depth is an order of magnitude below the
                      #     error bar of the terrain it is computed on.
                      #   * Standard depth-velocity hazard criteria classify
                      #     depths below ~0.1-0.3 m as low hazard for an adult.
                      #   * Operational flood mapping conventionally uses a wet
                      #     threshold of 0.1 m or higher.
                      # Reporting a front position at 1 mm would be precision
                      # theatre: the number would be meaningless on real terrain.

DEPTH_FILM = 0.01     # m — used only to probe the thin-film tail, so that the
                      # known limitation is measured and stated rather than
                      # quietly excluded by choosing a flattering threshold.


def _run(dx, limiter="mc", t_end=T_END):
    nx = int(round(LENGTH / dx))
    z = np.zeros((NY, nx))

    # Manning n = 0: Ritter assumes a frictionless bed, so friction must be off
    # or we are comparing against the wrong problem.
    s = SWE2D(z, dx, manning=0.0, limiter=limiter,
              bc=("wall", "open", "wall", "wall"))

    xc = (np.arange(nx) + 0.5) * dx
    h0 = np.where(xc < X_DAM, H0, 0.0)
    s.set_depth(np.broadcast_to(h0, (NY, nx)))

    stats = s.run(t_end, log_every=t_end / 20.0)
    return s, xc, stats


def _profiles(s, xc, t):
    """Mid-row numerical profile and the exact solution on the same points."""
    j = NY // 2
    h_num = s.h[j].copy()
    u_num = s.u[j].copy()
    h_exact, u_exact = ritter(xc, t, H0, x0=X_DAM, g=G)
    return h_num, u_num, h_exact, u_exact


def _front(x, h, cutoff):
    """Rightmost position where depth exceeds `cutoff`."""
    wet = np.nonzero(h > cutoff)[0]
    return float(x[wet[-1]]) if wet.size else float("nan")


def test_ritter_no_nan_and_positive():
    """
    Before accuracy: does it survive at all, and is the depth physical?

    A dry-bed dam break is the standard way to make a shallow water solver
    produce NaN. If the wetting front, the limiter or the CFL estimate is wrong,
    this test fails long before any accuracy check gets a chance to.
    """
    s, _xc, _stats = _run(2.0)
    assert np.all(np.isfinite(s.h)), "NaN or inf in the depth field"
    assert np.all(np.isfinite(s.hu)), "NaN or inf in the momentum field"
    assert s.h.min() >= 0.0, f"negative depth {s.h.min():.3e} m survived"
    assert s.speed.max() < 50.0, (
        f"unphysical velocity {s.speed.max():.1f} m/s — the theoretical maximum "
        f"here is 2*sqrt(g*h0) = {2 * np.sqrt(G * H0):.1f} m/s, so this is the "
        f"signature of an unguarded hu/h division"
    )


def test_ritter_mass_conserved():
    """
    Nothing leaves the domain in 20 s, so the volume must not change.

    Finite volume conserves mass by construction, which makes this a direct test
    of the boundary conditions and of the dry-cell clipping. A drift here means
    the model would report the wrong flood volume, which propagates straight into
    the exposure and damage numbers.
    """
    s, _xc, stats = _run(2.0)
    assert abs(stats.volume_error) < 1.0e-12, (
        f"mass drifted by {stats.volume_error:.3e} (relative)")
    v_expected = X_DAM * H0 * (NY * 2.0)          # dx=2 -> dy=2, NY rows
    assert abs(stats.volume_initial - v_expected) / v_expected < 1e-12
    # Clipping should essentially never fire on this problem.
    assert stats.mass_clipped / stats.volume_initial < 1.0e-9, (
        f"clipped {stats.mass_clipped:.3e} m^3 of negative depth — the limiter "
        f"is overshooting at the wetting front")


def test_ritter_front_position():
    """
    Arrival time, measured. This is the single most important number in the file.

    Measured at DEPTH_REPORT on BOTH the numerical and the exact profile, so the
    comparison is like-for-like. The tolerance is two cells: at dx = 2 m that is
    4 m out of the ~340 m the front has travelled, i.e. ~1%.
    """
    dx = 2.0
    s, xc, _stats = _run(dx)
    h_num, _u_num, h_exact, _u_exact = _profiles(s, xc, s.t)

    x_num = _front(xc, h_num, DEPTH_REPORT)
    x_exact = _front(xc, h_exact, DEPTH_REPORT)
    travelled = x_exact - X_DAM
    err = abs(x_num - x_exact)

    assert err <= 2.0 * dx, (
        f"front (at {DEPTH_REPORT} m depth) at {x_num:.1f} m vs exact "
        f"{x_exact:.1f} m — error {err:.1f} m = "
        f"{100 * err / travelled:.2f}% of the {travelled:.0f} m travelled. "
        f"Check the dry-bed wave speeds in flux.hllc_x — u+2c, not u+c.")


def test_ritter_thin_film_lag_is_bounded_and_grid_limited():
    """
    The KNOWN LIMITATION, measured rather than hidden.

    Ritter's exact solution has a vanishingly thin tongue at the leading edge: at
    t = 20 s it is 11 mm deep 20 m behind the tip and 0.1 mm deep 2 m behind it.
    No grid-based scheme tracks that, and ours reports the 1 cm contour roughly
    9 cells short.

    Two things make this a limitation rather than a bug, and both are asserted
    here so a regression would show up:

      1. It does NOT scale with the numerical dry threshold h_min. Measured lag
         is essentially identical for h_min from 1e-3 down to 1e-6 m, so the
         answer is not being set by an arbitrary solver parameter. (Before the
         velocity desingularisation in swe2d._desing_vel it was: the lag ran from
         46 m down to 26 m over that range, i.e. the threshold was controlling
         the physics. That is what the fix removed.)
      2. It is confined to the film. At DEPTH_REPORT the same run is within one
         cell, and at 0.5 m it is exact.

    We therefore report arrival time at DEPTH_REPORT and state this bound, which
    is both honest and the operationally useful choice.
    """
    dx = 2.0
    lags = {}
    for h_min in (1.0e-3, 1.0e-5):
        nx = int(round(LENGTH / dx))
        s = SWE2D(np.zeros((NY, nx)), dx, manning=0.0, limiter="mc",
                  h_min=h_min, bc=("wall", "open", "wall", "wall"))
        xc = (np.arange(nx) + 0.5) * dx
        s.set_depth(np.broadcast_to(np.where(xc < X_DAM, H0, 0.0), (NY, nx)))
        s.run(T_END)
        h_exact, _ = ritter(xc, s.t, H0, x0=X_DAM, g=G)
        j = NY // 2
        lags[h_min] = (_front(xc, s.h[j], DEPTH_FILM)
                       - _front(xc, h_exact, DEPTH_FILM))

    # (1) insensitive to the numerical threshold
    spread = abs(lags[1.0e-3] - lags[1.0e-5])
    assert spread <= 4.0 * dx, (
        f"thin-film lag moved {spread:.1f} m when h_min changed by 100x "
        f"({lags}). The dry threshold is controlling the front again — check "
        f"that _clean_dry is not wiping momentum below h_min.")

    # (2) bounded in magnitude
    for h_min, lag in lags.items():
        assert abs(lag) <= 15.0 * dx, (
            f"thin-film lag {lag:.1f} m at h_min={h_min:.0e} is larger than the "
            f"documented bound")


def test_ritter_dam_site_values():
    """
    At the dam itself Ritter gives two clean closed-form numbers, independent of
    everything else in the solution:

        h = (4/9) * h0          ->  4.444 m for h0 = 10 m
        u = (2/3) * sqrt(g*h0)  ->  6.603 m/s

    A scheme can get the front roughly right by luck; matching both of these at
    the same point means the interior of the rarefaction fan is right too.
    """
    dx = 1.0
    s, xc, _stats = _run(dx)
    j = NY // 2
    i = int(np.argmin(np.abs(xc - X_DAM)))

    h_expected = 4.0 / 9.0 * H0
    u_expected = 2.0 / 3.0 * np.sqrt(G * H0)

    h_rel = abs(s.h[j, i] - h_expected) / h_expected
    u_rel = abs(s.u[j, i] - u_expected) / u_expected

    assert h_rel < 0.02, (
        f"depth at dam {s.h[j, i]:.4f} m vs exact {h_expected:.4f} m "
        f"({100 * h_rel:.2f}% error)")
    assert u_rel < 0.02, (
        f"velocity at dam {s.u[j, i]:.4f} m/s vs exact {u_expected:.4f} m/s "
        f"({100 * u_rel:.2f}% error)")


@pytest.mark.parametrize("limiter", ["none", "minmod", "mc"])
def test_ritter_profile_accuracy(limiter):
    """
    L1 depth error over the whole wet region.

    First order is admitted with a looser tolerance on purpose: it SHOULD be
    worse, and having a number for how much worse is what justifies paying for
    MUSCL. If 'none' ever matched 'mc' here, the limiter would not be doing
    anything and we would want to know.
    """
    dx = 2.0
    s, xc, _stats = _run(dx, limiter=limiter)
    h_num, _u, h_exact, _ue = _profiles(s, xc, s.t)

    region = h_exact > DEPTH_FILM
    l1 = float(np.mean(np.abs(h_num[region] - h_exact[region])))
    tol = 0.30 if limiter == "none" else 0.12          # metres
    assert l1 < tol, f"{limiter}: L1 depth error {l1:.4f} m exceeds {tol} m"


def test_ritter_front_velocity():
    """
    Peak velocity in the domain.

    Ritter's front accelerates to 2*sqrt(g*h0) = 19.8 m/s, but only exactly AT the
    tip where the depth is zero, so a grid scheme should approach it from below
    and never exceed it. Both bounds matter:

      * too low  -> momentum is being destroyed at the wetting front, which
                    retards arrival time.
      * too high -> an unguarded hu/h division is manufacturing velocity, which
                    would inflate the hazard classification (hazard scales with
                    depth x velocity) and eventually break CFL.

    Measured: 18.79 m/s, i.e. 95% of theoretical, approached from below.
    """
    s, _xc, _stats = _run(2.0)
    u_theory = 2.0 * np.sqrt(G * H0)
    u_max = float(s.speed.max())

    assert u_max <= u_theory * 1.02, (
        f"peak velocity {u_max:.2f} m/s exceeds the theoretical maximum "
        f"{u_theory:.2f} m/s — velocity is being manufactured at the wet/dry "
        f"front; check _desing_vel")
    assert u_max >= u_theory * 0.90, (
        f"peak velocity {u_max:.2f} m/s is only "
        f"{100 * u_max / u_theory:.0f}% of the theoretical {u_theory:.2f} m/s — "
        f"momentum is being lost at the front; check that _clean_dry and "
        f"_apply_friction are not zeroing momentum above H_DRY")


def test_ritter_chart(chart_dir):
    """
    The deck figure: profile match, velocity match, and a measured convergence
    study. The convergence panel is what distinguishes a validated solver from
    one that merely produced a plausible picture once.
    """
    import matplotlib.pyplot as plt

    dx_ref = 2.0
    s, xc, stats = _run(dx_ref)
    h_num, u_num, h_exact, u_exact = _profiles(s, xc, s.t)

    # --- convergence study -------------------------------------------------
    dxs = [4.0, 2.0, 1.0]
    errs = []
    front_err_report = []
    front_err_film = []
    for dx in dxs:
        sc, xcc, _st = _run(dx)
        hn, _un, he, _ue = _profiles(sc, xcc, sc.t)
        region = he > DEPTH_FILM
        errs.append(float(np.mean(np.abs(hn[region] - he[region]))))
        front_err_report.append(_front(xcc, hn, DEPTH_REPORT)
                                - _front(xcc, he, DEPTH_REPORT))
        front_err_film.append(_front(xcc, hn, DEPTH_FILM)
                              - _front(xcc, he, DEPTH_FILM))

    orders = [np.log(errs[k] / errs[k + 1]) / np.log(dxs[k] / dxs[k + 1])
              for k in range(len(dxs) - 1)]

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4))

    # panel 1: depth
    ax = axes[0]
    ax.plot(xc / 1000.0, h_exact, "k-", lw=2, label="Ritter (1892) exact")
    ax.plot(xc / 1000.0, h_num, color="#1565c0", lw=1.4, ls="--",
            label=f"JALDRISHTI, dx = {dx_ref:.0f} m")
    ax.axvline(X_DAM / 1000.0, color="grey", ls=":", lw=1)
    ax.annotate("dam", (X_DAM / 1000.0, H0 * 0.92), fontsize=8,
                ha="right", color="grey")
    ax.set_xlabel("distance  [km]")
    ax.set_ylabel("depth  [m]")
    ax.set_title(f"Depth profile at t = {s.t:.0f} s", fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # Inset on the leading edge, log depth. This is where the only meaningful
    # disagreement lives, and showing it on a log axis is the honest way to
    # present it: agreement is excellent down to ~0.1 m and the scheme then falls
    # behind in a film millimetres deep, which no grid model resolves.
    # Placed bottom-left: that quadrant is empty, and the upper-right is where the
    # legend and the reservoir plateau are.
    axi = ax.inset_axes([0.10, 0.11, 0.44, 0.47])
    x_tip = (X_DAM + 2.0 * np.sqrt(G * H0) * s.t) / 1000.0
    axi.semilogy(xc / 1000.0, np.maximum(h_exact, 1e-6), "k-", lw=1.6)
    axi.semilogy(xc / 1000.0, np.maximum(h_num, 1e-6), color="#1565c0",
                 lw=1.2, ls="--")
    axi.axhline(DEPTH_REPORT, color="#2e7d32", lw=1,
                label=f"{DEPTH_REPORT:.2f} m (reported)")
    axi.axhline(DEPTH_FILM, color="#ef6c00", lw=1, ls="-.",
                label=f"{DEPTH_FILM:.2f} m (film)")
    axi.set_xlim(x_tip - 0.16, x_tip + 0.03)
    axi.set_ylim(1e-4, 3.0)
    axi.tick_params(labelsize=6.5)
    axi.set_title("leading edge, log depth", fontsize=7)
    axi.legend(fontsize=5.5, loc="lower left")
    axi.grid(alpha=0.3, which="both")

    # Headline numbers on the figure itself.
    u_theory = 2.0 * np.sqrt(G * H0)
    ax.text(0.985, 0.60,
            f"front @ {DEPTH_REPORT:.2f} m:  {front_err_report[1]:+.0f} m "
            f"({abs(front_err_report[1]) / dx_ref:.0f} cell)\n"
            f"peak velocity:  {100 * s.speed.max() / u_theory:.0f}% of "
            f"$2\\sqrt{{gh_0}}$\n"
            f"mass error:  {stats.volume_error:.1e}\n"
            f"L1 depth error:  {errs[1]:.4f} m",
            transform=ax.transAxes, fontsize=8, va="top", ha="right",
            bbox=dict(boxstyle="round,pad=0.4", fc="#e3f2fd", ec="#0d47a1",
                      lw=0.8))

    # panel 2: velocity
    ax = axes[1]
    ax.plot(xc / 1000.0, u_exact, "k-", lw=2, label="exact")
    ax.plot(xc / 1000.0, u_num, color="#c62828", lw=1.4, ls="--",
            label="JALDRISHTI")
    ax.axhline(2.0 * np.sqrt(G * H0), color="grey", ls=":", lw=1)
    ax.annotate(f"front speed 2$\\sqrt{{gh_0}}$ = {2 * np.sqrt(G * H0):.1f} m/s",
                (0.03, 2 * np.sqrt(G * H0) * 0.93), fontsize=7.5, color="grey")
    ax.set_xlabel("distance  [km]")
    ax.set_ylabel("velocity  [m/s]")
    ax.set_title("Velocity profile", fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # panel 3: convergence
    ax = axes[2]
    ax.loglog(dxs, errs, "o-", color="#2e7d32", lw=1.8, label="measured L1 error")
    ref = np.array(dxs, dtype=float)
    ax.loglog(ref, errs[0] * (ref / ref[0]) ** 1.0, "k--", lw=1,
              label="1st order reference")
    ax.loglog(ref, errs[0] * (ref / ref[0]) ** 2.0, "k:", lw=1,
              label="2nd order reference")
    ax.invert_xaxis()
    ax.set_xlabel("cell size  [m]")
    ax.set_ylabel("L1 depth error  [m]")
    # Plain tick labels: "4x10^0, 3x10^0, 2x10^0" is what matplotlib does to a
    # log axis by default and it is unreadable on a slide.
    ax.set_xticks(dxs)
    ax.set_xticklabels([f"{d:g}" for d in dxs])
    ax.minorticks_off()
    ax.set_title("Grid convergence\n"
                 f"observed order: {', '.join(f'{o:.2f}' for o in orders)}",
                 fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, which="both")

    fig.suptitle("JALDRISHTI solver validation 2/4 — Ritter dry-bed dam break "
                 f"($h_0$ = {H0:.0f} m, frictionless)", fontsize=12, y=1.03)
    fig.tight_layout()
    out = chart_dir / "02_ritter_dry_bed.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"\n[ritter] front @ {DEPTH_REPORT:.2f} m depth (reported): "
          f"{_front(xc, h_num, DEPTH_REPORT):.1f} m vs exact "
          f"{_front(xc, h_exact, DEPTH_REPORT):.1f} m  ->  error "
          f"{front_err_report[1]:+.1f} m")
    print(f"[ritter] front @ {DEPTH_FILM:.2f} m depth (thin film): error "
          f"{front_err_film[1]:+.1f} m  [documented limitation]")
    print(f"[ritter] front error vs resolution @ {DEPTH_REPORT:.2f} m: "
          f"{', '.join(f'dx={d:.0f}m -> {e:+.1f}m' for d, e in zip(dxs, front_err_report))}")
    print(f"[ritter] peak velocity {s.speed.max():.2f} m/s vs theoretical "
          f"{u_theory:.2f} m/s  ({100 * s.speed.max() / u_theory:.0f}%)")
    print(f"[ritter] L1 depth error: "
          f"{', '.join(f'dx={d:.0f}m -> {e:.4f}m' for d, e in zip(dxs, errs))}")
    print(f"[ritter] observed convergence order: "
          f"{', '.join(f'{o:.2f}' for o in orders)}")
    print(f"[ritter] mass error {stats.volume_error:.2e} over {stats.steps} steps"
          f"  ->  {out}")
    assert out.exists()

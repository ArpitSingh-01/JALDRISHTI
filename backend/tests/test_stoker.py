"""
Validation rung 3: STOKER (1957) — dam break onto a WET bed.

WHAT IS BEING TESTED
--------------------
Same instantaneous dam removal as Ritter, but now there is already water
downstream. That single change introduces a feature Ritter cannot produce: a
genuine SHOCK — a hydraulic bore, a near-discontinuous jump in water level that
propagates downstream at a speed set by the Rankine-Hugoniot conditions rather
than by the characteristic speed.

WHY THIS RUNG EXISTS AND WHY IT IS NOT OPTIONAL
----------------------------------------------
Malpasset is a wet-bed problem. The Reyran was not a dry channel: it carried
baseflow, and the 1959 flood wave propagated down it as a bore. So did the
Chamoni/Rishi Ganga flow. The dry-bed test (Ritter) proves we can start a flood;
this one proves we can propagate it correctly through water that is already
there, which is what actually happens in every real scenario we will run.

Three distinct failure modes live here, and none of them are visible in Ritter:

  1. WRONG BORE SPEED. A bore does not travel at sqrt(g*h). It travels at a speed
     determined by conservation across the jump. A scheme that averages instead of
     upwinding — or that uses the wrong wave-speed estimate — puts the bore in the
     wrong place, and the error GROWS LINEARLY IN TIME. Over 17 km of the Reyran
     that is the difference between a correct arrival time and a useless one.
  2. SMEARED BORE. A first-order or over-diffusive scheme turns the jump into a
     gentle ramp spread over tens of cells. The arrival time then depends on
     which contour you happen to pick, which is exactly the ambiguity we are
     trying to eliminate.
  3. OSCILLATION. An unlimited second-order scheme overshoots at the jump,
     producing spurious ripples ahead of the bore (the Gibbs phenomenon). In a
     flood model those ripples are fictitious waves arriving before the real
     flood — the single most dangerous possible error in an early-warning tool.
     The TVD limiter is what prevents this, and this test is where we prove it.

WHAT WE COMPARE AGAINST
-----------------------
Stoker's solution has no closed form for the intermediate depth; it comes from
matching the rarefaction to the shock, which leaves one scalar nonlinear equation
(solved in jaldrishti.validation.analytical by a bracketed root find). Everything
downstream of that — the middle-state velocity, the bore speed — then follows
exactly. The analytical module is independently checked: the mass and momentum
Rankine-Hugoniot conditions across the shock agree on the bore speed to 2e-15.

TAILWATER DEPTHS TESTED
-----------------------
hr/hl = 0.5, 0.1 and 0.01. The bore gets stronger as the tailwater gets shallower,
and the shallowest case is the hardest: it is close to the dry-bed limit, where the
middle state nearly vanishes and the wetting/drying logic starts to participate.
Testing only a weak bore would let a badly-upwinded scheme pass.
"""

from __future__ import annotations

import numpy as np
import pytest

from jaldrishti.solver import SWE2D
from jaldrishti.validation import stoker, stoker_middle_state

HL = 10.0            # reservoir depth, m
LENGTH = 1000.0      # domain length, m
X_DAM = 500.0        # dam location, m — lands on a cell FACE for every dx tested
T_END = 20.0         # s. Chosen so neither the rarefaction head (travelling left at
                     # -sqrt(g*hl) = -9.9 m/s) nor the bore (travelling right at
                     # 9.4-12.4 m/s depending on tailwater) reaches a boundary. The
                     # comparison is therefore against the pure Stoker solution with
                     # no boundary contamination.
NY = 4
G = 9.81

# Tailwater depths: weak bore, strong bore, near-dry bore.
TAILWATERS = [5.0, 1.0, 0.1]


def _run(hr, dx, limiter="mc", t_end=T_END):
    nx = int(round(LENGTH / dx))
    z = np.zeros((NY, nx))

    # Manning n = 0: Stoker, like Ritter, assumes a frictionless bed.
    s = SWE2D(z, dx, manning=0.0, limiter=limiter,
              bc=("wall", "open", "wall", "wall"))

    xc = (np.arange(nx) + 0.5) * dx
    h0 = np.where(xc < X_DAM, HL, hr)
    s.set_depth(np.broadcast_to(h0, (NY, nx)))

    stats = s.run(t_end)
    return s, xc, stats


def _profiles(s, xc, hr, t):
    j = NY // 2
    h_num = s.h[j].copy()
    u_num = s.u[j].copy()
    h_exact, u_exact = stoker(xc, t, HL, hr, x0=X_DAM, g=G)
    return h_num, u_num, h_exact, u_exact


def _shock_index(h):
    """
    Index of the cell immediately upstream of the bore.

    The bore is the steepest DOWNWARD step in the profile going left to right.
    The rarefaction fan also descends, but far more gently: for hl/hr = 10 it
    spreads ~6 m of depth over ~350 m, i.e. ~0.03 m per metre, against ~1 m per
    metre at the jump. So the steepest-descent test finds the bore unambiguously,
    and does not need to be told where to look.
    """
    return int(np.argmin(np.diff(h)))


def _shock_position(xc, h, hr, hm):
    """
    Sub-cell bore position, by linear interpolation of the half-height crossing.

    Taking the cell face nearest the jump would quantise the answer to dx, which
    is not merely imprecise — it is actively misleading, because the exact bore
    happens to sit just above x = 696 m and 696 is divisible by every dx we test,
    so all three resolutions would report the SAME error and the measurement would
    look grid-independent when it is really just rounding to the same place.

    Interpolating the level h = (hr + hm)/2 is unambiguous: the rarefaction fan
    bottoms out at hm, and the half-height is below hm by construction, so this
    level is crossed once and only once, at the bore.
    """
    level = 0.5 * (hr + hm)
    i = _shock_index(h)
    # Walk outward for the bracketing pair straddling `level`, in case the
    # steepest-gradient cell is one off from the crossing.
    lo = max(0, i - 3)
    hi = min(len(h) - 1, i + 4)
    for k in range(lo, hi):
        if h[k] >= level >= h[k + 1]:
            frac = (h[k] - level) / (h[k] - h[k + 1])
            return float(xc[k] + frac * (xc[k + 1] - xc[k]))
    return 0.5 * (xc[i] + xc[i + 1])       # fall back to the face


@pytest.mark.parametrize("hr", TAILWATERS, ids=[f"hr={h:g}" for h in TAILWATERS])
def test_stoker_survives_and_is_positive(hr):
    """Before accuracy: no NaN, no negative depth, no unphysical velocity."""
    s, _xc, _stats = _run(hr, 2.0)
    _hm, um, sh = stoker_middle_state(HL, hr, g=G)

    assert np.all(np.isfinite(s.h)), "NaN or inf in the depth field"
    assert np.all(np.isfinite(s.hu)), "NaN or inf in the momentum field"
    assert s.h.min() >= 0.0, f"negative depth {s.h.min():.3e} m survived"
    # Nothing in this problem moves faster than the bore or the middle state.
    assert s.speed.max() < 3.0 * max(um, sh), (
        f"velocity {s.speed.max():.1f} m/s is far beyond anything in the exact "
        f"solution (middle state {um:.2f}, bore {sh:.2f} m/s)")


@pytest.mark.parametrize("hr", TAILWATERS, ids=[f"hr={h:g}" for h in TAILWATERS])
def test_stoker_mass_conserved(hr):
    """
    Nothing leaves the domain in 20 s, so the volume must not change.

    Worth asserting separately from Ritter: the wet-bed case never triggers the
    dry-cell clipping path, so a drift here would point at the boundary treatment
    or at the flux accumulation rather than at wetting/drying.
    """
    dx = 2.0
    s, _xc, stats = _run(hr, dx)
    assert abs(stats.volume_error) < 1.0e-12, (
        f"hr={hr}: mass drifted by {stats.volume_error:.3e} (relative)")
    v_expected = (X_DAM * HL + (LENGTH - X_DAM) * hr) * (NY * dx)
    assert abs(stats.volume_initial - v_expected) / v_expected < 1e-12


@pytest.mark.parametrize("hr", TAILWATERS, ids=[f"hr={h:g}" for h in TAILWATERS])
def test_stoker_shock_position(hr):
    """
    Is the bore in the right place? This is the headline number of the file.

    Unlike a smooth error, a bore-speed error accumulates linearly with time, so
    getting this right at t = 20 s is what licenses us to trust a 3-hour Tehri
    run. Tolerance is 2 cells.
    """
    dx = 2.0
    s, xc, _stats = _run(hr, dx)
    j = NY // 2
    hm, _um, s_exact = stoker_middle_state(HL, hr, g=G)

    x_num = _shock_position(xc, s.h[j], hr, hm)
    x_exact = X_DAM + s_exact * s.t
    err = abs(x_num - x_exact)

    assert err <= 1.0 * dx, (
        f"hr={hr}: bore at {x_num:.1f} m vs exact {x_exact:.1f} m — error "
        f"{err:.1f} m = {100 * err / (x_exact - X_DAM):.2f}% of the "
        f"{x_exact - X_DAM:.0f} m travelled. A bore-speed error grows linearly in "
        f"time; check the HLLC middle-wave speed and the flux accumulation.")


@pytest.mark.parametrize("hr", TAILWATERS, ids=[f"hr={h:g}" for h in TAILWATERS])
def test_stoker_middle_state(hr):
    """
    The plateau between the rarefaction and the bore must sit at (hm, um).

    This is the strongest single check in the file. hm and um come from matching
    a rarefaction to a shock, so hitting both simultaneously means the scheme has
    the rarefaction structure AND the jump conditions right. Getting the bore
    POSITION right while missing hm would mean we had the right answer for the
    wrong reason.
    """
    dx = 1.0
    s, xc, _stats = _run(hr, dx)
    j = NY // 2
    hm, um, s_exact = stoker_middle_state(HL, hr, g=G)
    cm = np.sqrt(G * hm)

    # Sample the interior of the plateau, staying clear of both edges: the
    # rarefaction tail at xi = um - cm and the bore at xi = s_exact.
    x_lo = X_DAM + (um - cm) * s.t
    x_hi = X_DAM + s_exact * s.t
    margin = 0.15 * (x_hi - x_lo)
    band = (xc > x_lo + margin) & (xc < x_hi - margin)
    assert band.sum() >= 10, "plateau sampling window too narrow — adjust t_end"

    h_mid = float(np.mean(s.h[j][band]))
    u_mid = float(np.mean(s.u[j][band]))
    h_rel = abs(h_mid - hm) / hm
    u_rel = abs(u_mid - um) / um

    assert h_rel < 0.02, (
        f"hr={hr}: middle-state depth {h_mid:.4f} m vs exact {hm:.4f} m "
        f"({100 * h_rel:.2f}% error)")
    assert u_rel < 0.02, (
        f"hr={hr}: middle-state velocity {u_mid:.4f} m/s vs exact {um:.4f} m/s "
        f"({100 * u_rel:.2f}% error)")


@pytest.mark.parametrize("hr", TAILWATERS, ids=[f"hr={h:g}" for h in TAILWATERS])
def test_stoker_shock_is_sharp(hr):
    """
    How many cells does the bore occupy?

    A discontinuity can only ever be resolved over a finite number of cells, but
    HOW many is a direct measure of numerical diffusion. An HLLC + MUSCL scheme
    should capture a bore in a handful of cells. If it smears over tens of them,
    the arrival time becomes a matter of which contour you choose — precisely the
    ambiguity this project exists to remove.

    Measured as the number of cells whose depth lies strictly inside the middle
    5-95% of the jump, within a window around the detected bore.
    """
    dx = 2.0
    s, xc, _stats = _run(hr, dx)
    j = NY // 2
    h = s.h[j]
    hm, _um, _s = stoker_middle_state(HL, hr, g=G)

    lo = hr + 0.05 * (hm - hr)
    hi = hr + 0.95 * (hm - hr)
    i_shock = _shock_index(h)
    window = slice(max(0, i_shock - 20), min(len(h), i_shock + 21))
    n_cells = int(np.sum((h[window] > lo) & (h[window] < hi)))

    assert n_cells <= 6, (
        f"hr={hr}: bore smeared over {n_cells} cells (depth between {lo:.3f} and "
        f"{hi:.3f} m). The Riemann solver is not upwinding — a diffused bore makes "
        f"arrival time contour-dependent.")


@pytest.mark.parametrize("limiter", ["none", "minmod", "mc"])
def test_stoker_no_spurious_oscillation(limiter):
    """
    THE MOST SAFETY-CRITICAL TEST IN THE VALIDATION LADDER.

    The exact solution is bounded everywhere: hr <= h <= hl. Any depth outside
    that range is an oscillation manufactured by the scheme, and an oscillation
    ahead of the bore is a FICTITIOUS EARLY FLOOD WAVE. In an early-warning tool
    that is worse than being wrong — it is wrong in the direction that destroys
    trust, because the false alarm arrives before the real event.

    All three of our reconstruction options must be monotone: 'none' is
    piecewise-constant (trivially so), and 'minmod' and 'mc' are both TVD
    limiters. If a future change swapped in an unlimited centred slope for
    accuracy, this test is what would catch it.
    """
    hr = 1.0
    dx = 2.0
    s, xc, _stats = _run(hr, dx, limiter=limiter)
    h = s.h          # SWE2D.h exposes the INTERIOR field only; ghost cells are
                     # internal to the solver and never surface here.

    over = float(h.max() - HL)
    under = float(hr - h.min())
    scale = HL - hr

    assert over <= 0.01 * scale, (
        f"{limiter}: depth overshoots the reservoir level by {over:.4f} m "
        f"({100 * over / scale:.2f}% of the {scale:.1f} m jump). The limiter is "
        f"not enforcing TVD.")
    assert under <= 0.01 * scale, (
        f"{limiter}: depth undershoots the tailwater by {under:.4f} m "
        f"({100 * under / scale:.2f}% of the jump) — a spurious drawdown ahead of "
        f"the bore.")

    # Sharper form of the same statement: well ahead of the bore the water must
    # still be sitting undisturbed at exactly hr. Any ripple there is a phantom
    # wave that has outrun the physical one.
    j = NY // 2
    hm_ref, _um_ref, _s_ref = stoker_middle_state(HL, hr, g=G)
    x_shock = _shock_position(xc, s.h[j], hr, hm_ref)
    ahead = xc > x_shock + 15.0 * dx
    if ahead.sum() > 5:
        ripple = float(np.max(np.abs(s.h[j][ahead] - hr)))
        assert ripple <= 0.005 * scale, (
            f"{limiter}: {ripple:.5f} m ripple {15 * dx:.0f} m AHEAD of the bore — "
            f"a fictitious wave arriving before the real flood")


def test_stoker_bore_speed_measured_over_time():
    """
    Measure the bore CELERITY directly, rather than inferring it from one snapshot.

    Two independent runs to t = 10 s and t = 20 s; the bore displacement between
    them divided by the elapsed time is the propagation speed. This is the
    quantity that maps onto arrival time in a channel that already carries water,
    and measuring it over an interval cancels any constant offset in how we locate
    the jump — including the sub-cell bias of the half-height estimator, which is
    the same at both times and therefore drops out of the difference entirely.

    That cancellation is why this test can afford a 1% tolerance where the
    single-snapshot position test allows a whole cell.
    """
    hr = 1.0
    dx = 1.0
    hm, _um, s_exact = stoker_middle_state(HL, hr, g=G)

    s1, xc1, _ = _run(hr, dx, t_end=10.0)
    s2, xc2, _ = _run(hr, dx, t_end=20.0)
    j = NY // 2
    x1 = _shock_position(xc1, s1.h[j], hr, hm)
    x2 = _shock_position(xc2, s2.h[j], hr, hm)
    s_meas = (x2 - x1) / (s2.t - s1.t)
    rel = abs(s_meas - s_exact) / s_exact

    assert rel < 0.01, (
        f"measured bore speed {s_meas:.4f} m/s vs Rankine-Hugoniot "
        f"{s_exact:.4f} m/s ({100 * rel:.2f}% error). This error accumulates "
        f"linearly with distance, so 3% here is 3% of arrival time everywhere.")


@pytest.mark.parametrize("limiter", ["none", "minmod", "mc"])
def test_stoker_profile_accuracy(limiter):
    """
    L1 depth error over the whole domain.

    First order is admitted with a looser tolerance on purpose: it SHOULD be
    worse. The gap between 'none' and 'mc' is the measured value of MUSCL on a
    shock problem, and it is the quantitative answer to "why not just use a
    simple scheme?".
    """
    hr = 1.0
    dx = 2.0
    s, xc, _stats = _run(hr, dx, limiter=limiter)
    h_num, _u, h_exact, _ue = _profiles(s, xc, hr, s.t)

    l1 = float(np.mean(np.abs(h_num - h_exact)))
    tol = 0.35 if limiter == "none" else 0.15
    assert l1 < tol, f"{limiter}: L1 depth error {l1:.4f} m exceeds {tol} m"


def test_stoker_chart(chart_dir):
    """
    The deck figure. Four panels: profile match with the wave structure labelled,
    velocity match, the tailwater sweep (bore strengthens as the tailwater
    shallows), and a measured convergence study.
    """
    import matplotlib.pyplot as plt

    hr_ref = 1.0
    dx_ref = 2.0
    s, xc, stats = _run(hr_ref, dx_ref)
    h_num, u_num, h_exact, u_exact = _profiles(s, xc, hr_ref, s.t)
    hm, um, s_shock = stoker_middle_state(HL, hr_ref, g=G)
    cm = np.sqrt(G * hm)
    j = NY // 2

    # --- convergence study -------------------------------------------------
    dxs = [4.0, 2.0, 1.0]
    errs, shock_errs = [], []
    for dx in dxs:
        sc, xcc, _st = _run(hr_ref, dx)
        hn, _un, he, _ue = _profiles(sc, xcc, hr_ref, sc.t)
        errs.append(float(np.mean(np.abs(hn - he))))
        shock_errs.append(_shock_position(xcc, sc.h[j], hr_ref, hm)
                          - (X_DAM + s_shock * sc.t))

    orders = [np.log(errs[k] / errs[k + 1]) / np.log(dxs[k] / dxs[k + 1])
              for k in range(len(dxs) - 1)]

    fig, axes = plt.subplots(2, 2, figsize=(13.5, 8.4))

    # panel 1: depth profile, wave structure labelled
    ax = axes[0, 0]
    ax.plot(xc / 1000.0, h_exact, "k-", lw=2, label="Stoker (1957) exact")
    ax.plot(xc / 1000.0, h_num, color="#1565c0", lw=1.4, ls="--",
            label=f"JALDRISHTI, dx = {dx_ref:.0f} m")
    ax.axvline(X_DAM / 1000.0, color="grey", ls=":", lw=1)
    for xi, lbl in [(-np.sqrt(G * HL), "rarefaction\nhead"),
                    (um - cm, "fan tail"),
                    (s_shock, "BORE")]:
        xp = (X_DAM + xi * s.t) / 1000.0
        ax.annotate(lbl, (xp, 9.3), fontsize=7, ha="center", color="#37474f",
                    arrowprops=dict(arrowstyle="-", lw=0.7, color="#90a4ae"),
                    xytext=(xp, 10.6))
    ax.axhline(hm, color="#2e7d32", ls="-.", lw=1,
               label=f"middle state $h_m$ = {hm:.3f} m")
    ax.set_xlabel("distance  [km]")
    ax.set_ylabel("depth  [m]")
    ax.set_ylim(0, 12.2)
    ax.set_title(f"Depth profile at t = {s.t:.0f} s  "
                 f"($h_l/h_r$ = {HL / hr_ref:.0f})", fontsize=10)
    ax.legend(fontsize=7.5, loc="center left")
    ax.grid(alpha=0.3)

    # Box goes in the empty quadrant DOWNSTREAM of the bore, above the tailwater:
    # for x > 0.7 km the profile sits at h = 1 m, so everything above it is free.
    # Anywhere left of the bore would cover either the plateau or the jump itself,
    # which are the two features the panel exists to show.
    travelled = s_shock * s.t
    ax.text(0.99, 0.72,
            f"bore position error:  {shock_errs[1]:+.2f} m\n"
            f"    = {100 * abs(shock_errs[1]) / travelled:.3f}% of {travelled:.0f} m "
            f"travelled\n"
            f"bore speed:  {s_shock:.3f} m/s (Rankine-Hugoniot)\n"
            f"mass error:  {stats.volume_error:.1e}\n"
            f"L1 depth error:  {errs[1]:.4f} m",
            transform=ax.transAxes, fontsize=7.5, va="top", ha="right",
            bbox=dict(boxstyle="round,pad=0.4", fc="#e3f2fd", ec="#0d47a1",
                      lw=0.8))

    # panel 2: velocity
    ax = axes[0, 1]
    ax.plot(xc / 1000.0, u_exact, "k-", lw=2, label="exact")
    ax.plot(xc / 1000.0, u_num, color="#c62828", lw=1.4, ls="--",
            label="JALDRISHTI")
    ax.axhline(um, color="#2e7d32", ls="-.", lw=1,
               label=f"$u_m$ = {um:.3f} m/s")
    ax.set_xlabel("distance  [km]")
    ax.set_ylabel("velocity  [m/s]")
    ax.set_title("Velocity profile — note the jump AT the bore", fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    # panel 3: tailwater sweep
    ax = axes[1, 0]
    colours = ["#0277bd", "#00838f", "#558b2f"]
    for hr, col in zip(TAILWATERS, colours):
        sh, xch, _ = _run(hr, dx_ref)
        he, _ue = stoker(xch, sh.t, HL, hr, x0=X_DAM, g=G)
        # The exact solution is drawn as a WIDE PALE BAND rather than a thin solid
        # line. At this level of agreement a 2 pt solid line is completely hidden
        # under the dashed numerical line, which makes the panel look like it shows
        # one curve instead of two matching ones — the opposite of the intended
        # message. A fat translucent band with the dashed line running inside it
        # reads correctly at slide distance.
        ax.plot(xch / 1000.0, he, "-", color=col, lw=5.0, alpha=0.30)
        ax.plot(xch / 1000.0, sh.h[j], "--", color=col, lw=1.3,
                label=f"$h_r$ = {hr:g} m  ($h_l/h_r$ = {HL / hr:.0f})")
    ax.set_xlabel("distance  [km]")
    ax.set_ylabel("depth  [m]")
    ax.set_title("Tailwater sweep: the shallower the tailwater,\n"
                 "the stronger and faster the bore  "
                 "(pale band = exact, dashed = ours)", fontsize=10)
    ax.legend(fontsize=7.5)
    ax.grid(alpha=0.3)

    # panel 4: convergence
    ax = axes[1, 1]
    ax.loglog(dxs, errs, "o-", color="#2e7d32", lw=1.8, label="measured L1 error")
    ref = np.array(dxs, dtype=float)
    ax.loglog(ref, errs[0] * (ref / ref[0]) ** 1.0, "k--", lw=1,
              label="1st order reference")
    ax.invert_xaxis()
    ax.set_xticks(dxs)
    ax.set_xticklabels([f"{d:g}" for d in dxs])
    ax.minorticks_off()
    ax.set_xlabel("cell size  [m]")
    ax.set_ylabel("L1 depth error  [m]")
    ax.set_title("Grid convergence\n"
                 f"observed order: {', '.join(f'{o:.2f}' for o in orders)}  "
                 f"(1st order is CORRECT for a shock)", fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, which="both")

    fig.suptitle("JALDRISHTI solver validation 3/4 — Stoker wet-bed dam break "
                 "(shock capturing)", fontsize=12, y=1.00)
    fig.tight_layout()
    out = chart_dir / "03_stoker_wet_bed.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)

    # Sharpness and monotonicity, reported for the record.
    lo = hr_ref + 0.05 * (hm - hr_ref)
    hi = hr_ref + 0.95 * (hm - hr_ref)
    i_sh = _shock_index(s.h[j])
    win = slice(max(0, i_sh - 20), min(s.h.shape[1], i_sh + 21))
    n_cells = int(np.sum((s.h[j][win] > lo) & (s.h[j][win] < hi)))
    hint = s.h

    print(f"\n[stoker] bore position error vs resolution: "
          f"{', '.join(f'dx={d:.0f}m -> {e:+.3f}m' for d, e in zip(dxs, shock_errs))}"
          f"   (bore travelled {s_shock * s.t:.1f} m)")
    print(f"[stoker] bore speed (Rankine-Hugoniot) {s_shock:.4f} m/s; "
          f"middle state hm={hm:.4f} m, um={um:.4f} m/s")
    print(f"[stoker] bore captured in {n_cells} cells at dx={dx_ref:.0f} m")
    print(f"[stoker] monotonicity: overshoot above h_l "
          f"{max(0.0, hint.max() - HL):.2e} m, undershoot below h_r "
          f"{max(0.0, hr_ref - hint.min()):.2e} m")
    print(f"[stoker] L1 depth error: "
          f"{', '.join(f'dx={d:.0f}m -> {e:.4f}m' for d, e in zip(dxs, errs))}")
    print(f"[stoker] observed convergence order: "
          f"{', '.join(f'{o:.2f}' for o in orders)}")
    print(f"[stoker] mass error {stats.volume_error:.2e} over {stats.steps} steps"
          f"  ->  {out}")
    assert out.exists()

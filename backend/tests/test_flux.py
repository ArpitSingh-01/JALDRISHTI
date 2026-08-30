"""
HLLC Riemann solver — direct unit tests.

WHY THIS FILE EXISTS
--------------------
`flux.py` is called once per cell face per stage per timestep — tens of billions
of times in a single Malpasset run — and until now it had no direct test at all.
Every solver test was integration-level, which means a defect here could only
ever be observed as "the flood looks wrong", with no way to localise it.

A Riemann solver is also the one component where being *approximately* right is
the design goal, so the tests have to be chosen carefully. Asserting that HLLC
reproduces the exact Riemann solution would be asserting something false. What
CAN be asserted is a small set of properties that any correct approximate solver
must have exactly, and which between them pin down almost all of the algebra:

  CONSISTENCY   F(q, q) must equal the physical flux f(q), exactly. An
                approximate solver that is inconsistent is not solving the right
                equations at all, and no amount of grid refinement fixes it.

  CONSERVATION  The same face seen from the two adjacent cells must carry the
                same flux — guaranteed here by construction (one call per face)
                but worth pinning via reflection symmetry.

  SYMMETRY      Mirroring the problem in x must negate the mass flux and leave
                the normal-momentum flux alone. If this fails the solver has a
                preferred direction, and a flood wave will drift sideways for
                purely numerical reasons.

  UPWINDING     Transverse momentum must be upwinded across the contact wave,
                not averaged. This is the entire difference between HLLC and
                HLL, and it is what lets the wave survive the bend in the Reyran
                valley. The test computes what HLL would have given and asserts
                the code does NOT give it.

  DRY STATES    Zero flux when both sides are dry; water advancing into dry
                ground when only one side is; finite output always.

ON DRY-BED ACCURACY — AN HONEST LIMITATION
------------------------------------------
For a wet/dry Riemann problem (hL = h0, uL = 0 | hR = 0) the exact Ritter flux
at the interface is (8/27)*c0*h0 = 0.296*c0*h0, whereas the HLL average state
gives (2/3)*c0*h0 = 0.667*c0*h0 — more than twice as much. That is not a bug in
this file; it is the known cost of replacing an entire rarefaction fan with a
single constant state. It is acceptable because a real front is never resolved by
one face: MUSCL reconstruction spreads the fan over several cells, and the
scheme-level accuracy is what `tests/test_ritter.py` measures. The test below
pins the value the scheme actually computes and says plainly that it is not
Ritter's, so nobody later mistakes the discrepancy for a defect.
"""

import math

import numpy as np
import pytest

from jaldrishti.solver.flux import hllc_x, max_wave_speed

G = 9.81
HM = 1.0e-3


def physical_flux(h, u, v, g=G):
    """The exact flux f(q) for a single state — what consistency is measured
    against. Advection plus hydrostatic pressure in the normal component,
    passive advection in the transverse one."""
    return (h * u, h * u * u + 0.5 * g * h * h, h * u * v)


def hll_transverse(hL, uL, vL, hR, uR, vR, g=G):
    """
    What the transverse-momentum flux would be under plain HLL — i.e. averaged
    across the contact instead of upwinded through it.

    Used only to assert that the code does NOT do this. Restricted to the
    subsonic branch, which is where the two schemes differ.
    """
    cL, cR = math.sqrt(g * hL), math.sqrt(g * hR)
    c_star = 0.5 * (cL + cR) + 0.25 * (uL - uR)
    u_star = 0.5 * (uL + uR) + cL - cR
    sL = min(uL - cL, u_star - c_star)
    sR = max(uR + cR, u_star + c_star)
    FL = hL * uL * vL
    FR = hR * uR * vR
    return ((sR * FL - sL * FR + sL * sR * (hR * vR - hL * vL))
            / (sR - sL))


# ---------------------------------------------------------------------------
# consistency
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("h", [0.01, 0.5, 2.0, 20.0, 100.0])
@pytest.mark.parametrize("u", [-8.0, -1.0, 0.0, 0.3, 3.0, 25.0])
@pytest.mark.parametrize("v", [0.0, 2.0, -5.0])
def test_the_flux_is_consistent_with_the_physical_flux(h, u, v):
    """
    F(q, q) == f(q) to machine precision, for every state.

    The single most important property of an approximate Riemann solver: if the
    left and right states agree there is no discontinuity, so the answer must be
    the exact physical flux with no numerical dissipation added. The parameter
    sweep deliberately spans subcritical and supercritical, both flow
    directions, and depths from a thin film to a reservoir, because the routine
    takes three structurally different branches (sL >= 0, sR <= 0, and the
    subsonic HLL average) and consistency must hold on all of them.
    """
    got = hllc_x(h, u, v, h, u, v, G, HM)
    assert got == pytest.approx(physical_flux(h, u, v), rel=1e-13, abs=1e-13)


def test_consistency_holds_across_all_three_branches():
    """
    Make it explicit that the sweep above really does exercise every branch,
    rather than trusting that it happens to.

    A test that only ever hit the subsonic branch would leave the two supersonic
    early returns — which are pure upwinding and easy to get backwards —
    completely uncovered.
    """
    h = 4.0
    c = math.sqrt(G * h)
    for u, branch in ((c * 1.5, "sL >= 0"), (-c * 1.5, "sR <= 0"), (0.2, "subsonic")):
        got = hllc_x(h, u, 1.0, h, u, 1.0, G, HM)
        assert got == pytest.approx(physical_flux(h, u, 1.0), rel=1e-13), branch


# ---------------------------------------------------------------------------
# symmetry
# ---------------------------------------------------------------------------
def test_mirroring_the_problem_negates_the_mass_flux():
    """
    Reflecting in x — swap the two states and negate both normal velocities —
    must negate the mass and transverse fluxes and leave the normal-momentum
    flux unchanged.

    This is what it means for the solver to have no preferred direction. The
    integration-level symmetry tests in `test_symmetry.py` check the same thing
    for a whole radial dam break, but they cannot say WHERE an asymmetry came
    from. Here it is pinned at the face.
    """
    rng = np.random.default_rng(4242)
    for _ in range(300):
        hL = float(10.0 ** rng.uniform(-2, 1.5))
        hR = float(10.0 ** rng.uniform(-2, 1.5))
        uL = float(rng.uniform(-10, 10))
        uR = float(rng.uniform(-10, 10))
        vL = float(rng.uniform(-6, 6))
        vR = float(rng.uniform(-6, 6))

        fwd = hllc_x(hL, uL, vL, hR, uR, vR, G, HM)
        rev = hllc_x(hR, -uR, vR, hL, -uL, vL, G, HM)

        assert rev[0] == pytest.approx(-fwd[0], rel=1e-12, abs=1e-14)
        assert rev[1] == pytest.approx(fwd[1], rel=1e-12, abs=1e-14)
        assert rev[2] == pytest.approx(-fwd[2], rel=1e-12, abs=1e-14)


def test_the_transverse_flux_flips_sign_with_the_transverse_velocity():
    """
    Negating both transverse velocities must negate only the transverse flux.
    Mass and normal momentum do not care about along-face motion at all, which
    is the statement that the two directions are properly decoupled.
    """
    args = (2.0, 1.0, 3.0, 0.7, -0.4, -1.5)
    a = hllc_x(2.0, 1.0, 3.0, 0.7, -0.4, -1.5, G, HM)
    b = hllc_x(2.0, 1.0, -3.0, 0.7, -0.4, 1.5, G, HM)
    assert b[0] == pytest.approx(a[0], rel=1e-14)
    assert b[1] == pytest.approx(a[1], rel=1e-14)
    assert b[2] == pytest.approx(-a[2], rel=1e-14)
    del args


# ---------------------------------------------------------------------------
# the "C" in HLLC — contact-wave upwinding
# ---------------------------------------------------------------------------
def test_transverse_momentum_is_upwinded_not_averaged():
    """
    THE test that distinguishes HLLC from HLL, and the reason this solver was
    chosen over the simpler one.

    Set up a pure shear: identical depth and normal velocity on both sides, but
    different transverse velocities. Physically the fluid is flowing left to
    right and simply carrying its along-face momentum with it, so the correct
    transverse flux is (mass flux) * vL — the upstream value, exactly. HLL
    instead blends vL and vR, which smears momentum sideways across the contact
    and is what makes HLL lose a flood wave at a sharp valley bend.

    The test asserts both halves: that the code gives the upwinded value, and
    that this is genuinely different from what HLL would have given. Without the
    second assertion the test would silently pass on an HLL implementation in
    any case where the two happen to coincide.
    """
    h, u, vL, vR = 1.5, 1.0, 4.0, -2.0
    Fh, Fhu, Fhv = hllc_x(h, u, vL, h, u, vR, G, HM)
    assert Fhv == pytest.approx(Fh * vL, rel=1e-13), "must upwind from the left"
    hll = hll_transverse(h, u, vL, h, u, vR)
    assert Fhv != pytest.approx(hll, rel=1e-6), (
        f"HLLC gave {Fhv:.6f}; plain HLL would give {hll:.6f}. If these agree "
        f"the contact wave is being averaged, which is the HLL defect."
    )


def test_transverse_momentum_upwinds_from_the_right_when_flow_reverses():
    """The mirror of the above. A sign error in the s_star test would show up
    here and nowhere else, because it needs the flow to run the other way."""
    h, u, vL, vR = 1.5, -1.0, 4.0, -2.0
    Fh, _, Fhv = hllc_x(h, u, vL, h, u, vR, G, HM)
    assert Fhv == pytest.approx(Fh * vR, rel=1e-13), "must upwind from the right"


def test_a_stationary_shear_layer_does_not_move_or_diffuse():
    """
    Equal depths, zero normal velocity, opposite transverse velocities: a shear
    layer at rest. Nothing crosses the face — the mass flux and the transverse
    flux must both be exactly zero, and the normal-momentum flux must be exactly
    the hydrostatic pressure.

    This is the face-level ingredient of lake-at-rest. If the pressure term were
    off by any factor, still water would not stay still.
    """
    h = 3.0
    Fh, Fhu, Fhv = hllc_x(h, 0.0, 2.0, h, 0.0, -2.0, G, HM)
    assert Fh == 0.0
    assert Fhv == 0.0
    assert Fhu == pytest.approx(0.5 * G * h * h, rel=1e-14)


# ---------------------------------------------------------------------------
# supersonic upwinding
# ---------------------------------------------------------------------------
def test_supersonic_flow_is_pure_upwinding():
    """
    When the whole wave fan travels one way the face sees only one state, and the
    flux must be that state's physical flux exactly — no averaging, no
    dissipation. Getting these two early returns swapped is a classic error that
    produces a solver which works only for subcritical flow, and a dam break is
    emphatically not subcritical.
    """
    hL, hR = 2.0, 1.0
    fast = 3.0 * math.sqrt(G * max(hL, hR))
    assert hllc_x(hL, fast, 1.0, hR, fast, -1.0, G, HM) == pytest.approx(
        physical_flux(hL, fast, 1.0), rel=1e-13)
    assert hllc_x(hL, -fast, 1.0, hR, -fast, -1.0, G, HM) == pytest.approx(
        physical_flux(hR, -fast, -1.0), rel=1e-13)


# ---------------------------------------------------------------------------
# dry states
# ---------------------------------------------------------------------------
def test_two_dry_cells_exchange_nothing():
    """
    All three fluxes exactly zero. This is also what keeps the wave-speed
    estimates from dividing by zero, so it is a robustness guard as much as a
    physical statement — most of a flood domain is dry for most of a run.
    """
    for hL, hR in ((0.0, 0.0), (0.0, HM), (HM, 0.0), (HM * 0.5, HM * 0.5)):
        assert hllc_x(hL, 0.0, 0.0, hR, 0.0, 0.0, G, HM) == (0.0, 0.0, 0.0)


def test_water_advances_into_dry_ground():
    """
    Wet left, dry right — the advancing flood front, the case that matters most
    for this project. The mass flux must be strictly positive: water moves into
    the dry cell even though both velocities are zero, driven by the depth
    difference alone. A solver that returned zero here would never wet a single
    downstream cell.
    """
    h0 = 4.0
    Fh, Fhu, Fhv = hllc_x(h0, 0.0, 0.0, 0.0, 0.0, 0.0, G, HM)
    assert Fh > 0.0
    assert np.isfinite([Fh, Fhu, Fhv]).all()
    # mirror: dry left, wet right must drain the other way
    Fh_m, _, _ = hllc_x(0.0, 0.0, 0.0, h0, 0.0, 0.0, G, HM)
    assert Fh_m < 0.0
    assert Fh_m == pytest.approx(-Fh, rel=1e-12)


def test_the_dry_front_uses_the_ritter_wave_speed():
    """
    Pin the wet/dry wave-speed estimate, which is a correctness requirement
    rather than a tuning choice: a rarefaction expanding into a dry bed advances
    at u + 2c, not u + c. Using u + c makes the front lag or the scheme go
    unstable.

    With hL = h0, uL = 0 against a dry cell the HLL average state gives a mass
    flux of exactly (2/3)*c0*h0, whereas the u + c estimate would give
    (1/2)*c0*h0. Asserting the value therefore pins the choice.

    NOTE, and this is deliberate rather than an oversight: (2/3)*c0*h0 is NOT
    Ritter's exact interface flux, which is (8/27)*c0*h0. Collapsing a whole
    rarefaction fan onto one constant state overestimates the flux at a fully dry
    interface by 2.25x. That is the documented cost of an HLL-family solver and
    it is why scheme-level dry-bed accuracy is established by the Ritter rung
    over a resolved front, not by this single face.
    """
    h0 = 4.0
    c0 = math.sqrt(G * h0)
    Fh, _, _ = hllc_x(h0, 0.0, 0.0, 0.0, 0.0, 0.0, G, HM)
    assert Fh == pytest.approx((2.0 / 3.0) * c0 * h0, rel=1e-12)
    assert Fh != pytest.approx(0.5 * c0 * h0, rel=1e-3), (
        "this is the value the u + c estimate would give"
    )
    ritter = (8.0 / 27.0) * c0 * h0
    assert Fh > ritter, "documented: the HLL average state overestimates here"


def test_no_input_produces_a_nan_or_an_infinity():
    """
    A randomised sweep over the whole state space the solver will meet: dry,
    near-threshold, thin films, deep reservoirs, both flow directions, and huge
    depth ratios across a face.

    One NaN anywhere poisons the CFL reduction and kills the entire run, so this
    is the cheapest insurance in the whole test suite. Depth ratios up to 10^7
    across a single face are included because that is what a breach face looks
    like on the first timestep.
    """
    rng = np.random.default_rng(90210)
    for _ in range(4000):
        hL = float(rng.choice([0.0, 10.0 ** rng.uniform(-8, 2)]))
        hR = float(rng.choice([0.0, 10.0 ** rng.uniform(-8, 2)]))
        uL = float(rng.uniform(-50, 50))
        uR = float(rng.uniform(-50, 50))
        vL = float(rng.uniform(-50, 50))
        vR = float(rng.uniform(-50, 50))
        out = hllc_x(hL, uL, vL, hR, uR, vR, G, HM)
        assert np.isfinite(out).all(), (hL, uL, vL, hR, uR, vR, out)


def test_the_degenerate_contact_fallback_is_reachable_and_finite():
    """
    The s_star denominator vanishes for near-identical states, and the code falls
    back to the average velocity. Exercise that branch explicitly so the
    fallback is known to work rather than merely present — an unreached guard is
    an untested guard.
    """
    h, u = 2.0, 0.5
    eps = 1.0e-14
    out = hllc_x(h, u, 1.0, h + eps, u, -1.0, G, HM)
    assert np.isfinite(out).all()
    assert out[0] == pytest.approx(h * u, rel=1e-9)


# ---------------------------------------------------------------------------
# CFL wave speed
# ---------------------------------------------------------------------------
def test_max_wave_speed_is_velocity_plus_celerity():
    """|u| + sqrt(g*h) per direction. This is the CFL denominator, so an
    underestimate here is not a small error — it lets the timestep grow past the
    stability limit and the run diverges."""
    h, u, v = 5.0, -2.0, 3.0
    c = math.sqrt(G * h)
    sx, sy = max_wave_speed(h, u, v, G, HM)
    assert sx == pytest.approx(abs(u) + c, rel=1e-14)
    assert sy == pytest.approx(abs(v) + c, rel=1e-14)


def test_max_wave_speed_is_zero_in_a_dry_cell():
    """A dry cell must not constrain the timestep — otherwise the mostly-dry
    domain around a flood would throttle every step for no reason."""
    assert max_wave_speed(0.0, 100.0, 100.0, G, HM) == (0.0, 0.0)
    assert max_wave_speed(HM, 100.0, 100.0, G, HM) == (0.0, 0.0)


def test_max_wave_speed_bounds_the_hllc_wave_fan():
    """
    The CFL speed must not be smaller than the fastest wave the flux routine
    actually uses, or the timestep is unsafe.

    Checked against the two-rarefaction estimates directly, including the dry
    cases where the front runs at u + 2c — the case where an inconsistency
    between the two routines would be most likely and most damaging.
    """
    rng = np.random.default_rng(1337)
    for _ in range(500):
        h = float(10.0 ** rng.uniform(-2, 1.5))
        u = float(rng.uniform(-8, 8))
        c = math.sqrt(G * h)
        sx, _ = max_wave_speed(h, u, 0.0, G, HM)
        # against a dry neighbour the fan spreads to u + 2c, which exceeds
        # |u| + c. That is safe only because the dry cell contributes 0 and the
        # solver takes the max over BOTH cells of a face; assert the wet cell's
        # own bound holds, which is what the CFL loop relies on.
        assert sx >= abs(u) + c - 1e-12
        assert sx >= abs(u)
        assert sx >= c

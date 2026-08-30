"""
MUSCL slope limiters — direct unit tests.

WHY THIS FILE EXISTS
--------------------
`reconstruct.py` is the difference between a flood front that stays a wall of
water over 17 km and one that smears into a gentle ramp. It is also the piece
that, if wrong, drives depth negative — and a negative depth means sqrt(g*h) is
NaN, which spreads across the whole domain in a handful of timesteps. Until now
it had no direct test.

The limiters are thirty lines of branchless arithmetic, which makes them exactly
the kind of code that looks obviously right and is easy to get subtly wrong. The
properties below are the ones that matter:

  TVD / MONOTONICITY   The reconstructed face values must lie between the
                       neighbouring cell averages. This is the property that
                       prevents negative depth. Tested over a randomised sweep
                       rather than a handful of cases, because the failure mode
                       is an overshoot in a corner of the input space.

  EXTREMUM -> FLAT     At a local maximum or minimum the only monotone slope is
                       zero. Both limiters must return exactly 0.0 there.

  LINEAR EXACTNESS     On linear data the limiter must return the exact slope,
                       unclipped. This is what makes the scheme second-order; a
                       limiter that clipped smooth data would quietly reduce the
                       whole solver to first order and nobody would see an error,
                       only a blurrier flood.

  ANTISYMMETRY         Mirroring the stencil must negate the slope, and negating
                       the data must negate the slope. Either failing gives the
                       scheme a directional bias — which is what the radial
                       dam-break symmetry tests would eventually catch, but only
                       as a whole-domain symptom with no localisation.

  ORDERING             MC must be at least as steep as minmod everywhere, and
                       strictly steeper somewhere. That is the entire reason MC
                       is the default; if the two agreed always, the sharper
                       option would be a fiction.

  DISPATCH             `limited_slope` must route all three limiter codes
                       correctly, and LIMITER_NONE must give exactly first order.
"""

import itertools

import numpy as np
import pytest

from jaldrishti.solver.reconstruct import (
    LIMITER_MC,
    LIMITER_MINMOD,
    LIMITER_NAMES,
    LIMITER_NONE,
    limited_slope,
    mc_limiter,
    minmod,
)

ALL_LIMITERS = (LIMITER_NONE, LIMITER_MINMOD, LIMITER_MC)
TVD_LIMITERS = (LIMITER_MINMOD, LIMITER_MC)


# ---------------------------------------------------------------------------
# the two limiter functions in isolation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("lim", [minmod, mc_limiter])
@pytest.mark.parametrize("a, b", [
    (1.0, -1.0), (-1.0, 1.0), (3.0, -0.5), (-0.5, 3.0),
    (1.0, 0.0), (0.0, 1.0), (0.0, 0.0), (-2.0, 0.0),
])
def test_a_sign_change_or_a_zero_gives_a_flat_slope(lim, a, b):
    """
    Opposite-signed differences mean the cell sits at a local extremum, and a
    zero difference means one neighbour is level with it. In both cases the only
    monotone reconstruction is flat.

    Returning anything non-zero here is the overshoot that drives depth negative,
    so this is the load-bearing branch of both limiters. Note that a*b <= 0
    covers the zero cases too, which is why they are included: an
    implementation using `a*b < 0` instead would fail exactly these.
    """
    assert lim(a, b) == 0.0


@pytest.mark.parametrize("a, b, want", [
    (1.0, 3.0, 1.0),
    (3.0, 1.0, 1.0),
    (-1.0, -3.0, -1.0),
    (-3.0, -1.0, -1.0),
    (2.0, 2.0, 2.0),
])
def test_minmod_takes_the_smaller_magnitude_difference(a, b, want):
    """minmod is the least-magnitude choice — the most diffusive TVD limiter and
    therefore the most robust. It is the fallback when MC misbehaves."""
    assert minmod(a, b) == pytest.approx(want, rel=1e-15)


@pytest.mark.parametrize("a, b, want", [
    (2.0, 2.0, 2.0),        # smooth: the centred slope, unclipped
    (1.0, 3.0, 2.0),        # centred = 2, clip = 2*1 = 2 -> clipped
    (1.0, 9.0, 2.0),        # centred = 5, clip = 2*1 = 2 -> clipped hard
    (3.0, 3.5, 3.25),       # centred = 3.25, clip = 6 -> centred wins
    (-1.0, -9.0, -2.0),     # the mirror of the third case
])
def test_mc_uses_the_centred_slope_but_clips_it_near_a_jump(a, b, want):
    """
    MC's whole design: be second-order accurate where the solution is smooth by
    using the centred difference, and fall back to twice the smaller one-sided
    difference near a discontinuity. The clip factor of 2 is what keeps it TVD;
    any larger and it oscillates.
    """
    assert mc_limiter(a, b) == pytest.approx(want, rel=1e-15)


def test_mc_is_never_shallower_than_minmod_and_sometimes_steeper():
    """
    The justification for MC being the default limiter.

    If MC were ever shallower than minmod it would be the more diffusive of the
    two and the wrong default. If it were never steeper, the choice would be
    meaningless. Both halves are asserted over a randomised sweep, because a
    single hand-picked pair proves neither.
    """
    rng = np.random.default_rng(77)
    strictly_steeper = 0
    for _ in range(5000):
        a = float(rng.uniform(-10, 10))
        b = float(rng.uniform(-10, 10))
        m, c = minmod(a, b), mc_limiter(a, b)
        assert abs(c) >= abs(m) - 1e-15, f"MC shallower than minmod at {a}, {b}"
        if a * b > 0.0:
            assert m * c > 0.0, "both must agree in sign where they are non-zero"
        if abs(c) > abs(m) + 1e-12:
            strictly_steeper += 1
    assert strictly_steeper > 1000, "MC must be genuinely sharper, not marginally"


def test_the_mc_clip_never_exceeds_twice_the_smaller_difference():
    """
    The TVD bound on MC stated directly. |slope| <= 2*min(|a|, |b|) is what makes
    the half-cell reconstruction stay inside the neighbouring averages; exceeding
    it is precisely the superbee-and-beyond territory that oscillates.
    """
    rng = np.random.default_rng(505)
    for _ in range(5000):
        a = float(rng.uniform(-10, 10))
        b = float(rng.uniform(-10, 10))
        c = mc_limiter(a, b)
        assert abs(c) <= 2.0 * min(abs(a), abs(b)) + 1e-12


# ---------------------------------------------------------------------------
# the TVD property, which is what prevents negative depth
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("limiter", TVD_LIMITERS)
def test_reconstructed_face_values_stay_between_the_cell_averages(limiter):
    """
    THE property the solver's survival depends on.

    The reconstruction is q0 -+ 0.5*slope. Both face values must lie within
    [min(qm, q0, qp), max(qm, q0, qp)] — no new extrema. If they can leave that
    range then a cell adjacent to a dry cell can reconstruct a negative depth at
    its face, sqrt(g*h) returns NaN, and the run is dead within a few steps.

    Swept randomly over five decades of magnitude, including near-equal and
    opposite-signed neighbours, because an overshoot lives in a corner of the
    input space rather than at a round number.
    """
    rng = np.random.default_rng(2026)
    for _ in range(20000):
        scale = 10.0 ** rng.uniform(-4, 3)
        qm, q0, qp = (float(x) for x in rng.uniform(-1, 1, 3) * scale)
        s = limited_slope(qm, q0, qp, limiter)
        lo = min(qm, q0, qp)
        hi = max(qm, q0, qp)
        tol = 1e-12 * max(1.0, abs(lo), abs(hi))
        for face in (q0 - 0.5 * s, q0 + 0.5 * s):
            assert lo - tol <= face <= hi + tol, (
                f"overshoot: stencil {(qm, q0, qp)} slope {s} face {face}"
            )


@pytest.mark.parametrize("limiter", TVD_LIMITERS)
def test_a_face_next_to_a_dry_cell_cannot_reconstruct_a_negative_depth(limiter):
    """
    The TVD property applied to the case that actually kills solvers: a wet cell
    beside a dry one at the head of an advancing flood wave.

    With a non-negative stencil the reconstruction must stay non-negative. This
    is stated separately from the general TVD test because it is the specific
    failure this project cannot afford, and because a reader looking for "is
    wetting/drying safe here" should find it by name.
    """
    rng = np.random.default_rng(31337)
    for _ in range(20000):
        # a monotone or near-monotone drop towards a dry cell
        qm = float(10.0 ** rng.uniform(-4, 1.5))
        q0 = float(10.0 ** rng.uniform(-6, 1.5))
        qp = float(rng.choice([0.0, 10.0 ** rng.uniform(-8, 1.5)]))
        s = limited_slope(qm, q0, qp, limiter)
        assert q0 - 0.5 * s >= -1e-15
        assert q0 + 0.5 * s >= -1e-15


# ---------------------------------------------------------------------------
# accuracy on smooth data
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("limiter", TVD_LIMITERS)
@pytest.mark.parametrize("d", [-3.0, -0.001, 0.001, 1.0, 250.0])
def test_linear_data_is_reconstructed_exactly(limiter, d):
    """
    On a straight line both one-sided differences are equal, so the limiter must
    return that difference unclipped and the reconstruction is exact.

    This is what makes the scheme second-order. A limiter that clipped smooth
    data would silently degrade the solver to first order — no error, no warning,
    just a flood front that arrives smeared out and an arrival time that is too
    early at the front and too late at the useful depth. That is the worst kind
    of bug: invisible except in the number we ship.
    """
    q0 = 7.0
    s = limited_slope(q0 - d, q0, q0 + d, limiter)
    assert s == pytest.approx(d, rel=1e-14)


@pytest.mark.parametrize("limiter", ALL_LIMITERS)
def test_constant_data_gives_exactly_zero_slope(limiter):
    """
    Zero, not merely small. This is a hard requirement rather than an accuracy
    one: the well-balanced property depends on a constant water surface
    reconstructing to itself EXACTLY, and lake-at-rest is asserted at machine
    precision. A slope of 1e-18 here would become a spurious velocity there.
    """
    assert limited_slope(5.0, 5.0, 5.0, limiter) == 0.0
    assert limited_slope(-1e6, -1e6, -1e6, limiter) == 0.0


@pytest.mark.parametrize("limiter", TVD_LIMITERS)
def test_a_local_extremum_gives_exactly_zero_slope(limiter):
    """A peak or a trough is clipped flat by both limiters — the discrete
    statement that the scheme will not amplify an extremum."""
    assert limited_slope(1.0, 3.0, 1.0, limiter) == 0.0     # local max
    assert limited_slope(3.0, 1.0, 3.0, limiter) == 0.0     # local min


# ---------------------------------------------------------------------------
# symmetry — no directional bias
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("limiter", ALL_LIMITERS)
def test_mirroring_the_stencil_negates_the_slope(limiter):
    """
    Reversing (qm, q0, qp) to (qp, q0, qm) must negate the slope exactly.

    This is what stops the reconstruction from having a preferred direction. A
    failure here would make a radially symmetric dam break drift, which
    `test_symmetry.py` would catch at the domain level — but only as a symptom,
    with the cause anywhere in 1300 lines of solver.
    """
    rng = np.random.default_rng(808)
    for _ in range(5000):
        qm, q0, qp = (float(x) for x in rng.uniform(-20, 20, 3))
        fwd = limited_slope(qm, q0, qp, limiter)
        rev = limited_slope(qp, q0, qm, limiter)
        assert rev == pytest.approx(-fwd, rel=1e-14, abs=1e-15)


@pytest.mark.parametrize("limiter", ALL_LIMITERS)
def test_negating_the_data_negates_the_slope(limiter):
    """
    Both limiters must be odd functions of the data. Asserted because the sign
    handling in `mc_limiter` relies on `lim` and `centred` sharing a sign so that
    a magnitude comparison suffices — a claim in a comment, tested here.
    """
    rng = np.random.default_rng(909)
    for _ in range(5000):
        qm, q0, qp = (float(x) for x in rng.uniform(-20, 20, 3))
        a = limited_slope(qm, q0, qp, limiter)
        b = limited_slope(-qm, -q0, -qp, limiter)
        assert b == pytest.approx(-a, rel=1e-14, abs=1e-15)


@pytest.mark.parametrize("limiter", ALL_LIMITERS)
def test_adding_a_constant_to_the_stencil_does_not_change_the_slope(limiter):
    """
    The limiter sees only differences, so it must be translation invariant.

    This matters in practice rather than in principle: the reconstructed variable
    is the water-surface elevation eta = h + z, and z on the Bhagirathi is around
    800 m while the depth variations that matter are metres. If the limiter were
    not translation invariant, precision would be lost in exactly the way that
    makes still water on a high bed develop fake velocities.
    """
    rng = np.random.default_rng(1010)
    for _ in range(2000):
        qm, q0, qp = (float(x) for x in rng.uniform(-5, 5, 3))
        base = limited_slope(qm, q0, qp, limiter)
        for shift in (800.0, -2000.0):
            got = limited_slope(qm + shift, q0 + shift, qp + shift, limiter)
            assert got == pytest.approx(base, rel=1e-9, abs=1e-11)


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------
def test_limiter_none_is_exactly_first_order():
    """
    LIMITER_NONE must return 0.0 for every stencil, making the reconstruction
    piecewise constant. This is the diagnostic setting: when a run misbehaves,
    dropping to first order is the first thing to try, and it is only useful if
    it genuinely disables the reconstruction.
    """
    rng = np.random.default_rng(1111)
    for _ in range(1000):
        qm, q0, qp = (float(x) for x in rng.uniform(-50, 50, 3))
        assert limited_slope(qm, q0, qp, LIMITER_NONE) == 0.0


def test_limited_slope_dispatches_to_the_right_limiter():
    """
    Each code must route to its own function on the backward/forward differences
    a = q0 - qm and b = qp - q0. An off-by-one in which difference is which is
    invisible on symmetric data, so the stencils here are deliberately
    asymmetric.
    """
    for qm, q0, qp in itertools.product((0.0, 1.0, 4.0), (2.0, 5.0), (1.0, 9.0)):
        a, b = q0 - qm, qp - q0
        assert limited_slope(qm, q0, qp, LIMITER_MINMOD) == minmod(a, b)
        assert limited_slope(qm, q0, qp, LIMITER_MC) == mc_limiter(a, b)


def test_the_limiter_name_table_matches_the_constants():
    """
    `LIMITER_NAMES` is what the SWE2D constructor validates a user string
    against, so a mismatch between the table and the integer constants would
    silently select the wrong limiter — a quietly more diffusive solver with no
    error anywhere.
    """
    assert LIMITER_NAMES == {
        "none": LIMITER_NONE,
        "minmod": LIMITER_MINMOD,
        "mc": LIMITER_MC,
    }
    assert len(set(LIMITER_NAMES.values())) == 3, "codes must be distinct"


def test_an_unknown_limiter_code_falls_through_to_mc():
    """
    Document the fall-through rather than pretend it is unreachable.

    `limited_slope` tests for NONE, then MINMOD, then returns MC for anything
    else. The SWE2D constructor validates the name before it ever gets here, so
    an unknown code cannot arrive in practice — but the behaviour is worth
    pinning so that adding a fourth limiter and forgetting a branch produces a
    failing test rather than silently-MC results.
    """
    qm, q0, qp = 1.0, 4.0, 6.0
    assert limited_slope(qm, q0, qp, 99) == mc_limiter(q0 - qm, qp - q0)

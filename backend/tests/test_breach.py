"""
Tests for the breach module — the reservoir-drawdown model.

WHY THIS FILE MATTERS MORE THAN THE OTHER TEST FILES
----------------------------------------------------
The solver has analytical benchmarks (Ritter, Stoker) that pin it down. The
breach model has none: there is no closed-form solution for a reservoir draining
through a growing trapezoidal gap, and the field data that exists is for
embankment dams one to two orders of magnitude smaller than Tehri. So the only
things holding this module honest are conservation laws, algebraic identities,
and internal self-consistency — which is exactly what is tested here.

Both errors found in this module so far were factor-scale errors in the headline
number, and both were invisible to inspection:

  1. Constant reservoir area released 3.7x the water that exists.
     Caught here by `test_power_law_releases_exactly_the_gross_storage`.
  2. A 200 m breach in a 575 m dam implied a 721 m opening.
     Caught here by `test_tehri_200m_breach_is_refused`.

Neither would have been caught by a test that merely checked the code ran. The
tests below therefore assert PROPERTIES (mass conserved, formula exact,
monotone, dimensionally consistent) rather than remembered outputs.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from jaldrishti.scenario.breach import (
    C_SIDE,
    C_WEIR,
    GROWTH_MODES,
    SUBMERGENCE_LIMIT,
    BreachGeometry,
    ReservoirStorage,
    breach_state,
    breach_velocity,
    critical_velocity,
    formation_time_band,
    froehlich_breach_geometry,
    froehlich_peak_outflow,
    growth_fraction,
    max_bottom_width,
    mlm_peak_outflow,
    simulate_breach,
    submergence_factor,
    usbr_peak_outflow,
    weir_outflow,
)
from jaldrishti.solver.swe2d import GRAVITY

# Tehri, from config.py. Used throughout because it is the case that exposed
# both bugs and because its numbers are the ones that will be defended out loud.
TEHRI_FRL = 830.0
TEHRI_HEIGHT = 260.5
TEHRI_BED = TEHRI_FRL - TEHRI_HEIGHT          # 569.5 m
TEHRI_CREST_LEN = 575.0
TEHRI_VOLUME = 3.54e9
TEHRI_AREA = 52.0e6


def tehri_storage() -> ReservoirStorage:
    return ReservoirStorage.power_law(
        bed_m=TEHRI_BED, full_level_m=TEHRI_FRL,
        volume_m3=TEHRI_VOLUME, area_m2=TEHRI_AREA)


def tehri_geom(**kw) -> BreachGeometry:
    opts = dict(crest_m=TEHRI_FRL, invert_m=TEHRI_BED,
                crest_length_m=TEHRI_CREST_LEN, side_slope=1.0,
                formation_time_s=3600.0, growth="linear")
    opts.update(kw)
    return BreachGeometry.fit_within_crest(**opts)


# =============================================================================
# growth
# =============================================================================

def test_instant_growth_is_fully_open_immediately():
    for t in (0.0, 1.0, 1e6):
        assert growth_fraction(t, 3600.0, "instant") == 1.0


def test_linear_growth_is_exactly_proportional():
    tf = 1200.0
    for x in (0.0, 0.25, 0.5, 0.75, 1.0):
        assert growth_fraction(x * tf, tf, "linear") == pytest.approx(x)


def test_growth_clamps_outside_the_formation_window():
    for mode in ("linear", "erosion"):
        assert growth_fraction(-10.0, 100.0, mode) == 0.0
        assert growth_fraction(1e9, 100.0, mode) == 1.0


def test_erosion_growth_is_a_smoothstep():
    """
    The physical claim in the docstring is that a notch takes a while to
    establish and then widens rapidly. That means erosion must LAG linear in the
    first half and LEAD it in the second, crossing at the midpoint.
    """
    tf = 100.0
    assert growth_fraction(0.0, tf, "erosion") == 0.0
    assert growth_fraction(tf, tf, "erosion") == pytest.approx(1.0)
    assert growth_fraction(0.5 * tf, tf, "erosion") == pytest.approx(0.5)
    assert growth_fraction(0.25 * tf, tf, "erosion") < 0.25   # slow start
    assert growth_fraction(0.75 * tf, tf, "erosion") > 0.75   # then catches up


def test_zero_formation_time_is_instant_in_every_mode():
    """Guards a division by zero that would otherwise produce inf or nan."""
    for mode in GROWTH_MODES:
        assert growth_fraction(0.0, 0.0, mode) == 1.0


def test_unknown_growth_mode_raises():
    with pytest.raises(ValueError, match="unknown growth mode"):
        growth_fraction(10.0, 100.0, "exponential")


def test_breach_state_starts_closed_at_the_crest_and_ends_fully_open():
    geom = BreachGeometry(bottom_width_m=54.0, invert_m=TEHRI_BED,
                          formation_time_s=3600.0, growth="linear")
    w0, inv0 = breach_state(0.0, geom, TEHRI_FRL)
    assert w0 == 0.0
    assert inv0 == pytest.approx(TEHRI_FRL)          # cuts down FROM the crest

    w1, inv1 = breach_state(3600.0, geom, TEHRI_FRL)
    assert w1 == pytest.approx(54.0)
    assert inv1 == pytest.approx(TEHRI_BED)


def test_breach_state_is_monotone():
    """Width can only grow and the invert can only descend — erosion is one-way."""
    geom = BreachGeometry(bottom_width_m=54.0, invert_m=TEHRI_BED,
                          formation_time_s=3600.0, growth="erosion")
    ts = np.linspace(0.0, 4000.0, 200)
    ws, invs = zip(*(breach_state(float(t), geom, TEHRI_FRL) for t in ts))
    assert np.all(np.diff(ws) >= -1e-12)
    assert np.all(np.diff(invs) <= 1e-12)


# =============================================================================
# weir discharge
# =============================================================================

def test_weir_outflow_matches_the_trapezoid_formula():
    """Q = c_weir*b*H^1.5 + c_side*m*H^2.5, checked against hand arithmetic."""
    head, b, m = 9.0, 20.0, 1.5
    expect = C_WEIR * b * head ** 1.5 + C_SIDE * m * head ** 2.5
    got = weir_outflow(level_m=100.0 + head, invert_m=100.0,
                       width_m=b, side_slope=m)
    assert got == pytest.approx(expect)


def test_rectangular_breach_drops_the_side_term():
    head, b = 4.0, 10.0
    got = weir_outflow(level_m=head, invert_m=0.0, width_m=b, side_slope=0.0)
    assert got == pytest.approx(C_WEIR * b * head ** 1.5)


def test_weir_outflow_is_zero_at_or_below_the_invert():
    """
    Reached at the end of EVERY run. H^1.5 of a negative number is nan, and a
    single nan in the hydrograph propagates into the solver and destroys the run.
    """
    for level in (100.0, 99.9, 0.0, -50.0):
        q = weir_outflow(level_m=level, invert_m=100.0, width_m=20.0,
                         side_slope=1.0)
        assert q == 0.0
        assert math.isfinite(q)


def test_weir_outflow_is_zero_before_the_breach_opens():
    """Width is exactly zero at t=0 for every non-instant growth mode."""
    for w in (0.0, -1.0):
        assert weir_outflow(level_m=110.0, invert_m=100.0, width_m=w,
                            side_slope=1.0) == 0.0


def test_weir_outflow_increases_with_head():
    q = [weir_outflow(level_m=100.0 + h, invert_m=100.0, width_m=30.0,
                      side_slope=1.0) for h in np.linspace(0.0, 50.0, 60)]
    assert np.all(np.diff(q) > 0.0)


# =============================================================================
# submergence
# =============================================================================

def test_free_weir_ignores_the_tailwater_below_the_modular_limit():
    """
    Not a modelling convenience — a free-flowing weir has a critical control
    section, and information cannot travel upstream through critical flow.
    """
    for ratio in (0.0, 0.3, 0.5, SUBMERGENCE_LIMIT):
        assert submergence_factor(10.0, ratio * 10.0) == 1.0


def test_submergence_shuts_the_weir_when_the_tailwater_reaches_the_pool():
    assert submergence_factor(10.0, 10.0) == 0.0
    assert submergence_factor(10.0, 12.0) == 0.0


def test_submergence_matches_villemonte_between_the_limits():
    head, tw = 10.0, 8.5
    ratio = tw / head
    assert submergence_factor(head, tw) == pytest.approx(
        (1.0 - ratio ** 1.5) ** 0.385)


def test_submergence_decreases_monotonically():
    ks = [submergence_factor(10.0, tw) for tw in np.linspace(0.0, 10.0, 80)]
    assert np.all(np.diff(ks) <= 1e-12)


def test_submergence_of_zero_head_is_zero_not_a_division_by_zero():
    assert submergence_factor(0.0, 5.0) == 0.0
    assert submergence_factor(-1.0, 5.0) == 0.0


def test_tailwater_reduces_the_discharge():
    free = weir_outflow(level_m=110.0, invert_m=100.0, width_m=20.0,
                        side_slope=1.0)
    drowned = weir_outflow(level_m=110.0, invert_m=100.0, width_m=20.0,
                           side_slope=1.0, tailwater_m=109.0)
    assert 0.0 < drowned < free


# =============================================================================
# velocity — the self-consistency check between discharge and momentum
# =============================================================================

def test_critical_velocity_is_the_froude_one_condition():
    """U = sqrt(g*h_c) with h_c = (2/3)H. No coefficient, no calibration."""
    head = 12.0
    assert critical_velocity(head) == pytest.approx(
        math.sqrt(GRAVITY * 2.0 * head / 3.0))
    assert critical_velocity(0.0) == 0.0
    assert critical_velocity(-3.0) == 0.0


def test_weir_coefficient_agrees_with_critical_flow():
    """
    C_WEIR must equal (2/3)^1.5 * sqrt(g) = 1.7049, or the discharge and the
    injected momentum come from different assumptions and the solver's inflow
    boundary is internally inconsistent.

    The code uses the conventional rounded SI value 1.7, so they agree to 0.3%
    rather than exactly. That is a deliberate 0.3% inconsistency, not an error —
    but it must stay small, which is what this test pins down.
    """
    exact = (2.0 / 3.0) ** 1.5 * math.sqrt(GRAVITY)
    assert exact == pytest.approx(1.7049, abs=1e-3)
    assert abs(C_WEIR - exact) / exact < 0.005


def test_breach_velocity_reduces_to_critical_for_a_rectangular_breach():
    """
    Q/A must reproduce sqrt(2gH/3) when there are no side wedges. This is the
    continuity check in the docstring, and it is the reason the solver can be
    handed a velocity without a second free parameter.
    """
    head, b = 16.0, 40.0
    q = weir_outflow(level_m=head, invert_m=0.0, width_m=b, side_slope=0.0)
    u = breach_velocity(q, head, b, 0.0)
    assert u == pytest.approx(critical_velocity(head), rel=0.005)


def test_breach_velocity_guards_every_divisor():
    assert breach_velocity(0.0, 10.0, 20.0, 1.0) == 0.0
    assert breach_velocity(100.0, 0.0, 20.0, 1.0) == 0.0
    assert breach_velocity(100.0, 10.0, 0.0, 1.0) == 0.0


def test_submergence_lowers_the_reported_velocity():
    """
    Using Q/A rather than the closed form means a submergence-reduced discharge
    automatically reports a lower velocity. Asserted because the alternative
    (closed-form critical velocity) would silently keep the free-flow value.
    """
    head, b, m = 10.0, 20.0, 1.0
    free = weir_outflow(level_m=head, invert_m=0.0, width_m=b, side_slope=m)
    drowned = weir_outflow(level_m=head, invert_m=0.0, width_m=b, side_slope=m,
                           tailwater_m=9.0)
    assert breach_velocity(drowned, head, b, m) < breach_velocity(
        free, head, b, m)


# =============================================================================
# the crest constraint — a breach cannot be wider than the dam
# =============================================================================

def test_max_bottom_width_for_tehri_is_54_metres():
    """575 - 2(1.0)(260.5) = 54. The number that made the geometry forced."""
    assert max_bottom_width(TEHRI_CREST_LEN, TEHRI_HEIGHT, 1.0) == pytest.approx(
        54.0)


def test_max_bottom_width_never_returns_a_negative_width():
    """A negative width is not a smaller breach; it is an impossible one."""
    assert max_bottom_width(100.0, 260.5, 1.0) == 0.0
    assert max_bottom_width(100.0, 50.0, 2.0) == 0.0


def test_the_widest_fitting_breach_exactly_fills_the_crest():
    """
    Algebraic identity: b = L - 2mh, so top = b + 2mh = L exactly. If this ever
    fails, `max_bottom_width` and `top_width_m` have drifted apart.
    """
    for L, h, m in ((575.0, 260.5, 1.0), (300.0, 40.0, 1.5), (900.0, 100.0, 0.5)):
        b = max_bottom_width(L, h, m)
        geom = BreachGeometry(bottom_width_m=b, invert_m=0.0, side_slope=m,
                              crest_length_m=L)
        assert geom.top_width_m(h) == pytest.approx(L)


def test_tehri_200m_breach_is_refused():
    """
    THE SECOND FACTOR-SCALE BUG. A plausible-looking 200 m bottom width with 1:1
    sides over 260.5 m of head opens 721 m in a 575 m dam and overstates the
    peak by roughly three. Refused, not clamped: clamping would leave
    `weir_outflow` integrating a trapezoid that was never opened.
    """
    geom = BreachGeometry(bottom_width_m=200.0, invert_m=TEHRI_BED,
                          side_slope=1.0, crest_length_m=TEHRI_CREST_LEN)
    assert not geom.fits_within_crest(TEHRI_FRL)
    with pytest.raises(ValueError) as exc:
        geom.check_fits(TEHRI_FRL)
    msg = str(exc.value)
    assert "721 m opening" in msg          # what was actually being modelled
    assert "575 m crest" in msg
    assert "54 m" in msg                   # and what the caller should use


def test_check_fits_is_silent_when_the_breach_fits():
    tehri_geom().check_fits(TEHRI_FRL)                       # must not raise


def test_no_crest_length_means_no_constraint():
    """
    Backwards compatibility is deliberate: a landslide dam has no surveyed crest
    length, and refusing to model one would be worse than modelling it
    unconstrained. But the constraint is then absent, which the caller must know.
    """
    geom = BreachGeometry(bottom_width_m=5000.0, invert_m=0.0, side_slope=1.0)
    assert geom.crest_length_m is None
    assert geom.fits_within_crest(100.0)
    geom.check_fits(100.0)


def test_impossible_side_slope_is_reported_as_such():
    """
    When the side slopes alone exceed the crest there is no bottom width to
    suggest, so the message must point at the side slope instead.
    """
    geom = BreachGeometry(bottom_width_m=10.0, invert_m=0.0, side_slope=1.0,
                          crest_length_m=100.0)
    with pytest.raises(ValueError, match="No trapezoid"):
        geom.check_fits(260.5)


def test_fit_within_crest_round_trips_to_the_crest_length():
    geom = tehri_geom()
    assert geom.bottom_width_m == pytest.approx(54.0)
    assert geom.top_width_m(TEHRI_HEIGHT) == pytest.approx(TEHRI_CREST_LEN)
    assert geom.fits_within_crest(TEHRI_FRL)


def test_width_fraction_scales_the_top_width_and_keeps_the_side_slope():
    """
    Scaling the TOP width is the design choice: the side slope reflects the fill
    material and should not change just because a smaller breach was requested.

    Uses a broad, low dam rather than Tehri, because Tehri physically cannot
    have a partial breach at 1:1 sides — see the next test.
    """
    kw = dict(crest_m=100.0, invert_m=0.0, crest_length_m=900.0,
              side_slope=0.5)
    full = BreachGeometry.fit_within_crest(**kw)
    half = BreachGeometry.fit_within_crest(width_fraction=0.5, **kw)
    assert full.top_width_m(100.0) == pytest.approx(900.0)
    assert half.top_width_m(100.0) == pytest.approx(450.0)
    assert half.side_slope == full.side_slope == 0.5
    assert half.bottom_width_m < full.bottom_width_m


def test_tehri_cannot_have_a_partial_breach_at_one_to_one_sides():
    """
    A consequence of Tehri's proportions worth stating out loud: 1:1 sides over
    260.5 m of head consume 521 m, and the crest is 575 m. So a half-crest
    opening (287.5 m) cannot contain the side slopes at all — at 1:1 the breach
    is not merely constrained, it is UNIQUE: 54 m bottom, full 575 m top, or
    nothing. The only way to model a smaller Tehri breach is a steeper side
    slope, which is a statement about the fill material and must be argued for
    rather than assumed.
    """
    with pytest.raises(ValueError, match="needs"):
        tehri_geom(width_fraction=0.5)

    # Steeper sides make a partial breach possible again, which is the honest
    # route to a smaller scenario.
    steep = tehri_geom(side_slope=0.25, width_fraction=0.5)
    assert steep.top_width_m(TEHRI_HEIGHT) == pytest.approx(
        0.5 * TEHRI_CREST_LEN)


def test_width_fraction_must_be_a_fraction():
    for bad in (0.0, -0.5, 1.5):
        with pytest.raises(ValueError, match="width_fraction"):
            tehri_geom(width_fraction=bad)


def test_fit_within_crest_refuses_a_dam_too_tall_for_its_crest():
    with pytest.raises(ValueError, match="needs"):
        BreachGeometry.fit_within_crest(
            crest_m=300.0, invert_m=0.0, crest_length_m=100.0, side_slope=1.0)


def test_fit_within_crest_needs_positive_head():
    with pytest.raises(ValueError, match="above invert"):
        BreachGeometry.fit_within_crest(
            crest_m=100.0, invert_m=100.0, crest_length_m=500.0)


def test_geometry_validation():
    with pytest.raises(ValueError, match="bottom_width_m"):
        BreachGeometry(bottom_width_m=0.0, invert_m=0.0)
    with pytest.raises(ValueError, match="side_slope"):
        BreachGeometry(bottom_width_m=10.0, invert_m=0.0, side_slope=-0.1)
    with pytest.raises(ValueError, match="formation_time_s"):
        BreachGeometry(bottom_width_m=10.0, invert_m=0.0, formation_time_s=-1.0)
    with pytest.raises(ValueError, match="growth must be"):
        BreachGeometry(bottom_width_m=10.0, invert_m=0.0, growth="quadratic")
    with pytest.raises(ValueError, match="crest_length_m"):
        BreachGeometry(bottom_width_m=10.0, invert_m=0.0, crest_length_m=0.0)


# =============================================================================
# reservoir storage — where the first factor-scale bug lived
# =============================================================================

def test_storage_exponent_is_computed_not_fitted():
    """b = A0*H/V0. Tehri: 52e6 * 260.5 / 3.54e9 = 3.827, a deep narrow gorge."""
    store = tehri_storage()
    assert store.exponent == pytest.approx(TEHRI_AREA * TEHRI_HEIGHT
                                           / TEHRI_VOLUME)
    assert store.exponent == pytest.approx(3.827, abs=1e-3)
    assert store.mode == "power"


def test_power_law_releases_exactly_the_gross_storage():
    """
    THE FIRST FACTOR-SCALE BUG, as a property rather than a number. By
    construction the integral of A dh from bed to FRL is exactly V0, so a full
    drawdown cannot invent water. The old constant-area model released 3.7x.
    """
    store = tehri_storage()
    assert store.storage_at(TEHRI_FRL) == pytest.approx(TEHRI_VOLUME, rel=1e-12)
    assert store.storage_at(TEHRI_BED) == pytest.approx(0.0, abs=1e-6)


def test_the_area_curve_integrates_to_the_gross_storage():
    """
    Independent check of the same property: numerically integrate A(h), which is
    what the routing actually divides by, and compare with V(H), which is what
    the mass balance compares against. If dV/dh and A disagree, every run would
    balance against a curve it did not use.
    """
    store = tehri_storage()
    h = np.linspace(0.0, TEHRI_HEIGHT, 200_001)
    a = np.array([store.area_at(TEHRI_BED + float(x)) for x in h])
    assert float(np.trapezoid(a, h)) == pytest.approx(TEHRI_VOLUME, rel=1e-4)


def test_area_at_full_supply_is_the_published_area():
    assert tehri_storage().area_at(TEHRI_FRL) == pytest.approx(TEHRI_AREA,
                                                               rel=1e-9)


def test_area_grows_with_level_in_every_mode():
    """A reservoir cannot get narrower as it fills."""
    stores = [
        tehri_storage(),
        ReservoirStorage.constant(bed_m=TEHRI_BED, full_level_m=TEHRI_FRL,
                                  area_m2=TEHRI_AREA),
        ReservoirStorage.table(levels=[569.5, 650.0, 750.0, 830.0],
                               areas=[0.5e6, 8e6, 26e6, 52e6]),
    ]
    levels = np.linspace(TEHRI_BED, TEHRI_FRL, 300)
    for store in stores:
        a = np.array([store.area_at(float(z)) for z in levels])
        assert np.all(np.diff(a) >= -1e-6), store.mode


def test_storage_grows_with_level_in_every_mode():
    stores = [
        tehri_storage(),
        ReservoirStorage.constant(bed_m=TEHRI_BED, full_level_m=TEHRI_FRL,
                                  area_m2=TEHRI_AREA),
        ReservoirStorage.table(levels=[569.5, 650.0, 750.0, 830.0],
                               areas=[0.5e6, 8e6, 26e6, 52e6]),
    ]
    levels = np.linspace(TEHRI_BED, TEHRI_FRL, 300)
    for store in stores:
        v = np.array([store.storage_at(float(z)) for z in levels])
        assert np.all(np.diff(v) >= -1e-6), store.mode


def test_inconsistent_published_figures_are_refused():
    """
    b < 1 means A(h) -> infinity as h -> 0: a reservoir wider at the bottom than
    at the top. No valley does that, so the two published figures contradict
    each other and the caller must be told rather than handed a smooth wrong
    curve.
    """
    with pytest.raises(ValueError, match="wider at depth"):
        ReservoirStorage.power_law(bed_m=0.0, full_level_m=100.0,
                                   volume_m3=1e9, area_m2=1e6)


def test_power_law_validation():
    with pytest.raises(ValueError, match="above the streambed"):
        ReservoirStorage.power_law(bed_m=100.0, full_level_m=100.0,
                                   volume_m3=1e9, area_m2=1e7)
    with pytest.raises(ValueError, match="must be positive"):
        ReservoirStorage.power_law(bed_m=0.0, full_level_m=100.0,
                                   volume_m3=-1.0, area_m2=1e7)
    with pytest.raises(ValueError, match="must be positive"):
        ReservoirStorage.power_law(bed_m=0.0, full_level_m=100.0,
                                   volume_m3=1e9, area_m2=0.0)


def test_constant_storage_is_linear_in_depth():
    store = ReservoirStorage.constant(bed_m=100.0, full_level_m=200.0,
                                      area_m2=5e6)
    assert store.exponent == 1.0
    assert store.volume_m3 == pytest.approx(5e6 * 100.0)
    assert store.storage_at(150.0) == pytest.approx(5e6 * 50.0)
    assert store.area_at(101.0) == store.area_at(199.0) == 5e6
    with pytest.raises(ValueError, match="must be positive"):
        ReservoirStorage.constant(bed_m=0.0, full_level_m=10.0, area_m2=0.0)


def test_table_storage_interpolates_and_integrates():
    """
    Trapezoidal integral of a two-point curve is exact, so this can be checked
    by hand: mean area 3e6 over 100 m of depth = 3e8 m^3.
    """
    store = ReservoirStorage.table(levels=[0.0, 100.0], areas=[1e6, 5e6])
    assert store.area_at(50.0) == pytest.approx(3e6)
    assert store.storage_at(100.0) == pytest.approx(3e8)
    assert store.volume_m3 == pytest.approx(3e8)
    assert store.area_m2 == pytest.approx(5e6)


def test_table_storage_sorts_unordered_input():
    a = ReservoirStorage.table(levels=[100.0, 0.0, 50.0],
                               areas=[5e6, 1e6, 3e6])
    b = ReservoirStorage.table(levels=[0.0, 50.0, 100.0],
                               areas=[1e6, 3e6, 5e6])
    assert a.storage_at(75.0) == pytest.approx(b.storage_at(75.0))


def test_table_storage_validation():
    with pytest.raises(ValueError, match=">= 2 points"):
        ReservoirStorage.table(levels=[0.0], areas=[1e6])
    with pytest.raises(ValueError, match="equal-length"):
        ReservoirStorage.table(levels=[0.0, 1.0, 2.0], areas=[1e6, 2e6])
    with pytest.raises(ValueError, match="areas must be positive"):
        ReservoirStorage.table(levels=[0.0, 100.0], areas=[0.0, 5e6])
    with pytest.raises(ValueError):
        # Decreasing area with height is the same impossibility as b < 1.
        ReservoirStorage.table(levels=[0.0, 100.0], areas=[5e6, 1e6])


def test_storage_summary_names_the_model_it_used():
    """No chart can misrepresent which storage model produced it."""
    s = tehri_storage().summary()
    assert "power" in s
    assert "3.827" in s or "3.83" in s
    assert "gorge" in s               # the interpretable reading of b


# =============================================================================
# routing — the RK4 integration
# =============================================================================

def test_mass_balance_closes():
    """
    What left through the breach must equal the storage lost. This checks RK4
    against the trapezoidal integral of its own output, so it catches a routing
    error but NOT a wrong weir coefficient. A numerical check, not a physical one.
    """
    hyd = simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
                          storage=tehri_storage(), geom=tehri_geom(),
                          bed_m=TEHRI_BED, dt=2.0)
    assert hyd.meta["mass_balance_rel"] < 1e-6


def test_released_volume_cannot_exceed_the_gross_storage():
    """The property the constant-area model violated by a factor of 3.7."""
    hyd = simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
                          storage=tehri_storage(), geom=tehri_geom(),
                          bed_m=TEHRI_BED, dt=2.0)
    assert hyd.meta["released_fraction_of_storage"] <= 1.0 + 1e-6
    assert hyd.released_volume_m3 == pytest.approx(TEHRI_VOLUME, rel=1e-3)


def test_constant_area_still_over_releases_and_says_so():
    """
    The bias is retained deliberately, for comparison. Asserted so that a future
    change cannot quietly "fix" the constant-area path and thereby remove the
    contrast that justifies the power law.
    """
    flat = ReservoirStorage.constant(bed_m=TEHRI_BED, full_level_m=TEHRI_FRL,
                                     area_m2=TEHRI_AREA)
    hyd = simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
                          storage=flat, geom=tehri_geom(), bed_m=TEHRI_BED,
                          dt=2.0, reservoir_volume_m3=TEHRI_VOLUME)
    assert hyd.meta["storage_model"] == "constant"
    assert hyd.meta["released_fraction_of_storage"] > 3.0


def test_the_hydrograph_is_physically_ordered():
    hyd = simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
                          storage=tehri_storage(), geom=tehri_geom(),
                          bed_m=TEHRI_BED, dt=2.0)
    assert np.all(np.isfinite(hyd.q))
    assert np.all(np.isfinite(hyd.level))
    assert np.all(np.isfinite(hyd.velocity))
    assert np.all(hyd.q >= 0.0)
    assert np.all(np.diff(hyd.level) <= 1e-9)              # only ever drains
    assert hyd.level.min() >= TEHRI_BED - 1e-6             # never below the bed
    assert np.all(np.diff(hyd.t) > 0.0)


def test_routing_stops_at_the_streambed_not_the_dam_toe():
    """
    Storage below the original streambed is not released by a breach. Getting
    this wrong on a 260 m dam would release a reservoir that does not exist.
    """
    hyd = simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
                          storage=tehri_storage(), geom=tehri_geom(),
                          bed_m=TEHRI_BED, dt=2.0)
    assert hyd.meta["floor_m"] == pytest.approx(TEHRI_BED)
    assert hyd.level[-1] >= TEHRI_BED - 1e-6


def test_instant_growth_peaks_at_time_zero():
    hyd = simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
                          storage=tehri_storage(),
                          geom=tehri_geom(growth="instant"),
                          bed_m=TEHRI_BED, dt=2.0)
    assert hyd.t_peak == 0.0
    assert hyd.peak_q == pytest.approx(hyd.q[0])


def test_linear_growth_peaks_when_the_breach_finishes_forming():
    """
    Discharge rises with breach size and falls with head. For Tehri the breach
    wins until it is fully formed, so the peak lands at the formation time. A
    peak strictly inside the window would mean the reservoir is draining faster
    than the breach grows, which changes how the result must be described.
    """
    tf = 3600.0
    hyd = simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
                          storage=tehri_storage(),
                          geom=tehri_geom(formation_time_s=tf),
                          bed_m=TEHRI_BED, dt=2.0)
    assert hyd.t_peak == pytest.approx(tf, abs=4.0)


def test_rk4_peak_is_converged_at_the_working_timestep():
    """
    dt = 2 s is what the scripts use. Halving it must not move the peak, or the
    headline number is a discretisation artefact rather than a result.
    """
    kw = dict(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
              storage=tehri_storage(), geom=tehri_geom(), bed_m=TEHRI_BED)
    coarse = simulate_breach(dt=4.0, **kw)
    fine = simulate_breach(dt=0.5, **kw)
    assert coarse.peak_q == pytest.approx(fine.peak_q, rel=2e-3)
    assert coarse.released_volume_m3 == pytest.approx(
        fine.released_volume_m3, rel=1e-3)


def test_inflow_appears_in_the_mass_balance():
    q_in = 5000.0
    hyd = simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
                          storage=tehri_storage(), geom=tehri_geom(),
                          bed_m=TEHRI_BED, dt=2.0, inflow_m3s=q_in)
    assert hyd.meta["inflow_volume_m3"] == pytest.approx(q_in * hyd.t[-1])
    assert hyd.meta["mass_balance_rel"] < 1e-6
    assert hyd.released_volume_m3 > TEHRI_VOLUME       # storage plus the inflow


def test_free_outflow_reports_no_submergence():
    """
    max_submergence is the diagnostic for whether precomputing the hydrograph
    was legitimate. Any departure from 1.0 means the reservoir and the far field
    were coupled after all.
    """
    hyd = simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
                          storage=tehri_storage(), geom=tehri_geom(),
                          bed_m=TEHRI_BED, dt=2.0)
    assert hyd.meta["max_submergence"] == 1.0


def test_tailwater_submerges_the_breach_and_cuts_the_peak():
    kw = dict(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
              storage=tehri_storage(), geom=tehri_geom(), bed_m=TEHRI_BED,
              dt=2.0)
    free = simulate_breach(**kw)
    drowned = simulate_breach(tailwater_m=800.0, **kw)
    assert drowned.meta["max_submergence"] < 1.0
    assert drowned.peak_q < free.peak_q


def test_simulate_breach_enforces_the_crest_constraint():
    """The refusal must reach through the routing entry point, not just geometry."""
    bad = BreachGeometry(bottom_width_m=200.0, invert_m=TEHRI_BED,
                         side_slope=1.0, crest_length_m=TEHRI_CREST_LEN)
    with pytest.raises(ValueError, match="wider than the dam"):
        simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
                        storage=tehri_storage(), geom=bad, bed_m=TEHRI_BED)


def test_routing_validation():
    geom = tehri_geom()
    with pytest.raises(ValueError, match="already overtopping"):
        simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL + 1.0,
                        storage=tehri_storage(), geom=geom, bed_m=TEHRI_BED)
    with pytest.raises(ValueError, match="invert is above"):
        simulate_breach(
            crest_m=TEHRI_FRL, initial_level_m=TEHRI_BED + 1.0,
            storage=tehri_storage(),
            geom=BreachGeometry(bottom_width_m=54.0, invert_m=TEHRI_BED + 50.0),
            bed_m=TEHRI_BED)
    with pytest.raises(ValueError, match="pass either storage"):
        simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
                        geom=geom, bed_m=TEHRI_BED)


def test_area_shorthand_with_a_volume_builds_the_honest_curve():
    """
    When both figures are available the shorthand must NOT silently take the
    constant-area path — that path is what caused the 3.7x error.
    """
    hyd = simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
                          geom=tehri_geom(), bed_m=TEHRI_BED, dt=2.0,
                          reservoir_area_m2=TEHRI_AREA,
                          reservoir_volume_m3=TEHRI_VOLUME)
    assert hyd.meta["storage_model"] == "power"
    assert hyd.meta["released_fraction_of_storage"] <= 1.0 + 1e-6


def test_area_shorthand_alone_falls_back_to_constant():
    hyd = simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
                          geom=tehri_geom(), bed_m=TEHRI_BED, dt=2.0,
                          reservoir_area_m2=TEHRI_AREA)
    assert hyd.meta["storage_model"] == "constant"


def test_hydrograph_interpolation_is_clamped():
    hyd = simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
                          storage=tehri_storage(), geom=tehri_geom(),
                          bed_m=TEHRI_BED, dt=2.0)
    assert hyd.q_at(-100.0) == pytest.approx(hyd.q[0])
    assert hyd.q_at(1e9) == pytest.approx(hyd.q[-1])
    mid = 0.5 * (hyd.t[0] + hyd.t[-1])
    assert 0.0 <= hyd.q_at(mid) <= hyd.peak_q
    assert hyd.u_at(-1.0) == pytest.approx(hyd.velocity[0])
    assert hyd.u_at(1e9) == pytest.approx(hyd.velocity[-1])


def test_hydrograph_meta_records_the_geometry_actually_used():
    hyd = simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
                          storage=tehri_storage(), geom=tehri_geom(),
                          bed_m=TEHRI_BED, dt=2.0)
    assert hyd.meta["bottom_width_m"] == pytest.approx(54.0)
    assert hyd.meta["top_width_m"] == pytest.approx(TEHRI_CREST_LEN)
    assert hyd.meta["crest_length_m"] == pytest.approx(TEHRI_CREST_LEN)
    assert hyd.meta["truncated"] is False


def test_summary_reports_the_breach_as_a_fraction_of_the_crest():
    """
    The line that makes the constraint visible in the report rather than only in
    the code.
    """
    hyd = simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
                          storage=tehri_storage(), geom=tehri_geom(),
                          bed_m=TEHRI_BED, dt=2.0)
    s = hyd.summary()
    assert "54 m bottom" in s
    assert "575 m crest" in s
    assert "100%" in s


# =============================================================================
# the uncertainty band
# =============================================================================

def test_formation_time_band_returns_one_run_per_time():
    times = [900.0, 3600.0, 14400.0]
    band = formation_time_band(
        times_s=times, crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
        storage=tehri_storage(), geom=tehri_geom(), bed_m=TEHRI_BED, dt=4.0)
    assert sorted(band) == sorted(times)
    for tf in times:
        assert band[tf].meta["formation_time_s"] == pytest.approx(tf)


def test_a_slower_breach_gives_a_lower_peak():
    """
    The monotone relationship that makes the band interpretable: the fast end is
    the upper bound and the slow end the lower. If this ever inverted, quoting a
    range would be meaningless.
    """
    times = [900.0, 1800.0, 3600.0, 7200.0, 14400.0]
    band = formation_time_band(
        times_s=times, crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
        storage=tehri_storage(), geom=tehri_geom(), bed_m=TEHRI_BED, dt=4.0)
    peaks = [band[t].peak_q for t in times]
    assert np.all(np.diff(peaks) < 0.0)


def test_every_band_member_conserves_mass():
    """
    Tolerances are looser than the single-run test because the band runs at
    dt = 4 s and `released_volume_m3` is a trapezoidal integral of a discretely
    sampled hydrograph — it carries O(dt^2) quadrature error, which shows up as
    a released fraction of 1.000001 rather than exactly 1. Still six orders of
    magnitude away from the 3.7x error this property exists to catch.
    """
    times = [900.0, 3600.0, 14400.0]
    band = formation_time_band(
        times_s=times, crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
        storage=tehri_storage(), geom=tehri_geom(), bed_m=TEHRI_BED, dt=4.0)
    for tf, hyd in band.items():
        assert hyd.meta["mass_balance_rel"] < 1e-5, tf
        assert hyd.meta["released_fraction_of_storage"] <= 1.0 + 1e-4, tf


def test_the_band_keeps_the_crest_constraint():
    """
    `formation_time_band` rebuilds the geometry for each formation time. If it
    drops `crest_length_m` while doing so, every band member silently loses the
    check that a breach cannot be wider than the dam — the band would happily
    report peaks for an impossible geometry, and the band is what gets quoted.
    """
    band = formation_time_band(
        times_s=[1800.0], crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
        storage=tehri_storage(), geom=tehri_geom(), bed_m=TEHRI_BED, dt=4.0)
    hyd = band[1800.0]
    assert hyd.meta["crest_length_m"] == pytest.approx(TEHRI_CREST_LEN)


def test_the_band_refuses_an_impossible_geometry():
    """The same refusal must survive the rebuild, not just the first call."""
    bad = BreachGeometry(bottom_width_m=200.0, invert_m=TEHRI_BED,
                         side_slope=1.0, crest_length_m=TEHRI_CREST_LEN)
    with pytest.raises(ValueError, match="wider than the dam"):
        formation_time_band(
            times_s=[1800.0], crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
            storage=tehri_storage(), geom=bad, bed_m=TEHRI_BED, dt=4.0)


# =============================================================================
# empirical regressions — smell tests, never results
# =============================================================================

def test_regressions_reproduce_their_published_coefficients():
    """
    These are dimensional fits, so a transposed digit is not detectable by
    inspection — unlike the weir exponents, which follow from the physics. The
    only defence is checking the arithmetic against the printed formula.
    """
    v, h = 3.54e9, 260.5
    assert froehlich_peak_outflow(v, h) == pytest.approx(
        0.607 * v ** 0.295 * h ** 1.24)
    assert usbr_peak_outflow(h) == pytest.approx(19.1 * h ** 1.85)
    assert mlm_peak_outflow(v, h) == pytest.approx(1.154 * (v * h) ** 0.412)


def test_regressions_are_zero_for_degenerate_input():
    assert froehlich_peak_outflow(0.0, 100.0) == 0.0
    assert froehlich_peak_outflow(1e9, 0.0) == 0.0
    assert usbr_peak_outflow(0.0) == 0.0
    assert usbr_peak_outflow(-1.0) == 0.0
    assert mlm_peak_outflow(0.0, 100.0) == 0.0


def test_froehlich_geometry_uses_the_right_overtopping_factor():
    """Ko = 1.4 overtopping, 1.0 piping — a 40% difference in predicted width."""
    v, h = 3.54e9, 260.5
    w_over, t_over = froehlich_breach_geometry(v, h, "overtopping")
    w_pipe, t_pipe = froehlich_breach_geometry(v, h, "piping")
    assert w_over / w_pipe == pytest.approx(1.4)
    assert t_over == pytest.approx(t_pipe)              # time has no Ko
    assert t_over == pytest.approx(0.00254 * v ** 0.53 * h ** -0.90 * 3600.0)


def test_froehlich_geometry_validation():
    with pytest.raises(ValueError, match="must be positive"):
        froehlich_breach_geometry(0.0, 100.0)
    with pytest.raises(ValueError, match="must be positive"):
        froehlich_breach_geometry(1e9, 0.0)


def test_the_empirical_envelope_is_reported_but_not_used():
    """
    The regressions must appear in meta as a cross-check and must NOT influence
    the routed result. Asserted by confirming the routed peak is independent of
    them: it comes from the weir formula, which does not reference them at all.
    """
    hyd = simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
                          storage=tehri_storage(), geom=tehri_geom(),
                          bed_m=TEHRI_BED, dt=2.0)
    emp = hyd.meta["empirical"]
    assert set(emp) == {"Froehlich 1995", "USBR 1982", "MacDonald & L-M 1984"}
    assert all(v > 0.0 for v in emp.values())
    # The routed peak exceeds all three, which is the documented extrapolation
    # problem, not a bug: these are fits to embankment dams tens of metres high.
    assert hyd.peak_q > max(emp.values())


def test_the_summary_labels_the_envelope_as_a_smell_test():
    """
    A jury-facing string. If this label is ever dropped, an unverified
    regression starts looking like a result.
    """
    hyd = simulate_breach(crest_m=TEHRI_FRL, initial_level_m=TEHRI_FRL,
                          storage=tehri_storage(), geom=tehri_geom(),
                          bed_m=TEHRI_BED, dt=2.0)
    assert "smell test" in hyd.summary()

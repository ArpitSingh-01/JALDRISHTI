"""
Tests for `jaldrishti.analysis` — hazard, arrival, exposure, damage, summary.

WHY THIS FILE EXISTS
--------------------
The analysis package is where physics becomes a number a district officer acts
on. Nothing in it is hard to compute; everything in it is easy to get subtly and
invisibly wrong, because every output is a plausible-looking integer. A hazard
class off by one band, a population total that double-counts the reservoir, a
JSON payload carrying a bare NaN — none of those crash, and all of them reach a
slide.

So every test here checks an answer that is known ANALYTICALLY, not one recorded
from a previous run:

  * hazard ratings against the published formula evaluated by hand;
  * band edges against the exact boundary value, from both sides;
  * cell area against the surface area of a sphere, which is 4*pi*R^2 and not
    open to interpretation;
  * population against (cells x people-per-cell), an exact integer;
  * damage fractions against linear interpolation between tabulated points.

Two tests are regressions for bugs found by running the modules for the first
time, and both are marked as such. Neither raised an exception — that is the
point.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from jaldrishti.analysis import (
    AIDR_CLASSES,
    DEFRA_BANDS,
    DEFRA_CLASS_NAMES,
    INITIALLY_WET,
    NEVER_FLOODED,
    DamageRange,
    DamageResult,
    ScenarioSummary,
    aidr_hazard_class,
    analyse_arrival,
    analyse_exposure,
    area_damage,
    band_index,
    band_labels,
    building_damage,
    classify_hazard,
    damage_fraction,
    damage_limitations,
    debris_factor,
    defra_hazard_class,
    defra_hazard_rating,
    front_speed,
    geographic_cell_area_m2,
    road_damage,
    to_minutes,
)
from jaldrishti.analysis.exposure import EARTH_RADIUS_M

DX = 90.0


# ---------------------------------------------------------------------------
# fixtures — one synthetic scenario whose every answer is known by hand
# ---------------------------------------------------------------------------
@pytest.fixture
def scene():
    """
    A 20 x 20 grid. Columns 0-9 are flooded, 10-19 dry. Columns 0-1 are the
    "reservoir" — water before the failure.

    Every count in the tests below derives from those integers:
        flooded cells        = 20 rows x 10 cols = 200
        reservoir cells      = 20 x 2            =  40
        newly flooded cells  = 20 x 8            = 160
        cell area            = 90 x 90           = 8100 m^2
    """
    ny, nx = 20, 20
    depth = np.zeros((ny, nx))
    speed = np.zeros((ny, nx))
    depth[:, :10] = 2.0
    speed[:, :10] = 1.5

    initially_wet = np.zeros((ny, nx), dtype=bool)
    initially_wet[:, :2] = True

    # arrival every 5 minutes across the flooded columns: 0, 5, ... 45 min
    arrival_s = np.full((ny, nx), np.nan)
    arrival_s[:, :10] = np.arange(10) * 300.0

    haz = classify_hazard(depth, speed, depth * speed, dx=DX,
                          initially_wet=initially_wet)
    arr = analyse_arrival(arrival_s, dx=DX, initially_wet=initially_wet,
                          run_duration_s=3600.0)
    return {
        "ny": ny, "nx": nx, "depth": depth, "speed": speed,
        "initially_wet": initially_wet, "arrival_s": arrival_s,
        "hazard": haz, "arrival": arr,
    }


# ===========================================================================
# 1. hazard — the published formula, evaluated by hand
# ===========================================================================
def test_defra_rating_matches_the_published_formula_by_hand():
    """
    HR = d(v + 0.5) + DF, from FD2320.

    d = 1.0, v = 1.5, urban land cover. d >= 0.75 puts the cell in the "deep"
    debris row, where urban DF = 1.0. So

        HR = 1.0 * (1.5 + 0.5) + 1.0 = 3.0

    computed on paper, not read off a previous run.
    """
    hr = defra_hazard_rating(np.array([[1.0]]), np.array([[1.5]]),
                             landcover="urban")
    assert float(hr[0, 0]) == pytest.approx(3.0, abs=1e-12)


def test_the_velocity_offset_stops_still_water_scoring_zero():
    """
    Standing water is a hazard through drowning depth alone. 3 m of motionless
    water must not score 0, or the map declares a lake safe.

    d = 3.0, v = 0.0 -> HR = 3.0 * 0.5 + DF(deep, urban=1.0) = 2.5, which is at
    the top band edge and therefore Extreme. That is the correct answer: 3 m of
    still water drowns an adult.
    """
    hr = float(defra_hazard_rating(np.array([[3.0]]), np.array([[0.0]]))[0, 0])
    assert hr == pytest.approx(2.5, abs=1e-12)
    assert int(defra_hazard_class(np.array([[hr]]))[0, 0]) == 3


def test_debris_factor_treats_fast_shallow_water_as_debris_carrying():
    """
    The velocity clause in the debris table is an OR, not an AND: 0.1 m moving
    at 3 m/s carries fenceposts just as well as 1 m does. Getting this wrong
    understates the hazard exactly where a dam-break front is most dangerous —
    at its leading edge, which is fast and thin.
    """
    shallow_slow = float(debris_factor(np.array([[0.1]]), np.array([[0.1]]))[0, 0])
    shallow_fast = float(debris_factor(np.array([[0.1]]), np.array([[3.0]]))[0, 0])
    assert shallow_slow == 0.0
    assert shallow_fast == 1.0            # deep row, urban column


def test_debris_factor_varies_with_land_cover():
    d = np.full((1, 3), 1.0)
    v = np.zeros((1, 3))
    cover = np.array([[0, 1, 2]])         # pasture, woodland, urban
    df = debris_factor(d, v, landcover=cover)
    assert list(df[0]) == [0.5, 1.0, 1.0]


def test_defra_bands_are_closed_below_at_every_edge():
    """
    A value sitting exactly on a band edge must land in the HIGHER band. Off-by-
    one here silently downgrades the worst cells in the domain.
    """
    for i, edge in enumerate(DEFRA_BANDS):
        below = np.array([[edge - 1e-12]])
        exact = np.array([[edge]])
        assert int(defra_hazard_class(below)[0, 0]) == i
        assert int(defra_hazard_class(exact)[0, 0]) == i + 1


def test_dry_cells_are_minus_one_and_not_low_hazard(scene):
    """
    -1 must mean "not flooded" and 0 must mean "flooded, low hazard". Collapsing
    them makes every dry cell in the domain appear in the exposure table.
    """
    haz = scene["hazard"]
    assert int(haz.defra_class[0, 19]) == NEVER_FLOODED
    assert int(haz.aidr_class[0, 19]) == NEVER_FLOODED
    assert (haz.defra_class[:, :10] >= 0).all()


def test_max_dv_gives_a_lower_rating_than_multiplying_two_peaks():
    """
    The correctness point in `defra_hazard_rating`'s docstring, made testable.

    A dam-break front is fast and shallow; its body is deep and slow. Peak depth
    and peak speed therefore occur at DIFFERENT times, and multiplying them
    overstates the hazard. `max_dv` is the running maximum of the product itself.

    Depth peaks at 4 m, speed at 5 m/s, but the largest simultaneous product was
    only 6.0 (say 3 m at 2 m/s). Using the peaks gives 20; using max_dv gives 6.
    """
    d = np.array([[4.0]])
    v = np.array([[5.0]])
    dv = np.array([[6.0]])
    naive = float(defra_hazard_rating(d, v)[0, 0])
    honest = float(defra_hazard_rating(d, v, dv=dv)[0, 0])
    assert naive == pytest.approx(4.0 * 5.0 + 2.0 + 1.0)      # 23.0
    assert honest == pytest.approx(6.0 + 2.0 + 1.0)           # 9.0
    assert honest < naive


def test_aidr_puts_shallow_fast_water_in_h5_because_of_velocity():
    """
    0.2 m at 3 m/s. dv = 0.6, so H2 and H3's dv limit is satisfied — but their
    velocity limit (2.0 m/s) is not, and neither is H4's. The first class whose
    THREE limits all hold is H5. That is the scheme working as designed: the
    danger is the velocity, and a depth-only classification would call this
    ankle-deep and safe.
    """
    cls = int(aidr_hazard_class(np.array([[0.2]]), np.array([[3.0]]))[0, 0])
    assert AIDR_CLASSES[cls][0] == "H5"


def test_aidr_assigns_the_safest_class_that_fits():
    """Still puddle -> H1. Walking from most to least hazardous must not skip it."""
    cls = int(aidr_hazard_class(np.array([[0.2]]), np.array([[0.5]]))[0, 0])
    assert AIDR_CLASSES[cls][0] == "H1"


def test_hazard_areas_are_exact_cell_counts(scene):
    haz = scene["hazard"]
    cell_km2 = DX * DX / 1.0e6
    assert haz.flooded_cells == 200
    assert haz.flooded_area_km2 == pytest.approx(200 * cell_km2)
    assert haz.newly_flooded_area_km2 == pytest.approx(160 * cell_km2)
    # every flooded cell is 2 m at 1.5 m/s -> HR = 3 + 1 + 1 = ... Extreme
    by_class = haz.area_by_defra_class_km2()
    assert by_class["Extreme"] == pytest.approx(200 * cell_km2)
    assert sum(by_class.values()) == pytest.approx(200 * cell_km2)


def test_hazard_rejects_a_mismatched_initially_wet_mask(scene):
    with pytest.raises(ValueError, match="initially_wet"):
        classify_hazard(scene["depth"], scene["speed"], None, dx=DX,
                        initially_wet=np.zeros((3, 3), dtype=bool))


def test_hazard_warns_when_no_reservoir_mask_is_given(scene):
    """Silence about a missing mask is what made the reservoir bug invisible."""
    haz = classify_hazard(scene["depth"], scene["speed"], None, dx=DX)
    assert any("initially-wet" in t for t in haz.limitations)
    assert haz.newly_flooded_area_km2 == haz.flooded_area_km2


def test_hazard_sources_are_all_flagged_unverified():
    """
    Until someone opens FD2320 and AIDR Guideline 7-3 and checks the tables, the
    citations must stay `verified=False`, and the result must be able to say so.
    Flipping these to True is a research task with a paper trail, not an edit.
    """
    haz = classify_hazard(np.array([[1.0]]), np.array([[1.0]]), None, dx=DX)
    assert len(haz.unverified_sources()) == 2


# ===========================================================================
# 2. arrival — band edges, and the reservoir regression
# ===========================================================================
def test_nan_survives_the_conversion_to_minutes():
    """NaN is load-bearing: it is the only marker for 'water never arrived'."""
    out = to_minutes(np.array([0.0, 600.0, np.nan]))
    assert out[0] == 0.0
    assert out[1] == pytest.approx(10.0)
    assert np.isnan(out[2])


def test_band_edges_are_exact_from_both_sides():
    """
    Bands are [lo, hi). A cell at exactly 30.0 minutes belongs to 30-60, not to
    15-30. An evacuation order is written from these edges.
    """
    minutes = np.array([[0.0, 14.999, 15.0, 29.999, 30.0, 59.999,
                         60.0, 119.999, 120.0, 5000.0]])
    idx = band_index(minutes)
    assert list(idx[0]) == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]


def test_band_labels_line_up_with_band_indices():
    labels = band_labels()
    assert len(labels) == 5
    assert labels[0] == "0-15 min"
    assert labels[2] == "30-60 min"
    assert labels[-1] == ">120 min"


def test_cells_the_water_never_reached_are_never_flooded_not_late():
    idx = band_index(np.array([[np.nan, 10.0]]))
    assert int(idx[0, 0]) == NEVER_FLOODED
    assert int(idx[0, 1]) == 0


def test_the_reservoir_is_excluded_from_arrival_figures(scene):
    """
    REGRESSION. The reservoir is wet at t = 0, so the solver records arrival
    time 0 there. Left in:

      * `first_arrival_minutes()` returned 0.0 for every dam-break run, and the
        headline sentence read "first arrival 0 min after failure";
      * the reservoir's surface was counted in the 0-15 minute band, so the
        population needing to move within 15 minutes included everyone the
        population raster placed on the lake.

    Neither raised an exception. Both would have gone on a slide.
    """
    arr = scene["arrival"]
    # columns 0-1 are the reservoir; column 2 is the first real arrival at 10 min
    assert int(arr.band[0, 0]) == INITIALLY_WET
    assert int(arr.band[0, 1]) == INITIALLY_WET
    assert arr.first_arrival_minutes() == pytest.approx(10.0)
    assert arr.last_arrival_minutes() == pytest.approx(45.0)

    cell_km2 = DX * DX / 1.0e6
    # band 0 is now only column 2 (10 min); columns 0-1 have left it
    assert arr.area_by_band_km2()["0-15 min"] == pytest.approx(20 * cell_km2)
    assert arr.flooded_area_km2 == pytest.approx(160 * cell_km2)


def test_without_a_reservoir_mask_first_arrival_is_zero_and_says_so(scene):
    """
    The counterfactual, kept so the failure mode stays documented and so nobody
    'simplifies' the mask away. Note the run does not fail — it reports a
    nonsense 0.0 and flags itself.
    """
    arr = analyse_arrival(scene["arrival_s"], dx=DX)
    assert arr.first_arrival_minutes() == pytest.approx(0.0)
    assert any("initially-wet mask" in t for t in arr.limitations)


def test_arrival_area_by_band_is_an_exact_cell_count(scene):
    arr = scene["arrival"]
    cell_km2 = DX * DX / 1.0e6
    areas = arr.area_by_band_km2()
    # cols 2,3 -> 10,15 min: 10 is band 0, 15 is band 1
    # cols 4..5 -> 20,25 min: band 1.  cols 6..9 -> 30,35,40,45: band 2
    assert areas["0-15 min"] == pytest.approx(20 * 1 * cell_km2)
    assert areas["15-30 min"] == pytest.approx(20 * 3 * cell_km2)
    assert areas["30-60 min"] == pytest.approx(20 * 4 * cell_km2)
    assert sum(areas.values()) == pytest.approx(160 * cell_km2)


def test_front_speed_recovers_a_known_constant_speed():
    """
    Arrival time t = x / c gives |grad t| = 1/c everywhere, so the front speed is
    exactly c — including at the array edges, where `np.gradient` switches to
    one-sided differences that remain exact for a linear field.
    """
    c = 7.5
    ny, nx = 6, 40
    x = np.arange(nx) * DX
    t = np.tile(x / c, (ny, 1))
    speed = front_speed(t, DX)
    assert np.nanmax(np.abs(speed - c)) < 1e-9


def test_arrival_reports_the_open_boundary_contamination_width():
    arr = analyse_arrival(np.zeros((4, 4)), dx=DX, open_bc_cells=10)
    note = [t for t in arr.limitations if "open boundary" in t]
    assert len(note) == 1
    assert "0.9 km" in note[0]            # 10 cells x 90 m


def test_arrival_rejects_a_mismatched_reservoir_mask(scene):
    with pytest.raises(ValueError, match="initially_wet"):
        analyse_arrival(scene["arrival_s"], dx=DX,
                        initially_wet=np.zeros((3, 3), dtype=bool))


def test_a_run_where_nothing_floods_does_not_crash():
    """
    An all-NaN arrival raster is a legitimate result — the scenario flooded
    nothing. It must produce NaN and empty bands, not an exception, because the
    API has to be able to return "no inundation" as an answer.
    """
    arr = analyse_arrival(np.full((5, 5), np.nan), dx=DX)
    assert math.isnan(arr.first_arrival_minutes())
    assert arr.flooded_area_km2 == 0.0
    assert all(v == 0.0 for v in arr.area_by_band_km2().values())


# ===========================================================================
# 3. exposure — a sphere's surface area, and an exact head count
# ===========================================================================
def test_geographic_cell_areas_sum_to_the_surface_of_the_sphere():
    """
    The strongest available check on `geographic_cell_area_m2`, and the reason it
    uses the exact spherical-quadrilateral formula rather than dx*cos(lat)*dy.

    Tile the whole globe in 1-degree cells and sum:

        sum = 360 * R^2 * (pi/180) * sum_rows (sin(top) - sin(bot))
            = 2*pi*R^2 * (sin(90) - sin(-90))
            = 4*pi*R^2

    which is the surface area of a sphere. Any latitude-dependent error in the
    formula breaks this identity; the cos(lat) approximation misses it by ~1.4%.
    """
    lats = np.arange(-89.5, 90.0, 1.0)          # 180 row centres
    per_cell = geographic_cell_area_m2(lats, 1.0, 1.0)
    total = float(per_cell.sum()) * 360.0
    expected = 4.0 * math.pi * EARTH_RADIUS_M ** 2
    assert total == pytest.approx(expected, rel=1e-12)


def test_a_cell_shrinks_east_west_with_latitude():
    """At 60 N a cell is about half the area of one at the equator."""
    eq = float(geographic_cell_area_m2(0.0, 1.0, 1.0))
    hi = float(geographic_cell_area_m2(60.0, 1.0, 1.0))
    assert hi / eq == pytest.approx(0.5, abs=0.01)


def test_uniform_population_over_a_known_flood_gives_an_exact_count(scene):
    """
    The ROADMAP acceptance criterion for this package, stated literally: uniform
    depth over a known population raster gives an exact expected count.

    160 newly flooded cells x 10 people per cell = 1,600 people. Not
    approximately 1,600 — exactly, because both factors are integers and no
    resampling is involved.
    """
    pop = np.full((scene["ny"], scene["nx"]), 10.0)
    ex = analyse_exposure(pop, scene["hazard"], scene["arrival"])
    assert ex.total_population == pytest.approx(1600.0, abs=1e-9)


def test_the_exposure_marginals_are_forced_to_agree(scene):
    """
    The by-hazard column and the by-band column count the same people two ways.
    Before `analyse_exposure` existed they disagreed by exactly the reservoir's
    population — 2,000 against 1,600 in this fixture — because the hazard raster
    has no notion of "already wet" and the band raster does. A table whose rows
    and columns do not add up is indefensible in front of a jury.
    """
    pop = np.full((scene["ny"], scene["nx"]), 10.0)
    ex = analyse_exposure(pop, scene["hazard"], scene["arrival"])
    total = ex.total_population
    assert sum(ex.population_by_hazard.values()) == pytest.approx(total)
    assert sum(ex.population_by_arrival_band.values()) == pytest.approx(total)
    assert sum(v for row in ex.population_cross_tab.values()
               for v in row.values()) == pytest.approx(total)


def test_the_cross_tab_is_the_operational_table(scene):
    """
    "200 people in Extreme hazard with under 15 minutes" is what orders a staged
    evacuation. Marginals alone cannot say it.
    """
    pop = np.full((scene["ny"], scene["nx"]), 10.0)
    ex = analyse_exposure(pop, scene["hazard"], scene["arrival"])
    # column 2 arrives at 10 min: 20 cells x 10 people, all Extreme
    assert ex.population_cross_tab["Extreme"]["0-15 min"] == pytest.approx(200.0)
    assert ex.population_cross_tab["Low"]["0-15 min"] == 0.0


def test_exposure_excludes_people_the_flood_never_reaches(scene):
    """
    Population outside the flood must contribute nothing. Putting the entire
    population in the dry half proves the mask is applied and not merely
    documented.
    """
    pop = np.zeros((scene["ny"], scene["nx"]))
    pop[:, 10:] = 1000.0                       # all of it on dry land
    ex = analyse_exposure(pop, scene["hazard"], scene["arrival"])
    assert ex.total_population == 0.0


def test_population_is_reported_to_two_significant_figures():
    """
    Reporting 12,437 implies a per-person census of a modelled surface. The PDF
    prints this; the JSON keeps the raw float so nothing is lost.
    """
    from jaldrishti.analysis import ExposureResult
    ex = ExposureResult(12_437.4, {}, {}, {})
    assert ex.rounded_population() == 12_000
    assert ex.rounded_population(0.0) == 0
    assert ex.rounded_population(847.0) == 850


def test_exposure_rejects_a_population_grid_of_the_wrong_shape(scene):
    with pytest.raises(ValueError, match="does not match the model grid"):
        analyse_exposure(np.zeros((3, 3)), scene["hazard"], scene["arrival"])


# ===========================================================================
# 4. damage — interpolation, clamping, and the range that cannot be discarded
# ===========================================================================
def test_damage_fraction_hits_every_tabulated_point_exactly():
    from jaldrishti.analysis import CURVES
    for name, c in CURVES.items():
        got = damage_fraction(np.array(c["depths"]), curve=name)
        assert np.allclose(got, np.array(c["damage"]), atol=1e-12), name


def test_damage_fraction_interpolates_linearly_between_points():
    """0.25 m sits halfway between 0.0 (0.00) and 0.5 (0.32) -> 0.16 exactly."""
    assert float(damage_fraction(0.25)) == pytest.approx(0.16, abs=1e-12)
    # 1.75 m: halfway between 1.5 (0.68) and 2.0 (0.80) -> 0.74
    assert float(damage_fraction(1.75)) == pytest.approx(0.74, abs=1e-12)


def test_damage_fraction_clamps_and_never_exceeds_total_loss():
    """
    Extrapolating a fitted curve past its range would invent damage fractions
    above 1 — more than total loss — which then multiply an asset value.
    """
    assert float(damage_fraction(500.0)) == 1.0
    assert float(damage_fraction(-5.0)) == 0.0


def test_an_unknown_curve_name_is_an_error_not_a_default():
    with pytest.raises(ValueError, match="unknown damage curve"):
        damage_fraction(1.0, curve="mud_brick")


def test_the_mean_of_the_damage_is_not_the_damage_of_the_mean():
    """
    Why `building_damage` samples depth per building instead of applying an
    average depth to a count. Two buildings at 0.5 m and 3.0 m:

        mean of fractions = (0.32 + 0.93) / 2 = 0.625
        fraction at mean depth (1.75 m)       = 0.740

    an 18% difference in the same direction as the curve's concavity. With a
    curve that is convex at low depth and concave above, the error runs both
    ways and cannot be dismissed as conservative.
    """
    per_building = float(damage_fraction(np.array([0.5, 3.0])).mean())
    at_mean_depth = float(damage_fraction(1.75))
    assert per_building == pytest.approx(0.625, abs=1e-12)
    assert at_mean_depth == pytest.approx(0.740, abs=1e-12)
    assert abs(at_mean_depth - per_building) > 0.1


def test_building_damage_is_the_summed_fraction_times_unit_value():
    depth = np.zeros((4, 4))
    depth[0, 0] = 2.0            # fraction 0.80
    depth[0, 1] = 1.0            # fraction 0.53
    rng, frac = building_damage(depth, [0, 0], [0, 1], unit_value=1_000_000.0)
    assert list(frac) == pytest.approx([0.80, 0.53], abs=1e-12)
    assert rng.central == pytest.approx(1.33 * 1_000_000.0, rel=1e-12)


def test_building_damage_on_an_empty_building_list_is_zero_not_an_error():
    rng, frac = building_damage(np.zeros((3, 3)), [], [])
    assert rng.central == 0.0
    assert frac.size == 0


def test_area_damage_integrates_cell_by_cell():
    """
    One 90 m cell at 1.0 m depth, agriculture curve (0.62), at Rs 250,000/ha.
    Cell area = 8100 m^2 = 0.81 ha, so central = 0.62 * 0.81 * 250000.
    """
    depth = np.zeros((2, 2))
    depth[0, 0] = 1.0
    rng = area_damage(depth, dx=DX, value_per_hectare=250_000.0)
    assert rng.central == pytest.approx(0.62 * 0.81 * 250_000.0, rel=1e-12)


def test_a_damage_range_cannot_be_silently_collapsed_to_one_number():
    """
    `DamageRange` deliberately has no `.value`. Code that wants a point estimate
    must say `.central`, which makes discarding the uncertainty visible in
    review rather than implicit.
    """
    r = DamageRange.around(100.0)
    assert not hasattr(r, "value")
    assert r.central == 100.0
    assert (r.low, r.high) == (50.0, 200.0)


def test_damage_ranges_add_component_wise():
    total = DamageRange.around(100.0) + DamageRange.around(300.0)
    assert (total.low, total.central, total.high) == (200.0, 400.0, 800.0)


def test_adding_ranges_in_different_units_is_refused():
    with pytest.raises(ValueError, match="cannot add"):
        DamageRange.around(1.0) + DamageRange.around(1.0, unit="USD")


def test_crore_conversion_and_formatting():
    r = DamageRange.around(8.47e9)                      # Rs 847 crore central
    lo, ce, hi = r.in_crore()
    assert ce == pytest.approx(847.0)
    assert lo == pytest.approx(423.5)
    txt = r.format_crore()
    assert "order-of-magnitude" in txt
    assert "crore" in txt


def test_road_damage_uses_a_single_flagged_fraction():
    r = road_damage(10.0, value_per_km=25_000_000.0, curve_fraction=0.35)
    assert r.central == pytest.approx(10.0 * 25_000_000.0 * 0.35)


def test_damage_result_total_is_the_sum_of_its_categories():
    dm = DamageResult(by_category={
        "residential": DamageRange.around(100.0),
        "roads": DamageRange.around(50.0),
    })
    assert dm.total.central == pytest.approx(150.0)


def test_damage_limitations_name_the_velocity_omission():
    """
    Depth-damage curves ignore velocity, which for a dam break is the mechanism
    that destroys masonry. The caveat must be present, and the AIDR H5-H6 count
    reported alongside, or the loss figure quietly understates the worst areas.
    """
    texts = " ".join(damage_limitations()).lower()
    assert "velocity" in texts
    assert "order-of-magnitude" in texts
    assert "loss of life" in texts


# ===========================================================================
# 5. summary — the release gate and the JSON regression
# ===========================================================================
def _summary(scene, **kw):
    from affine import Affine
    pop = np.full((scene["ny"], scene["nx"]), 10.0)
    ex = analyse_exposure(pop, scene["hazard"], scene["arrival"])
    dm = DamageResult(
        by_category={"residential": DamageRange.around(1.0e8)},
        structural_failure_buildings=7,
        limitations=damage_limitations(),
    )
    defaults = dict(
        run_id="test-0001", study_area="Synthetic", scenario="test breach",
        transform=Affine(DX, 0.0, 300000.0, 0.0, -DX, 3400000.0),
        crs="EPSG:32644", dx=DX, shape=(scene["ny"], scene["nx"]),
        max_depth=scene["depth"], max_speed=scene["speed"],
        max_dv=scene["depth"] * scene["speed"],
        hazard=scene["hazard"], arrival=scene["arrival"],
        exposure=ex, damage=dm,
        duration_s=3600.0, wall_time_s=4.2, steps=1234, volume_error=3.1e-13,
    )
    defaults.update(kw)
    return ScenarioSummary(**defaults)


def test_to_dict_emits_strict_json_with_no_nan(scene):
    """
    REGRESSION. `json.dumps` writes bare `NaN` and `Infinity` by default, and
    NEITHER is valid JSON — `JSON.parse` throws on both. Arrival time is NaN
    wherever water never arrived, so a scenario that floods nothing produced an
    API response the frontend could not parse. `allow_nan=False` is the whole
    test: it fails on exactly the values a browser would reject.
    """
    s = _summary(scene)
    payload = json.dumps(s.to_dict(), allow_nan=False)
    assert json.loads(payload)["run_id"] == "test-0001"


def test_to_dict_survives_a_scenario_that_floods_nothing():
    """The empty case is where the NaN escaped. It must serialise as null."""
    from affine import Affine
    zeros = np.zeros((5, 5))
    haz = classify_hazard(zeros, zeros, None, dx=DX)
    arr = analyse_arrival(np.full((5, 5), np.nan), dx=DX)
    s = ScenarioSummary(
        run_id="empty", study_area="Nowhere", scenario="no failure",
        transform=Affine(DX, 0.0, 0.0, 0.0, -DX, 0.0), crs="EPSG:32644",
        dx=DX, shape=(5, 5), max_depth=zeros, max_speed=zeros, max_dv=zeros,
        hazard=haz, arrival=arr)
    d = json.loads(json.dumps(s.to_dict(), allow_nan=False))
    assert d["results"]["first_arrival_min"] is None
    assert d["results"]["flooded_area_km2"] == 0.0
    assert s.peak_depth_m == 0.0


def test_the_headline_is_the_sentence_the_project_exists_to_produce(scene):
    s = _summary(scene)
    line = s.headline()
    assert "first arrival 10 min" in line
    assert "1,600 people" in line
    assert "Synthetic" in line


def test_the_headline_reports_new_flooding_not_the_reservoir(scene):
    """
    160 cells x 8100 m^2 = 1.296 km^2 of NEW inundation, against 1.62 km^2 of
    total wetted area. Quoting the total would add the reservoir's own surface to
    every result — at a large dam, tens of km^2 that were water all along.
    """
    s = _summary(scene)
    assert s.flooded_area_km2 == pytest.approx(1.296)
    assert s.total_wetted_area_km2 == pytest.approx(1.62)


def test_unverified_sources_propagate_all_the_way_up(scene):
    """
    Six unverified citations feed this run: two hazard schemes, two exposure
    datasets, the JRC curves and the asset values. All six must reach the
    summary, because `export/report.py` prints this list and a missing entry is
    an unlabelled claim.
    """
    s = _summary(scene)
    assert len(s.unverified_inputs) == 6
    ok, reasons = s.is_presentable()
    assert ok is False
    assert any("not verified" in r for r in reasons)


def test_a_large_mass_error_blocks_presentation(scene):
    s = _summary(scene, volume_error=-0.32)
    _ok, reasons = s.is_presentable()
    assert any("mass conservation" in r for r in reasons)
    assert any("Mass conservation error" in t for t in s.limitations)


def test_a_failed_population_resample_blocks_presentation(scene):
    from jaldrishti.analysis import ExposureResult
    ex = ExposureResult(1.0, {}, {}, {},
                        resample_report={"conserved": False,
                                         "residual_fraction": -0.22})
    s = _summary(scene, exposure=ex)
    _ok, reasons = s.is_presentable()
    assert any("resampling did not conserve" in r for r in reasons)


def test_limitations_are_gathered_from_every_stage_and_deduplicated(scene):
    dup = "Population is a residential night-time distribution. It does not " \
          "represent people at work, in transit, at a market, or on a " \
          "pilgrimage route — which for the Bhagirathi and Alaknanda valleys " \
          "is a material seasonal omission."
    s = _summary(scene, extra_limitations=[dup, "A unique extra caveat."])
    texts = s.limitations
    assert texts.count(dup) == 1
    assert "A unique extra caveat." in texts
    # every stage contributed
    assert any("neighbourhood" in t for t in texts)          # hazard
    assert any("NOT warning time" in t for t in texts)       # arrival
    assert any("WorldPop" in t for t in texts)               # exposure
    assert any("ORDER-OF-MAGNITUDE" in t for t in texts)     # damage


def test_interpolated_dem_cells_under_the_flood_are_counted_and_flagged(scene):
    """
    A depth over terrain filled across a DEM void is weaker evidence than a
    depth over surveyed terrain, and the map cannot show the difference. The
    count has to travel with the result.
    """
    valid = np.ones((scene["ny"], scene["nx"]), dtype=bool)
    valid[:, :5] = False                     # 100 of the 200 flooded cells
    s = _summary(scene, dem_valid_mask=valid)
    assert s.interpolated_flooded_cells == 100
    assert any("interpolated across a DEM void" in t for t in s.limitations)


def test_summary_renders_without_optional_stages(scene):
    """
    Exposure and damage are optional — a run before the population raster
    downloads must still produce a report rather than an AttributeError.
    """
    s = _summary(scene, exposure=None, damage=None)
    text = s.summary()
    assert "test breach" in text
    assert "1,600 people" not in s.headline()
    json.dumps(s.to_dict(), allow_nan=False)
    assert len(s.unverified_inputs) == 2      # hazard only

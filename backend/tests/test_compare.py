"""
Tests for validation/compare.py — the "compare the modelling approaches"
module (problem-statement requirement).

The comparisons run on small, fully synthetic problems so the suite stays
fast; the same functions power the larger scripted comparison in
scripts/compare_solvers.py.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from jaldrishti.validation import (
    compare_hydrographs,
    compare_solvers,
    ritter_breach_discharge,
)
from jaldrishti.solver import DamBreakSPH


# ---------------------------------------------------------------------------
# Hydrograph comparison
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def short_sph_run():
    """A short SPH run with a gauge, reused across hydrograph tests."""
    a = 0.5
    sim = DamBreakSPH(2 * a, a, 6 * a, a / 15)
    sim.set_gauge(1.1 * a)
    sim.run(0.45, callback_every=10)
    return sim


def test_ritter_breach_discharge_value():
    # 8/27 * sqrt(9.81) * 0.5^1.5 — hard-coded independent recomputation.
    expected = 8.0 / 27.0 * math.sqrt(9.81) * 0.5 ** 1.5
    assert ritter_breach_discharge(0.5) == pytest.approx(expected)


def test_hydrograph_comparison_against_ritter(short_sph_run):
    comp = compare_hydrographs(short_sph_run, t_end=0.45)
    assert comp.q_ritter == pytest.approx(
        ritter_breach_discharge(short_sph_run.column_height))
    # SPH peak per-unit-width discharge should be of the same order as the
    # analytical constant — not zero, not 100x. Loose band on purpose: the
    # point is order-of-magnitude sanity, exact agreement is not expected
    # between a vertical-plane particle model and a depth-averaged law.
    peak = float(comp.q_sph.max())
    assert 0.3 * comp.q_ritter < peak < 3.0 * comp.q_ritter, (
        f"SPH peak {peak:.3f} vs analytical {comp.q_ritter:.3f}"
    )
    assert comp.volume_sph > 0


# ---------------------------------------------------------------------------
# Solver-level comparison (SWE vs SPH vs Ritter)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_solver_comparison_fronts_agree(chart_dir):
    """
    Front placement on the shared dam-break problem.

    The SWE engine is the depth-averaged frictionless model itself, so its
    front must sit within 15% of Ritter. The SPH engine is a vertical-plane
    particle model: it reproduces the MARTIN & MOYCE experiment (see
    test_sph), whose measured front is genuinely 20-30% slower than Ritter's
    inviscid depth-averaged front because real collapse dissipates. The
    honest assertion is therefore: SPH slower than Ritter, but within 35%.
    """
    comp = compare_solvers(t_end=0.60)
    ritter_front = comp.ritter_front_m

    assert abs(comp.swe_front_m - ritter_front) / ritter_front < 0.15, (
        f"swe front {comp.swe_front_m:.2f} m vs analytical "
        f"{ritter_front:.2f} m at t=0.60 s"
    )
    assert comp.sph_front_m <= ritter_front * 1.02, (
        "sph front should not outrun the inviscid depth-averaged front")
    assert (ritter_front - comp.sph_front_m) / ritter_front < 0.35, (
        f"sph front {comp.sph_front_m:.2f} m is more than 35% behind "
        f"analytical {ritter_front:.2f} m")
    import matplotlib
    matplotlib.use("Agg")
    from jaldrishti.validation.compare import write_solver_comparison_chart
    out = write_solver_comparison_chart(comp, chart_dir / "compare_profile.png")
    assert out.exists()


@pytest.mark.slow
def test_solver_comparison_chart_writes(chart_dir):
    comp = compare_solvers(t_end=0.45)
    from jaldrishti.validation.compare import write_solver_comparison_chart
    out = write_solver_comparison_chart(comp, chart_dir / "compare_profile_045.png")
    assert out.exists()


# ---------------------------------------------------------------------------
# Scenario-level: routing two different inflows through one domain
# ---------------------------------------------------------------------------


def _make_two_inflows():
    """SPH-derived inflow vs a scaled constant, over the same cells.

    The SPH gauge measures per-unit-width discharge (~0.3 m2/s); the breach
    width scales it to a reach-sized flood (150 m x 0.3 = ~45 m3/s) so both
    inflows are of comparable magnitude and the routed comparison is
    meaningful.
    """
    a = 0.5
    sim = DamBreakSPH(2 * a, a, 6 * a, a / 15)
    sim.set_gauge(1.1 * a)
    sim.run(0.45, callback_every=10)
    cells = np.array([[5, 4], [6, 4], [5, 5], [6, 5]])
    inflow_sph = sim.to_inflow(width=200.0, cells=cells)

    def q_const(t):
        return 60.0 if t > 10.0 else 0.0

    from jaldrishti.solver import Inflow
    inflow_const = Inflow(cells, q_const, direction=(1.0, 0.0),
                          speed=2.0, label="constant")
    return {"sph": inflow_sph, "constant": inflow_const}


@pytest.mark.slow
def test_scenario_comparison_gauges_differ_or_agree():
    from jaldrishti.validation.compare import route_through_domain

    inflows = _make_two_inflows()
    result = route_through_domain(
        inflows,
        domain={"nx": 160, "ny": 10, "dx": 20.0, "slope": 0.002,
                "manning": 0.033},
        gauge_points={"mid": (5, 30), "lower": (5, 70)},
        t_end=3600.0,
    )
    for label, gauges in result.gauges.items():
        for name, g in gauges.items():
            assert g is not None, f"{label}/{name}: flood never arrived"
            assert g.arrival_s > 0
            assert g.peak_depth_m > 0

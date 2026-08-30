"""
Inflow source term and output accumulators.

WHAT IS BEING TESTED
--------------------
Two pieces of machinery that sit between the breach model and the product's
headline numbers, and which have no analytical benchmark of their own:

  1. `add_inflow` — a discharge hydrograph Q(t) injected into named cells. This
     is the ONLY way a dam breach enters the simulation, so if the volume it
     puts in is wrong, every downstream number is wrong by the same factor and
     nothing else in the validation ladder would notice.

  2. `track_maxima` — max depth, max speed, max depth*velocity and first arrival
     time, accumulated every timestep. Arrival time is the number this project
     exists to report ("water reaches this village in 47 minutes"), and it is
     the one output that cannot be recovered after the fact from saved frames.

WHY MASS BALANCE IS THE CENTRAL TEST HERE
-----------------------------------------
Heun's method applied to a source term is the trapezoidal rule. That is a
mathematical fact, not an approximation, so for a linear Q(t) the volume the
solver injects must equal the analytic integral to round-off. Asserting a loose
tolerance would let a factor-of-two stage-weighting bug pass — the classic
failure being to add the source once per step instead of once per stage, or to
add it twice at full weight. Both give volumes wrong by exactly 2x, and both
still produce a plausible-looking flood.

THE ARRIVAL-TIME TEST IS ANALYTICAL
-----------------------------------
Arrival time gets a real benchmark rather than a regression check. In the Ritter
dry-bed dam break the depth field is known in closed form,

    h(x, t) = (1/(9g)) * (2*c0 - x/t)^2,     c0 = sqrt(g*h0)

so the moment a given station first exceeds the arrival threshold is also known:
set h = h_thresh and solve for t,

    t_arrival(x) = x / (2*c0 - 3*sqrt(g*h_thresh))

Note this is LATER than the front arrival x/(2*c0), because the front of a
dry-bed dam break is an infinitely thin wedge. That distinction matters for the
product: reporting the front rather than a usable depth would tell a district
officer the water arrives sooner than anything they could observe.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from jaldrishti.solver import GRAVITY, SWE2D

MASS_TOL = 1.0e-12


# =============================================================================
# mass conservation of the source term
# =============================================================================

def test_constant_inflow_volume_is_exact():
    """
    Constant Q into a closed, already-wet basin. Injected volume must equal Q*T
    to round-off, and total volume must equal initial + injected.

    The basin starts wet everywhere so there are no dry cells for `_clean_dry`
    to touch: this isolates the source term from the wetting/drying machinery,
    which is tested separately.
    """
    ny, nx, dx = 30, 30, 20.0
    s = SWE2D(np.zeros((ny, nx)), dx, manning=0.0,
              bc=("wall", "wall", "wall", "wall"))
    s.set_depth(1.0)
    v0 = s.volume()

    q = 500.0
    s.add_inflow([(15, 15)], q, label="test")
    t_end = 60.0
    s.run(t_end, dt_max=0.5)

    assert s.stats.volume_injected == pytest.approx(q * t_end, rel=1e-12)
    assert s.stats.volume_final == pytest.approx(v0 + q * t_end, rel=MASS_TOL)
    assert abs(s.stats.volume_error) < MASS_TOL
    assert s.stats.mass_clipped == 0.0


def test_linear_ramp_inflow_volume_is_exact():
    """
    Q(t) = a*t. The trapezoidal rule is exact for a linear integrand, so the
    injected volume must equal a*T^2/2 to round-off regardless of the step size.

    This is the test that catches a stage-weighting error. A source added once
    per step at full weight, or evaluated at the same time in both stages, gives
    a volume that is wrong by a fixed factor and would sail past any tolerance
    set in percent.
    """
    ny, nx, dx = 24, 24, 25.0
    s = SWE2D(np.zeros((ny, nx)), dx, manning=0.0,
              bc=("wall", "wall", "wall", "wall"))
    s.set_depth(2.0)
    v0 = s.volume()

    a = 20.0    # m^3/s per second
    s.add_inflow([(12, 12)], lambda t: a * t)
    t_end = 40.0
    s.run(t_end, dt_max=0.4)

    analytic = 0.5 * a * t_end ** 2
    assert s.stats.volume_injected == pytest.approx(analytic, rel=1e-12)
    assert s.stats.volume_final == pytest.approx(v0 + analytic, rel=MASS_TOL)


def test_inflow_into_dry_domain_conserves_mass():
    """
    The realistic case: a hydrograph into a dry channel. Mass must still balance,
    which means the wetting front must not be inventing or destroying water.
    """
    ny, nx, dx = 40, 40, 30.0
    s = SWE2D(np.zeros((ny, nx)), dx, manning=0.03,
              bc=("wall", "wall", "wall", "wall"))

    q = 2000.0
    s.add_inflow([(20, 20)], q)
    s.run(120.0, dt_max=1.0)

    injected = s.stats.volume_injected
    assert injected == pytest.approx(q * 120.0, rel=1e-12)
    # Allow for the small positivity repair at the wave front, but require it to
    # be a round-off-scale effect rather than a leak.
    assert abs(s.stats.volume_error) < 1e-8
    assert s.stats.mass_clipped < 1e-6 * injected


def test_weights_split_discharge_in_proportion():
    """
    Unequal weights must split the discharge in exactly that ratio. Weights are
    how a breach several cells wide distributes its flow, so getting the
    normalisation wrong would concentrate the whole hydrograph into one cell.
    """
    ny, nx, dx = 20, 20, 10.0
    s = SWE2D(np.zeros((ny, nx)), dx, manning=0.0,
              bc=("wall", "wall", "wall", "wall"))
    s.add_inflow([(10, 8), (10, 12)], 100.0, weights=[3.0, 1.0])
    # One very small step: the injected depth is still local to the source cells.
    s.step(dt=1.0e-3)
    h = s.h
    # Not bit-exact, and correctly so: RK2's second stage sees water that stage
    # one put there, and the deeper cell sheds slightly more of it. The residual
    # is the physics, not the split.
    assert h[10, 8] == pytest.approx(3.0 * h[10, 12], rel=1e-4)
    # The DOMAIN total, by contrast, is exact — the box has walls, so nothing
    # left. Summing only the two source cells would miss the sliver that stage
    # two has already pushed into their neighbours.
    assert s.volume() == pytest.approx(100.0 * 1.0e-3, rel=1e-12)


def test_weights_are_normalised_regardless_of_scale():
    """Weights [30, 10] must behave identically to [3, 1]."""
    ny, nx, dx = 20, 20, 10.0
    out = []
    for w in ([3.0, 1.0], [30.0, 10.0], [0.75, 0.25]):
        s = SWE2D(np.zeros((ny, nx)), dx, manning=0.0,
                  bc=("wall", "wall", "wall", "wall"))
        s.add_inflow([(10, 8), (10, 12)], 100.0, weights=w)
        s.step(dt=1.0e-3)
        out.append(s.h[10, 8])
    assert out[0] == pytest.approx(out[1], rel=1e-12)
    assert out[0] == pytest.approx(out[2], rel=1e-12)


def test_multiple_inflows_accumulate():
    """Two independent hydrographs must both be injected, not the last one only."""
    ny, nx, dx = 20, 20, 10.0
    s = SWE2D(np.zeros((ny, nx)), dx, manning=0.0,
              bc=("wall", "wall", "wall", "wall"))
    s.set_depth(0.5)
    v0 = s.volume()
    s.add_inflow([(5, 5)], 100.0, label="a")
    s.add_inflow([(15, 15)], 300.0, label="b")
    s.run(10.0, dt_max=0.5)
    assert s.stats.volume_injected == pytest.approx(400.0 * 10.0, rel=1e-12)
    assert s.stats.volume_final == pytest.approx(v0 + 4000.0, rel=MASS_TOL)


def test_zero_discharge_is_a_no_op():
    """A hydrograph that has not started yet must not perturb the solution."""
    ny, nx, dx = 20, 20, 10.0
    z = np.linspace(0.0, 5.0, nx)[None, :] * np.ones((ny, 1))
    s = SWE2D(z, dx, manning=0.03, bc=("wall", "wall", "wall", "wall"))
    s.set_surface(6.0)
    s.add_inflow([(10, 10)], lambda t: 0.0 if t < 100.0 else 500.0)
    s.run(20.0, dt_max=1.0)
    assert s.stats.volume_injected == 0.0
    # Still lake-at-rest: the source must not have broken well-balancedness.
    assert np.max(np.abs(s.speed)) < 1.0e-9


# =============================================================================
# momentum injection
# =============================================================================

def test_directed_inflow_carries_the_prescribed_velocity():
    """
    Water injected with direction and speed must arrive already moving at that
    speed, not be accelerated from rest afterwards.

    This is the property that makes the scheme safe. Mass enters at rate R and
    momentum at rate R*U, so in the source cell hu/h = (R*U*dt)/(R*dt) = U
    exactly, from the very first step and at any depth — including the first
    step into a dry cell, where a mass-only source followed by a pressure-driven
    acceleration is the standard way to produce a spurious velocity spike.

    The step is sized so the resulting depth clears `h_min`. Below h_min the
    REPORTED velocity is deliberately desingularised towards zero (see
    `_desing_vel`), which is exactly the protection we want in a thin film but
    would mask the ratio this test is about. hu/h is checked directly for that
    reason, and the desingularised view is checked separately.
    """
    ny, nx, dx = 40, 40, 50.0
    u_in = 12.0
    q = 8000.0
    s = SWE2D(np.zeros((ny, nx)), dx, manning=0.0,
              bc=("wall", "wall", "wall", "wall"))
    s.add_inflow([(20, 10)], q, direction=(1.0, 0.0), speed=u_in)
    dt = 0.2
    s.step(dt=dt)

    h = s.h[20, 10]
    assert h > s.h_min, "step too small to clear the dry threshold"
    # The cell holds a little less than rate*dt because it has already started
    # shedding water downstream — which is the point of injecting momentum.
    assert h == pytest.approx(q * dt / (dx * dx), rel=0.10)
    assert s.hu[20, 10] / h == pytest.approx(u_in, rel=2e-2)
    assert s.u[20, 10] == pytest.approx(u_in, rel=3e-2)
    assert abs(s.v[20, 10]) < 1e-9


def test_directed_inflow_stays_near_prescribed_velocity_while_growing():
    """
    The ratio property holds while the depth is still building, which is the
    regime a slowly forming breach spends its first minutes in.
    """
    ny, nx, dx = 40, 40, 50.0
    u_in = 15.0
    s = SWE2D(np.zeros((ny, nx)), dx, manning=0.0,
              bc=("wall", "wall", "wall", "wall"))
    # Ramp sized so the source cell holds ~1 m by the end of the loop.
    s.add_inflow([(20, 10)], lambda t: 5000.0 * t,
                 direction=(1.0, 0.0), speed=u_in)
    for _ in range(20):
        s.step(dt=0.05)
    assert s.h[20, 10] > s.h_min
    # Flux out of the source cell perturbs the ratio, so this is a few-percent
    # check rather than an exact one.
    assert s.hu[20, 10] / s.h[20, 10] == pytest.approx(u_in, rel=0.10)


def test_diagonal_direction_is_normalised():
    """A direction of (1, 1) must give speed U, not U*sqrt(2)."""
    ny, nx, dx = 40, 40, 50.0
    u_in = 10.0
    s = SWE2D(np.zeros((ny, nx)), dx, manning=0.0,
              bc=("wall", "wall", "wall", "wall"))
    s.add_inflow([(20, 20)], 8000.0, direction=(1.0, 1.0), speed=u_in)
    s.step(dt=0.2)
    h = s.h[20, 20]
    sp = math.hypot(s.hu[20, 20], s.hv[20, 20]) / h
    assert sp == pytest.approx(u_in, rel=5e-3)
    assert s.hu[20, 20] == pytest.approx(s.hv[20, 20], rel=1e-9)


def test_mass_only_inflow_injects_no_momentum():
    """Without a direction the water must enter at rest and spread symmetrically."""
    ny, nx, dx = 41, 41, 20.0
    s = SWE2D(np.zeros((ny, nx)), dx, manning=0.0,
              bc=("wall", "wall", "wall", "wall"))
    s.add_inflow([(20, 20)], 5000.0)
    s.step(dt=1.0e-4)
    assert abs(s.hu[20, 20]) < 1e-12
    assert abs(s.hv[20, 20]) < 1e-12
    # Symmetry of the resulting spread, which a stray momentum term would break.
    h = s.h
    assert h[20, 19] == pytest.approx(h[20, 21], rel=1e-12)
    assert h[19, 20] == pytest.approx(h[21, 20], rel=1e-12)


def test_large_inflow_into_dry_domain_stays_stable():
    """
    A Tehri-scale discharge dumped into a dry 90 m grid. This is the case that
    breaks a naive source term: the domain is dry, so the CFL limiter has no wave
    speed to work with and hands back the cap, and then the source creates a deep
    fast cell inside a step that was never checked for stability.

    `_inflow_dt_limit` exists for exactly this and must keep the run finite.
    """
    ny, nx, dx = 30, 30, 90.0
    s = SWE2D(np.zeros((ny, nx)), dx, manning=0.03,
              bc=("wall", "wall", "wall", "wall"))
    s.add_inflow([(15, 15)], 200_000.0, direction=(1.0, 0.0), speed=25.0)
    s.run(60.0, dt_max=5.0)
    assert np.all(np.isfinite(s.h))
    assert np.all(np.isfinite(s.hu))
    assert np.all(s.h >= 0.0)
    assert s.stats.volume_injected == pytest.approx(200_000.0 * 60.0, rel=1e-12)
    assert abs(s.stats.volume_error) < 1e-6


# =============================================================================
# accumulators
# =============================================================================

def test_lake_at_rest_accumulators():
    """
    Still water on a slope: max depth equals the depth, max speed is zero, and
    every wet cell arrived at t = 0 while every dry cell never arrives.

    The t=0 part is why `track_maxima` seeds itself from the initial condition.
    Without that seed the reservoir behind the dam would report "never flooded",
    which is both wrong and embarrassing on a map.
    """
    ny, nx, dx = 30, 40, 25.0
    z = np.linspace(0.0, 40.0, nx)[None, :] * np.ones((ny, 1))
    s = SWE2D(z, dx, manning=0.03, bc=("wall", "wall", "wall", "wall"))
    s.set_surface(20.0)
    h0 = s.h.copy()

    s.track_maxima(threshold=0.1)
    s.run(30.0, dt_max=1.0)

    assert np.allclose(s.max_depth, h0, atol=1e-9)
    assert np.max(s.max_speed) < 1e-9
    assert np.max(s.max_dv) < 1e-8

    ta = s.arrival_time
    wet = h0 >= 0.1
    assert np.all(ta[wet] == 0.0)
    assert np.all(np.isnan(ta[~wet]))


def test_accumulators_require_track_maxima():
    """Reading an accumulator that was never switched on must fail loudly."""
    s = SWE2D(np.zeros((10, 10)), 10.0)
    for name in ("max_depth", "max_speed", "max_dv", "arrival_time"):
        with pytest.raises(RuntimeError, match="track_maxima"):
            getattr(s, name)


def test_max_depth_is_a_running_maximum():
    """
    A pulse that rises then drains must leave max_depth at the peak, not at the
    final state. If it recorded the final state the flood map would show the
    receded water, which is the map nobody needs.
    """
    ny, nx, dx = 20, 60, 20.0
    s = SWE2D(np.zeros((ny, nx)), dx, manning=0.02,
              bc=("wall", "open", "wall", "wall"))
    s.add_inflow([(10, 3)], lambda t: 3000.0 if t < 20.0 else 0.0)
    s.track_maxima(threshold=0.05)
    s.run(200.0, dt_max=1.0)

    peak = s.max_depth[10, 3]
    assert peak > s.h[10, 3] + 1e-3
    assert np.all(s.max_depth >= s.h - 1e-12)


def test_max_dv_is_not_the_product_of_the_two_maxima():
    """
    depth*velocity must be accumulated in its own right.

    max_depth * max_speed multiplies two peaks that happen at different times —
    the front of a dam-break wave is fast and shallow, the body behind it is deep
    and slow — and the product therefore overstates the hazard. The hazard rating
    that classifies a village as "unsafe for vehicles" depends on this number, so
    the distinction is not academic. Here we require it to be strictly smaller
    somewhere, which is only possible if it was tracked separately.
    """
    ny, nx, dx = 20, 80, 20.0
    z = np.linspace(20.0, 0.0, nx)[None, :] * np.ones((ny, 1))
    s = SWE2D(z, dx, manning=0.03, bc=("wall", "open", "wall", "wall"))
    s.set_surface(20.0, where=np.arange(nx)[None, :] < 15)
    s.track_maxima(threshold=0.05)
    s.run(120.0, dt_max=1.0)

    product = s.max_depth * s.max_speed
    dv = s.max_dv
    # Never larger, by construction.
    assert np.all(dv <= product + 1e-9)
    # And genuinely smaller over a good part of the wetted area, i.e. the two
    # maxima really do occur at different times.
    wet = s.max_depth > 0.1
    assert np.any(dv[wet] < 0.9 * product[wet])


def test_arrival_time_is_monotone_downstream():
    """Water cannot reach a downstream station before an upstream one."""
    ny, nx, dx = 10, 120, 20.0
    z = np.zeros((ny, nx))
    s = SWE2D(z, dx, manning=0.0, bc=("wall", "open", "wall", "wall"))
    s.set_depth(np.where(np.arange(nx)[None, :] < 20, 10.0, 0.0)
                * np.ones((ny, 1)))
    s.track_maxima(threshold=0.1)
    s.run(100.0, dt_max=1.0)

    ta = s.arrival_time[5, 25:110]
    arrived = ~np.isnan(ta)
    seq = ta[arrived]
    assert seq.size > 30
    assert np.all(np.diff(seq) >= -1e-9)


def test_arrival_time_matches_ritter_analytical():
    """
    Arrival time against the closed-form Ritter solution.

    For a dry-bed dam break the depth is h(x,t) = (2*c0 - x/t)^2/(9g), so the
    first time station x exceeds h_thresh is

        t = x / (2*c0 - 3*sqrt(g*h_thresh))

    This is the only place the arrival-time machinery gets checked against
    physics rather than against itself, and it is checked at the threshold the
    product actually reports rather than at the front.
    """
    h0, h_thresh = 10.0, 0.1
    ny, nx, dx = 6, 400, 10.0
    dam = 100

    s = SWE2D(np.zeros((ny, nx)), dx, manning=0.0,
              bc=("open", "open", "wall", "wall"))
    s.set_depth(np.where(np.arange(nx)[None, :] < dam, h0, 0.0)
                * np.ones((ny, 1)))
    s.track_maxima(threshold=h_thresh)
    s.run(120.0, dt_max=2.0)

    c0 = math.sqrt(GRAVITY * h0)
    celerity = 2.0 * c0 - 3.0 * math.sqrt(GRAVITY * h_thresh)

    ta = s.arrival_time[3]
    errs = []
    for i in range(dam + 40, dam + 180, 20):
        x = (i - dam + 0.5) * dx
        expect = x / celerity
        got = ta[i]
        assert not np.isnan(got), f"no arrival recorded at x = {x:.0f} m"
        errs.append(abs(got - expect) / expect)
    # A dry-bed front is the hardest thing a shallow water scheme does, and a
    # first-order-accurate wetting front is characteristically a little late.
    # 10% on arrival time at 90 m resolution is well inside what the DEM itself
    # justifies claiming.
    assert max(errs) < 0.10, f"arrival-time errors {errs}"


def test_arrival_threshold_changes_arrival_time():
    """
    A deeper threshold must give a later arrival, everywhere it arrives at all.

    Trivially true physically, and worth pinning because it proves the threshold
    is actually being used rather than a hardcoded default. Compared cell by cell
    over the stations that both runs wetted — a 1 m threshold legitimately never
    fires far downstream, and requiring it to would be testing the wrong thing.
    """
    ny, nx, dx = 6, 200, 10.0
    dam = 50

    def run(thresh):
        s = SWE2D(np.zeros((ny, nx)), dx, manning=0.0,
                  bc=("open", "open", "wall", "wall"))
        s.set_depth(np.where(np.arange(nx)[None, :] < dam, 8.0, 0.0)
                    * np.ones((ny, 1)))
        s.track_maxima(threshold=thresh)
        s.run(60.0, dt_max=2.0)
        return s.arrival_time[3]

    shallow = run(0.05)
    deep = run(1.0)

    both = ~np.isnan(shallow) & ~np.isnan(deep)
    assert both.sum() > 40, "not enough common stations to compare"
    assert np.all(deep[both] >= shallow[both] - 1e-9)
    # And strictly later somewhere downstream of the dam, where the wave has
    # thinned enough for the two thresholds to separate.
    tail = both.copy()
    tail[:dam + 20] = False
    assert np.any(deep[tail] > shallow[tail] + 1e-6)
    # The deeper threshold must also wet strictly fewer cells.
    assert np.count_nonzero(~np.isnan(deep)) < np.count_nonzero(~np.isnan(shallow))


def test_arrival_time_uses_minus_one_sentinel_internally():
    """
    The internal sentinel must be -1, not NaN.

    This looks like a detail and is actually a total-failure mode: the kernel
    records first arrival with `if t_arrival < 0`, and any comparison against NaN
    is false, so a NaN sentinel means arrival time is never recorded anywhere and
    the map comes out uniformly blank.
    """
    s = SWE2D(np.zeros((10, 10)), 10.0, bc=("wall",) * 4)
    acc = s.track_maxima(threshold=0.1)
    assert np.all(acc.t_arrival == -1.0)
    assert not np.any(np.isnan(acc.t_arrival))
    # The public view converts to NaN for the caller.
    assert np.all(np.isnan(s.arrival_time))


def test_accumulator_cost_does_not_change_the_solution():
    """
    Switching the accumulators on must not perturb the physics. They are
    diagnostics; if they changed the answer they would be a bug.
    """
    def run(track):
        ny, nx, dx = 12, 80, 20.0
        z = np.linspace(10.0, 0.0, nx)[None, :] * np.ones((ny, 1))
        s = SWE2D(z, dx, manning=0.03, bc=("wall", "open", "wall", "wall"))
        s.set_surface(10.0, where=np.arange(nx)[None, :] < 20)
        if track:
            s.track_maxima(threshold=0.1)
        s.run(60.0, dt_max=1.0)
        return s.h.copy()

    a, b = run(False), run(True)
    assert np.array_equal(a, b)


# =============================================================================
# input validation
# =============================================================================

def test_inflow_rejects_out_of_domain_cells():
    s = SWE2D(np.zeros((10, 10)), 10.0)
    with pytest.raises(ValueError, match="outside the interior"):
        s.add_inflow([(10, 5)], 100.0)
    with pytest.raises(ValueError, match="outside the interior"):
        s.add_inflow([(-1, 5)], 100.0)
    with pytest.raises(ValueError, match="outside the interior"):
        s.add_inflow([(5, 10)], 100.0)


def test_inflow_rejects_direction_without_speed():
    """
    A direction with no speed is ambiguous, and the tempting default — speed
    zero — would silently discard the momentum the caller clearly wanted.
    """
    s = SWE2D(np.zeros((10, 10)), 10.0)
    with pytest.raises(ValueError, match="needs a speed"):
        s.add_inflow([(5, 5)], 100.0, direction=(1.0, 0.0))


def test_inflow_rejects_degenerate_inputs():
    s = SWE2D(np.zeros((10, 10)), 10.0)
    with pytest.raises(ValueError):
        s.add_inflow(np.zeros((0, 2), dtype=int), 100.0)
    with pytest.raises(ValueError, match="non-zero vector"):
        s.add_inflow([(5, 5)], 100.0, direction=(0.0, 0.0), speed=1.0)
    with pytest.raises(ValueError, match="one entry per cell"):
        s.add_inflow([(5, 5), (5, 6)], 100.0, weights=[1.0])
    with pytest.raises(ValueError, match="non-negative"):
        s.add_inflow([(5, 5), (5, 6)], 100.0, weights=[1.0, -1.0])
    with pytest.raises(ValueError, match="sum to zero"):
        s.add_inflow([(5, 5), (5, 6)], 100.0, weights=[0.0, 0.0])


def test_track_maxima_rejects_nonpositive_threshold():
    s = SWE2D(np.zeros((10, 10)), 10.0)
    with pytest.raises(ValueError, match="positive"):
        s.track_maxima(threshold=0.0)


def test_single_cell_shorthand():
    """add_inflow((j, i), q) should work without wrapping in a list."""
    s = SWE2D(np.zeros((10, 10)), 10.0, manning=0.0, bc=("wall",) * 4)
    s.add_inflow((5, 5), 100.0)
    s.step(dt=1.0e-3)
    assert s.h[5, 5] > 0.0


def test_volume_error_credits_injected_volume():
    """
    `volume_error` must compare against initial + injected, not initial alone.

    Otherwise every inflow run reports a huge "mass conservation failure" and the
    one diagnostic that would catch a real leak becomes noise that gets ignored.
    """
    s = SWE2D(np.zeros((20, 20)), 20.0, manning=0.0, bc=("wall",) * 4)
    s.set_depth(1.0)
    s.add_inflow([(10, 10)], 400.0)
    s.run(20.0, dt_max=1.0)
    assert s.stats.volume_injected > 0.0
    assert abs(s.stats.volume_error) < MASS_TOL


def test_history_records_inflow_discharge():
    """The logged history carries Q so the hydrograph can be plotted alongside
    the mass balance — the chart that shows the two agree."""
    s = SWE2D(np.zeros((20, 20)), 20.0, manning=0.0, bc=("wall",) * 4)
    s.set_depth(1.0)
    s.add_inflow([(10, 10)], lambda t: 100.0 + 10.0 * t)
    s.run(20.0, dt_max=1.0, log_every=5.0)
    assert len(s.stats.history) >= 4
    assert all(len(row) == 4 for row in s.stats.history)
    q_logged = [row[3] for row in s.stats.history]
    assert q_logged[-1] > q_logged[1] > 0.0

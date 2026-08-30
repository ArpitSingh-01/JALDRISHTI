"""
Boundary conditions — the open/wall ghost-cell treatment.

WHY THIS FILE EXISTS
--------------------
`_extend_static` fills the ghost band for the two time-invariant fields (bed
elevation and Manning n). How it does that at an OPEN boundary is a genuine
trade-off rather than an obvious choice, and the trade-off was discovered the
hard way: a uniform-flow test configuration silently drained and ponded, losing
39% of its water, and the cause was the bed treatment at the boundary rather than
anything in the solver.

The finding, stated plainly: a zero-gradient transmissive boundary CANNOT be
exact for both still water and uniform flow on a slope.

  * Copy the bed FLAT (what we do). The ghost eta is then level with the
    interior, so still water stays still to machine precision. But the bed stops
    sloping, the limiter returns exactly zero slope for the edge cell, that cell
    loses its gravitational forcing, and a backwater forms at the outflow.

  * CONTINUE the bed slope. Uniform flow becomes exact -- and still water on a
    slope spontaneously accelerates to Manning normal velocity, because the ghost
    eta is no longer level. A model that invents a 2 m/s current in a reservoir
    is unusable.

We keep the still-water-exact form. Lake-at-rest holding to machine precision is
the invariant that stops the model inventing floods out of nothing, and it
applies everywhere there is water; the backwater is bounded and confined to a
handful of cells at the outflow, where we simply do not report results.

Every number asserted below was measured, not assumed, and the counterfactual is
tested too -- so the file records not just that the current choice works but why
the alternative is worse. That is the part a jury will ask about.

The consequence for domain design is `OPEN_BC_INFLUENCE_CELLS`: the domain must
extend that many cells past anything we report (900 m at 90 m resolution, 300 m
at 30 m).
"""

import math

import numpy as np
import pytest

from jaldrishti.solver.swe2d import (
    GRAVITY,
    NG,
    OPEN_BC_INFLUENCE_CELLS,
    SWE2D,
)

G = GRAVITY

# One channel geometry used throughout, so the measured numbers in the
# assertions all refer to the same physical setup.
S0 = 0.002          # bed slope, 1 in 500 -- a plausible Himalayan valley floor
N_MAN = 0.033       # gravel/cobble channel
H0 = 2.0            # uniform depth
DX = 100.0
NX, NY = 120, 5

U_NORMAL = H0 ** (2.0 / 3.0) * math.sqrt(S0) / N_MAN     # Manning, ~2.151 m/s
TAU = U_NORMAL / (2.0 * G * S0)                          # relaxation timescale


def sloping_bed(nx=NX, ny=NY):
    """Bed falling uniformly in +x. z decreases as i increases."""
    x = np.arange(nx) * DX
    return np.broadcast_to(-S0 * x, (ny, nx)).copy()


def continue_bed_into_ghosts(s, nx=NX):
    """
    Overwrite the ghost bed so the slope carries on through it, which is the
    alternative treatment this file exists to reject. Done by writing `_z`
    directly because the solver deliberately offers no option to do it.
    """
    xg = (np.arange(nx + 2 * NG) - NG) * DX
    s._z[:, :] = np.broadcast_to(-S0 * xg, s._z.shape)


# ---------------------------------------------------------------------------
# the invariant the flat copy protects
# ---------------------------------------------------------------------------
def test_still_water_on_a_slope_stays_still_at_an_open_boundary():
    """
    Lake-at-rest with all four boundaries OPEN and a sloping bed underneath.

    This is the strictest form of the well-balanced requirement: an open boundary
    gives the water an unobstructed way out, so any imbalance in the ghost band
    shows up immediately as flow through it. `test_lake_at_rest.py` covers this
    across bed shapes and limiters; here it is pinned specifically as the property
    that the flat bed copy exists to deliver.
    """
    s = SWE2D(sloping_bed(), DX, manning=N_MAN, bc=("open",) * 4)
    eta0 = 5.0
    s.set_surface(eta0)
    v0 = s.volume()

    dt = s.compute_dt()
    for _ in range(200):
        s.step(dt=dt)

    wet = s.h > s.h_min
    assert wet.any(), "the test is vacuous if nothing is wet"
    assert float(s.speed[wet].max()) < 1.0e-10, "spurious current in still water"
    assert float(np.max(np.abs((s.h + s.z)[wet] - eta0))) < 1.0e-11
    assert s.volume() == pytest.approx(v0, rel=1e-13)


def test_continuing_the_bed_slope_turns_a_still_lake_into_a_river():
    """
    THE COUNTERFACTUAL, and the reason the flat copy is not a bug.

    Continuing the bed into the ghosts is the "obvious fix" for the outflow
    backwater measured below. It is also catastrophic: with the ghost bed sloping
    but the ghost DEPTH a zero-gradient copy, the ghost water surface is no longer
    level with the interior, so still water accelerates downhill.

    Run to steady state the end state is unambiguous -- the lake does not merely
    develop a current, it becomes a uniform-flow river. Measured (eta0 = 5 m over
    a 1:500 bed, so initial depth 5 -> 26 m):

        steps   t (s)    max|u|    h range        max(u/u_n)   mass drift
          200    238     1.629    5.91 - 26.00      0.294       -2.1%
         1000   1190     6.276    7.64 - 15.33      0.802      -33.3%
         3000   3570     5.301    7.71 -  7.86      0.998      -54.2%
         8000   9519     5.275    7.71 -  7.71      0.998      -54.4%

    Depth becomes uniform at 7.71 m and the speed lands on Manning normal
    velocity for that depth to within 0.2%. Over half the water has left. That is
    precisely the failure the well-balanced property exists to prevent, it happens
    everywhere there is water rather than near one boundary, and no amount of grid
    refinement helps because it is not a discretisation error.

    Asserted against the LOCAL normal velocity rather than a fixed number, because
    a level surface over a sloping bed has a different depth -- and so a different
    terminal velocity -- in every cell. The `u/u_n -> 1` identity is what makes
    "it turned into a river" a measurement rather than a figure of speech.

    If this test ever starts passing quietly it means someone "fixed" the boundary
    treatment and reintroduced a far worse defect.
    """
    s = SWE2D(sloping_bed(), DX, manning=N_MAN, bc=("open",) * 4)
    continue_bed_into_ghosts(s)
    s.set_surface(5.0)
    v0 = s.volume()

    dt = s.compute_dt()
    for _ in range(3000):
        s.step(dt=dt)

    wet = s.h > s.h_min
    assert wet.any(), "the test is vacuous if everything drained"
    speed = s.speed[wet]
    spurious = float(speed.max())
    assert spurious > 1.0, (
        f"expected still water to run away at metres per second with the bed "
        f"continued into the ghosts; got {spurious:.3e} m/s. If this is now "
        f"small, the boundary treatment changed -- re-derive the trade-off "
        f"before trusting it."
    )

    # the identity: terminal speed IS Manning normal velocity for the local depth
    u_normal_local = s.h[wet] ** (2.0 / 3.0) * math.sqrt(S0) / N_MAN
    assert float((speed / u_normal_local).max()) == pytest.approx(1.0, abs=0.05), (
        "at steady state the spurious flow should be uniform flow at Manning "
        "normal velocity -- i.e. the lake has become a river"
    )
    assert float(np.ptp(s.h[wet])) < 0.5, "and its depth should be near-uniform"

    # and it drains, catastrophically
    assert s.volume() / v0 - 1.0 < -0.1, (
        "a still lake with nowhere to go should not lose a tenth of its water"
    )


# ---------------------------------------------------------------------------
# the cost of that choice, measured and bounded
# ---------------------------------------------------------------------------
def _uniform_flow_deviation(continue_bed):
    """
    Run uniform flow down the channel to steady state and return the per-cell
    fractional depth deviation from normal depth along the centre row.

    Started AT the analytical fixed point (normal depth and normal velocity), so
    a correct treatment has nothing to do and any deviation is boundary-induced.
    """
    s = SWE2D(sloping_bed(), DX, manning=N_MAN, bc=("open", "open", "wall", "wall"))
    continue_bed_into_ghosts(s)
    if not continue_bed:
        # put the east ghost band back to what the solver really does, leaving
        # the west continued so the inflow end does not confound the measurement
        s._z[:, -NG:] = s._z[:, -NG - 1:-NG]
    s.set_depth(np.full((NY, NX), H0))
    s.hu[:] = H0 * U_NORMAL
    s.run(8.0 * TAU, dt_max=0.5)
    return s.h[NY // 2] / H0 - 1.0


def test_uniform_flow_is_exact_when_the_bed_slope_continues():
    """
    Establishes that the backwater measured in the next test really is caused by
    the bed treatment and nothing else.

    With the slope carried through every ghost cell, uniform flow holds to
    machine precision -- the boundary does no harm at all. So the deviation seen
    with the flat copy is entirely attributable to the flat copy.
    """
    dev = _uniform_flow_deviation(continue_bed=True)
    assert float(np.abs(dev).max()) < 1.0e-9, (
        "with the slope continued, uniform flow should be exact"
    )


def test_the_outflow_backwater_is_confined_to_the_documented_width():
    """
    Quantify the cost of the still-water-exact choice.

    The last interior cell loses its bed-slope forcing (the limiter sees
    opposite-signed differences across a bed that stops sloping, and returns
    exactly zero), so water backs up at the outflow. Measured profile, depth
    above normal:

        edge +36.9% | -1 +29.9% | -2 +22.3% | -3 +15.7%
        -4 +10.2%   | -6  +3.1% | -8  +0.5% | -12 and beyond ~0

    The assertions below pin three things: the artefact is real and substantial at
    the edge, it decays monotonically inward, and it has died away well before
    OPEN_BC_INFLUENCE_CELLS. The last is what licenses the reporting mask.
    """
    dev = _uniform_flow_deviation(continue_bed=False)

    # real and substantial at the boundary
    assert dev[-1] > 0.2, "the outflow backwater should be clearly visible"
    # it is a backwater (deeper), not a drawdown
    assert dev[-1] > dev[-2] > dev[-3] > dev[-4], "must decay monotonically inward"

    # and it is gone by the documented mask width
    interior = dev[:NX - OPEN_BC_INFLUENCE_CELLS]
    assert float(np.abs(interior).max()) < 0.01, (
        f"deviation must be under 1% more than {OPEN_BC_INFLUENCE_CELLS} cells "
        f"from the open boundary; worst was "
        f"{float(np.abs(interior).max()):.4%}"
    )


def test_the_reporting_mask_covers_the_measured_artefact():
    """
    OPEN_BC_INFLUENCE_CELLS is a documented constant, so tie it to a measurement
    rather than letting it drift into folklore. The artefact must be contained
    with room to spare, and the constant must not be so large that it would mask
    a useful fraction of a real domain.
    """
    dev = _uniform_flow_deviation(continue_bed=False)
    beyond_1pct = np.where(np.abs(dev) > 0.01)[0]
    assert beyond_1pct.size, "test is vacuous if there is no artefact at all"
    extent = NX - 1 - int(beyond_1pct.min())
    assert extent <= OPEN_BC_INFLUENCE_CELLS, (
        f"artefact reaches {extent} cells inward but the mask is only "
        f"{OPEN_BC_INFLUENCE_CELLS}"
    )
    assert OPEN_BC_INFLUENCE_CELLS <= 20, "mask is too coarse to be useful"


# ---------------------------------------------------------------------------
# the other half of _extend_static: walls
# ---------------------------------------------------------------------------
def test_a_wall_mirrors_the_bed_so_nothing_leaks_through_it():
    """
    At a wall the bed must be MIRRORED, not copied. `_fill_ghosts` mirrors depth
    and negates the normal momentum; the reflection is only exact if eta in the
    ghosts is the mirror image of eta inside, which needs the bed mirrored the
    same way. Otherwise the reconstructed slopes are not antisymmetric and a
    small flux crosses what is meant to be solid ground.

    Tested on an asymmetric bed with water sloshing against the wall, because a
    symmetric bed would satisfy mirror and copy identically and prove nothing.
    """
    z = sloping_bed()
    s = SWE2D(z, DX, manning=0.0, bc=("wall", "wall", "wall", "wall"))
    # a mound of water against the west wall, free to slosh
    h = np.zeros((NY, NX))
    h[:, :30] = 6.0
    s.set_depth(h)
    v0 = s.volume()
    s.run(400.0)
    assert s.volume() == pytest.approx(v0, rel=1e-12), (
        "a fully walled domain must conserve mass exactly -- any drift is a leak "
        "through a wall, which means the bed is not mirrored correctly"
    )


def test_the_bed_ghosts_mirror_at_a_wall_and_flatten_at_an_opening():
    """
    Inspect the ghost band directly, rather than inferring it from behaviour.
    This is the clearest statement of what `_extend_static` actually does, and it
    is what makes the two tests above interpretable.
    """
    z = sloping_bed()
    s = SWE2D(z, DX, manning=N_MAN, bc=("wall", "open", "wall", "wall"))
    row = s._z[NY // 2 + NG]

    # west is a wall: ghosts mirror the first interior cells
    assert row[NG - 1] == pytest.approx(row[NG])
    assert row[NG - 2] == pytest.approx(row[NG + 1])

    # east is open: ghosts flat-copy the last interior cell
    assert row[-NG] == pytest.approx(row[-NG - 1])
    assert row[-1] == pytest.approx(row[-NG - 1])


def test_manning_n_is_copied_not_extrapolated_at_an_open_boundary():
    """
    `_extend_static` handles the bed and Manning n with the same code path, which
    is correct: a plain copy is right for n regardless of boundary type. Pinning
    it because extrapolating a roughness field could produce a NEGATIVE n, and a
    negative n silently reverses the friction term into an accelerator.
    """
    z = sloping_bed()
    n = np.linspace(0.02, 0.09, NX)[None, :] * np.ones((NY, 1))
    s = SWE2D(z, DX, manning=n, bc=("open", "open", "open", "open"))
    assert float(s._n.min()) > 0.0, "no ghost may hold a non-positive Manning n"
    row = s._n[NY // 2 + NG]
    assert row[NG - 1] == pytest.approx(row[NG])
    assert row[-NG] == pytest.approx(row[-NG - 1])

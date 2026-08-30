"""
Rung 3b of the validation ladder: directional symmetry and isotropy.

WHY THIS FILE EXISTS
--------------------
Every other test in this directory drives water along +x on a grid where `dy` is
left to default to `dx`. That leaves three things completely unexercised, and
each is a plausible one-character bug that the entire existing suite would pass:

  1. THE Y SWEEP. `_rhs` hand-writes the y direction as a near-copy of the x
     direction, with u and v swapped going into the Riemann solver and the
     returned momentum fluxes swapped back on the way out. A transposed index or
     one unswapped component there is invisible to a test that never puts water
     in motion along y.

  2. dy ITSELF. Because no test has ever passed dy != dx, every `/dx` that
     should read `/dy` currently cancels out silently. Both production domains
     use square cells, so this would stay hidden indefinitely — which is worse
     than failing, because someone would read the code and trust it.

  3. THE TRANSVERSE MOMENTUM FLUX Fhv. This is the contact wave, and it is the
     entire reason flux.py implements HLLC instead of HLL. A one-dimensional
     problem carries no transverse momentum at all, so the one feature we pay
     extra for is the one feature never tested.

WHY SYMMETRY, RATHER THAN MORE ANALYTICAL SOLUTIONS
---------------------------------------------------
These are symmetry tests, and that is a deliberate choice: they need no exact
solution and no reference data, so they are EXACT rather than approximate.

The shallow water equations are rotationally invariant, and this discretisation
is unsplit — the x and y sweeps both read the same input state and their
contributions are summed, rather than being applied one after the other. That
makes the 90-degree rotations and the reflections of the grid exact symmetries
of the scheme, not approximate ones. So "the +y answer equals the +x answer
transposed" is an identity that must hold to floating-point round-off. There is
no physical tolerance to negotiate, and no discretisation error to excuse a
mismatch.

That is what makes these tests sharp. A Ritter error of 3% could be the limiter,
the grid, the thin film at the front, or a bug — you cannot tell. A broken
symmetry is unambiguously a bug, and it names the direction it lives in.

(Had the scheme used a Strang or alternating-direction split, exact 4-fold
symmetry would NOT hold and these tolerances would be wrong. If someone later
switches the time integration to a directional split, these tests are expected
to fail and the tolerances must be revisited rather than relaxed.)
"""

from __future__ import annotations

import numpy as np
import pytest

from jaldrishti.solver.swe2d import GRAVITY, SWE2D

# Symmetry is exact arithmetic, so the tolerance only has to absorb round-off in
# the accumulated flux sums, not any modelling error. Depths here are O(1-10 m),
# so 1e-12 m is roughly a thousand epsilons of headroom: tight enough that any
# real directional bug fails by many orders of magnitude, loose enough that the
# test is not brittle. If one of these fails at 1e-11 you have a bug, not noise.
SYM_ATOL = 1.0e-12


# =============================================================================
# helpers
# =============================================================================

def _riemann_1d_x(nx=120, ny=6, dx=2.0, dy=None, h_left=6.0, h_right=0.0,
                  bed_slope=0.0, limiter="mc"):
    """
    A dam break running along +x, uniform in y. The classic Ritter/Stoker setup.

    `bed_slope` tilts the bed in x only, so s_z_y stays identically zero and the
    problem stays genuinely one-dimensional however the grid is shaped.
    """
    x = (np.arange(nx) + 0.5) * dx
    z = np.broadcast_to(bed_slope * x, (ny, nx)).copy()

    s = SWE2D(z, dx, dy, manning=0.0, limiter=limiter,
              bc=("wall", "open", "wall", "wall"))
    h = np.where(x < 0.5 * nx * dx, h_left, h_right)
    s.set_depth(np.broadcast_to(h, (ny, nx)).copy())
    return s


def _transpose_of(builder_kwargs):
    """
    The same physical problem rotated 90 degrees, so x-quantities become
    y-quantities.

    Everything must be transposed together and consistently: the bed, the
    initial depth, the cell size, and the boundary conditions. `bc` is ordered
    (west, east, south, north); under x<->y, west<->south and east<->north, so
    the tuple is reordered rather than reversed. Getting that reordering wrong
    would make the test fail for a reason that has nothing to do with the
    solver, which is exactly the sort of self-inflicted false positive that
    makes people delete symmetry tests.
    """
    nx = builder_kwargs["nx"]
    ny = builder_kwargs["ny"]
    dx = builder_kwargs["dx"]
    dy = builder_kwargs.get("dy") or dx
    slope = builder_kwargs.get("bed_slope", 0.0)
    h_left = builder_kwargs.get("h_left", 6.0)
    h_right = builder_kwargs.get("h_right", 0.0)
    limiter = builder_kwargs.get("limiter", "mc")

    y = (np.arange(nx) + 0.5) * dx            # the "long" axis, now vertical
    z = np.broadcast_to((slope * y)[:, None], (nx, ny)).copy()

    s = SWE2D(z, dy, dx, manning=0.0, limiter=limiter,
              bc=("wall", "wall", "wall", "open"))
    h = np.where(y < 0.5 * nx * dx, h_left, h_right)
    s.set_depth(np.broadcast_to(h[:, None], (nx, ny)).copy())
    return s


def _radial_dam_break(n=101, dx=1.0, dy=None, h_in=2.0, h_out=0.1, radius=12.0,
                      limiter="mc"):
    """
    A cylindrical column of water collapsing on a flat bed — the standard
    circular dam break.

    This is the test that actually exercises the contact wave. At any face that
    is not aligned with the flow (i.e. almost every face, once the wave is
    circular) there is genuine transverse momentum for HLLC's Fhv to transport,
    which no 1D problem provides.

    `n` is odd on purpose so there is a true centre CELL rather than a centre
    face. With an even count the initial condition cannot be made exactly
    symmetric, and the test would measure that asymmetry instead of the
    solver's.
    """
    c = (n - 1) // 2
    i = np.arange(n) - c
    # Build the radius from an outer product of the SAME 1-D index array, so the
    # radius field is bit-for-bit symmetric under both reflections and the
    # transpose. Constructing it from two separate linspaces invites an
    # asymmetry of one ulp, which then shows up as a "solver bug".
    r = np.sqrt((i[:, None] ** 2 + i[None, :] ** 2).astype(np.float64)) * dx

    z = np.zeros((n, n))
    s = SWE2D(z, dx, dy, manning=0.0, limiter=limiter,
              bc=("wall", "wall", "wall", "wall"))
    s.set_depth(np.where(r <= radius, h_in, h_out))
    return s, c


def _fixed_dt_march(s, dt, nsteps):
    """
    March with an externally imposed dt.

    Needed because the CFL condition is the correct 2D form,
    dt <= cfl/((|u|+c)/dx + (|v|+c)/dy), which depends on dy even for a purely
    one-dimensional flow. So changing dy legitimately changes the timestep, and
    a test of "does dy leak into the x update" has to hold dt fixed or it would
    just be measuring that dependence.
    """
    for _ in range(nsteps):
        s.step(dt=dt)
    return s


def _report(label, a, b):
    """Max absolute difference, with a message that says which field and where."""
    d = np.abs(a - b)
    k = int(np.argmax(d))
    where = np.unravel_index(k, d.shape)
    return f"{label}: max|diff| = {d.max():.3e} at {where}"


# =============================================================================
# 1. dy must not leak into a purely x-directional problem
# =============================================================================

@pytest.mark.parametrize("dy_factor", [1.0, 3.0, 0.25])
def test_x_flow_is_independent_of_dy(dy_factor):
    """
    A flow that is uniform in y must not care what dy is.

    This is the most direct possible test for a misplaced `/dx`. Nothing varies
    along y, so every y-face flux and the entire y bed source are identically
    zero; dy therefore cannot appear in the answer through any legitimate route.
    If it does appear, some term is being divided by the wrong cell size.

    dt is imposed rather than computed, because the 2D CFL condition contains dy
    legitimately (see _fixed_dt_march).
    """
    kw = dict(nx=100, ny=6, dx=2.0, h_left=6.0, h_right=0.0)
    dt = 0.02                                  # comfortably inside CFL for all cases

    ref = _fixed_dt_march(_riemann_1d_x(**kw), dt, 200)
    alt = _fixed_dt_march(_riemann_1d_x(**kw, dy=2.0 * dy_factor), dt, 200)

    assert np.allclose(ref.h, alt.h, atol=SYM_ATOL, rtol=0.0), \
        _report(f"depth changed when dy scaled by {dy_factor}", ref.h, alt.h)
    assert np.allclose(ref.hu, alt.hu, atol=SYM_ATOL, rtol=0.0), \
        _report(f"x-momentum changed when dy scaled by {dy_factor}", ref.hu, alt.hu)
    # hv must be zero, not merely unchanged: a y-uniform problem may never
    # develop transverse momentum. This catches a sign or index slip in the
    # y sweep that happens to be antisymmetric and so cancels in the depth.
    assert np.max(np.abs(alt.hv)) < SYM_ATOL, \
        f"spurious y-momentum {np.max(np.abs(alt.hv)):.3e} in a y-uniform flow"


# =============================================================================
# 2. the y sweep must reproduce the x sweep exactly
# =============================================================================

@pytest.mark.parametrize("limiter", ["none", "minmod", "mc"])
def test_y_sweep_matches_x_sweep(limiter):
    """
    Rotate the problem 90 degrees; the answer must rotate with it.

    Depth maps to its transpose, and the momentum components must EXCHANGE:
    hv from the rotated run equals hu from the original, transposed. Checking
    the depth alone is not enough — depth is a scalar and would survive a
    u/v mix-up in the y sweep. The momentum exchange is the part that pins down
    the swap of the returned HLLC momentum fluxes.
    """
    kw = dict(nx=90, ny=6, dx=2.0, h_left=5.0, h_right=0.0, limiter=limiter)
    t_end = 6.0

    sx = _riemann_1d_x(**kw)
    sx.run(t_end)
    sy = _transpose_of(kw)
    sy.run(t_end)

    # The CFL sum (|u|+c)/dx + (|v|+c)/dy is the same two addends in the
    # opposite order in the rotated run, and IEEE addition is commutative, so
    # the two runs should take an identical sequence of timesteps. If they do
    # not, the comparison below is meaningless, so assert it first and get a
    # clear failure instead of a confusing one.
    assert sx.stats.steps == sy.stats.steps, (
        f"rotated run took {sy.stats.steps} steps vs {sx.stats.steps}; "
        f"the timestep sequences diverged, so the fields are not comparable")
    assert sx.t == pytest.approx(sy.t, abs=1e-15)

    assert np.allclose(sx.h, sy.h.T, atol=SYM_ATOL, rtol=0.0), \
        _report("depth: x-run vs transposed y-run", sx.h, sy.h.T)
    assert np.allclose(sx.hu, sy.hv.T, atol=SYM_ATOL, rtol=0.0), \
        _report("hu(x-run) vs hv(y-run).T", sx.hu, sy.hv.T)
    assert np.max(np.abs(sx.hv)) < SYM_ATOL, "x-run grew transverse momentum"
    assert np.max(np.abs(sy.hu)) < SYM_ATOL, "y-run grew transverse momentum"


def test_y_sweep_matches_x_sweep_on_anisotropic_cells():
    """
    The same rotation test, but with dx != dy — so the two runs swap their cell
    dimensions as well as their axes.

    This is the case that catches a `/dx` where `/dy` belongs. With square cells
    such a bug is invisible; here the two lengths differ by a factor of 4, so a
    single misplaced divisor moves the answer by a factor of 4, not by round-off.
    """
    kw = dict(nx=90, ny=6, dx=2.0, dy=8.0, h_left=5.0, h_right=0.0)
    t_end = 6.0

    sx = _riemann_1d_x(**kw)
    sx.run(t_end)
    sy = _transpose_of(kw)                     # builds with dx and dy exchanged
    sy.run(t_end)

    assert (sx.dx, sx.dy) == (sy.dy, sy.dx), "test set up the cell sizes wrongly"
    assert sx.stats.steps == sy.stats.steps, (
        f"rotated run took {sy.stats.steps} steps vs {sx.stats.steps}")

    assert np.allclose(sx.h, sy.h.T, atol=SYM_ATOL, rtol=0.0), \
        _report("depth on anisotropic cells", sx.h, sy.h.T)
    assert np.allclose(sx.hu, sy.hv.T, atol=SYM_ATOL, rtol=0.0), \
        _report("momentum on anisotropic cells", sx.hu, sy.hv.T)


# =============================================================================
# 3. reflection symmetry
# =============================================================================

@pytest.mark.parametrize("axis", ["x", "y"])
def test_reflection_symmetry(axis):
    """
    Mirror the initial condition and the answer must mirror too, with the
    normal momentum changing sign.

    Catches a sign error or an off-by-one in the flux difference — a bug that
    biases the solution in one direction along an axis. Ritter would not
    necessarily catch it, because Ritter only ever looks downstream.
    """
    n, dx, h_in, h_out = 81, 1.0, 3.0, 0.2
    c = (n - 1) // 2
    i = np.arange(n) - c

    z = np.zeros((n, n))
    band = np.abs(i) <= 8

    if axis == "x":
        h0 = np.broadcast_to(np.where(band, h_in, h_out), (n, n)).copy()
        flip = lambda a: a[:, ::-1]            # noqa: E731
        normal = "hu"
    else:
        h0 = np.broadcast_to(np.where(band, h_in, h_out)[:, None], (n, n)).copy()
        flip = lambda a: a[::-1, :]            # noqa: E731
        normal = "hv"

    s = SWE2D(z, dx, manning=0.0, bc=("wall",) * 4)
    s.set_depth(h0)
    s.run(4.0)

    assert np.allclose(s.h, flip(s.h), atol=SYM_ATOL, rtol=0.0), \
        _report(f"depth not symmetric under {axis} reflection", s.h, flip(s.h))

    q = getattr(s, normal)
    assert np.allclose(q, -flip(q), atol=SYM_ATOL, rtol=0.0), \
        _report(f"{normal} not antisymmetric under {axis} reflection", q, -flip(q))


# =============================================================================
# 4. the radial dam break — the real test of the transverse flux
# =============================================================================

def test_radial_dam_break_is_four_fold_symmetric():
    """
    A collapsing circular column must stay circular, exactly.

    An initially axisymmetric state on a square grid cannot stay perfectly
    ROUND — the grid is anisotropic along the diagonal, and that discretisation
    error is real and expected. But it must stay symmetric under the eight
    operations that map the grid onto itself: the two reflections, the
    transpose, and the resulting 90-degree rotations.

    Three separate things are checked because they fail for different reasons:
      * transpose invariance     -> the x and y sweeps are inconsistent
      * reflection invariance    -> a sign or index slip along one axis
      * the four axial profiles  -> any of the above, localised to a direction

    This is also the only test in the suite where Fhv is doing real work, so if
    the contact-wave upwinding in flux.py is wrong, this is where it shows.
    """
    s, c = _radial_dam_break(n=101, dx=1.0, h_in=2.0, h_out=0.1, radius=12.0)
    s.run(6.0)

    h = s.h
    u, v = s.u, s.v

    # -- transpose: x and y sweeps must agree on a genuinely 2D flow ----------
    assert np.allclose(h, h.T, atol=SYM_ATOL, rtol=0.0), \
        _report("depth not transpose-invariant", h, h.T)
    # Under transpose the velocity components exchange as well.
    assert np.allclose(u, v.T, atol=SYM_ATOL, rtol=0.0), \
        _report("u vs v.T", u, v.T)

    # -- reflections ---------------------------------------------------------
    assert np.allclose(h, h[:, ::-1], atol=SYM_ATOL, rtol=0.0), \
        _report("depth not symmetric in x", h, h[:, ::-1])
    assert np.allclose(h, h[::-1, :], atol=SYM_ATOL, rtol=0.0), \
        _report("depth not symmetric in y", h, h[::-1, :])

    # -- the four axial rays must be one profile -----------------------------
    east = h[c, c:]
    west = h[c, :c + 1][::-1]
    north = h[c:, c]
    south = h[:c + 1, c][::-1]
    for name, ray in (("west", west), ("north", north), ("south", south)):
        assert np.allclose(east, ray, atol=SYM_ATOL, rtol=0.0), \
            _report(f"east ray vs {name} ray", east, ray)

    # -- and the flow must actually have gone somewhere ----------------------
    # Without this a solver that did nothing at all would pass every assertion
    # above. Symmetry tests are vulnerable to exactly that failure mode.
    assert h[c, c] < 1.9, "column never collapsed; test proves nothing"
    assert np.max(np.abs(u)) > 0.5, "no radial flow developed"


def test_radial_dam_break_conserves_mass():
    """
    Mass conservation on a genuinely 2D flow with closed walls.

    The 1D tests conserve mass through the x sweep only. With walls on all four
    sides and no outflow, the total volume here must be constant to round-off,
    which additionally proves the y-direction wall is watertight — a leaky wall
    ghost cell would show up here and nowhere else.
    """
    s, _ = _radial_dam_break(n=81, dx=1.0, h_in=2.0, h_out=0.1, radius=10.0)
    v0 = s.volume()
    s.run(5.0)
    v1 = s.volume()

    rel = abs(v1 - v0) / v0
    assert rel < 1e-12, f"mass drift {rel:.3e} (clipped {s.stats.mass_clipped:.3e} m3)"


# =============================================================================
# 5. well-balancedness with dy in play
# =============================================================================

@pytest.mark.parametrize("dy", [5.0, 20.0])
def test_lake_at_rest_on_a_bed_sloping_in_both_directions(dy):
    """
    Still water on a doubly-tilted bed, on non-square cells, must stay still.

    The existing lake-at-rest test uses square cells, so the y bed source term
    `g*h*s_z_y/dy` has never been checked against a dy that differs from dx. If
    that divisor were dx, the y momentum source would be wrong by dy/dx and
    still water on a slope would start to move — the exact failure mode the
    project rules call out as "the model invents a flood out of nothing".

    The bed slopes in BOTH directions so neither source term can hide behind a
    zero.
    """
    ny, nx, dx = 40, 50, 5.0
    xs = (np.arange(nx) + 0.5) * dx
    ys = (np.arange(ny) + 0.5) * dy
    # A tilted plane plus a bump, so the slope is neither zero nor constant.
    z = (-0.02 * xs[None, :] - 0.05 * ys[:, None]
         + 0.8 * np.exp(-((xs[None, :] - 120.0) ** 2
                          + (ys[:, None] - 100.0) ** 2) / 2000.0))

    level = z.max() + 3.0
    s = SWE2D(z, dx, dy, manning=0.03, bc=("wall",) * 4)
    s.set_surface(level)

    v0 = s.volume()
    s.run(60.0)

    # Velocity is the sharp diagnostic: a well-balanced scheme keeps it at
    # round-off, a merely "close" one leaks millimetres per second which then
    # advect the surface over a long run.
    assert np.max(np.abs(s.u)) < 1e-12, \
        f"spurious u = {np.max(np.abs(s.u)):.3e} m/s at rest (dy={dy})"
    assert np.max(np.abs(s.v)) < 1e-12, \
        f"spurious v = {np.max(np.abs(s.v)):.3e} m/s at rest (dy={dy})"

    eta = s.h + s.z
    assert np.max(np.abs(eta[s.wet] - level)) < 1e-12, "surface drifted off level"
    assert abs(s.volume() - v0) / v0 < 1e-14, "mass drifted at rest"


# =============================================================================
# chart
# =============================================================================

def test_symmetry_chart(chart_dir):
    """
    Four panels for the deck. This one is worth showing to a jury because it is
    the only chart in the set whose correct answer is exact: the four profiles
    must lie on top of one another, and any visible spread is a bug.
    """
    import matplotlib.pyplot as plt

    s, c = _radial_dam_break(n=101, dx=1.0, h_in=2.0, h_out=0.1, radius=12.0)

    times, asym = [], []

    def probe(sol):
        times.append(sol.t)
        # One scalar that captures every symmetry at once: the worst violation
        # over the transpose and both reflections.
        hh = sol.h
        asym.append(max(np.max(np.abs(hh - hh.T)),
                        np.max(np.abs(hh - hh[:, ::-1])),
                        np.max(np.abs(hh - hh[::-1, :]))))

    probe(s)
    s.run(6.0, callback=probe, callback_every=0.25)

    fig, ax = plt.subplots(2, 2, figsize=(12, 9))

    # -- depth field ---------------------------------------------------------
    im = ax[0, 0].imshow(s.h, origin="lower", cmap="Blues")
    ax[0, 0].contour(s.h, levels=8, colors="k", linewidths=0.4)
    ax[0, 0].set_title(f"Radial dam break, t = {s.t:.1f} s\n"
                       "depth (m), contours every ~0.2 m")
    fig.colorbar(im, ax=ax[0, 0], fraction=0.046)

    # -- the four rays -------------------------------------------------------
    r = np.arange(c + 1) * s.dx
    ax[0, 1].plot(r, s.h[c, c:], lw=3.0, alpha=0.35, label="east (+x)")
    ax[0, 1].plot(r, s.h[c, :c + 1][::-1], lw=1.5, ls="--", label="west (-x)")
    ax[0, 1].plot(r, s.h[c:, c], lw=1.5, ls=":", label="north (+y)")
    ax[0, 1].plot(r, s.h[:c + 1, c][::-1], lw=1.5, ls="-.", label="south (-y)")
    ax[0, 1].set_xlabel("radius (m)")
    ax[0, 1].set_ylabel("depth (m)")
    ax[0, 1].set_title("Four axial profiles\n(must be indistinguishable)")
    ax[0, 1].legend()
    ax[0, 1].grid(alpha=0.3)

    # -- symmetry error vs time ---------------------------------------------
    ax[1, 0].semilogy(times, np.maximum(asym, 1e-18), lw=1.5)
    ax[1, 0].axhline(SYM_ATOL, color="r", ls="--", lw=1.0,
                     label=f"test tolerance {SYM_ATOL:.0e}")
    ax[1, 0].set_xlabel("time (s)")
    ax[1, 0].set_ylabel("max symmetry violation (m)")
    ax[1, 0].set_title("Symmetry error stays at round-off\n"
                       "(transpose and both reflections)")
    ax[1, 0].legend()
    ax[1, 0].grid(alpha=0.3, which="both")

    # -- rotation equivalence on anisotropic cells --------------------------
    kw = dict(nx=90, ny=6, dx=2.0, dy=8.0, h_left=5.0, h_right=0.0)
    sx = _riemann_1d_x(**kw)
    sx.run(6.0)
    sy = _transpose_of(kw)
    sy.run(6.0)
    xs = (np.arange(kw["nx"]) + 0.5) * kw["dx"]
    ax[1, 1].plot(xs, sx.h[kw["ny"] // 2, :], lw=3.0, alpha=0.35,
                  label="x sweep, dx=2 dy=8")
    ax[1, 1].plot(xs, sy.h[:, kw["ny"] // 2], lw=1.5, ls="--",
                  label="y sweep, dx=8 dy=2")
    ax[1, 1].set_xlabel("distance along flow (m)")
    ax[1, 1].set_ylabel("depth (m)")
    ax[1, 1].set_title("Rotation equivalence on non-square cells\n"
                       "(catches a misplaced dx/dy divisor)")
    ax[1, 1].legend()
    ax[1, 1].grid(alpha=0.3)

    fig.suptitle("Validation rung 3b: directional symmetry and isotropy",
                 fontsize=13)
    fig.tight_layout()
    out = chart_dir / "symmetry.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)

    assert out.exists()
    assert max(asym) < SYM_ATOL, f"chart run broke symmetry at {max(asym):.3e}"

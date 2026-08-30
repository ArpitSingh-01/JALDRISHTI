"""
Flow routing on surfaces whose answer is known by construction.

WHY THIS FILE EXISTS
--------------------
Routing has no analytical benchmark the way the solver has Ritter and Stoker, and
it fails silently. A D8 grid with a diagonal bias still produces a connected
drainage network, a plausible-looking accumulation raster and a river that
generally goes downhill — it just puts the channel in the wrong place. Every
number the project reports downstream of that (where the hydrograph is injected,
which towns lie on the flood path, what distance arrival time is plotted against)
is then wrong, and nothing about the output looks wrong.

So the tests here use synthetic surfaces where the correct answer is forced by
geometry: a pure east-facing plane can only drain east, a V-valley's HAND is the
height above its own thalweg, and total accumulation over the outlets must equal
the cell count because every cell drains itself exactly once.

Three of these target specific, named failure modes rather than general
correctness:

  * `test_d8_prefers_cardinal_when_the_diagonal_drop_is_larger` is the
    centre-to-centre distance bug. If the slope is computed as a bare elevation
    difference, diagonals win whenever the drop is larger in absolute terms, and
    channels zig-zag across the valley instead of following it.
  * `test_accumulation_sums_to_cell_count_over_outlets` is the routing-integrity
    check. It is the same argument as the solver's mass balance: a cell counted
    twice or dropped shows up as a total that is not N.
  * `test_snap_prefers_the_trunk_over_a_nearer_tributary` is the wrong-valley
    bug. It is the one that would put a dam-break flood on the wrong side of a
    ridge, and the whole reason snapping maximises area instead of minimising
    distance.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from rasterio.transform import from_origin

from jaldrishti.terrain.dem import TerrainGrid
from jaldrishti.terrain.hydrology import (
    FILL_EPS,
    _d8,
    _priority_flood,
    analyse_flow,
)

DX = 90.0


def make_grid(z: np.ndarray, dx: float = DX) -> TerrainGrid:
    """A minimal TerrainGrid around a synthetic elevation array."""
    ny, nx = z.shape
    return TerrainGrid(
        z=np.ascontiguousarray(z, dtype=np.float64),
        dx=dx,
        crs="EPSG:32644",
        transform=from_origin(0.0, ny * dx, dx, dx),
        source="synthetic",
    )


def east_slope(ny: int = 20, nx: int = 30, drop: float = 1.0) -> np.ndarray:
    """A plane falling towards +i (east). Every cell must drain due east."""
    return np.tile(np.arange(nx, dtype=np.float64)[::-1] * drop, (ny, 1))


def v_valley(ny: int = 40, nx: int = 31, *, side: float = 5.0,
             fall: float = 2.0) -> np.ndarray:
    """
    A straight V-shaped valley running south, thalweg down the middle column.

    Elevation is `fall` per row of downstream distance plus `side` per column of
    lateral offset, so HAND at column offset k is exactly `side * k` — an
    analytical target for the HAND pass.
    """
    j = np.arange(ny, dtype=np.float64)[:, None]
    i = np.arange(nx, dtype=np.float64)[None, :]
    centre = (nx - 1) // 2
    return 1000.0 - fall * j + side * np.abs(i - centre)


# =============================================================================
# priority-flood
# =============================================================================

def test_fill_never_lowers_the_surface():
    """
    A fill that goes downwards would invent drainage that does not exist.

    Checked as a strict inequality on the whole array rather than on the mean,
    because a single lowered cell is enough to create a spurious outlet.
    """
    z = east_slope()
    z[10, 15] = -50.0                        # a pit
    zr = z.ravel().copy()
    _priority_flood(zr, *z.shape, FILL_EPS)
    assert np.all(zr >= z.ravel() - 1e-12)


def test_fill_leaves_every_interior_cell_with_a_lower_neighbour():
    """
    This is D8's precondition, and the entire reason the fill exists.

    One interior cell without a strictly lower 8-neighbour means D8 has nowhere
    to send that cell's water, accumulation stalls there, and HAND upslope of it
    references the wrong cell.
    """
    rng = np.random.default_rng(0)
    z = east_slope(ny=25, nx=25, drop=0.5)
    # Punch in enough pits and flats that an unfilled surface would certainly
    # fail: 60 random depressions plus a large flat plateau.
    for _ in range(60):
        j, i = rng.integers(1, 24), rng.integers(1, 24)
        z[j, i] -= rng.uniform(1.0, 20.0)
    z[8:14, 8:14] = 7.0                      # a flat, which is the harder case

    ny, nx = z.shape
    zr = z.ravel().copy()
    _priority_flood(zr, ny, nx, FILL_EPS)
    zr2 = zr.reshape(ny, nx)

    bad = []
    for j in range(1, ny - 1):
        for i in range(1, nx - 1):
            nb = zr2[j - 1:j + 2, i - 1:i + 2]
            if not (nb < zr2[j, i]).any():
                bad.append((j, i))
    assert not bad, f"{len(bad)} interior cells have no lower neighbour: {bad[:5]}"


def test_fill_barely_touches_an_already_draining_surface():
    """
    On a monotone slope the fill should be a no-op to within the epsilon.

    If it raises cells here it is over-filling, which would flatten real
    topography in the routing scaffold and blur the channel.
    """
    z = east_slope(ny=15, nx=20, drop=2.0)
    zr = z.ravel().copy()
    _priority_flood(zr, *z.shape, FILL_EPS)
    assert np.abs(zr - z.ravel()).max() <= 10.0 * FILL_EPS


def test_fill_raises_a_pit_to_its_rim():
    """A pit must come out at (or just above) the lowest point of its rim."""
    z = np.full((15, 15), 100.0)
    z += east_slope(15, 15, drop=0.01)       # a whisper of slope for an outlet
    z[7, 7] = 60.0                           # 40 m deep pit
    rim = min(z[6, 7], z[8, 7], z[7, 6], z[7, 8],
              z[6, 6], z[6, 8], z[8, 6], z[8, 8])
    zr = z.ravel().copy()
    _priority_flood(zr, *z.shape, FILL_EPS)
    filled = zr.reshape(z.shape)[7, 7]
    assert filled == pytest.approx(rim, abs=1e-3), (
        f"pit filled to {filled}, rim is {rim}")


# =============================================================================
# D8
# =============================================================================

def test_d8_on_an_east_facing_plane_points_due_east():
    """
    The diagonal-bias smoke test.

    On a plane falling east, the cardinal drop is `drop` over dx and the diagonal
    drop is also `drop` but over dx*sqrt(2) — so east wins on slope. Any
    implementation comparing raw elevation differences ties here and picks
    whichever direction it happens to test first.
    """
    z = east_slope(ny=12, nx=12, drop=1.0)
    down, code = _d8(z.ravel().copy(), *z.shape, DX, DX)
    code2 = code.reshape(z.shape)
    interior = code2[1:-1, 1:-1]
    assert np.all(interior == 1), (
        f"expected ESRI code 1 (east) everywhere, got "
        f"{np.unique(interior).tolist()}")


def test_d8_prefers_cardinal_when_the_diagonal_drop_is_larger():
    """
    THE distance-normalisation test, with the numbers chosen to make it bite.

    Cell (1,1) is offered an east neighbour 10 m lower and a south-east
    neighbour 13 m lower. Raw difference says south-east (13 > 10). Slope says
    east, because 13 / (90*sqrt(2)) = 0.102 while 10 / 90 = 0.111.

    A solver fed the diagonal answer produces a channel that zig-zags, and the
    along-channel distance that arrival time is plotted against comes out
    roughly sqrt(2) too long.
    """
    z = np.full((4, 4), 1000.0)
    z[1, 1] = 100.0
    z[1, 2] = 90.0                           # east:  drop 10 over 90 m
    z[2, 2] = 87.0                           # SE:    drop 13 over 127.3 m
    z[2, 1] = 99.0                           # south: drop  1, a decoy

    assert 13.0 / (DX * math.sqrt(2)) < 10.0 / DX, "test premise broken"

    down, code = _d8(z.ravel().copy(), *z.shape, DX, DX)
    nx = z.shape[1]
    assert down[1 * nx + 1] == 1 * nx + 2, "D8 did not pick the steepest slope"
    assert code.reshape(z.shape)[1, 1] == 1


def test_d8_marks_boundary_cells_as_outlets():
    """Boundary cells drain off-grid; anything else would trap water at the edge."""
    z = east_slope(ny=10, nx=10)
    down, code = _d8(z.ravel().copy(), *z.shape, DX, DX)
    d2 = down.reshape(z.shape)
    assert np.all(d2[0, :] == -1) and np.all(d2[-1, :] == -1)
    assert np.all(d2[:, 0] == -1) and np.all(d2[:, -1] == -1)
    assert np.all(d2[1:-1, 1:-1] >= 0)


def test_d8_receiver_is_always_strictly_lower():
    """
    Guards the assumption both single-sweep passes depend on.

    `_accumulate` and `_hand_reference` are O(N) only because a cell's receiver
    is guaranteed to be strictly lower, so an elevation sort resolves the
    dependency order. If a receiver could be equal, a tie in the sort would let
    a cell read its own unresolved reference.
    """
    rng = np.random.default_rng(3)
    z = east_slope(ny=30, nx=30, drop=0.4)
    z += rng.normal(0.0, 3.0, z.shape)       # rough enough to create pits
    zr = z.ravel().copy()
    _priority_flood(zr, *z.shape, FILL_EPS)
    down, _ = _d8(zr, *z.shape, DX, DX)
    has = down >= 0
    assert np.all(zr[down[has]] < zr[has])


# =============================================================================
# accumulation
# =============================================================================

def test_accumulation_sums_to_cell_count_over_outlets():
    """
    Routing integrity: every cell drains itself exactly once.

    The same role the volume check plays in the solver. A cell counted twice or
    lost gives a total that is not N, and the failure is otherwise invisible.
    """
    rng = np.random.default_rng(7)
    z = east_slope(ny=35, nx=45, drop=0.6) + rng.normal(0.0, 2.0, (35, 45))
    hydro = analyse_flow(make_grid(z), verbose=False)
    total = int(hydro.accumulation.reshape(-1)[hydro.down < 0].sum())
    assert total == z.size


def test_accumulation_is_at_least_one_everywhere():
    """Every cell contributes itself, so nothing may come out below 1."""
    z = v_valley()
    hydro = analyse_flow(make_grid(z), verbose=False)
    assert hydro.accumulation.min() >= 1.0


def test_accumulation_grows_monotonically_downstream():
    """
    Along a flow path accumulation can only increase.

    A decrease would mean a cell received less than one of its own contributors,
    which is a routing graph error rather than a rounding one.
    """
    z = v_valley(ny=50, nx=31)
    hydro = analyse_flow(make_grid(z), verbose=False)
    js, is_, _ = hydro.trace_downstream(2, 15)
    acc = hydro.accumulation[js, is_]
    assert np.all(np.diff(acc) >= 0.0), "accumulation fell downstream"
    assert acc[-1] > acc[0]


def test_valley_thalweg_carries_more_than_the_hillside():
    """
    The channel must be where the geometry says it is.

    If this fails the drainage network has been placed on the valley sides,
    which is what a diagonal-biased or unfilled routing surface produces.
    """
    z = v_valley(ny=60, nx=31)
    hydro = analyse_flow(make_grid(z), verbose=False)
    acc = hydro.accumulation
    row = 40
    centre = 15
    assert acc[row, centre] == acc[row].max(), (
        f"row {row} peak accumulation at column {int(acc[row].argmax())}, "
        f"expected the thalweg at {centre}")
    assert acc[row, centre] > 10.0 * acc[row, centre + 8]


def test_stream_threshold_is_an_area_not_a_cell_count():
    """
    The network must mean the same thing at 30 m and 90 m.

    This is what makes a resolution comparison compare floods rather than
    differently-defined rivers. Halving the cell size quadruples the cell count
    needed to reach the same square kilometres.
    """
    z = v_valley(ny=60, nx=31)
    coarse = analyse_flow(make_grid(z, dx=90.0), stream_threshold_km2=1.0,
                          verbose=False)
    fine = analyse_flow(make_grid(z, dx=45.0), stream_threshold_km2=1.0,
                        verbose=False)
    need_coarse = 1.0e6 / 90.0 ** 2
    need_fine = 1.0e6 / 45.0 ** 2
    assert need_fine == pytest.approx(4.0 * need_coarse)
    # The same physical channel, so the fine grid must flag FEWER cells as
    # stream (it takes 4x the cells to reach 1 km2) on an identical array.
    assert fine.stream.sum() < coarse.stream.sum()


# =============================================================================
# HAND
# =============================================================================

def test_hand_is_zero_on_the_drainage_network():
    """A stream cell is its own drainage reference, by definition."""
    z = v_valley(ny=60, nx=31)
    hydro = analyse_flow(make_grid(z), verbose=False)
    assert np.abs(hydro.hand[hydro.stream]).max() < 1e-9


def test_hand_matches_the_analytical_v_valley():
    """
    HAND on a V-valley is the height above its own thalweg — a known number.

    With a lateral gradient of `side` m per column, the cell `k` columns off the
    centreline sits exactly `side * k` above the channel. Checked away from the
    boundary rows, where cells drain off-grid and reference themselves.

    The stream threshold has to be high enough that only the thalweg qualifies.
    At 0.05 km2 (6 cells at 90 m) the hillside cells are themselves "stream", and
    HAND is then correctly zero everywhere — a passing-looking result that tests
    nothing.
    """
    side = 5.0
    z = v_valley(ny=60, nx=31, side=side, fall=2.0)
    hydro = analyse_flow(make_grid(z), stream_threshold_km2=1.0, verbose=False)
    centre = 15
    assert hydro.stream[25:45, centre].all(), "premise: thalweg must be stream"
    assert not hydro.stream[25:45, centre + 1].any(), (
        "premise: the first hillside column must NOT be stream, or HAND there "
        "is zero by definition and the test is vacuous")

    hand = hydro.hand
    for k in (1, 2, 3, 5, 8):
        got = hand[25:45, centre + k]
        assert got == pytest.approx(side * k, abs=1e-6), (
            f"HAND {k} columns off the thalweg: expected {side * k}, "
            f"got {got.min()}..{got.max()}")


def test_hand_is_non_negative_when_no_filling_was_needed():
    """
    On a surface that already drains, HAND cannot go negative.

    The real Tehri domain DOES produce negative HAND, and this test pins down
    why that is not a bug: it only happens where the routing scaffold was
    raised, so a genuine depression preserved in the solver bed sits below the
    stream cell it drains to. Remove the filling and the negatives vanish.
    """
    z = v_valley(ny=50, nx=31)
    hydro = analyse_flow(make_grid(z), verbose=False)
    assert hydro.fill_stats["cells"] == 0, "premise: this surface needs no fill"
    assert hydro.hand.min() >= -1e-9


def test_negative_hand_comes_from_a_depression_the_solver_keeps():
    """
    A hillside pit gives negative HAND, and the fill is why.

    The pit must be OFF the channel: a pit in the thalweg is itself a stream
    cell, so it is its own reference and HAND is zero there no matter how deep
    it is. Off-channel, the pit drains (on the scaffold) to the thalweg while
    its real bed sits below that thalweg, and the difference is negative.

    This is the documented consequence of routing on a filled scaffold while
    reading heights off the real bed, and it is why `summary()` reports the
    count instead of treating it as an error.
    """
    z = v_valley(ny=50, nx=31, side=5.0, fall=2.0)
    # Row 25, five columns off the thalweg: real bed 25 m above the channel.
    # Drop it 40 m and it ends up below the channel it drains to.
    z[25, 20] -= 40.0
    grid = make_grid(z)
    hydro = analyse_flow(grid, verbose=False)

    assert not hydro.stream[25, 20], "premise: the pit must be off the channel"
    assert hydro.hand[25, 20] < 0.0, "the pit must sit below its own reference"

    # Assert the INVARIANT rather than a hand-computed number. HAND must equal
    # the real bed minus the real bed of the first stream cell the flow path
    # reaches — which is what the implementation claims to do, and the only
    # thing that stays true regardless of which way the fill sends the outflow.
    #
    # Worth being concrete about why: computing "25 m above the thalweg, minus
    # 40 m, so -15 m" gives the wrong answer (-13 m). Once the fill raises the
    # pit to its rim, the steepest descent out of it is DIAGONAL — south-west,
    # gaining a row of downstream fall — so the reference is one row further
    # down the valley and 2 m lower. The path, not the geometry, decides.
    js, is_, _ = hydro.trace_downstream(25, 20)
    k = next(k for k in range(len(js)) if hydro.stream[js[k], is_[k]])
    ref = grid.z[js[k], is_[k]]
    assert hydro.hand[25, 20] == pytest.approx(grid.z[25, 20] - ref, abs=1e-9)

    raised = (hydro.z_routing - grid.z) > 10.0 * FILL_EPS
    assert raised[25, 20], "the fill must have raised the pit in the scaffold"
    # And the negatives are confined to the depression, not scattered.
    neg = hydro.hand < -1e-6
    assert neg.sum() <= 5, f"{neg.sum()} negative cells from one pit"


def test_summary_reports_negative_hand_when_present():
    """
    708 cells at -50 m on the real domain must read as documented, not as a bug.

    A reader who sees a negative minimum in the summary and no explanation will
    reasonably conclude the HAND pass is broken.
    """
    z = v_valley(ny=50, nx=31)
    z[25, 20] -= 40.0
    hydro = analyse_flow(make_grid(z), verbose=False)
    text = hydro.summary()
    assert "below drainage" in text, text
    assert "not an error" in text.lower(), text


def test_summary_labels_the_catchment_as_in_domain():
    """
    The largest in-domain catchment on the real grid is 2,809 km2 against
    Tehri's true ~7,500 km2, because the margin clips the upstream basin.
    Reported without that label it reads as a contradiction of the dam spec.
    """
    text = analyse_flow(make_grid(v_valley(ny=30, nx=31)),
                        verbose=False).summary()
    assert "IN-DOMAIN" in text, text


# =============================================================================
# snapping
# =============================================================================

TRUNK_COL = 30
TRIB_COL = 33


def two_channels(ny: int = 40, nx: int = 41) -> np.ndarray:
    """
    A trunk river and a small tributary, three columns apart.

    Laid out deliberately so the NEARER channel is the SMALLER one:

      * columns 1..32 form a broad bowl draining to the trunk at column 30
      * column 33 is a narrow incision — a local minimum in the lateral
        direction, so it becomes its own channel and drains south
      * columns 34+ fall away eastward off the grid, so only column 34 joins
        the tributary

    The trunk therefore collects ~32 columns and the tributary ~2. A point at
    column 32 is 2 cells from the trunk and 1 from the tributary, so
    distance-based snapping picks the wrong one and area-based picks right.

    Getting this backwards is easy and the test then passes for the wrong
    reason, so `test_snap_prefers_the_trunk_over_a_nearer_tributary` asserts the
    area ratio before it asserts anything about snapping.
    """
    i = np.arange(nx, dtype=np.float64)[None, :]
    j = np.arange(ny, dtype=np.float64)[:, None]

    lateral = 3.0 * np.abs(i - float(TRUNK_COL))          # the bowl
    lateral = np.where(i == TRIB_COL, 5.0, lateral)        # the incision
    east = i > TRIB_COL
    lateral = np.where(east, 80.0 - 5.0 * (i - TRIB_COL - 1.0), lateral)
    return 1000.0 - 2.0 * j + lateral


def test_snap_prefers_the_trunk_over_a_nearer_tributary():
    """
    THE wrong-valley test.

    Injecting a dam-break hydrograph into a tributary sends the entire flood
    down the wrong side of a ridge and produces a confident, plausible,
    completely wrong inundation map. This is why `snap_to_stream` identifies the
    channel by contributing area before it minimises distance.
    """
    hydro = analyse_flow(make_grid(two_channels()), verbose=False)
    acc = hydro.accumulation
    assert acc[20, TRUNK_COL] > 5.0 * acc[20, TRIB_COL], (
        f"premise broken: trunk carries {acc[20, TRUNK_COL]} cells, tributary "
        f"{acc[20, TRIB_COL]} — the tributary must be much the smaller")

    sj, si, info = hydro.snap_to_stream(20, 32, radius_cells=4)
    assert si == TRUNK_COL, (
        f"snapped to column {si} ({info['area_after_km2']:.2f} km2); the trunk "
        f"at column {TRUNK_COL} carries "
        f"{acc[20, TRUNK_COL] * hydro.cell_area_m2 / 1e6:.2f} km2")
    assert info["area_after_km2"] > info["area_before_km2"]


def test_snap_does_not_slide_the_point_downstream():
    """
    Accumulation grows downstream, so a bare argmax always lands at the
    DOWNSTREAM edge of the search window.

    On the real Tehri domain that moved the dam axis 805 m down-valley — 805 m
    of channel the flood would never be routed through, biasing every arrival
    time low. The trunk is identified by area and then the NEAREST trunk cell is
    taken, so a point already on the channel must not move along it at all.
    """
    hydro = analyse_flow(make_grid(two_channels()), verbose=False)
    sj, si, info = hydro.snap_to_stream(20, TRUNK_COL, radius_cells=8)
    assert (sj, si) == (20, TRUNK_COL), (
        f"a point already on the trunk moved to ({sj},{si}), "
        f"{info['moved_m']:.0f} m away")
    assert info["moved_m"] == 0.0


def test_snap_reports_how_far_it_moved():
    """The run report needs this: a 400 m snap means the coordinate is suspect."""
    hydro = analyse_flow(make_grid(two_channels()), verbose=False)
    _, _, info = hydro.snap_to_stream(20, 32, radius_cells=4)
    assert info["moved_cells"] == pytest.approx(2.0)
    assert info["moved_m"] == pytest.approx(2.0 * DX)
    assert info["from"] == (20, 32)


def test_snap_min_area_rejects_a_hillside_point():
    """
    Asking for an area no nearby cell has must fail loudly.

    Silently snapping to the best of a bad set is how a run ends up injecting
    into a gully. The error message carries the largest area actually found so
    the caller can see how far off the coordinate is.
    """
    hydro = analyse_flow(make_grid(v_valley(ny=40, nx=41)), verbose=False)
    with pytest.raises(ValueError, match="contributing area"):
        hydro.snap_to_stream(20, 38, radius_cells=2, min_area_km2=500.0)


def test_snap_flags_a_suspect_result():
    """
    A snap that lands on a minor channel while a much larger one sits just
    outside the search radius must say so.

    This is the Rishikesh failure on the real domain: an 8-cell radius at 90 m
    searches only +/-720 m, the point landed on a 6.1 km2 tributary, and nothing
    in the output said the Ganga trunk was 450x bigger a little further away.
    """
    hydro = analyse_flow(make_grid(two_channels()), verbose=False)
    # Radius 2 from the tributary cannot reach the trunk 3 columns west, but the
    # 2x re-search (radius 4) can.
    sj, si, info = hydro.snap_to_stream(20, TRIB_COL, radius_cells=2)
    assert si == TRIB_COL, "premise: radius 2 must stay on the tributary"
    assert info["suspect"] is True, info
    assert info["best_nearby_km2"] > 5.0 * info["area_after_km2"]
    assert "wrong valley" in info["warning"]
    assert info["suggested_radius_cells"] >= 3


def test_snap_does_not_flag_a_good_result():
    """The flag has to be quiet when the snap found the trunk."""
    hydro = analyse_flow(make_grid(two_channels()), verbose=False)
    _, _, info = hydro.snap_to_stream(20, 32, radius_cells=4)
    assert info["suspect"] is False, info
    assert "warning" not in info


def test_snap_clamps_a_point_outside_the_grid():
    """Out-of-range indices must not raise or wrap around to the far edge."""
    hydro = analyse_flow(make_grid(v_valley(ny=30, nx=31)), verbose=False)
    sj, si, _ = hydro.snap_to_stream(-5, 99, radius_cells=3)
    assert 0 <= sj < 30 and 0 <= si < 31


# =============================================================================
# tracing
# =============================================================================

def test_trace_reaches_the_domain_edge():
    """
    A trace must terminate at an outlet, not stall or cycle.

    Termination is guaranteed by receivers being strictly lower, so a trace that
    stops early is evidence the fill left a pit.
    """
    z = v_valley(ny=50, nx=31)
    hydro = analyse_flow(make_grid(z), verbose=False)
    js, is_, dist = hydro.trace_downstream(2, 15)
    assert hydro.down[js[-1] * 31 + is_[-1]] == -1, "trace stopped at a non-outlet"
    assert js[-1] == 49, f"expected to exit at the south edge, got row {js[-1]}"
    assert len(js) > 40


def test_trace_distance_is_monotone_and_starts_at_zero():
    z = v_valley(ny=40, nx=31)
    hydro = analyse_flow(make_grid(z), verbose=False)
    _, _, dist = hydro.trace_downstream(2, 15)
    assert dist[0] == 0.0
    assert np.all(np.diff(dist) > 0.0)


def test_trace_measures_diagonal_steps_at_dx_root_two():
    """
    Along-channel distance is what arrival time is plotted against.

    Counting a diagonal step as dx understates the travel path by 29% per
    diagonal cell, which would make the flood look faster than it is — an error
    in the direction that flatters us.
    """
    # A staircase forcing pure diagonal flow: drop along the j==i diagonal.
    n = 12
    z = np.full((n, n), 500.0)
    for k in range(n):
        z[k, k] = 400.0 - 10.0 * k
    hydro = analyse_flow(make_grid(z), verbose=False)
    js, is_, dist = hydro.trace_downstream(1, 1)
    steps = np.hypot(np.diff(js), np.diff(is_))
    diag = steps > 1.4
    assert diag.any(), "premise: this surface should route diagonally"
    assert np.diff(dist)[diag] == pytest.approx(DX * math.sqrt(2))


def test_trace_of_an_outlet_cell_is_a_single_point():
    """Degenerate but reachable: snapping can land on the boundary."""
    hydro = analyse_flow(make_grid(v_valley(ny=30, nx=31)), verbose=False)
    js, is_, dist = hydro.trace_downstream(29, 15)
    assert len(js) == 1 and dist[0] == 0.0


# =============================================================================
# masks and reporting
# =============================================================================

def test_valley_mask_tightens_with_the_threshold():
    z = v_valley(ny=50, nx=31, side=5.0)
    hydro = analyse_flow(make_grid(z), verbose=False)
    counts = [hydro.valley_mask(t).sum() for t in (10.0, 25.0, 50.0, 150.0)]
    assert counts == sorted(counts)
    assert counts[0] < counts[-1]


def test_mask_is_safe_detects_a_flood_at_the_mask_edge():
    """
    Restricting the domain is only legitimate if we check the flood respected it.

    Without this the valley mask is an unfalsifiable assumption; with it, a run
    that touched the edge is flagged for a rerun at a larger threshold.
    """
    z = v_valley(ny=50, nx=31, side=5.0)
    hydro = analyse_flow(make_grid(z), verbose=False)
    mask = hydro.valley_mask(25.0)

    contained = np.zeros_like(mask)
    contained[20:30, 14:17] = True           # deep in the thalweg
    safe, n = hydro.mask_is_safe(contained, 25.0)
    assert safe and n == 0

    safe, n = hydro.mask_is_safe(mask, 25.0)  # wet everywhere the mask allows
    assert not safe and n > 0


def test_contributing_area_matches_cell_count_times_cell_area():
    hydro = analyse_flow(make_grid(v_valley(ny=30, nx=31)), verbose=False)
    expected = hydro.accumulation * DX * DX / 1e6
    assert hydro.contributing_area_km2 == pytest.approx(expected)


def test_analyse_flow_rejects_a_grid_with_voids():
    """
    A NaN in the bed poisons the fill, the sort and every pass after it.

    Failing at the entry point with a message naming `fill_voids` is far more
    useful than a silently NaN-filled accumulation raster.
    """
    z = v_valley(ny=20, nx=21)
    z[10, 10] = np.nan
    with pytest.raises(ValueError, match="void-free"):
        analyse_flow(make_grid(z), verbose=False)


def test_d8_codes_are_valid_esri_bytes():
    """The field is exported for QGIS, so the codes must be the real ones."""
    hydro = analyse_flow(make_grid(v_valley(ny=30, nx=31)), verbose=False)
    codes = set(np.unique(hydro.d8_code).tolist())
    assert codes <= {0, 1, 2, 4, 8, 16, 32, 64, 128}, codes
    assert set(np.unique(hydro.d8_code[1:-1, 1:-1]).tolist()) - {0}


def test_summary_runs_and_names_the_two_dem_split():
    """
    The summary is what goes in the run report, so it must say the fill is
    topology-only. A reader who thinks the solver bed was filled would
    reasonably object that the model cannot pond water.
    """
    z = v_valley(ny=30, nx=31)
    z[15, 15] -= 20.0
    text = analyse_flow(make_grid(z), verbose=False).summary()
    assert "solver bed is" in text
    assert "km2" in text

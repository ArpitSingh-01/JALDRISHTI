"""
Scenario comparison between modelling approaches.

The problem statement asks the software to "compare the scenario produced by
these modelling approaches" — SPH, our own shallow-water solver, and Delft3D.
This module is where that comparison lives, and it is built from three
overlays, each answering a different question a jury will actually ask:

1. SOLVER-LEVEL: the same dam-break problem (Martin & Moyce column, the
   identical geometry the SPH rung validates against) solved by BOTH our
   engines. The SWE solver represents the column as a depth; the SPH solver
   as particles. Overlaid against Ritter's analytical solution, the chart
   shows where the two approaches agree (bulk profile, front speed) and
   where they legitimately diverge (the near-front jet, which SPH resolves
   and depth-averaging cannot).

2. HYDROGRAPH-LEVEL: the outflow hydrograph measured inside the SPH domain
   against the parametric weir-equation breach hydrograph (`scenario.breach`)
   and against Ritter's closed-form constant breach discharge 8/27 √g h0^{3/2}.
   These are the two candidate "how much water enters the river" models.

3. SCENARIO-LEVEL: both hydrographs routed through the IDENTICAL downstream
   domain, comparing arrival time and peak depth at a gauge. This is the
   decision-relevant comparison: if two near-field models that disagree in
   the first minutes converge to within minutes and metres downstream, that
   is a quantified statement about how much the breach model choice matters.

Delft3D enters as an imported overlay: `interop.delft3d.import_delft3d_map`
(or a table of published Delft3D results) supplies the third party's curves,
and every chart labels the source. The module never labels anything Delft3D
that did not come out of Delft3D.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .analytical import ritter
from ..solver.sph2d import GRAVITY


# ---------------------------------------------------------------------------
# 1. Solver-level: SWE vs SPH on the identical dam-break problem
# ---------------------------------------------------------------------------


@dataclass
class SolverComparison:
    """Result of running the same dam break through both engines."""
    swe_x: np.ndarray            # cell centres, m
    swe_h: np.ndarray            # SWE depth profile, m
    sph_x: np.ndarray            # bin centres, m
    sph_h: np.ndarray            # SPH free-surface height, m
    ritter_x: np.ndarray
    ritter_h: np.ndarray
    t: float                     # comparison time, s
    swe_front_m: float
    sph_front_m: float
    ritter_front_m: float
    notes: list = field(default_factory=list)


def swe_dam_break_profile(column_width, column_height, tank_length, dx,
                          t_end, ny=4):
    """
    Run the Ritter problem through the 2D SWE solver on a flat frictionless
    bed and return (x_centres, h) along the centreline at t_end.

    The domain is 2D but uniform across-channel with slip walls, so the
    centreline is the 1D solution; this makes it directly comparable to the
    SPH vertical-plane experiment.
    """
    from ..solver.swe2d import SWE2D

    nx = int(round(tank_length / dx))
    z = np.zeros((ny, nx))
    sol = SWE2D(z, dx, manning=0.0, bc=("wall", "wall", "wall", "wall"))
    x = (np.arange(nx) + 0.5) * dx
    h0 = np.where(x < column_width, column_height, 0.0)
    sol.set_depth(np.broadcast_to(h0, (ny, nx)).copy())
    sol.run(t_end)
    j = ny // 2
    return x, sol.h[j].copy(), sol


def sph_dam_break_profile(column_width, column_height, tank_length, dp,
                          t_end, sound_speed=None):
    """Run the identical problem through the SPH engine; returns profile."""
    from ..solver.sph2d import DamBreakSPH

    sim = DamBreakSPH(column_width, column_height, tank_length, dp,
                      sound_speed=sound_speed)
    sim.run(t_end, callback_every=1000)
    cx, h = sim.free_surface_profile(binsize=2.0 * dp)
    return cx, h, sim


def compare_solvers(column_width=1.0, column_height=0.5, tank_length=8.0,
                    dx=0.02, t_end=0.75) -> SolverComparison:
    """
    The same dam break through both engines, evaluated against Ritter.

    Defaults reproduce the Martin & Moyce n²=1 column (height a = 0.5 m,
    width 2a) used by the SPH validation rung, so both engines are compared
    on the exact problem SPH is already benchmarked against.
    """
    # SWE: depth-averaged solution
    swe_x, swe_h, sol = swe_dam_break_profile(
        column_width, column_height, tank_length, dx, t_end)

    # SPH: same geometry, particle spacing = dx
    sph_x, sph_h, sim = sph_dam_break_profile(
        column_width, column_height, tank_length, dx, t_end)

    # Analytical: Ritter on the (t, h0) of the SWE problem
    c0 = math.sqrt(GRAVITY * column_height)
    ritter_h = ritter(swe_x, t_end, column_height, x0=column_width)[0]
    ritter_front = column_width + 2.0 * c0 * t_end

    def front_of(x, h, h_thresh):
        wet = h > h_thresh
        return float(x[wet].max()) if wet.any() else column_width

    # Front thresholds differ by engine. For SWE the depth at the Ritter
    # front decays quadratically, so even a 1 mm threshold sits ~0.3 m behind
    # the true tip; a 1 cm threshold sits 3.1 m back on this domain and would
    # masquerade as a solver error. SPH bins are particle-counting quantised
    # (binsize 2 dp), so a slightly larger threshold avoids lone-particle noise.
    return SolverComparison(
        swe_x=swe_x, swe_h=swe_h,
        sph_x=sph_x, sph_h=sph_h,
        ritter_x=swe_x, ritter_h=ritter_h,
        t=t_end,
        swe_front_m=front_of(swe_x, swe_h, 1.0e-3),
        sph_front_m=front_of(sph_x, sph_h, 5.0e-3),
        ritter_front_m=ritter_front,
        notes=[
            "SPH resolves the vertical-plane jet; SWE depth-averages it. "
            "Near-front disagreement is expected physics, not error.",
            "Both engines use the same column geometry, frictionless bed "
            "and closed walls.",
        ],
    )


# ---------------------------------------------------------------------------
# 2. Hydrograph-level: SPH vs parametric breach vs Ritter's constant
# ---------------------------------------------------------------------------


def ritter_breach_discharge(column_height: float) -> float:
    """
    Ritter's constant breach discharge per unit width, 8/27 √g h0^{3/2}:
    the depth and velocity at the dam site in the dry-bed analytical solution
    are h = 4h0/9 and u = 2c0/3, and their product is constant in time.
    """
    return 8.0 / 27.0 * math.sqrt(GRAVITY) * column_height ** 1.5


@dataclass
class HydrographComparison:
    t: np.ndarray                  # s, common sample grid
    q_sph: np.ndarray              # m²/s per unit width (SPH gauge)
    q_breach: np.ndarray | None    # m²/s per unit width (parametric model)
    q_ritter: float                # m²/s per unit width (analytical constant)
    volume_sph: float
    volume_breach: float | None
    notes: list = field(default_factory=list)


def compare_hydrographs(sph_sim, breach_hydrograph=None,
                        breach_width=None, t_end=None) -> HydrographComparison:
    """
    Normalise both hydrographs to per-unit-width discharge and compare.

    `sph_sim` is a run DamBreakSPH with a gauge; `breach_hydrograph` is a
    scenario.breach.BreachHydrograph scaled to per-unit-width by
    `breach_width` when provided.
    """
    t_g, q_g = sph_sim.gauge_hydrograph()
    if t_g.size < 2:
        raise ValueError("SPH gauge has no samples")
    t_max = t_end if t_end is not None else t_g[-1]
    tt = np.linspace(t_g[0], max(t_max, t_g[-1]), 400)
    q_sph = np.interp(tt, t_g, q_g)
    q_ritter = ritter_breach_discharge(sph_sim.column_height)

    q_breach = None
    if breach_hydrograph is not None and breach_width:
        q_breach = np.array(
            [breach_hydrograph.q_at(t) for t in tt]) / breach_width

    return HydrographComparison(
        t=tt,
        q_sph=q_sph,
        q_breach=q_breach,
        q_ritter=q_ritter,
        volume_sph=float(np.trapezoid(q_sph, tt)),
        volume_breach=(None if q_breach is None
                       else float(np.trapezoid(q_breach, tt))),
        notes=[
            "Ritter's 8/27 √g h0^{3/2} is the exact dry-bed solution; it is "
            "the reference both measured curves should approach.",
        ],
    )


# ---------------------------------------------------------------------------
# 3. Scenario-level: two hydrographs, one downstream domain
# ---------------------------------------------------------------------------


@dataclass
class GaugeResult:
    arrival_s: float
    peak_depth_m: float
    peak_speed_ms: float


@dataclass
class ScenarioComparison:
    gauges: dict[str, dict[str, GaugeResult | None]]
    inflow_volume: dict[str, float]
    notes: list = field(default_factory=list)


def route_through_domain(solvers_inflows: dict[str, object],
                         domain: "SWE2D factory spec",
                         gauge_points: dict[str, tuple[int, int]],
                         t_end: float,
                         threshold: float = 0.05) -> ScenarioComparison:
    """
    Route each named inflow through a freshly built copy of the same domain
    and measure arrival / peak at the same gauges.

    `domain` is a spec dict for _build_domain: {"nx","ny","dx","slope",
    "manning"} — a synthetic reach, so the comparison isolates the inflow
    model from terrain uncertainty. `solvers_inflows` maps a label to a
    swe2d.Inflow. Every run starts from an identical dry domain.
    """
    results: dict[str, dict[str, GaugeResult | None]] = {}

    for label, inflow in solvers_inflows.items():
        sol = _build_domain(**domain)
        sol.add_inflow(inflow.cells, inflow.q, direction=inflow.direction,
                       speed=inflow.speed, label=inflow.label)
        acc = sol.track_maxima(threshold=threshold)
        sol.run(t_end)
        gauges: dict[str, GaugeResult | None] = {}
        for name, (j, i) in gauge_points.items():
            if acc.t_arrival[j, i] < 0:
                gauges[name] = None
                continue
            gauges[name] = GaugeResult(
                arrival_s=float(acc.t_arrival[j, i]),
                peak_depth_m=float(acc.h_max[j, i]),
                peak_speed_ms=float(acc.speed_max[j, i]),
            )
        results[label] = gauges
    return ScenarioComparison(
        gauges=results, inflow_volume={},
        notes=["Identical dry synthetic reach; only the inflow model differs."])


def _build_domain(nx=240, ny=12, dx=10.0, slope=0.001, manning=0.033):
    """A synthetic sloping reach with closed walls — the shared test river."""
    from ..solver.swe2d import SWE2D

    z = (-slope * (np.arange(nx) + 0.5) * dx)[None, :] \
        * np.ones((ny, 1))
    return SWE2D(z, dx, manning=manning,
                 bc=("wall", "wall", "wall", "wall"))


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------


def write_solver_comparison_chart(comp: SolverComparison, path):
    """Profile overlay: Ritter (analytical), SWE (grid), SPH (particles)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(comp.ritter_x, comp.ritter_h, "k--", lw=1.2,
            label=f"Ritter analytical (t = {comp.t:.2f} s)")
    ax.plot(comp.swe_x, comp.swe_h, "-", lw=1.8,
            label="JALDRISHTI SWE (finite volume, HLLC)")
    ax.plot(comp.sph_x, comp.sph_h, ".", ms=3, alpha=0.8,
            label="JALDRISHTI SPH (particles)")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("water height (m)")
    ax.set_title("Same dam break, two engines — Martin & Moyce column")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def write_hydrograph_comparison_chart(comp: HydrographComparison, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(comp.t, comp.q_sph, "-", lw=1.8, label="SPH measured at gauge")
    if comp.q_breach is not None:
        ax.plot(comp.t, comp.q_breach, "--", lw=1.8,
                label="Parametric weir breach")
    ax.axhline(comp.q_ritter, color="k", ls=":", lw=1.2,
               label="Ritter 8/27 √g·h0^{3/2}")
    ax.set_xlabel("t (s)")
    ax.set_ylabel("discharge per unit width (m²/s)")
    ax.set_title("Near-field outflow: SPH vs parametric breach vs analytical")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def write_delft3d_comparison_chart(our_max_depth, our_xy, d3d, path):
    """
    Overlay our maximum-depth field against imported Delft3D output.

    `d3d` is the dict from interop.delft3d.import_delft3d_map. If face
    coordinates are available a scatter overlay is drawn; otherwise only our
    field is drawn with a note that no Delft3D arrays were provided.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), sharey=True)
    has_d3d = "max_depth" in d3d and "face_x" in d3d

    sc0 = axes[0].scatter(our_xy[:, 0], our_xy[:, 1], c=our_max_depth,
                          s=4, cmap="viridis")
    axes[0].set_title("JALDRISHTI SWE — max depth")
    fig.colorbar(sc0, ax=axes[0], label="m")

    if has_d3d:
        sc1 = axes[1].scatter(d3d["face_x"], d3d["face_y"],
                              c=d3d["max_depth"], s=4, cmap="viridis")
        axes[1].set_title("Delft3D-FM output (imported)")
        fig.colorbar(sc1, ax=axes[1], label="m")
    else:
        axes[1].text(0.5, 0.5, "No Delft3D arrays provided.\n"
                     "JALDRISHTI does not claim Delft3D results\n"
                     "that were not produced by Delft3D.",
                     ha="center", va="center", transform=axes[1].transAxes,
                     fontsize=10)
        axes[1].set_xticks([])
        axes[1].set_yticks([])
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path

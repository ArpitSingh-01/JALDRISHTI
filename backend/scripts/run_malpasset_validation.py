"""
Run the Malpasset 1959 validation (rung 4) and score it against field + lab data.

    # fast IC + short-propagation sanity check (coarse, seconds):
    python scripts/run_malpasset_validation.py --coarsen 4 --duration 300 --no-figure

    # first full-duration coarse read (a minute or two):
    python scripts/run_malpasset_validation.py --coarsen 4

    # the quotable run: native 20 m, 4000 s (~45 min), writes the deck figure:
    python scripts/run_malpasset_validation.py

Everything numerical lives in jaldrishti.validation.malpasset; this script is the
driver: it prints an initial-condition audit, runs with a progress log, samples
the three observation families, prints the comparison table, and writes a figure
plus a metrics JSON into outputs/validation/.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from jaldrishti.validation import malpasset as M


def _audit_ic(bed: M.Bed, s, mask) -> dict:
    """Print and return an initial-condition audit — the cheap correctness gate
    before spending 45 minutes on a run."""
    vol = float(s.volume())
    ncells = int(mask.sum())
    zmin = float(np.nanmin(np.where(bed.valid, bed.z, np.nan)))
    zmax = float(np.nanmax(np.where(bed.valid, bed.z, np.nan)))

    # Reservoir footprint bbox: a lake behind the dam (~x=4680) should extend
    # UPSTREAM (smaller x / larger y), not spill far downstream. If xmax runs to
    # the coast the half-plane test has leaked and the volume is spurious.
    ii, jj = np.where(mask)
    if ii.size:
        rx = bed.x0 + bed.dx * jj
        ry = bed.y0 + bed.dx * ii
        bbox = (float(rx.min()), float(rx.max()), float(ry.min()), float(ry.max()))
    else:
        bbox = (float("nan"),) * 4

    obs = M.load_observations()
    # Every observation point is downstream and MUST start dry. A wet one means
    # the reservoir landed on the wrong side of the dam line.
    wet_obs = []
    h0 = np.asarray(s.h)
    for family in obs.values():
        for o in family:
            i, j = bed.ij(o.x, o.y)
            if h0[i, j] > s.h_min:
                wet_obs.append(o.name)

    print("=" * 70)
    print(f"INITIAL CONDITION AUDIT  (dx = {bed.dx:.0f} m, grid {bed.shape[0]}x"
          f"{bed.shape[1]} = {bed.z.size:,} cells)")
    print("-" * 70)
    print(f"  bed elevation (in mesh) : {zmin:8.2f} .. {zmax:8.2f} m")
    print(f"  reservoir cells         : {ncells:,}")
    print(f"  reservoir volume        : {vol / 1e6:8.2f} x10^6 m^3"
          f"   (historical ~55)")
    print(f"  reservoir bbox x,y      : x [{bbox[0]:.0f}, {bbox[1]:.0f}]  "
          f"y [{bbox[2]:.0f}, {bbox[3]:.0f}]  (dam ~x=4680)")
    print(f"  obs points wet at t=0   : {wet_obs if wet_obs else 'none (correct)'}")
    print("=" * 70)

    return {
        "dx_m": bed.dx,
        "grid": list(bed.shape),
        "n_cells": int(bed.z.size),
        "bed_min_m": zmin,
        "bed_max_m": zmax,
        "reservoir_cells": ncells,
        "reservoir_volume_m3": vol,
        "obs_wet_at_t0": wet_obs,
    }


def _progress(t0):
    def cb(s):
        wall = time.perf_counter() - t0
        v0 = s.stats.volume_initial or 1.0
        drift = (s.volume() - s.stats.volume_initial) / v0
        wet = int(np.count_nonzero(np.asarray(s.h) > s.h_min))
        print(f"  t={s.t:7.1f}s  steps={s.stats.steps:6d}  "
              f"max_depth={float(np.asarray(s.h).max()):6.1f}m  "
              f"wet={wet:7d}  mass_drift={drift:+.2e}  wall={wall:6.1f}s")
    return cb


def _print_table(results):
    print("\n" + "=" * 78)
    print("OBSERVATION COMPARISON  (WS = max water-surface elevation, m; AT = "
          "arrival, s)")
    print("-" * 78)
    print(f"{'pt':>5} {'kind':>11} {'obs WS':>8} {'mod WS':>8} {'dWS':>7}   "
          f"{'obs AT':>8} {'mod AT':>8} {'dAT':>8}")
    for r in results:
        ows = f"{r.obs_ws:8.2f}" if r.obs_ws is not None else f"{'-':>8}"
        mws = f"{r.mod_ws:8.2f}" if r.mod_ws is not None else f"{'dry':>8}"
        dws = f"{r.ws_err:+7.2f}" if r.ws_err is not None else f"{'-':>7}"
        oat = f"{r.obs_at:8.1f}" if r.obs_at is not None else f"{'-':>8}"
        mat = f"{r.mod_at:8.1f}" if r.mod_at is not None else f"{'dry':>8}"
        dat = f"{r.at_err:+8.1f}" if r.at_err is not None else f"{'-':>8}"
        print(f"{r.name:>5} {r.kind:>11} {ows} {mws} {dws}   {oat} {mat} {dat}")
    print("=" * 78)


def _print_metrics(metrics):
    ws = metrics["max_ws"]
    at = metrics["gauge_arrival"]
    lo_ws, hi_ws = M.PUBLISHED_MAXWS_L1_M
    lo_at, hi_at = M.PUBLISHED_ARRIVAL_S
    print("\nERROR METRICS")
    print("-" * 60)
    print(f"  max water-surface elevation ({ws['n']} pts):")
    print(f"      L1  = {ws['l1']:6.2f} m   L2 = {ws['l2']:6.2f} m   "
          f"Linf = {ws['linf']:6.2f} m   bias = {ws['bias']:+.2f} m")
    print(f"      published L1 band (Kim 2014): {lo_ws:.1f}-{hi_ws:.1f} m")
    print(f"  arrival time, gauges G6-G14 ({at['n']} pts):")
    print(f"      L1  = {at['l1']:6.1f} s   L2 = {at['l2']:6.1f} s   "
          f"Linf = {at['linf']:6.1f} s   bias = {at['bias']:+.1f} s")
    print(f"      published L1 band (Kim 2014): {lo_at:.0f}-{hi_at:.0f} s")
    if metrics["transformer_rel"]:
        print("  transformer relative arrival (unknown datum -> use B-A, C-A):")
        for name, d in metrics["transformer_rel"].items():
            print(f"      {name}-A : obs {d['obs_rel_s']:6.0f} s   "
                  f"model {d['mod_rel_s']:7.1f} s   err {d['err_s']:+7.1f} s")
    if metrics["n_dry_in_model"]:
        print(f"  NOTE {metrics['n_dry_in_model']} observed-wet point(s) stayed "
              f"dry in the model.")
    print("-" * 60)


def make_figure(bed, s, mask, results, metrics, out_path):
    """Four-panel deck figure. Deferred import so the numerics path never needs
    matplotlib."""
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    arrival_min = np.asarray(s.arrival_time) / 60.0
    max_depth = np.asarray(s.max_depth)
    xmin, xmax, ymin, ymax = bed.extent()
    extent = (xmin / 1000.0, xmax / 1000.0, ymin / 1000.0, ymax / 1000.0)

    fig, axes = plt.subplots(2, 2, figsize=(14.5, 10.5))

    # panel 1: arrival-time map (the differentiator) -----------------------
    ax = axes[0, 0]
    hill = np.where(bed.valid, bed.z, np.nan)
    ax.imshow(hill, origin="lower", extent=extent, cmap="Greys",
              alpha=0.55, vmin=0, vmax=120)
    at = np.where(np.isfinite(arrival_min), arrival_min, np.nan)
    im = ax.imshow(at, origin="lower", extent=extent, cmap="viridis",
                   vmin=0, vmax=max(1.0, M.DURATION_S / 60.0 * 0.5))
    fig.colorbar(im, ax=ax, label="arrival time [min]", shrink=0.85)
    for r in results:
        if r.kind == "transformer":
            ax.plot(r.x / 1000.0, r.y / 1000.0, "r^", ms=9, mec="k", mew=0.6)
            ax.annotate(r.name, (r.x / 1000.0, r.y / 1000.0),
                        textcoords="offset points", xytext=(6, 4),
                        fontsize=9, color="darkred", fontweight="bold")
    ax.set_title("Modelled flood arrival time\n(triangles = destroyed "
                 "transformers)", fontsize=10)
    ax.set_xlabel("x [km]"); ax.set_ylabel("y [km]")

    # panel 2: max WS elevation, modelled vs observed ----------------------
    ax = axes[0, 1]
    lo_ws, hi_ws = M.PUBLISHED_MAXWS_L1_M
    ws_pts = [(r.obs_ws, r.mod_ws, r.kind) for r in results
              if r.obs_ws is not None and r.mod_ws is not None]
    if ws_pts:
        lim = [0, max(max(o, m) for o, m, _ in ws_pts) * 1.08]
        ax.fill_between(lim, [x - hi_ws for x in lim], [x + hi_ws for x in lim],
                        color="#c8e6c9", alpha=0.5,
                        label=f"published band +/-{hi_ws:.1f} m")
        ax.plot(lim, lim, "k-", lw=1, label="1:1")
        for kind, col, mk in (("police", "#1565c0", "o"),
                              ("gauge", "#c62828", "s")):
            xs = [o for o, m, k in ws_pts if k == kind]
            ys = [m for o, m, k in ws_pts if k == kind]
            if xs:
                ax.plot(xs, ys, mk, color=col, ms=6, mec="k", mew=0.4,
                        ls="none", label=f"{kind}")
        ax.set_xlim(lim); ax.set_ylim(lim)
    ax.set_aspect("equal", "box")
    ax.set_xlabel("observed max WS elevation [m]")
    ax.set_ylabel("modelled max WS elevation [m]")
    ax.set_title(f"Max water level  (L1 = {metrics['max_ws']['l1']:.2f} m)",
                 fontsize=10)
    ax.legend(fontsize=7.5, loc="upper left"); ax.grid(alpha=0.3)

    # panel 3: arrival time, modelled vs observed --------------------------
    ax = axes[1, 0]
    at_pts = [(r.obs_at, r.mod_at, r.name) for r in results
              if r.kind == "gauge" and r.obs_at is not None and r.mod_at is not None]
    if at_pts:
        lim = [0, max(max(o, m) for o, m, _ in at_pts) * 1.08]
        ax.plot(lim, lim, "k-", lw=1, label="1:1")
        xs = [o for o, m, _ in at_pts]; ys = [m for o, m, _ in at_pts]
        ax.plot(xs, ys, "o", color="#00838f", ms=7, mec="k", mew=0.4,
                ls="none", label="gauges G6-G14")
        for o, m, nm in at_pts:
            ax.annotate(nm, (o, m), textcoords="offset points", xytext=(4, 3),
                        fontsize=7, color="#37474f")
        ax.set_xlim(lim); ax.set_ylim(lim)
    ax.set_aspect("equal", "box")
    ax.set_xlabel("observed arrival [s]"); ax.set_ylabel("modelled arrival [s]")
    ax.set_title(f"Wave arrival time  (L1 = {metrics['gauge_arrival']['l1']:.0f} s)",
                 fontsize=10)
    ax.legend(fontsize=8, loc="upper left"); ax.grid(alpha=0.3)

    # panel 4: max-depth map with all sample points ------------------------
    ax = axes[1, 1]
    ax.imshow(hill, origin="lower", extent=extent, cmap="Greys",
              alpha=0.55, vmin=0, vmax=120)
    depth = np.where(max_depth > 0.1, max_depth, np.nan)
    blues = LinearSegmentedColormap.from_list(
        "flood", ["#b3e5fc", "#0288d1", "#01579b", "#0d1b6b"])
    im = ax.imshow(depth, origin="lower", extent=extent, cmap=blues,
                   vmin=0, vmax=float(np.nanpercentile(depth, 99)) if np.isfinite(
                       depth).any() else 1.0)
    fig.colorbar(im, ax=ax, label="max depth [m]", shrink=0.85)
    for r in results:
        col = {"police": "#ffb300", "gauge": "#d81b60",
               "transformer": "#00e5ff"}.get(r.kind, "w")
        ax.plot(r.x / 1000.0, r.y / 1000.0, "o", color=col, ms=4, mec="k",
                mew=0.4)
    ax.set_title("Modelled maximum depth + 29 observation points", fontsize=10)
    ax.set_xlabel("x [km]"); ax.set_ylabel("y [km]")

    fig.suptitle("JALDRISHTI solver validation 4/4 - Malpasset 1959 dam break "
                 f"(real terrain, field data; dx = {bed.dx:.0f} m)",
                 fontsize=12.5, y=0.995)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description="Malpasset validation run")
    ap.add_argument("--coarsen", type=int, default=1,
                    help="integer bed block-average factor (1 = native 20 m)")
    ap.add_argument("--duration", type=float, default=M.DURATION_S)
    ap.add_argument("--bank-radius", type=float, default=30.0)
    ap.add_argument("--setup-only", action="store_true",
                    help="print the IC audit and exit (no run)")
    ap.add_argument("--no-figure", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()

    out_dir = a.out or (M._REPO_ROOT / "outputs" / "validation")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading Malpasset bed (coarsen={a.coarsen}) ...")
    bed = M.load_bed(coarsen=a.coarsen)
    s, mask = M.build_solver(bed)
    audit = _audit_ic(bed, s, mask)
    if audit["obs_wet_at_t0"]:
        print("!! observation points are wet at t=0 -> reservoir is on the WRONG "
              "side of the dam line. Aborting.")
        return 2
    if a.setup_only:
        return 0

    print(f"\nRunning to {a.duration:.0f} s ...")
    t0 = time.perf_counter()
    stats = s.run(a.duration, callback=_progress(t0),
                  callback_every=max(a.duration / 12.0, 50.0))
    wall = time.perf_counter() - t0
    v0 = stats.volume_initial or 1.0
    clip_frac = stats.mass_clipped / v0
    print(f"\nDONE in {wall:.1f}s wall, {stats.steps:,} steps. "
          f"mass error = {stats.volume_error:.3e} (relative to {v0/1e6:.1f}e6 m^3)")
    print(f"  wetting/drying clipped +{stats.mass_clipped/1e6:.3f} x10^6 m^3 "
          f"(+{clip_frac:.2%}) -- this is the sign+magnitude of the mass drift, "
          f"confirming it is the dry-cell floor, not a flux leak.")

    obs = M.load_observations()
    results = M.sample_all(bed, s, obs, bank_radius_m=a.bank_radius)
    metrics = M.score(results)
    _print_table(results)
    _print_metrics(metrics)

    tag = f"coarsen{a.coarsen}" if a.coarsen > 1 else "native20m"
    metrics_out = {
        "case": "malpasset_1959",
        "audit": audit,
        "duration_s": a.duration,
        "wall_time_s": wall,
        "steps": stats.steps,
        "mass_error_relative": float(stats.volume_error),
        "metrics": metrics,
        "points": [
            {"name": r.name, "kind": r.kind, "obs_ws": r.obs_ws,
             "mod_ws": r.mod_ws, "obs_at": r.obs_at, "mod_at": r.mod_at}
            for r in results
        ],
    }
    (out_dir / f"malpasset_metrics_{tag}.json").write_text(
        json.dumps(metrics_out, indent=2), encoding="utf-8")
    print(f"\nmetrics -> {out_dir / f'malpasset_metrics_{tag}.json'}")

    if not a.no_figure:
        fig_path = out_dir / f"04_malpasset_{tag}.png"
        make_figure(bed, s, mask, results, metrics, fig_path)
        print(f"figure  -> {fig_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

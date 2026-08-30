"""
Build check for the pieces that had never been executed: flow routing, roughness
and the breach hydrograph.

Not a test — a smoke check. It runs the real Tehri domain through
`analyse_flow`, `roughness_for` and `simulate_breach`, prints what came back, and
writes GeoTIFFs and a hydrograph chart so the results can be looked at in QGIS
rather than judged from scalars.

Usage:
    python scripts/check_hydrology.py [--dx 90] [--no-landcover]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from jaldrishti.config import DATA_DIR, OUTPUT_DIR, TEHRI
from jaldrishti.scenario import (
    BreachGeometry,
    ReservoirStorage,
    formation_time_band,
    simulate_breach,
)
from jaldrishti.terrain import analyse_flow, prepare_terrain, roughness_for


def _val(x):
    """Unwrap a provenance-tracked value if that is what this is."""
    return x.value if hasattr(x, "value") else x


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dx", type=float, default=90.0)
    ap.add_argument("--no-landcover", action="store_true",
                    help="skip the WorldCover download")
    ap.add_argument("--stream-km2", type=float, default=1.0)
    args = ap.parse_args()

    out = OUTPUT_DIR / "terrain"
    out.mkdir(parents=True, exist_ok=True)

    pts = ([(TEHRI.dam.lat, TEHRI.dam.lon)]
           + [(p.lat, p.lon) for p in TEHRI.downstream])

    print("=" * 74)
    print(f"1. TERRAIN   dx = {args.dx:g} m")
    print("=" * 74)
    t0 = time.perf_counter()
    grid = prepare_terrain(
        points=pts, dst_crs=TEHRI.domain.crs, dx=args.dx, margin_km=8.0,
        cache_dir=DATA_DIR / "dem", max_fill_m=2.0)
    print(grid.summary())
    print(f"elapsed: {time.perf_counter() - t0:.1f} s")

    print()
    print("=" * 74)
    print("2. FLOW ROUTING")
    print("=" * 74)
    t0 = time.perf_counter()
    hydro = analyse_flow(grid, stream_threshold_km2=args.stream_km2)
    print(hydro.summary())
    print(f"elapsed: {time.perf_counter() - t0:.1f} s")

    # --- the checks that would catch a broken routing surface ----------------
    print("\nchecks:")
    n_cells = grid.z.size
    outlets = int((hydro.down < 0).sum())
    print(f"  boundary outlets            : {outlets:,} "
          f"({100.0 * outlets / n_cells:.2f}% of cells)")

    # Every interior cell must have a receiver. A single -1 in the interior means
    # priority-flood left a pit and D8 had nowhere to send the water.
    interior = np.ones(grid.z.shape, dtype=bool)
    interior[0, :] = interior[-1, :] = False
    interior[:, 0] = interior[:, -1] = False
    orphans = int((hydro.down.reshape(grid.z.shape)[interior] < 0).sum())
    print(f"  interior cells with no receiver: {orphans}   "
          f"{'OK' if orphans == 0 else '*** PIT LEFT BEHIND ***'}")

    # Accumulation must sum to the cell count: every cell drains itself plus its
    # upslope area exactly once, so the maximum cannot exceed N and the outlets
    # must between them account for all of it.
    acc = hydro.accumulation
    print(f"  max accumulation            : {acc.max():,} cells "
          f"= {acc.max() * hydro.cell_area_m2 / 1e6:,.0f} km2")
    out_total = int(acc.reshape(-1)[hydro.down < 0].sum())
    print(f"  sum over outlets            : {out_total:,} of {n_cells:,} "
          f"{'OK' if out_total == n_cells else '*** MASS LOST IN ROUTING ***'}")

    # The filled scaffold must never sit below the real bed.
    lowered = int((hydro.z_routing < grid.z - 1e-9).sum())
    print(f"  scaffold below real bed     : {lowered}   "
          f"{'OK' if lowered == 0 else '*** FILL WENT DOWNWARDS ***'}")

    hand = hydro.hand
    print(f"  HAND range                  : {np.nanmin(hand):.1f} .. "
          f"{np.nanmax(hand):.1f} m")
    neg = int((hand < -1e-6).sum())
    print(f"  negative HAND               : {neg}   "
          f"{'OK' if neg == 0 else '(cells below their own drainage reference)'}")

    # --- snapping every reported location to the river -----------------------
    from pyproj import Transformer
    from rasterio.transform import rowcol
    tr = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)

    print(f"\n{'location':26s} {'moved m':>8s} {'km2 before':>11s} "
          f"{'km2 after':>10s} {'km2 near':>9s} {'HAND m':>7s}  flag")
    named = ([(TEHRI.dam.name, TEHRI.dam.lat, TEHRI.dam.lon)]
             + [(p.name, p.lat, p.lon) for p in TEHRI.downstream])
    snapped = {}
    warnings = []
    for name, lat, lon in named:
        xm, ym = tr.transform(lon, lat)
        r, c = rowcol(grid.transform, xm, ym)
        if not (0 <= r < grid.z.shape[0] and 0 <= c < grid.z.shape[1]):
            print(f"{name:26s}   OUTSIDE DOMAIN")
            continue
        sj, si, info = hydro.snap_to_stream(r, c, radius_cells=8)
        snapped[name] = (sj, si)
        flag = "SUSPECT" if info["suspect"] else "ok"
        print(f"{name:26s} {info['moved_m']:8.0f} "
              f"{info['area_before_km2']:11.1f} {info['area_after_km2']:10.1f} "
              f"{info['best_nearby_km2']:9.1f} {hand[sj, si]:7.1f}  {flag}")
        if info["suspect"]:
            warnings.append(f"  {name}: {info['warning']}")
    for w in warnings:
        print(w)

    # --- does the river actually run from the dam to the towns? -------------
    if TEHRI.dam.name in snapped:
        dj, di = snapped[TEHRI.dam.name]
        js, is_, dist = hydro.trace_downstream(dj, di)
        print(f"\ndownstream trace from the dam: {len(js):,} cells, "
              f"{dist[-1] / 1000.0:.1f} km")
        drop = grid.z[dj, di] - grid.z[js[-1], is_[-1]]
        print(f"  bed drop along the trace    : {drop:.0f} m "
              f"({1000.0 * drop / max(dist[-1], 1.0):.2f} m/km)")
        on_path = set(zip(js.tolist(), is_.tolist()))
        for name, (sj, si) in snapped.items():
            if name == TEHRI.dam.name:
                continue
            hit = (sj, si) in on_path
            if hit:
                k = next(k for k, (a, b) in enumerate(zip(js, is_))
                         if (a, b) == (sj, si))
                print(f"  {name:24s} ON the trace at "
                      f"{dist[k] / 1000.0:6.1f} km")
            else:
                print(f"  {name:24s} not on the trace "
                      f"(tributary, or the trace ends first)")

    mask = hydro.valley_mask(max_hand_m=150.0)
    print(f"\nvalley mask (HAND <= 150 m): {mask.sum():,} cells "
          f"= {100.0 * mask.mean():.1f}% of the domain")

    grid.to_geotiff(out / f"tehri_hand_{int(args.dx)}m.tif", array=hand)
    grid.to_geotiff(out / f"tehri_acc_{int(args.dx)}m.tif",
                    array=np.log10(np.maximum(acc, 1)).astype("float32"))
    grid.to_geotiff(out / f"tehri_stream_{int(args.dx)}m.tif",
                    array=hydro.stream.astype("float32"))
    print(f"wrote HAND / log10(accumulation) / stream rasters to {out}")

    # =======================================================================
    print()
    print("=" * 74)
    print("3. ROUGHNESS")
    print("=" * 74)
    if args.no_landcover:
        print("skipped (--no-landcover)")
    else:
        try:
            t0 = time.perf_counter()
            rough = roughness_for(grid, cache_dir=DATA_DIR / "landcover",
                                  allow_fallback=True)
            print(rough.summary())
            print(f"elapsed: {time.perf_counter() - t0:.1f} s")
            grid.to_geotiff(out / f"tehri_manning_{int(args.dx)}m.tif",
                            array=rough.n.astype("float32"))
            print(f"wrote Manning n raster to {out}")
        except Exception as exc:      # noqa: BLE001 - a build check should report
            print(f"FAILED: {type(exc).__name__}: {exc}")

    # =======================================================================
    print()
    print("=" * 74)
    print("4. BREACH HYDROGRAPH")
    print("=" * 74)
    dam = TEHRI.dam
    crest = _val(dam.crest_m) if hasattr(dam, "crest_m") else None
    frl = _val(dam.frl_m)
    height = _val(dam.height_m)
    storage = _val(dam.gross_storage_m3) if hasattr(dam, "gross_storage_m3") else None
    area = _val(dam.reservoir_area_m2) if hasattr(dam, "reservoir_area_m2") else None
    crest_len = _val(dam.crest_length_m) if hasattr(dam, "crest_length_m") else None

    print(f"dam       : {dam.name}")
    print(f"FRL       : {frl} m")
    print(f"height    : {height} m")
    print(f"crest len : {crest_len} m")
    print(f"storage   : {storage if storage is None else f'{storage / 1e9:.2f} x 10^9 m3'}")
    print(f"area      : {area if area is None else f'{area / 1e6:.1f} km2'}")

    if None in (frl, height, storage, area, crest_len):
        print("\nmissing a required spec — skipping the routing run")
        return 0

    crest = crest if crest is not None else frl
    bed = frl - height
    store = ReservoirStorage.power_law(
        bed_m=bed, full_level_m=frl, volume_m3=storage, area_m2=area)
    print()
    print(store.summary())

    # The breach is NOT a free parameter. A 260.5 m deep trapezoid with 1:1 sides
    # needs 521 m of crest for its side slopes alone, so a 575 m dam leaves 54 m
    # of bottom width. Ask for the widest breach that fits rather than guessing.
    geom = BreachGeometry.fit_within_crest(
        crest_m=crest, invert_m=bed, crest_length_m=crest_len,
        side_slope=1.0, formation_time_s=3600.0, growth="linear")
    print()
    print(f"breach geometry (widest that fits a {crest_len:.0f} m crest):")
    print(f"  bottom width    : {geom.bottom_width_m:.0f} m")
    print(f"  top width       : {geom.top_width_m(crest - bed):.0f} m "
          f"at {crest - bed:.1f} m of head")

    # What the old hand-picked 200 m would have implied, and why it is refused.
    try:
        BreachGeometry(bottom_width_m=200.0, invert_m=bed, side_slope=1.0,
                       formation_time_s=3600.0, growth="linear",
                       crest_length_m=crest_len).check_fits(crest)
        print("  200 m bottom    : accepted (unexpected)")
    except ValueError as exc:
        print(f"  200 m bottom    : REFUSED - {exc}")

    hyd = simulate_breach(
        crest_m=crest, initial_level_m=frl, storage=store,
        geom=geom, bed_m=bed, dt=2.0)
    print()
    print(hyd.summary())

    # The comparison that shows why the storage curve matters. Same dam, same
    # breach, the only difference being A(h) versus A = A0.
    flat = simulate_breach(
        crest_m=crest, initial_level_m=frl, geom=geom, bed_m=bed, dt=2.0,
        storage=ReservoirStorage.constant(
            bed_m=bed, full_level_m=frl, area_m2=area))
    print()
    print("-" * 74)
    print("constant-area model, for contrast (NOT used for results):")
    print(f"  peak      : {flat.peak_q:,.0f} m3/s "
          f"vs {hyd.peak_q:,.0f} with the curve")
    print(f"  released  : {flat.released_volume_m3 / 1e6:,.0f} x 10^6 m3 "
          f"vs {hyd.released_volume_m3 / 1e6:,.0f} with the curve")
    print(f"  vs storage: {flat.released_volume_m3 / storage:.2f}x "
          f"vs {hyd.released_volume_m3 / storage:.2f}x actual gross storage")
    print("-" * 74)

    # Formation time is unknowable, so the answer is a band, not a number.
    print()
    times = [900.0, 1800.0, 3600.0, 7200.0, 14400.0]
    band = formation_time_band(
        times_s=times, crest_m=crest, initial_level_m=frl, storage=store,
        geom=geom, bed_m=bed, dt=2.0)
    print(f"{'t_form':>8s} {'peak m3/s':>12s} {'t_peak min':>11s} "
          f"{'drain h':>8s} {'peak vel':>9s}")
    for tf in times:
        h = band[tf]
        print(f"{tf / 60.0:6.0f}m {h.peak_q:12,.0f} {h.t_peak / 60.0:11.1f} "
              f"{h.t[-1] / 3600.0:8.2f} {h.peak_velocity:8.1f}")
    lo = min(b.peak_q for b in band.values())
    hi = max(b.peak_q for b in band.values())
    print(f"peak outflow band: {lo:,.0f} - {hi:,.0f} m3/s "
          f"({hi / lo:.1f}x across a 16x range of formation time)")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
        for tf in times:
            h = band[tf]
            ax[0].plot(h.t / 3600.0, h.q / 1000.0, lw=1.2, alpha=0.55,
                       color="#888888")
        ax[0].plot(flat.t / 3600.0, flat.q / 1000.0, color="#CC3333", lw=1.6,
                   ls="--", label="constant area (rejected)")
        ax[0].plot(hyd.t / 3600.0, hyd.q / 1000.0, color="#138808", lw=2.4,
                   label=f"level-area curve, b = {store.exponent:.2f}")
        ax[0].plot([], [], color="#888888", lw=1.2,
                   label="formation time 15 min - 4 h")
        ax[0].set_ylabel("outflow, 10$^3$ m$^3$/s")
        ax[0].set_title(f"{dam.name} — hypothetical breach hydrograph, "
                        f"{geom.bottom_width_m:.0f} m breach in a "
                        f"{crest_len:.0f} m crest")
        ax[0].legend(fontsize=8)
        ax[0].grid(alpha=0.3)
        ax[1].plot(flat.t / 3600.0, flat.level, color="#CC3333", lw=1.6, ls="--")
        ax[1].plot(hyd.t / 3600.0, hyd.level, color="#000080", lw=2,
                   label="reservoir level")
        ax[1].plot(hyd.t / 3600.0, hyd.invert, color="#FF9933", lw=2,
                   label="breach invert")
        ax[1].axhline(bed, color="#333333", lw=0.8, ls=":", label="streambed")
        ax[1].set_xlabel("time, hours")
        ax[1].set_ylabel("elevation, m")
        ax[1].legend(fontsize=8)
        ax[1].grid(alpha=0.3)
        fig.tight_layout()
        p = OUTPUT_DIR / "validation" / "tehri_breach_hydrograph.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(p, dpi=140)
        print(f"wrote {p}")
    except Exception as exc:          # noqa: BLE001
        print(f"chart failed: {type(exc).__name__}: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

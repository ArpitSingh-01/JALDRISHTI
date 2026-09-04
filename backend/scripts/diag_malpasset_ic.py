"""
Diagnose the Malpasset initial condition: is the reservoir mask ONE lake behind
the dam, or is the infinite-line half-plane test leaking water into disconnected
downstream / side pockets that inflate the impounded volume?

    python scripts/diag_malpasset_ic.py --coarsen 4     # fast read
    python scripts/diag_malpasset_ic.py                 # native 20 m

Why this matters: reservoir_mask() classifies a cell as reservoir when it is on
the positive side of the INFINITE line through the two dam-crest points (and is
below 100 m, and inside the mesh). The dam itself is a short, tilted segment, so
far from the crest that infinite line can sweep terrain that is actually
downstream or in an adjacent valley onto the "reservoir" side. The physical
reservoir is a single connected water body that touches the dam; any other wet
blob at t=0 is spurious fill. This labels the connected components of the initial
wet mask and reports how much volume sits OUTSIDE the component that touches the
dam. If that spurious fraction is large it explains the 80 vs ~55 x10^6 m^3 gap
and biases every modelled depth high; if it is ~0 the extra volume is a genuine
property of the "fill the branched valley to 100 m" benchmark IC and gets
disclosed rather than fixed.
"""
from __future__ import annotations

import argparse

import numpy as np

from jaldrishti.validation import malpasset as M


def _components(mask):
    """Label 4-connected components of a boolean mask (water spreads across the
    solver's N/S/E/W faces, so 4-connectivity is the right adjacency). Uses
    scipy when available, else a BFS flood fill."""
    try:
        from scipy import ndimage

        lbl, n = ndimage.label(mask)
        return lbl, int(n)
    except Exception:
        from collections import deque

        lbl = np.zeros(mask.shape, dtype=np.int32)
        ny, nx = mask.shape
        n = 0
        for i0 in range(ny):
            for j0 in range(nx):
                if mask[i0, j0] and lbl[i0, j0] == 0:
                    n += 1
                    dq = deque([(i0, j0)])
                    lbl[i0, j0] = n
                    while dq:
                        i, j = dq.popleft()
                        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                            a, b = i + di, j + dj
                            if 0 <= a < ny and 0 <= b < nx and mask[a, b] and lbl[a, b] == 0:
                                lbl[a, b] = n
                                dq.append((a, b))
        return lbl, n


def main() -> int:
    ap = argparse.ArgumentParser(description="Malpasset IC connectivity diagnostic")
    ap.add_argument("--coarsen", type=int, default=1)
    a = ap.parse_args()

    bed = M.load_bed(coarsen=a.coarsen)
    s, mask = M.build_solver(bed)
    h0 = np.asarray(s.h)
    wet0 = h0 > s.h_min
    cell_area = bed.dx * bed.dx

    lbl, n = _components(wet0)
    comps = []
    for k in range(1, n + 1):
        m = lbl == k
        comps.append((k, int(m.sum()), float(h0[m].sum() * cell_area)))
    comps.sort(key=lambda t: t[2], reverse=True)
    total = sum(c[2] for c in comps) or 1.0

    # Find the component that sits just upstream of the dam. Walk a normal off
    # the dam midpoint toward the positive (reservoir) side until we hit a
    # labelled cell.
    (x1, y1), (x2, y2) = M.DAM_LINE
    mid = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
    ddx, ddy = (x2 - x1), (y2 - y1)
    L = (ddx * ddx + ddy * ddy) ** 0.5
    nrmx, nrmy = -ddy / L, ddx / L
    sd = M._signed_distance(bed, *M.DAM_LINE)
    pi, pj = bed.ij(mid[0] + nrmx * bed.dx * 2, mid[1] + nrmy * bed.dx * 2)
    if sd[pi, pj] < 0:
        nrmx, nrmy = -nrmx, -nrmy
    dam_comp = 0
    for step in (2, 3, 4, 5, 6, 8, 10, 14):
        pi, pj = bed.ij(mid[0] + nrmx * bed.dx * step, mid[1] + nrmy * bed.dx * step)
        if lbl[pi, pj] != 0:
            dam_comp = int(lbl[pi, pj])
            break

    dam_vol = next((v for (k, c, v) in comps if k == dam_comp), 0.0)
    spurious = total - dam_vol

    print("=" * 72)
    print(f"Malpasset IC connected components  (dx = {bed.dx:.0f} m)")
    print(f"  wet cells at t=0 : {int(wet0.sum()):,}      components : {n}")
    print(f"  total IC volume  : {total / 1e6:8.2f} x10^6 m^3   (historical ~55)")
    print(f"  component touching dam upstream side : #{dam_comp}")
    print("-" * 72)
    print(f"{'rank':>4} {'label':>5} {'cells':>9} {'vol 1e6 m3':>12} {'% tot':>7}  dam?")
    for rank, (k, cells, vol) in enumerate(comps[:12], 1):
        tag = "  <== reservoir" if k == dam_comp else ""
        print(f"{rank:>4} {k:>5} {cells:>9,} {vol / 1e6:>12.3f} {100 * vol / total:>7.1f}{tag}")
    print("-" * 72)
    print(f"  reservoir (dam-touching component) : {dam_vol / 1e6:8.2f} x10^6 m^3")
    print(f"  spurious (all other components)    : {spurious / 1e6:8.2f} x10^6 m^3"
          f"  ({100 * spurious / total:.1f}% of IC)")
    if spurious / total > 0.02:
        print("  VERDICT: half-plane leaks -> restrict reservoir_mask to the dam "
              "component.")
    else:
        print("  VERDICT: single lake; extra volume is the benchmark IC, not a "
              "leak -> disclose.")
    print("=" * 72)

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xmin, xmax, ymin, ymax = bed.extent()
    ext = (xmin / 1000, xmax / 1000, ymin / 1000, ymax / 1000)
    obs = M.load_observations()
    hill = np.where(bed.valid, bed.z, np.nan)

    fig, ax = plt.subplots(1, 3, figsize=(19, 6.4))
    for k in range(3):
        ax[k].plot([x1 / 1000, x2 / 1000], [y1 / 1000, y2 / 1000], "r-", lw=2.5)
        for fam in obs.values():
            for o in fam:
                ax[k].plot(o.x / 1000, o.y / 1000, "kx", ms=4, mew=0.8)
        ax[k].set_xlabel("x [km]")
        ax[k].set_ylabel("y [km]")

    im0 = ax[0].imshow(hill, origin="lower", extent=ext, cmap="terrain", vmin=0, vmax=200)
    fig.colorbar(im0, ax=ax[0], shrink=0.8, label="bed elev [m]")
    ax[0].set_title("Bed + dam line (red) + obs (x)")

    wshow = np.where(wet0, h0, np.nan)
    im1 = ax[1].imshow(wshow, origin="lower", extent=ext, cmap="Blues", vmin=0, vmax=100)
    fig.colorbar(im1, ax=ax[1], shrink=0.8, label="initial depth [m]")
    ax[1].set_title(f"Initial reservoir depth ({total / 1e6:.1f}e6 m3)")

    comp_show = np.where(wet0, lbl.astype(float), np.nan)
    ax[2].imshow(hill, origin="lower", extent=ext, cmap="Greys", vmin=0, vmax=200, alpha=0.4)
    ax[2].imshow(comp_show, origin="lower", extent=ext, cmap="tab20")
    ax[2].set_title(f"Connected components (n={n}; reservoir=#{dam_comp})")

    out = M._REPO_ROOT / "outputs" / "validation" / "diag_malpasset_ic.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"figure -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Flow routing, drainage network, and height above nearest drainage (HAND).

WHAT THIS IS FOR, CONCRETELY
---------------------------
Three things the rest of the system cannot work without:

1. SNAPPING. The dam coordinate from `config.py` is a point on the Earth taken
   from a register. It does not land on the DEM's channel — it is metres to tens
   of metres off, and at 90 m resolution that is easily the wrong cell. Injecting
   the breach hydrograph into the wrong cell puts the entire flood on a hillside,
   where it runs down a gully and produces a plausible-looking, completely wrong
   answer. `snap_to_stream` fixes that by moving the injection point to the
   nearest cell that actually carries drainage.

2. THE VALLEY MASK. At 30 m over a 60 km reach, most of the domain is mountainside
   that no dam-break can reach. Knowing which cells those are lets us state the
   active fraction honestly and bound the cost of the high-resolution run.

3. THE LONGITUDINAL PROFILE. Arrival time is our headline output and it is only
   meaningful against distance downstream along the channel — not straight-line
   distance. `trace_downstream` produces the actual water path, cell by cell.

TWO DEMs, AND WHY THAT IS NOT A HACK
------------------------------------
This module builds its own internal, fully depression-filled elevation array and
uses it for TOPOLOGY ONLY. The solver keeps the physical bed from
`dem.fill_depressions`, which deliberately preserves real depressions because
water genuinely ponds in them.

The two requirements are irreconcilable in one array:

  * D8 flow routing cannot tolerate a single pit or flat. Every cell must have a
    strictly lower neighbour or the algorithm has nowhere to send water.
  * A shallow water solver MUST keep real depressions. Filling them destroys
    storage, and a flood that cannot pond arrives downstream too early and too
    large — an error in the direction that makes us look good, which is the worst
    kind.

So: `z_routing` is a scaffold for defining where the channel is. `grid.z` is the
bed the water actually flows over. Nothing physical is ever computed from
`z_routing`, and HAND heights are read off the real bed even though the paths are
traced on the scaffold.

THE FILLING ALGORITHM
---------------------
Priority-Flood with an epsilon gradient (Barnes, Lehman & Mulla 2014, "Priority-
flood: An optimal depression-filling and watershed-labeling algorithm for digital
elevation models", Computers & Geosciences 62:117-127).

Start a priority queue seeded with the domain boundary, always expand from the
lowest cell on the frontier, and raise each newly reached cell to at least
`eps` above the cell it was reached from. Because cells are finalised in
increasing order of their final elevation, and each is set strictly above its
parent, the result has a strictly descending path from every cell to the
boundary. That is exactly D8's precondition, established in a single O(N log N)
pass.

The epsilon also disposes of flats, which is the part that usually needs a
separate and fiddly algorithm (Garbrecht & Martz 1997). At 1e-6 m, a 6000-cell
path accumulates 6 mm of artificial rise — far below the DEM's own 4 m vertical
accuracy, and it never touches the solver's bed anyway.

REFERENCES
----------
Barnes, R., Lehman, C. & Mulla, D. (2014). Priority-flood. Computers &
    Geosciences 62:117-127.
Renno, C.D. et al. (2008). HAND, a new terrain descriptor using SRTM-DEM.
    Remote Sensing of Environment 112(9):3469-3481.
Nobre, A.D. et al. (2011). Height Above the Nearest Drainage - a hydrologically
    relevant new terrain model. Journal of Hydrology 404(1-2):13-29.
O'Callaghan, J.F. & Mark, D.M. (1984). The extraction of drainage networks from
    digital elevation data. Computer Vision, Graphics and Image Processing 28.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numba import njit

_JIT = dict(cache=True, nogil=True, fastmath=False)

# Epsilon gradient imposed on filled depressions and flats. See module docstring.
FILL_EPS = 1.0e-6

# Neighbour offsets, clockwise from east. Row index j increases southward for a
# north-up transform, which is what rasterio's from_origin produces.
_DJ = np.array([0, 1, 1, 1, 0, -1, -1, -1], dtype=np.int64)
_DI = np.array([1, 1, 0, -1, -1, -1, 0, 1], dtype=np.int64)

# ESRI D8 direction codes, for interoperability when the flow grid is exported.
_ESRI_CODE = np.array([1, 2, 4, 8, 16, 32, 64, 128], dtype=np.uint8)


# =============================================================================
# binary heap (Numba has no heapq)
# =============================================================================

@njit(inline="always", **_JIT)
def _heap_push(hk, hv, size, k, v):
    i = size
    hk[i] = k
    hv[i] = v
    while i > 0:
        p = (i - 1) >> 1
        if hk[p] <= hk[i]:
            break
        tk = hk[p]; hk[p] = hk[i]; hk[i] = tk
        tv = hv[p]; hv[p] = hv[i]; hv[i] = tv
        i = p
    return size + 1


@njit(inline="always", **_JIT)
def _heap_pop(hk, hv, size):
    top_k = hk[0]
    top_v = hv[0]
    size -= 1
    hk[0] = hk[size]
    hv[0] = hv[size]
    i = 0
    while True:
        l = 2 * i + 1
        r = l + 1
        m = i
        if l < size and hk[l] < hk[m]:
            m = l
        if r < size and hk[r] < hk[m]:
            m = r
        if m == i:
            break
        tk = hk[m]; hk[m] = hk[i]; hk[i] = tk
        tv = hv[m]; hv[m] = hv[i]; hv[i] = tv
        i = m
    return top_k, top_v, size


# =============================================================================
# kernels
# =============================================================================

@njit(**_JIT)
def _priority_flood(zf, ny, nx, eps):
    """
    In-place Priority-Flood + epsilon on a FLAT elevation array.

    Guarantees on return: every cell not on the domain boundary has at least one
    strictly lower 8-neighbour. That is the precondition D8 needs, and it is what
    makes the accumulation and HAND passes below correct rather than approximate.
    """
    n = ny * nx
    visited = np.zeros(n, dtype=np.bool_)
    hk = np.empty(n, dtype=np.float64)
    hv = np.empty(n, dtype=np.int64)
    size = 0

    for j in range(ny):
        for i in range(nx):
            if j == 0 or j == ny - 1 or i == 0 or i == nx - 1:
                c = j * nx + i
                visited[c] = True
                size = _heap_push(hk, hv, size, zf[c], c)

    while size > 0:
        _, c, size = _heap_pop(hk, hv, size)
        cj = c // nx
        ci = c - cj * nx
        zc = zf[c]
        for d in range(8):
            nj = cj + _DJ[d]
            ni = ci + _DI[d]
            if nj < 0 or nj >= ny or ni < 0 or ni >= nx:
                continue
            nc = nj * nx + ni
            if visited[nc]:
                continue
            visited[nc] = True
            if zf[nc] <= zc:
                zf[nc] = zc + eps
            size = _heap_push(hk, hv, size, zf[nc], nc)


@njit(**_JIT)
def _d8(zf, ny, nx, dx, dy):
    """
    Steepest-descent flow direction.

    Returns (down, code). `down` is the FLAT INDEX of the receiving cell, or -1
    for a boundary cell that drains off-grid. `code` is the ESRI D8 byte, 0 where
    there is no receiver, so the field can be written out and opened in QGIS or
    ArcGIS without translation.

    Slope is elevation drop divided by CENTRE-TO-CENTRE DISTANCE, so diagonals
    are correctly penalised by sqrt(2). Omitting that division is a classic bug:
    it biases every flow path towards the diagonals, and the resulting channel
    zig-zags instead of following the valley.
    """
    dist = np.empty(8, dtype=np.float64)
    diag = math.sqrt(dx * dx + dy * dy)
    for d in range(8):
        if _DJ[d] == 0:
            dist[d] = dx
        elif _DI[d] == 0:
            dist[d] = dy
        else:
            dist[d] = diag

    n = ny * nx
    down = np.full(n, -1, dtype=np.int64)
    code = np.zeros(n, dtype=np.uint8)

    for j in range(ny):
        for i in range(nx):
            c = j * nx + i
            if j == 0 or j == ny - 1 or i == 0 or i == nx - 1:
                continue                       # drains out of the domain
            zc = zf[c]
            best = 0.0
            bd = -1
            for d in range(8):
                nc = (j + _DJ[d]) * nx + (i + _DI[d])
                s = (zc - zf[nc]) / dist[d]
                if s > best:
                    best = s
                    bd = d
            if bd >= 0:
                down[c] = (j + _DJ[bd]) * nx + (i + _DI[bd])
                code[c] = _ESRI_CODE[bd]
    return down, code


@njit(**_JIT)
def _accumulate(down, order_asc):
    """
    Contributing cell count, by a single sweep in descending elevation.

    The trick that makes this O(N) rather than a graph traversal: process cells
    from high to low, and a cell's accumulation is already final by the time it
    is reached, because everything that drains into it is strictly higher and was
    therefore processed earlier. `order_asc` is walked backwards so only one sort
    is needed for this pass and the HAND pass.
    """
    n = down.size
    acc = np.ones(n, dtype=np.float64)
    for k in range(n - 1, -1, -1):
        c = order_asc[k]
        d = down[c]
        if d >= 0:
            acc[d] += acc[c]
    return acc


@njit(**_JIT)
def _hand_reference(down, order_asc, stream, z_real):
    """
    Elevation of the drainage cell each cell drains to, by one ascending sweep.

    Mirror image of the accumulation trick: walking from low to high, a cell's
    receiver is strictly lower and hence already resolved, so the reference
    propagates upslope in a single pass.

    Note `z_real`, not the routing surface: the height is read off the PHYSICAL
    bed even though the path was traced on the filled scaffold. Reporting HAND
    against a synthetic elevation would be a real error, since HAND ends up in
    the valley-mask threshold and thence in what we claim about the domain.
    """
    n = down.size
    ref = np.empty(n, dtype=np.float64)
    for k in range(n):
        c = order_asc[k]
        if stream[c] or down[c] < 0:
            ref[c] = z_real[c]
        else:
            ref[c] = ref[down[c]]
    return ref


@njit(**_JIT)
def _trace(down, start, max_len):
    """Follow D8 downstream from `start`, returning the flat indices visited."""
    path = np.empty(max_len, dtype=np.int64)
    c = start
    k = 0
    while k < max_len:
        path[k] = c
        k += 1
        d = down[c]
        if d < 0:
            break
        c = d
    return path[:k]


# =============================================================================
# result container
# =============================================================================

@dataclass
class HydroGrid:
    """
    Flow routing products for one TerrainGrid.

    All 2D arrays share the parent grid's shape, CRS and transform, so any of
    them can be written with `TerrainGrid.to_geotiff(array=...)` and inspected in
    QGIS. That is the intended debugging route when a flood goes somewhere
    surprising: look at `accumulation` and `stream` first, because a wrong
    channel explains more wrong answers than a wrong solver ever will.
    """
    grid: object                      # the parent TerrainGrid
    down: np.ndarray                  # (ny*nx,) flat receiver index, -1 = outlet
    d8_code: np.ndarray               # (ny, nx) uint8 ESRI direction code
    accumulation: np.ndarray          # (ny, nx) contributing cell count
    stream: np.ndarray                # (ny, nx) bool drainage network
    hand: np.ndarray                  # (ny, nx) height above nearest drainage, m
    z_routing: np.ndarray             # (ny, nx) filled scaffold (topology only)
    stream_threshold_km2: float = 1.0
    fill_stats: dict | None = None

    @property
    def shape(self):
        return self.grid.z.shape

    @property
    def cell_area_m2(self) -> float:
        return self.grid.dx * self.grid.dx

    @property
    def contributing_area_km2(self) -> np.ndarray:
        return self.accumulation * self.cell_area_m2 / 1.0e6

    def valley_mask(self, max_hand_m: float = 150.0) -> np.ndarray:
        """
        Cells within `max_hand_m` of the drainage network.

        DELIBERATELY GENEROUS. The default of 150 m is far above any depth this
        flood will reach; the mask exists to exclude ridge tops and tributary
        headwalls, NOT to predict the inundation extent. Tightening it towards
        the expected flood depth would make the mask determine the answer, which
        is circular — the model would then be unable to tell us it disagrees.

        Use `mask_is_safe` to confirm the flood never touched the boundary.
        """
        return self.hand <= max_hand_m

    def mask_is_safe(self, wet: np.ndarray, max_hand_m: float = 150.0,
                     *, margin_cells: int = 2) -> tuple[bool, int]:
        """
        Did the flood stay clear of the valley-mask edge?

        Returns (safe, n_touching). If any wet cell sits within `margin_cells` of
        the mask boundary, the mask may have constrained the result and the run
        must be repeated with a larger threshold. Without this check, restricting
        the domain would be an unfalsifiable assumption; with it, it is a
        verified one.
        """
        from scipy import ndimage
        mask = self.valley_mask(max_hand_m)
        eroded = ndimage.binary_erosion(
            mask, iterations=max(1, margin_cells), border_value=0)
        edge_band = mask & ~eroded
        n = int((wet & edge_band).sum())
        return n == 0, n

    def snap_to_stream(self, j: int, i: int, *, radius_cells: int = 8,
                       min_area_km2: float | None = None,
                       suspect_ratio: float = 5.0,
                       trunk_fraction: float = 0.5
                       ) -> tuple[int, int, dict]:
        """
        Move a point to the nearest cell on the main channel near it.

        Two steps, and the order is the whole point:

          1. IDENTIFY THE CHANNEL BY AREA. Search a square window and find the
             largest contributing area in it. Every cell carrying at least
             `trunk_fraction` of that is taken to be the same channel.
          2. THEN MINIMISE DISTANCE, but only within that set.

        Doing it the other way round — nearest stream cell — picks a small
        tributary over a trunk river two cells further out, and injecting a
        dam-break hydrograph into a tributary sends the flood down the wrong
        valley and produces a confident, plausible, completely wrong map.

        Doing step 1 alone is also wrong, and less obviously so. Accumulation
        grows monotonically downstream, so the single largest cell in any window
        is always at its DOWNSTREAM edge. A bare argmax therefore slides the
        point up to `radius_cells` downstream — on the real Tehri domain it moved
        the dam axis 805 m down-valley, which is 805 m of channel the flood would
        never be routed through and a direct bias on every arrival time.
        Restricting to the trunk and then taking the nearest cell keeps the dam
        at the dam.

        Returns (j, i, info). `info` records how far the point moved and how the
        contributing area changed, both of which belong in the run report,
        because a snap of 400 m means the input coordinate is suspect.

        THE SEARCH RADIUS IS ITSELF A FAILURE MODE
        ------------------------------------------
        Step 1 only finds the trunk if the trunk is inside the window. At 90 m
        the default radius searches +/-720 m, and on the real Tehri domain the
        Rishikesh coordinate landed on a 6.1 km2 tributary while the Ganga trunk
        carried 2,771 km2 slightly further out — so the snap succeeded on its own
        terms and still chose the wrong channel.

        So the window is re-searched at twice the radius, and `info["suspect"]`
        is set when that finds a channel more than `suspect_ratio` times larger.
        A caller that ignores the flag gets the same answer as before; a caller
        that reports it turns a silent wrong-valley injection into a visible
        warning. `info["suggested_radius_cells"]` says what would have found it.
        """
        ny, nx = self.shape
        j = int(np.clip(j, 0, ny - 1))
        i = int(np.clip(i, 0, nx - 1))
        r = int(radius_cells)
        if not 0.0 < trunk_fraction <= 1.0:
            raise ValueError("trunk_fraction must be in (0, 1]")

        sj, si = self._best_in_window(j, i, r, min_area_km2, trunk_fraction)

        # Look further out. Not to move the point — the caller chose the radius
        # for a reason — but to find out whether the choice mattered.
        wj, wi = self._best_in_window(j, i, 2 * r, None, 1.0)
        best_nearby = float(self.accumulation[wj, wi] * self.cell_area_m2 / 1e6)
        chosen = float(self.accumulation[sj, si] * self.cell_area_m2 / 1e6)
        suspect = bool(chosen > 0.0 and best_nearby > suspect_ratio * chosen)

        info = {
            "from": (j, i),
            "to": (sj, si),
            "moved_cells": float(math.hypot(sj - j, si - i)),
            "moved_m": float(math.hypot(sj - j, si - i) * self.grid.dx),
            "area_before_km2": float(
                self.accumulation[j, i] * self.cell_area_m2 / 1e6),
            "area_after_km2": chosen,
            "best_nearby_km2": best_nearby,
            "search_radius_cells": r,
            "suspect": suspect,
        }
        if suspect:
            info["suggested_radius_cells"] = int(
                math.ceil(max(abs(wj - j), abs(wi - i))))
            info["warning"] = (
                f"snapped to {chosen:.2f} km2 but a {best_nearby:.2f} km2 "
                f"channel lies at ({wj},{wi}), "
                f"{math.hypot(wj - j, wi - i) * self.grid.dx / 1000.0:.2f} km "
                f"away — the injection point may be in the wrong valley")
        return sj, si, info

    def _best_in_window(self, j: int, i: int, r: int,
                        min_area_km2: float | None,
                        trunk_fraction: float) -> tuple[int, int]:
        """
        Nearest cell to (j, i) whose area is within `trunk_fraction` of the best.

        `trunk_fraction = 1.0` degenerates to a plain argmax, which is what the
        suspect-check wants: it asks only how big the biggest nearby channel is,
        not where the point should go.
        """
        ny, nx = self.shape
        j0, j1 = max(0, j - r), min(ny, j + r + 1)
        i0, i1 = max(0, i - r), min(nx, i + r + 1)

        window = self.accumulation[j0:j1, i0:i1]
        if min_area_km2 is not None:
            need = min_area_km2 * 1.0e6 / self.cell_area_m2
            ok = window >= need
            if not ok.any():
                raise ValueError(
                    f"no cell within {r} cells of ({j},{i}) has a "
                    f"contributing area of {min_area_km2} km2; the largest is "
                    f"{window.max() * self.cell_area_m2 / 1e6:.2f} km2. The "
                    f"input coordinate is probably in the wrong place.")
            window = np.where(ok, window, -1.0)

        peak = float(window.max())
        if trunk_fraction >= 1.0 or peak <= 0.0:
            k = int(np.argmax(window))
            dj, di = divmod(k, i1 - i0)
            return j0 + dj, i0 + di

        # Cells on the same channel as the window's best, then nearest wins.
        on_trunk = window >= trunk_fraction * peak
        jj, ii = np.nonzero(on_trunk)
        d2 = (jj + j0 - j) ** 2 + (ii + i0 - i) ** 2
        # Break distance ties towards the larger catchment, so a point exactly
        # between two trunk cells still moves onto the more established one.
        best = np.lexsort((-window[jj, ii], d2))[0]
        return int(jj[best] + j0), int(ii[best] + i0)

    def trace_downstream(self, j: int, i: int, *, max_len: int | None = None):
        """
        The water's path from a cell to the domain edge.

        Returns (js, is_, distance_m) with distance measured along the path, so a
        longitudinal profile of bed elevation, depth or arrival time is a direct
        index into these arrays. Straight-line distance would understate the
        travel path substantially in a meandering Himalayan gorge.
        """
        ny, nx = self.shape
        if max_len is None:
            max_len = 4 * (ny + nx)
        flat = _trace(self.down, int(j) * nx + int(i), int(max_len))
        js = (flat // nx).astype(np.int64)
        is_ = (flat - js * nx).astype(np.int64)
        step = np.hypot(np.diff(js), np.diff(is_)) * self.grid.dx
        dist = np.concatenate(([0.0], np.cumsum(step)))
        return js, is_, dist

    def summary(self) -> str:
        area = self.contributing_area_km2
        ny, nx = self.shape
        n_stream = int(self.stream.sum())
        lines = [
            f"flow routing on {nx} x {ny} at {self.grid.dx:g} m",
            f"  drainage network : {n_stream:,} cells "
            f"({100 * n_stream / self.stream.size:.2f}% of domain) at a "
            f"{self.stream_threshold_km2:g} km2 threshold",
            f"  largest catchment: {area.max():,.1f} km2 "
            f"(IN-DOMAIN only — the margin clips the upstream basin)",
            f"  HAND             : {self.hand.min():.1f} to "
            f"{self.hand.max():.1f} m",
        ]
        # Negative HAND is expected and needs saying so, or a reader concludes
        # the HAND pass is broken. It is the direct consequence of the two-DEM
        # split: paths are traced on the filled scaffold, heights are read off
        # the real bed, so a depression the solver keeps sits BELOW the stream
        # cell it drains to. On the 90 m Tehri domain this is 708 cells (0.15%)
        # reaching -50 m, all of them inside preserved depressions.
        n_neg = int((self.hand < -1e-6).sum())
        if n_neg:
            lines.append(
                f"  below drainage   : {n_neg:,} cells "
                f"({100 * n_neg / self.hand.size:.2f}%) have negative HAND — "
                f"real depressions kept in the solver bed but filled in the "
                f"routing scaffold, so they sit below their own stream "
                f"reference. Expected, not an error.")
        for thr in (50.0, 100.0, 150.0, 300.0):
            frac = float((self.hand <= thr).mean())
            lines.append(f"  HAND <= {thr:5.0f} m   : {frac * 100:5.1f}% "
                         f"of the domain")
        if self.fill_stats:
            fs = self.fill_stats
            lines.append(
                f"  routing fill     : {fs['cells']:,} cells raised, max "
                f"{fs['max_m']:.2f} m (topology only; the solver bed is "
                f"untouched)")
        return "\n".join(lines)


# =============================================================================
# driver
# =============================================================================

def analyse_flow(grid, *, stream_threshold_km2: float = 1.0,
                 eps: float = FILL_EPS, verbose: bool = True) -> HydroGrid:
    """
    Full routing analysis of a TerrainGrid: fill -> D8 -> accumulate -> HAND.

    `stream_threshold_km2` is the contributing area above which a cell counts as
    part of the drainage network. Expressed as an AREA rather than a cell count
    on purpose: the network then means the same thing at 30 m and at 90 m, so a
    resolution comparison compares floods rather than differently-defined rivers.
    1 km2 is a conventional value for mountain headwater channels.
    """
    z = np.ascontiguousarray(grid.z, dtype=np.float64)
    if not np.isfinite(z).all():
        raise ValueError("analyse_flow requires a void-free grid; "
                         "call fill_voids first")
    ny, nx = z.shape

    z_flat = z.ravel().copy()
    zr = z_flat.copy()
    if verbose:
        print(f"[hydro] priority-flood fill on {nx} x {ny} "
              f"({nx * ny:,} cells)...")
    _priority_flood(zr, ny, nx, eps)

    raised = zr - z_flat
    fill_stats = {"cells": int((raised > eps).sum()),
                  "max_m": float(raised.max())}

    down, code = _d8(zr, ny, nx, grid.dx, grid.dx)
    order_asc = np.argsort(zr, kind="stable")
    acc = _accumulate(down, order_asc)

    need_cells = stream_threshold_km2 * 1.0e6 / (grid.dx * grid.dx)
    stream = acc >= need_cells
    ref = _hand_reference(down, order_asc, stream, z_flat)
    hand = z_flat - ref

    hg = HydroGrid(
        grid=grid,
        down=down,
        d8_code=code.reshape(ny, nx),
        accumulation=acc.reshape(ny, nx),
        stream=stream.reshape(ny, nx),
        hand=hand.reshape(ny, nx),
        z_routing=zr.reshape(ny, nx),
        stream_threshold_km2=float(stream_threshold_km2),
        fill_stats=fill_stats,
    )
    # Deliberately does NOT print hg.summary(). `verbose` governs progress
    # reporting on the slow priority-flood pass; the caller decides whether the
    # result gets reported. Printing it here as well duplicated the whole block
    # in scripts/check_hydrology.py.
    return hg

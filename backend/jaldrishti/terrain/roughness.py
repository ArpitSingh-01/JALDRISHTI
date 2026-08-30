"""
Manning's n from land cover.

WHY ROUGHNESS IS NOT A TUNING KNOB HERE
---------------------------------------
Manning's n is the single most-abused parameter in flood modelling. It is easy to
adjust, it changes the answer a lot, and nobody can measure it directly — so it
is routinely tuned until the model reproduces whatever it was asked to
reproduce. A model calibrated that way has no predictive value: it has been
fitted, and the fit absorbs every other error in the model along with it.

We refuse that. Roughness is derived from an independent, published, global land
cover product with a documented class-to-n mapping, and it is not adjusted to
improve any result. If our Malpasset hindcast disagrees with the survey, that
disagreement is reported, not tuned away.

The one place a multiplier is legitimate is the Chamoli debris flow, where the
flowing material is a sediment slurry rather than water. There the elevated
resistance is a stated model of a different physical process, applied uniformly
and declared — not a per-case fit.

DATA SOURCE: ESA WORLDCOVER 10 m
-------------------------------
Sentinel-1 + Sentinel-2 derived, 11 classes, global, 10 m, CC-BY 4.0, on AWS
open data with no authentication. Chosen for the same reason as Copernicus DEM:
it needs no account approval we do not have.

10 m is finer than our 30 m or 90 m computational grid, which is the right way
round. Aggregating a fine categorical map to a coarse cell is a defensible
averaging operation; interpolating a coarse map to a fine grid would be
invention.

HOW THE 10 m CLASSES BECOME ONE NUMBER PER CELL
-----------------------------------------------
A 90 m cell contains 81 WorldCover pixels and is generally not all one class. We
map each 10 m pixel to its n value and then AREA-AVERAGE the n values, rather
than taking the majority class and mapping that.

The difference matters at the edges of things. A cell that is 55% grassland and
45% forest is "grassland" by majority, giving n = 0.035 and discarding the
forest entirely. Area-averaging gives 0.064, which is much closer to the
resistance such a cell really presents. Majority resampling makes roughness
change in discrete jumps along class boundaries; averaging makes it vary
smoothly, and a smoothly varying friction field is also better behaved
numerically.

The dominant class is still computed and returned, because it is what makes the
output explicable — "this cell is n = 0.087 because it is mostly tree cover" is
auditable in a way that a bare number is not.

NOTE ON COMPOSITE-ROUGHNESS THEORY. Horton and Einstein's composite formula
weights n^1.5 by wetted perimeter, which is the correct treatment for
subdividing a single channel cross-section. It does not transfer to areal
averaging over a 2D cell, where the sub-cell patches are in parallel across the
flow rather than in series around a perimeter. Arithmetic area-weighting is what
2D flood models conventionally use, and it is what we use. Stated because it is
the kind of thing a hydraulics examiner will ask about.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")

WORLDCOVER_BASE = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com"
                   "/v200/2021/map")
WORLDCOVER_VERSION = "v200"
WORLDCOVER_YEAR = "2021"

# WorldCover tiles are 3 x 3 degrees, named by their south-west corner on a grid
# aligned to the equator and the prime meridian.
WC_TILE_DEG = 3

WGS84 = "EPSG:4326"

# -----------------------------------------------------------------------------
# class -> Manning's n
# -----------------------------------------------------------------------------
# Values are mid-range figures from the two standard references for overland and
# floodplain resistance:
#
#   Chow, V.T. (1959) Open-Channel Hydraulics, Table 5-6 ("Natural streams -
#       flood plains"), McGraw-Hill.
#   Arcement, G.J. & Schneider, V.R. (1989) Guide for Selecting Manning's
#       Roughness Coefficients for Natural Channels and Flood Plains, USGS
#       Water-Supply Paper 2339.
#
# Each entry records the published range as well as the value used, because the
# WIDTH of that range is the honest measure of how much of our uncertainty comes
# from roughness. `sensitivity_bounds` below turns those ranges into a low/high
# pair so the effect can be quantified instead of asserted.
#
#   code : (name, n_used, n_low, n_high, note)
WORLDCOVER_CLASSES: dict[int, tuple[str, float, float, float, str]] = {
    10: ("Tree cover", 0.100, 0.080, 0.160,
         "Chow: dense willows/heavy stand of timber 0.10-0.16. Dominant class "
         "on Himalayan valley sides below the treeline."),
    20: ("Shrubland", 0.060, 0.035, 0.070,
         "Chow: medium to dense brush 0.070; scattered brush 0.035."),
    30: ("Grassland", 0.035, 0.025, 0.050,
         "Chow: high grass 0.035, short grass 0.030."),
    40: ("Cropland", 0.040, 0.020, 0.050,
         "Chow: mature field crops 0.040; no crop 0.030."),
    50: ("Built-up", 0.080, 0.050, 0.150,
         "No consensus value. Buildings are unresolved obstructions at 30-90 m, "
         "so n absorbs their blockage; published urban 2D values span "
         "0.05-0.15. The upper end matters because our exposure counts are "
         "concentrated in exactly these cells."),
    60: ("Bare / sparse vegetation", 0.025, 0.020, 0.035,
         "Chow: smooth bare soil 0.020-0.030; gravel surfaces to 0.035."),
    70: ("Snow and ice", 0.020, 0.010, 0.030,
         "Smooth. Relevant to the Chamoli source zone, not to the routing "
         "reach."),
    80: ("Permanent water bodies", 0.040, 0.025, 0.055,
         "A COMPROMISE, and the least satisfactory entry here. This class is "
         "both the smooth reservoir surface (n ~ 0.030) and the boulder-bed "
         "Bhagirathi gorge (Chow: mountain stream with cobbles and boulders "
         "0.040-0.070). 0.040 sits between them. Override the channel "
         "explicitly via `channel_n` when the reach is known to be a "
         "steep boulder bed."),
    90: ("Herbaceous wetland", 0.050, 0.035, 0.080,
         "Chow: floodplain with scattered brush and heavy weeds."),
    95: ("Mangroves", 0.100, 0.070, 0.160,
         "Treated as dense timber. Not present in our Himalayan domains; "
         "included so the mapping is total over the WorldCover legend."),
    100: ("Moss and lichen", 0.025, 0.020, 0.035,
          "Thin ground cover over rock; treated as bare."),
}

# WorldCover uses 0 for no-data. Anything unmapped falls back to this, which is
# Chow's value for a clean, straight natural channel — a deliberately
# unremarkable choice, so a fallback that ends up dominating a domain shows up as
# an implausibly uniform friction field rather than as a plausible-looking one.
FALLBACK_N = 0.033

# Applied to the whole field for a debris flow. See the module docstring: this is
# a declared model of a different material, not a calibration.
#
# Sediment-laden flows present much higher resistance than clear water at the
# same depth. Published back-analyses of Himalayan debris flows use effective
# Manning n of 0.10-0.20 against 0.03-0.05 for water, i.e. a factor of roughly
# 3-4. We take 3.0 and report it, and the result is presented as a bracket over
# this factor rather than as a single simulation.
DEBRIS_FLOW_N_FACTOR = 3.0


# -----------------------------------------------------------------------------
# tiles
# -----------------------------------------------------------------------------

def worldcover_tile_id(lat: int, lon: int) -> str:
    """Tile name for the 3-degree cell whose south-west corner is (lat, lon)."""
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return (f"ESA_WorldCover_10m_{WORLDCOVER_YEAR}_{WORLDCOVER_VERSION}_"
            f"{ns}{abs(int(lat)):02d}{ew}{abs(int(lon)):03d}_Map")


def worldcover_tile_url(name: str) -> str:
    return f"/vsicurl/{WORLDCOVER_BASE}/{name}.tif"


def worldcover_tiles_for_bounds(bounds: tuple[float, float, float, float]
                                ) -> list[str]:
    """Tile names covering a geographic bbox (west, south, east, north)."""
    w, s, e, n = bounds
    d = WC_TILE_DEG
    lon0 = math.floor(w / d) * d
    lat0 = math.floor(s / d) * d
    lon1 = math.floor((e - 1e-9) / d) * d
    lat1 = math.floor((n - 1e-9) / d) * d
    return [worldcover_tile_id(la, lo)
            for la in range(lat0, lat1 + d, d)
            for lo in range(lon0, lon1 + d, d)]


# -----------------------------------------------------------------------------
# result container
# -----------------------------------------------------------------------------

@dataclass
class RoughnessField:
    """
    Manning's n on the computational grid, plus the evidence behind it.

    `dominant_class` is what makes a value explicable; `fraction` is what makes
    the domain describable in one line of a report ("62% tree cover, 11%
    built-up"); `low`/`high` are the sensitivity bounds built from the published
    ranges. All three exist so roughness can be defended rather than merely
    stated.
    """
    n: np.ndarray                          # (ny, nx) Manning's n, used
    dominant_class: np.ndarray | None = None   # (ny, nx) uint8 WorldCover code
    n_low: np.ndarray | None = None         # published lower bound per cell
    n_high: np.ndarray | None = None        # published upper bound per cell
    fraction: dict[int, float] = field(default_factory=dict)
    source: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def sensitivity_ratio(self) -> float:
        """
        Area-mean n_high / area-mean n_low.

        A single honest number for "how much could roughness alone move our
        answer". Wave celerity in the friction-dominated limit scales roughly as
        n^(-0.5)-ish, so a ratio of 2 is a substantial uncertainty in arrival
        time and must be shown as a band on the chart.
        """
        if self.n_low is None or self.n_high is None:
            return 1.0
        lo = float(self.n_low.mean())
        return float(self.n_high.mean()) / lo if lo > 0 else 1.0

    def summary(self) -> str:
        lines = [
            f"Manning n : {self.n.min():.3f} to {self.n.max():.3f} "
            f"(area mean {self.n.mean():.3f})",
            f"  source  : {self.source}",
        ]
        if self.fraction:
            lines.append("  cover   :")
            for code, frac in sorted(self.fraction.items(),
                                     key=lambda kv: -kv[1]):
                if frac < 0.001:
                    continue
                name = WORLDCOVER_CLASSES.get(code, ("unmapped",))[0]
                lines.append(f"      {frac * 100:5.1f}%  {name} ({code})")
        if self.n_low is not None:
            lines.append(
                f"  published range spans a factor of "
                f"{self.sensitivity_ratio:.2f} in area-mean n — this is the "
                f"roughness contribution to the uncertainty band")
        for note in self.notes:
            lines.append(f"  ! {note}")
        return "\n".join(lines)


# -----------------------------------------------------------------------------
# fetch
# -----------------------------------------------------------------------------

def fetch_landcover(bounds: tuple[float, float, float, float], *,
                    cache_dir: str | Path | None = None,
                    verbose: bool = True):
    """
    Read a geographic window from ESA WorldCover, mosaicking tiles as needed.

    Returns (uint8 class array, transform, crs). Class 0 marks cells no tile
    covered.

    Raises RuntimeError if no tile could be opened at all, so the caller can
    decide whether to fall back to a uniform n. That decision belongs to the
    caller and must be visible — silently substituting a constant would let a
    network failure masquerade as a roughness field.
    """
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.windows import from_bounds as window_from_bounds

    w, s, e, n = bounds
    names = worldcover_tiles_for_bounds(bounds)
    if not names:
        raise ValueError(f"no WorldCover tiles cover bounds {bounds}")

    cache_path = None
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        key = f"wc10_{w:.4f}_{s:.4f}_{e:.4f}_{n:.4f}".replace(".", "p")
        cache_path = cache_dir / f"{key}.tif"
        if cache_path.exists():
            if verbose:
                print(f"[cover] cache hit: {cache_path.name}")
            with rasterio.open(cache_path) as src:
                return src.read(1), src.transform, str(src.crs)

    res = None
    for name in names:
        try:
            with rasterio.open(worldcover_tile_url(name)) as src:
                res = src.res[0]
                break
        except Exception:
            continue
    if res is None:
        raise RuntimeError(
            f"could not open any WorldCover tile for {bounds}. Tried: {names}. "
            f"Check network access to {WORLDCOVER_BASE}.")

    nx = int(round((e - w) / res))
    ny = int(round((n - s) / res))
    w_snap = math.floor(w / res) * res
    n_snap = math.ceil(n / res) * res
    dst_transform = from_origin(w_snap, n_snap, res, res)
    mosaic = np.zeros((ny, nx), dtype=np.uint8)

    for name in names:
        try:
            with rasterio.open(worldcover_tile_url(name)) as src:
                tw, ts, te, tn = src.bounds
                iw, is_, ie, in_ = max(w, tw), max(s, ts), min(e, te), min(n, tn)
                if iw >= ie or is_ >= in_:
                    continue
                win = window_from_bounds(iw, is_, ie, in_, src.transform)
                data = src.read(1, window=win, boundless=True, fill_value=0)
                col0 = int(round((iw - w_snap) / res))
                row0 = int(round((n_snap - in_) / res))
                bh, bw = data.shape
                r1, c1 = min(row0 + bh, ny), min(col0 + bw, nx)
                if r1 <= row0 or c1 <= col0:
                    continue
                block = data[:r1 - row0, :c1 - col0]
                target = mosaic[row0:r1, col0:c1]
                np.copyto(target, block, where=block > 0)
                if verbose:
                    print(f"[cover] {name}: read {block.shape}")
        except Exception as exc:
            if verbose:
                print(f"[cover] {name}: unavailable ({type(exc).__name__})")

    n_gap = int((mosaic == 0).sum())
    if verbose:
        print(f"[cover] mosaic {mosaic.shape}, {n_gap:,} unclassified "
              f"({100 * n_gap / mosaic.size:.3f}%)")
    if n_gap == mosaic.size:
        raise RuntimeError(f"WorldCover returned no data anywhere for {bounds}")

    if cache_path is not None:
        with rasterio.open(
            cache_path, "w", driver="GTiff", height=ny, width=nx, count=1,
            dtype="uint8", crs=WGS84, transform=dst_transform, nodata=0,
            compress="deflate", tiled=True,
        ) as dst:
            dst.write(mosaic, 1)
        if verbose:
            print(f"[cover] cached -> {cache_path}")

    return mosaic, dst_transform, WGS84


# -----------------------------------------------------------------------------
# class array -> n field on the computational grid
# -----------------------------------------------------------------------------

def _lut(index: int) -> np.ndarray:
    """
    256-entry lookup table mapping a WorldCover byte code to a float.

    index 1 -> n used, 2 -> published low, 3 -> published high.

    A LUT rather than a chain of comparisons because the source array has tens of
    millions of pixels and `table[classes]` is a single vectorised gather.
    """
    table = np.full(256, FALLBACK_N, dtype=np.float32)
    for code, entry in WORLDCOVER_CLASSES.items():
        table[code] = entry[index]
    return table


def manning_from_landcover(grid, *, cache_dir: str | Path | None = None,
                           channel_n: float | None = None,
                           debris_flow: bool = False,
                           fallback_n: float = FALLBACK_N,
                           verbose: bool = True) -> RoughnessField:
    """
    Build a Manning's n field matching a TerrainGrid, cell for cell.

    Parameters
    ----------
    grid        : TerrainGrid — supplies the target CRS, transform and shape
    channel_n   : override for WorldCover class 80 (permanent water). Set this
                  when the reach is a known boulder-bed mountain stream, where
                  the class-80 compromise value of 0.040 is too low.
    debris_flow : multiply the whole field by DEBRIS_FLOW_N_FACTOR. For Chamoli.
    fallback_n  : value for unclassified pixels.

    On network failure this raises. It does not silently return a constant —
    see `roughness_for` for the fallback path, which is explicit and reports
    itself.
    """
    from rasterio.enums import Resampling
    from rasterio.warp import reproject

    from .dem import geographic_bounds_for

    ny, nx = grid.z.shape
    bounds = geographic_bounds_for(grid.bounds, grid.crs)
    classes, src_transform, src_crs = fetch_landcover(
        bounds, cache_dir=cache_dir, verbose=verbose)

    n_lut = _lut(1)
    lo_lut = _lut(2)
    hi_lut = _lut(3)
    if channel_n is not None:
        n_lut[80] = channel_n
        # Widen the published bracket to contain the override, so the sensitivity
        # bounds cannot end up excluding the value we actually used.
        lo_lut[80] = min(lo_lut[80], channel_n)
        hi_lut[80] = max(hi_lut[80], channel_n)
    n_lut[0] = lo_lut[0] = hi_lut[0] = fallback_n

    def warp(src_float, resampling):
        dst = np.full((ny, nx), np.nan, dtype=np.float32)
        reproject(
            source=src_float, destination=dst,
            src_transform=src_transform, src_crs=src_crs,
            dst_transform=grid.transform, dst_crs=grid.crs,
            dst_nodata=np.nan, resampling=resampling)
        return dst

    # Area-weighted average of n over the fine pixels falling in each coarse
    # cell. See the module docstring for why this and not majority.
    n_field = warp(n_lut[classes], Resampling.average)
    n_low = warp(lo_lut[classes], Resampling.average)
    n_high = warp(hi_lut[classes], Resampling.average)

    # Dominant class, for explicability. Mode resampling on the raw codes.
    dom = np.zeros((ny, nx), dtype=np.uint8)
    reproject(
        source=classes, destination=dom,
        src_transform=src_transform, src_crs=src_crs,
        dst_transform=grid.transform, dst_crs=grid.crs,
        src_nodata=0, dst_nodata=0, resampling=Resampling.mode)

    notes = []
    for name, arr in (("n", n_field), ("n_low", n_low), ("n_high", n_high)):
        bad = ~np.isfinite(arr)
        if bad.any():
            # Can happen at the very edge of the domain if the padded geographic
            # window still misses a sliver. Fill rather than hand a NaN to the
            # solver, where it would poison the whole run within a few steps.
            arr[bad] = fallback_n
            if name == "n":
                notes.append(
                    f"{int(bad.sum()):,} cells had no land-cover overlap and "
                    f"were set to the fallback n = {fallback_n:g}")

    if debris_flow:
        n_field *= DEBRIS_FLOW_N_FACTOR
        n_low *= DEBRIS_FLOW_N_FACTOR
        n_high *= DEBRIS_FLOW_N_FACTOR
        notes.append(
            f"debris-flow resistance applied: all n multiplied by "
            f"{DEBRIS_FLOW_N_FACTOR:g}. This models a sediment slurry, not "
            f"water; results must be presented as a bracket over this factor.")

    codes, counts = np.unique(dom, return_counts=True)
    fraction = {int(c): float(k) / dom.size for c, k in zip(codes, counts)}

    rf = RoughnessField(
        n=n_field.astype(np.float64),
        dominant_class=dom,
        n_low=n_low.astype(np.float64),
        n_high=n_high.astype(np.float64),
        fraction=fraction,
        source=(f"ESA WorldCover 10 m {WORLDCOVER_YEAR} {WORLDCOVER_VERSION} "
                f"(CC-BY 4.0); n from Chow 1959 Table 5-6 and USGS WSP 2339"),
        notes=notes,
    )
    # Deliberately does NOT print rf.summary(). `verbose` governs progress
    # reporting on a slow S3 fetch — the caller decides whether the result gets
    # reported, and printing it here as well duplicated the whole block in
    # scripts/check_hydrology.py.
    return rf


def roughness_for(grid, *, cache_dir: str | Path | None = None,
                  channel_n: float | None = None,
                  debris_flow: bool = False,
                  uniform_n: float = FALLBACK_N,
                  allow_fallback: bool = True,
                  verbose: bool = True) -> RoughnessField:
    """
    `manning_from_landcover` with an explicit, self-reporting fallback.

    If WorldCover cannot be reached, returns a uniform field whose `notes`
    record that this happened and whose `source` says so. The run still
    completes — a demo must not die because an S3 bucket is slow — but nothing
    downstream can mistake a constant for a derived roughness field, because the
    provenance travels with the array.

    Set allow_fallback=False for validation runs, where silently substituting a
    constant would invalidate the comparison.
    """
    try:
        return manning_from_landcover(
            grid, cache_dir=cache_dir, channel_n=channel_n,
            debris_flow=debris_flow, verbose=verbose)
    except Exception as exc:
        if not allow_fallback:
            raise
        n = uniform_n * (DEBRIS_FLOW_N_FACTOR if debris_flow else 1.0)
        if verbose:
            print(f"[cover] FALLBACK: {type(exc).__name__}: {exc}")
            print(f"[cover] using uniform n = {n:g}")
        return RoughnessField(
            n=np.full(grid.z.shape, n, dtype=np.float64),
            source=f"UNIFORM n = {n:g} (land cover unavailable)",
            notes=[f"land cover fetch failed ({type(exc).__name__}: {exc}); "
                   f"roughness is a single constant, NOT derived from land "
                   f"cover. Do not present this run as land-cover based."],
        )

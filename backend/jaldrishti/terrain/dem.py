"""
DEM acquisition and hydrological conditioning.

DATA SOURCE: COPERNICUS DEM GLO-30
----------------------------------
30 m global DEM, derived from TanDEM-X radar interferometry, distributed as
Cloud-Optimized GeoTIFF on AWS open data with NO authentication required.

That last property decided it. The alternatives all gate on account approval we
do not have and cannot wait for:
  * NASA Earthdata (SRTM/NASADEM) — registration required
  * OpenTopography — API key required
  * Google Earth Engine — approval can take days
Copernicus needs none of them, and it is the better DEM anyway: TanDEM-X has far
fewer voids than SRTM and no SRTM-style radar shadow gaps in steep Himalayan
terrain, which is exactly where our domains are.

Being a real COG with internal tiling and overviews also means GDAL can read just
our domain window over HTTP. We never download a whole 1-degree tile.

THE LIMITATION THAT MATTERS MOST, AND WHY IT SHAPES THE ARCHITECTURE
--------------------------------------------------------------------
Radar does not penetrate water. Copernicus DEM was acquired 2011-2015, so for any
reservoir that existed then — Tehri was commissioned in 2006 — the DEM records the
RESERVOIR WATER SURFACE as a flat plateau, not the valley floor beneath it. The
bathymetry is simply absent.

Two consequences, and neither is optional:

  1. A reservoir volume computed by integrating (FRL - DEM) is a LOWER BOUND, and
     a bad one. The released volume must come from the published gross storage
     figure (CWC / NRLD), not from the terrain.
  2. Initialising the reservoir by setting water level = FRL over the DEM would
     give almost zero depth, because the DEM surface already IS the water. The
     reservoir would appear empty.

So we do not resolve the reservoir on the grid at all. The far-field domain starts
at the dam, and the breach enters as an inflow hydrograph derived from the
published storage-elevation relationship (or from the SPH near-field model). The
DEM is used only for downstream routing, which is what it can actually support.

Stating this is not a weakness in the submission. Every serious dam-break study
handles reservoir volume this way, and a jury that asks "where did you get the
bathymetry?" is asking the right question — we should have the answer ready rather
than a filled contour that quietly assumes it away.

OTHER STATED LIMITATIONS
------------------------
  * GLO-30 is a DSM, not a DTM: it includes vegetation and buildings. In a forested
    Himalayan valley the apparent bed sits above the true bed by roughly the canopy
    height. Depths are correspondingly biased.
  * A 30 m cell cannot resolve a gorge narrower than about 90 m. The Bhagirathi is
    locally narrower than that, so the modelled channel is wider and shallower than
    the real one, which spreads and slows the wave.
  * Vertical accuracy is specified at better than 4 m (90% linear error). Flood
    depths below that are not meaningful, which is the quantitative reason our
    arrival-time reporting threshold sits at 0.1 m rather than at 1 mm.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# GDAL environment for anonymous COG access over HTTPS. Set before rasterio is
# used; harmless if rasterio is already imported, because rasterio.Env re-reads
# these. Kept as module-level side effects on purpose: forgetting them produces a
# confusing 403 rather than an obvious error.
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
os.environ.setdefault("GDAL_HTTP_MULTIPLEX", "YES")
os.environ.setdefault("GDAL_HTTP_VERSION", "2")
os.environ.setdefault("VSI_CACHE", "TRUE")
os.environ.setdefault("VSI_CACHE_SIZE", "100000000")     # 100 MB block cache

COP30_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"
COP90_BASE = "https://copernicus-dem-90m.s3.amazonaws.com"

WGS84 = "EPSG:4326"

# Copernicus voids and ocean. nodata is not set in the file headers, so we mask by
# value; no real terrain on Earth is below -500 m except a few closed basins none
# of our domains touch.
VOID_BELOW = -500.0


# ---------------------------------------------------------------------------
# tiles
# ---------------------------------------------------------------------------

def tile_id(lat: int, lon: int, *, arcsec: int = 10) -> str:
    """
    Copernicus DEM tile name for the 1-degree cell whose SOUTH-WEST corner is
    (lat, lon).

    `arcsec` is the product's naming code, not a resolution in arcseconds:
    10 -> GLO-30 (1 arcsec, ~30 m), 30 -> GLO-90 (3 arcsec, ~90 m).
    """
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return (f"Copernicus_DSM_COG_{arcsec}_"
            f"{ns}{abs(int(lat)):02d}_00_{ew}{abs(int(lon)):03d}_00_DEM")


def tile_url(name: str, *, resolution: str = "30m") -> str:
    base = COP30_BASE if resolution == "30m" else COP90_BASE
    return f"/vsicurl/{base}/{name}/{name}.tif"


def tiles_for_bounds(bounds: tuple[float, float, float, float],
                     *, resolution: str = "30m") -> list[str]:
    """
    Tile names covering a geographic bbox (west, south, east, north) in degrees.

    Tiles are named by their south-west corner, so we floor the lower bounds and
    step by whole degrees. The upper bound is treated as exclusive when it lands
    exactly on a degree line, so a bbox of (78, 30, 79, 31) asks for one tile and
    not four.
    """
    w, s, e, n = bounds
    arcsec = 10 if resolution == "30m" else 30
    lon0, lat0 = math.floor(w), math.floor(s)
    lon1 = math.ceil(e) - 1 if float(e).is_integer() else math.floor(e)
    lat1 = math.ceil(n) - 1 if float(n).is_integer() else math.floor(n)
    return [tile_id(la, lo, arcsec=arcsec)
            for la in range(lat0, lat1 + 1)
            for lo in range(lon0, lon1 + 1)]


# ---------------------------------------------------------------------------
# grid container
# ---------------------------------------------------------------------------

@dataclass
class TerrainGrid:
    """
    A metric, square-celled elevation grid — the form the solver consumes.

    The solver needs exactly three things: a 2D bed array, a single cell size in
    metres, and no NaNs. Everything else here exists so the export layer can
    georeference the result.

    `mask_valid` is False where the DEM had a void. Those cells are filled for
    the solver's benefit (a NaN would poison the whole run) but flagged so the
    output can be honest about which cells are interpolated.
    """
    z: np.ndarray                     # (ny, nx) bed elevation, metres
    dx: float                         # cell size, metres (square cells)
    crs: str
    transform: object                 # affine.Affine
    mask_valid: np.ndarray | None = None
    source: str = "Copernicus DEM GLO-30"
    conditioning: list[str] | None = None

    def __post_init__(self):
        if self.conditioning is None:
            self.conditioning = []

    @property
    def shape(self) -> tuple[int, int]:
        return self.z.shape

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        from rasterio.transform import array_bounds
        ny, nx = self.z.shape
        return array_bounds(ny, nx, self.transform)

    def summary(self) -> str:
        ny, nx = self.z.shape
        void = (0 if self.mask_valid is None
                else int((~self.mask_valid).sum()))
        return (f"{nx} x {ny} cells at {self.dx:g} m  ({nx * ny:,} cells, "
                f"{nx * self.dx / 1000:.1f} x {ny * self.dx / 1000:.1f} km)\n"
                f"  crs        : {self.crs}\n"
                f"  elevation  : {self.z.min():.1f} to {self.z.max():.1f} m\n"
                f"  voids      : {void:,} cells "
                f"({100 * void / (nx * ny):.3f}%)\n"
                f"  source     : {self.source}\n"
                f"  conditioned: {', '.join(self.conditioning) or 'raw'}")

    def to_geotiff(self, path: str | Path, *, array: np.ndarray | None = None,
                   nodata: float = -9999.0) -> Path:
        """
        Write to GeoTIFF, deflate-compressed and tiled.

        Used constantly for debugging: per CLAUDE.md, when a run misbehaves the
        fix is to dump the field and open it in QGIS, not to squint at scalars.
        """
        import rasterio
        a = self.z if array is None else array
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(
            path, "w", driver="GTiff",
            height=a.shape[0], width=a.shape[1], count=1,
            dtype="float32", crs=self.crs, transform=self.transform,
            nodata=nodata, compress="deflate", tiled=True,
            blockxsize=256, blockysize=256,
        ) as dst:
            dst.write(np.asarray(a, dtype="float32"), 1)
        return path


# ---------------------------------------------------------------------------
# bounds helpers
# ---------------------------------------------------------------------------

def bounds_from_points(points, margin_km: float = 5.0
                       ) -> tuple[float, float, float, float]:
    """
    Geographic bbox enclosing (lat, lon) pairs with a margin.

    Preferable to a hand-written rectangle because it is derived from the places
    we actually have to report on — the dam and the settlements downstream — so
    the domain cannot silently exclude one of them.
    """
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    lat_c = 0.5 * (min(lats) + max(lats))
    dlat = margin_km / 111.32
    dlon = margin_km / (111.32 * max(0.2, math.cos(math.radians(lat_c))))
    return (min(lons) - dlon, min(lats) - dlat,
            max(lons) + dlon, max(lats) + dlat)


def utm_crs_for(lat: float, lon: float) -> str:
    """EPSG code of the UTM zone containing a point."""
    zone = int((lon + 180.0) / 6.0) + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"


def metric_extent_for(points, dst_crs: str, dx: float,
                      margin_km: float = 8.0
                      ) -> tuple[float, float, float, float]:
    """
    The computational rectangle in metres, snapped to the cell lattice.

    We define the output rectangle FIRST and fetch terrain to fill it, rather than
    reprojecting a lat/lon box and accepting whatever rectangle falls out. The
    difference is not cosmetic: a lat/lon rectangle maps to a curved quadrilateral
    in UTM, so the bounding box around it has empty corners. Filling those corners
    by interpolation invents terrain and inflates the void count — 4.5% instead of
    the true 0.1% — which would make the interpolated-cell flag useless.

    Snapping to whole multiples of dx means the 30 m and 90 m grids are nested and
    directly comparable, so a resolution-sensitivity figure is a like-for-like
    comparison rather than two differently-aligned runs.
    """
    from pyproj import Transformer
    tr = Transformer.from_crs(WGS84, dst_crs, always_xy=True)
    xs, ys = zip(*(tr.transform(lon, lat) for lat, lon in points))
    m = margin_km * 1000.0
    xmin = math.floor((min(xs) - m) / dx) * dx
    ymin = math.floor((min(ys) - m) / dx) * dx
    xmax = math.ceil((max(xs) + m) / dx) * dx
    ymax = math.ceil((max(ys) + m) / dx) * dx
    return (xmin, ymin, xmax, ymax)


def geographic_bounds_for(extent: tuple[float, float, float, float],
                          src_crs: str, *, pad_deg: float = 0.01
                          ) -> tuple[float, float, float, float]:
    """
    Geographic bbox guaranteed to cover a metric extent.

    `transform_bounds` with densification samples along the edges instead of only
    the corners, which matters because the edges bow outward: the extreme latitude
    of a UTM rectangle's northern edge is at its middle, not at either corner.
    Corner-only transformation would clip a sliver off the top and leave a genuine
    strip of missing data along it.
    """
    from rasterio.warp import transform_bounds
    w, s, e, n = transform_bounds(src_crs, WGS84, *extent, densify_pts=64)
    return (w - pad_deg, s - pad_deg, e + pad_deg, n + pad_deg)


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

def fetch_dem(bounds: tuple[float, float, float, float],
              *, resolution: str = "30m",
              cache_dir: str | Path | None = None,
              verbose: bool = True):
    """
    Read a geographic window from Copernicus DEM, mosaicking tiles as needed.

    Returns (array, transform, crs). Missing tiles (ocean) are skipped and left as
    voids rather than raising, because a coastal domain legitimately has some.

    The result is cached as a GeoTIFF keyed by rounded bounds, so re-running a
    scenario does not re-fetch over the network.
    """
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.windows import from_bounds as window_from_bounds

    w, s, e, n = bounds
    names = tiles_for_bounds(bounds, resolution=resolution)
    if not names:
        raise ValueError(f"no Copernicus tiles cover bounds {bounds}")

    cache_path = None
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        key = f"cop{resolution}_{w:.4f}_{s:.4f}_{e:.4f}_{n:.4f}".replace(".", "p")
        cache_path = cache_dir / f"{key}.tif"
        if cache_path.exists():
            if verbose:
                print(f"[dem] cache hit: {cache_path.name}")
            with rasterio.open(cache_path) as src:
                a = src.read(1)
                return a, src.transform, str(src.crs)

    # Copernicus pixel size in degrees, from the product spec: 1 arcsec for
    # GLO-30. Taken from the first readable tile rather than assumed, so a product
    # change cannot silently misalign the mosaic.
    res = None
    for name in names:
        try:
            with rasterio.open(tile_url(name, resolution=resolution)) as src:
                res = src.res[0]
                break
        except Exception:
            continue
    if res is None:
        raise RuntimeError(
            f"could not open any Copernicus {resolution} tile for {bounds}. "
            f"Tried: {names}. Check network access to the AWS open-data bucket.")

    # Destination grid, snapped to the source pixel lattice so the mosaic needs no
    # resampling and introduces no interpolation error at this stage.
    nx = int(round((e - w) / res))
    ny = int(round((n - s) / res))
    w_snap = math.floor(w / res) * res
    n_snap = math.ceil(n / res) * res
    dst_transform = from_origin(w_snap, n_snap, res, res)
    mosaic = np.full((ny, nx), np.nan, dtype=np.float32)

    for name in names:
        url = tile_url(name, resolution=resolution)
        try:
            with rasterio.open(url) as src:
                # Intersect requested bounds with this tile.
                tw, ts, te, tn = src.bounds
                iw, is_, ie, in_ = max(w, tw), max(s, ts), min(e, te), min(n, tn)
                if iw >= ie or is_ >= in_:
                    continue
                win = window_from_bounds(iw, is_, ie, in_, src.transform)
                data = src.read(1, window=win, boundless=True,
                                fill_value=np.nan).astype(np.float32)
                # Where does this block land in the mosaic?
                col0 = int(round((iw - w_snap) / res))
                row0 = int(round((n_snap - in_) / res))
                bh, bw = data.shape
                r1, c1 = min(row0 + bh, ny), min(col0 + bw, nx)
                if r1 <= row0 or c1 <= col0:
                    continue
                block = data[:r1 - row0, :c1 - col0]
                target = mosaic[row0:r1, col0:c1]
                np.copyto(target, block, where=np.isfinite(block))
                if verbose:
                    print(f"[dem] {name}: read {block.shape}")
        except Exception as exc:                      # missing tile = ocean
            if verbose:
                print(f"[dem] {name}: unavailable ({type(exc).__name__}) — "
                      f"treated as void")

    mosaic[mosaic < VOID_BELOW] = np.nan
    n_void = int(np.isnan(mosaic).sum())
    if verbose:
        print(f"[dem] mosaic {mosaic.shape}, {n_void:,} void cells "
              f"({100 * n_void / mosaic.size:.3f}%)")
    if n_void == mosaic.size:
        raise RuntimeError(
            f"every cell is void for bounds {bounds} — wrong hemisphere sign, or "
            f"an all-ocean domain?")

    if cache_path is not None:
        with rasterio.open(
            cache_path, "w", driver="GTiff", height=ny, width=nx, count=1,
            dtype="float32", crs="EPSG:4326", transform=dst_transform,
            nodata=np.nan, compress="deflate", tiled=True,
        ) as dst:
            dst.write(mosaic, 1)
        if verbose:
            print(f"[dem] cached -> {cache_path}")

    return mosaic, dst_transform, "EPSG:4326"


# ---------------------------------------------------------------------------
# reproject
# ---------------------------------------------------------------------------

def to_metric_grid(array: np.ndarray, src_transform, src_crs: str,
                   *, dst_crs: str, dx: float,
                   extent: tuple[float, float, float, float] | None = None,
                   resampling: str = "bilinear",
                   verbose: bool = True) -> TerrainGrid:
    """
    Reproject a geographic DEM onto a square metric grid at cell size `dx`.

    Square cells in metres are not a nicety: the solver's flux and CFL logic
    assumes dx == dy, and a geographic grid has cells that are ~13% narrower in x
    than in y at 30 degrees latitude. Running the solver on degrees would stretch
    the flood in one direction by that factor.

    Pass `extent` (xmin, ymin, xmax, ymax in dst_crs) to pin the output rectangle.
    Without it the rectangle is derived from the reprojected footprint, which
    leaves empty corners — see metric_extent_for.

    Bilinear resampling by default. Nearest would preserve the original values
    exactly but produce stair-stepped slopes, and a bed-slope source term
    differentiates the bed — stair steps become spurious accelerations.
    """
    from rasterio.enums import Resampling
    from rasterio.transform import array_bounds, from_origin
    from rasterio.warp import calculate_default_transform, reproject

    ny_src, nx_src = array.shape
    src_bounds = array_bounds(ny_src, nx_src, src_transform)

    if extent is None:
        dst_transform, nx, ny = calculate_default_transform(
            src_crs, dst_crs, nx_src, ny_src, *src_bounds, resolution=dx)
    else:
        xmin, ymin, xmax, ymax = extent
        nx = int(round((xmax - xmin) / dx))
        ny = int(round((ymax - ymin) / dx))
        dst_transform = from_origin(xmin, ymax, dx, dx)

    dst = np.full((ny, nx), np.nan, dtype=np.float32)
    reproject(
        source=np.asarray(array, dtype=np.float32),
        destination=dst,
        src_transform=src_transform, src_crs=src_crs, src_nodata=np.nan,
        dst_transform=dst_transform, dst_crs=dst_crs, dst_nodata=np.nan,
        resampling=getattr(Resampling, resampling),
    )

    mask_valid = np.isfinite(dst)
    if verbose:
        print(f"[dem] reprojected to {dst_crs} at {dx:g} m -> {nx} x {ny} "
              f"({nx * ny:,} cells)")
    return TerrainGrid(z=dst, dx=float(dx), crs=dst_crs,
                       transform=dst_transform, mask_valid=mask_valid,
                       conditioning=[f"reprojected {src_crs}->{dst_crs} "
                                     f"({resampling}, {dx:g} m)"])


# ---------------------------------------------------------------------------
# conditioning
# ---------------------------------------------------------------------------

def fill_voids(grid: TerrainGrid, *, verbose: bool = True) -> TerrainGrid:
    """
    Replace DEM voids with an interpolated surface.

    A single NaN anywhere in the bed poisons the entire run: it propagates through
    the flux computation into the CFL estimate and every cell goes NaN within a
    few steps. So this is mandatory, not optional.

    `mask_valid` is preserved so the output can mark interpolated cells rather
    than presenting them as measured.
    """
    bad = ~np.isfinite(grid.z)
    n_bad = int(bad.sum())
    if n_bad == 0:
        return grid

    from scipy import ndimage
    # Nearest-neighbour fill: with voids this sparse, a fancier interpolant would
    # imply precision we do not have. distance_transform_edt returns, for each
    # void cell, the index of the closest valid cell.
    idx = ndimage.distance_transform_edt(
        bad, return_distances=False, return_indices=True)
    z = grid.z.copy()
    z[bad] = grid.z[tuple(i[bad] for i in idx)]

    if verbose:
        print(f"[dem] filled {n_bad:,} void cells by nearest neighbour")
    return TerrainGrid(
        z=z, dx=grid.dx, crs=grid.crs, transform=grid.transform,
        mask_valid=~bad if grid.mask_valid is None else grid.mask_valid & ~bad,
        source=grid.source,
        conditioning=list(grid.conditioning) + [f"filled {n_bad} voids (nearest)"],
    )


def fill_depressions(grid: TerrainGrid, *, max_fill_m: float | None = None,
                     verbose: bool = True) -> TerrainGrid:
    """
    Fill closed depressions by grayscale morphological reconstruction.

    WHY THIS IS LESS AGGRESSIVE THAN IN A NORMAL HYDROLOGY PIPELINE
    ---------------------------------------------------------------
    Classic D8 flow routing cannot tolerate a single pit, so hydrology pipelines
    fill everything. A shallow water solver has no such problem: water that runs
    into a real depression fills it and stops, which is what real water does. Over-
    filling would actively destroy information — a filled depression cannot store
    water, so the flood arrives downstream too early and too large.

    What we do need to remove are the SPURIOUS one- and two-cell pits that radar
    DEMs produce as speckle noise. Those trap water that should have kept moving,
    and at 30 m there are thousands of them.

    So `max_fill_m` caps how deep a depression may be before we leave it alone: a
    0.5-2 m cap removes speckle while preserving real valley-floor storage. Pass
    None to fill everything (classic behaviour) only if you know why you want it.
    """
    from skimage.morphology import reconstruction

    z = np.asarray(grid.z, dtype=np.float64)
    if not np.isfinite(z).all():
        raise ValueError("fill_depressions requires a void-free grid; "
                         "call fill_voids first")

    # Reconstruction by erosion from a seed that is high everywhere except the
    # border. The result is the lowest surface that is >= z and has no interior
    # minima: exactly the depression-filled DEM.
    seed = np.full_like(z, z.max())
    seed[0, :] = z[0, :]
    seed[-1, :] = z[-1, :]
    seed[:, 0] = z[:, 0]
    seed[:, -1] = z[:, -1]
    filled = reconstruction(seed, z, method="erosion")

    depth = filled - z
    if max_fill_m is not None:
        # Only accept the fill where the depression was shallow. A depression
        # deeper than the cap is judged real and left as terrain.
        deep = depth > max_fill_m
        # All-or-nothing per connected depression, not per cell: partially filling
        # a depression would leave an unphysical shelf part-way up its side.
        from scipy import ndimage
        lab, n_lab = ndimage.label(depth > 0)
        if n_lab:
            keeps_deep = ndimage.labeled_comprehension(
                deep, lab, np.arange(1, n_lab + 1), np.any, bool, False)
            reject = np.zeros(n_lab + 1, dtype=bool)
            reject[1:] = keeps_deep
            filled = np.where(reject[lab], z, filled)
            depth = filled - z

    n_filled = int((depth > 0).sum())
    total = float(depth.sum()) * grid.dx * grid.dx
    if verbose:
        cap = "uncapped" if max_fill_m is None else f"cap {max_fill_m:g} m"
        print(f"[dem] filled {n_filled:,} depression cells ({cap}), "
              f"max {depth.max():.2f} m, "
              f"{total / 1e6:.3f} x 10^6 m^3 of storage removed")

    note = (f"depressions filled ({n_filled} cells, "
            f"cap {'none' if max_fill_m is None else f'{max_fill_m:g} m'})")
    return TerrainGrid(
        z=filled.astype(np.float32), dx=grid.dx, crs=grid.crs,
        transform=grid.transform, mask_valid=grid.mask_valid,
        source=grid.source, conditioning=list(grid.conditioning) + [note],
    )


def prepare_terrain(*, dst_crs: str, dx: float,
                    points=None,
                    extent: tuple[float, float, float, float] | None = None,
                    bounds: tuple[float, float, float, float] | None = None,
                    margin_km: float = 8.0,
                    resolution: str = "30m",
                    cache_dir: str | Path | None = None,
                    max_fill_m: float | None = 2.0,
                    verbose: bool = True) -> TerrainGrid:
    """
    The whole pipeline: fetch -> reproject -> fill voids -> despeckle pits.

    This is what a scenario calls. The returned grid is guaranteed finite and has
    square metric cells, i.e. it is directly consumable by SWE2D.

    Give it EITHER `points` (a list of (lat, lon) the domain must contain — the dam
    and every settlement we report on) OR an explicit metric `extent`. Deriving the
    domain from the points we have to report on is the safer default, because it
    cannot silently leave one of them outside the grid.

    `bounds` overrides the geographic fetch window; normally it is computed to
    cover `extent` with a margin and there is no reason to set it by hand.
    """
    if extent is None:
        if points is None:
            raise ValueError("prepare_terrain needs points= or extent=")
        extent = metric_extent_for(points, dst_crs, dx, margin_km=margin_km)
        if verbose:
            print(f"[dem] extent from {len(points)} points, {margin_km:g} km "
                  f"margin: {extent[0]:.0f} {extent[1]:.0f} "
                  f"{extent[2]:.0f} {extent[3]:.0f}  ({dst_crs})")

    if bounds is None:
        bounds = geographic_bounds_for(extent, dst_crs)

    array, transform, crs = fetch_dem(
        bounds, resolution=resolution, cache_dir=cache_dir, verbose=verbose)
    grid = to_metric_grid(array, transform, crs, dst_crs=dst_crs, dx=dx,
                          extent=extent, verbose=verbose)
    grid = fill_voids(grid, verbose=verbose)
    grid = fill_depressions(grid, max_fill_m=max_fill_m, verbose=verbose)
    return grid

"""
Sentinel-1 SAR flood observation via Google Earth Engine.

WHAT THIS IS, AND WHY IT EARNS ITS PLACE
----------------------------------------
Everything else in JALDRISHTI is a forward model: given a breach, predict the
flood. This module is the one piece of INDEPENDENT OBSERVATION — it asks the
satellite record what the ground actually looked like, and hands back a flood
extent nobody's solver produced. For the Rishi Ganga / Chamoli scenario that is
worth a great deal: it lets us overlay "what our model routes" on "what Sentinel-1
saw," and a jury trusts a model that is willing to be checked against reality far
more than one that only ever shows its own output.

WHY SAR, AND WHY SENTINEL-1 SPECIFICALLY
----------------------------------------
Optical satellites (Sentinel-2, Landsat) cannot see through cloud, and a
Himalayan disaster in February is under cloud. Synthetic Aperture Radar sees
through cloud and works day or night, because it supplies its own illumination.
Sentinel-1 (ESA, C-band, 5.4 GHz) is free, has a 6-12 day repeat over India, and
its Ground Range Detected (GRD) product is preprocessed by Google Earth Engine to
analysis-ready backscatter (thermal-noise removal, radiometric calibration,
terrain correction). We use the VV polarisation: smooth open water is a near-
specular reflector, so it bounces the radar away from the sensor and returns very
LOW backscatter — water shows up dark. A flood is therefore "pixels that turned
dark between a before image and an after image."

THE METHOD: CHANGE DETECTION, NOT THRESHOLDING A SINGLE IMAGE
-------------------------------------------------------------
This is the UN-SPIDER / Sentinel-1 recommended practice, chosen because it is the
one every remote-sensing reviewer will recognise:

  1. Take a PRE-event stack (median over a quiet window before the event) and a
     POST-event stack (median over a window starting on the event date). Median
     over several passes suppresses the salt-and-pepper speckle inherent to SAR
     without a dedicated speckle filter erasing real edges.
  2. Form the ratio  pre / post  (a difference in dB space). Where the after
     image is much darker than before, the ratio is high -> newly inundated.
  3. Threshold the ratio. A pixel newly darker by more than THRESHOLD_DB is a
     flood candidate.
  4. REFINE, because raw SAR flood maps are notoriously false-positive-prone:
       * remove JRC permanent water (a river is not a flood),
       * remove steep slopes (SAR layover/shadow on Himalayan walls mimics water;
         flood water does not sit on a 15 deg slope anyway),
       * remove tiny specks (connected-pixel count) that are residual speckle.

WHAT WE DELIBERATELY DO NOT CLAIM
---------------------------------
  * This detects STANDING WATER. The Chamoli event was a fast debris flow that had
    largely passed within hours; the 6-12 day Sentinel-1 repeat may miss the peak
    entirely and instead capture residual ponding, the lake that formed behind the
    deposits, and scoured/wet valley floor. We report it as "SAR-observed surface
    change consistent with inundation/wetting," not "the flood."
  * SAR backscatter over rough, wind-roughened, or sediment-laden water can be
    HIGH, not low, so a violent debris flow is exactly the case where the dark-
    water assumption is weakest. Stated plainly, not hidden.
  * Radiometric terrain flattening in steep terrain is imperfect; residual
    topographic backscatter is the dominant error source here, which is why the
    slope mask is not optional.

EXPORT DISCIPLINE (HARD CONSTRAINT)
-----------------------------------
Results are exported with ee.batch.Export.image.toDrive() ONLY. The Community /
non-commercial Earth Engine tier this project uses has NO billing account, so
Export.image.toCloudStorage() fails. This is enforced here and must never be
"fixed" by switching to Cloud Storage.

AUTHENTICATION
--------------
ee.Initialize() needs credentials and a registered project; it is therefore NOT
called at import time (importing this module must stay side-effect-free and
testable offline). Call initialize() explicitly, or pass an already-initialised
ee module in. `earthengine authenticate` (once, interactively) provisions the
local credentials this then picks up.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

# Sentinel-1 GRD backscatter is delivered by GEE in decibels already.
S1_COLLECTION = "COPERNICUS/S1_GRD"
JRC_WATER = "JRC/GSW1_4/GlobalSurfaceWater"      # permanent-water mask source
HYDROSHEDS_DEM = "WWF/HydroSHEDS/03VFDEM"         # void-filled 3-arc-sec DEM for slope

# Method parameters. These are the UN-SPIDER defaults, kept as named constants so
# they are visible and defensible rather than buried as magic numbers.
DIFF_THRESHOLD_DB = 1.25   # pre/post ratio above this (in linear-of-dB) = flood
PERMANENT_WATER_MIN_OCCURRENCE = 50   # % JRC occurrence treated as "permanent"
MAX_SLOPE_DEG = 5.0        # flood water does not stand on slopes steeper than this
CONNECTED_PIXEL_MIN = 8    # drop blobs smaller than this many pixels (speckle)
SPECKLE_SMOOTH_RADIUS_M = 50.0

# Sentinel-1 acquisition geometry defaults for the change-detection pair.
DEFAULT_PRE_WINDOW_DAYS = 24    # ~2-4 passes before the event for a clean median
DEFAULT_POST_WINDOW_DAYS = 16   # a couple of passes after; first is the key one
EXPORT_SCALE_M = 30            # output pixel size; matches our 30 m high-res grid


@dataclass(frozen=True)
class AOI:
    """A geographic area of interest as a lon/lat bounding box (EPSG:4326).

    GEE speaks WGS84 lon/lat. Our study-area domains are in projected metres
    (UTM), so `from_domain` does the reprojection once, here, rather than letting
    raw UTM metres leak into an Earth Engine geometry where they would be silently
    misinterpreted as degrees.
    """
    west: float
    south: float
    east: float
    north: float

    def to_ee_geometry(self, ee: Any):
        return ee.Geometry.Rectangle(
            [self.west, self.south, self.east, self.north], proj="EPSG:4326",
            geodesic=False)

    @classmethod
    def from_domain(cls, domain: Any) -> "AOI":
        """Reproject a config.Domain's projected-metre bounds to a lon/lat box.

        Uses pyproj (always-transform, so axis order is explicit lon/lat). The
        four corners are transformed and the envelope taken, which is correct for
        a north-up UTM rectangle and slightly conservative for any rotation.
        """
        from pyproj import Transformer

        t = Transformer.from_crs(domain.crs, "EPSG:4326", always_xy=True)
        xs = [domain.xmin, domain.xmax, domain.xmax, domain.xmin]
        ys = [domain.ymin, domain.ymin, domain.ymax, domain.ymax]
        lons, lats = t.transform(xs, ys)
        return cls(west=min(lons), south=min(lats),
                   east=max(lons), north=max(lats))


@dataclass(frozen=True)
class FloodObsSpec:
    """A fully-specified, reproducible SAR flood-observation request.

    Everything the query depends on lives here so a run is described by one
    serialisable object — the provenance record for "how this flood map was made."
    """
    aoi: AOI
    event_date: date
    pre_window_days: int = DEFAULT_PRE_WINDOW_DAYS
    post_window_days: int = DEFAULT_POST_WINDOW_DAYS
    diff_threshold_db: float = DIFF_THRESHOLD_DB
    max_slope_deg: float = MAX_SLOPE_DEG
    permanent_water_min_occurrence: int = PERMANENT_WATER_MIN_OCCURRENCE
    connected_pixel_min: int = CONNECTED_PIXEL_MIN
    polarization: str = "VV"
    orbit_pass: Optional[str] = None   # 'ASCENDING'|'DESCENDING'|None(=either)
    export_scale_m: float = EXPORT_SCALE_M

    @property
    def pre_start(self) -> date:
        return self.event_date - timedelta(days=self.pre_window_days)

    @property
    def pre_end(self) -> date:
        return self.event_date

    @property
    def post_start(self) -> date:
        return self.event_date

    @property
    def post_end(self) -> date:
        return self.event_date + timedelta(days=self.post_window_days)

    @classmethod
    def for_study_area(cls, area: Any, **overrides: Any) -> "FloodObsSpec":
        """Build a spec from a config.StudyArea that carries a blockage event date.

        Pulls the AOI from the study domain and the event date from the blockage
        record — the two things that make the observation specific to Chamoli
        without hardcoding anything here.
        """
        if area.blockage is None or not area.blockage.event_date:
            raise ValueError(
                f"study area '{area.key}' has no blockage.event_date to anchor a "
                "SAR observation window on")
        ev = _parse_date(area.blockage.event_date)
        return cls(aoi=AOI.from_domain(area.domain), event_date=ev, **overrides)


def _parse_date(s: str) -> date:
    y, m, d = (int(p) for p in s.split("-"))
    return date(y, m, d)


def _iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


# --------------------------------------------------------------------------- #
# Earth Engine session
# --------------------------------------------------------------------------- #
def initialize(project: Optional[str] = None, ee: Any = None) -> Any:
    """Initialise Earth Engine and return the ee module.

    Kept separate from import so the module is testable offline and so an
    auth/project error surfaces at an obvious call site rather than at import.
    Pass `project` for the Cloud project registered with Earth Engine (required
    on the current EE API); if omitted it falls back to the ``EE_PROJECT``
    environment variable (which the driver loads from ``backend/.env``). Raises a
    clear error if credentials are missing.
    """
    if ee is None:
        import ee as _ee
        ee = _ee
    import os

    project = project or os.environ.get("EE_PROJECT")
    try:
        if project:
            ee.Initialize(project=project)
        else:
            ee.Initialize()
    except Exception as exc:  # ee raises a bare EEException here
        raise RuntimeError(
            "Earth Engine failed to initialise. Run `earthengine authenticate` "
            "once, then either pass project=<your-registered-cloud-project> or "
            "set EE_PROJECT in backend/.env. Underlying error: "
            f"{exc}"
        ) from exc
    return ee


# --------------------------------------------------------------------------- #
# core image algebra (pure ee expressions; no network until .getInfo/export)
# --------------------------------------------------------------------------- #
def _s1_median(ee: Any, geom: Any, start: date, end: date, spec: FloodObsSpec):
    """Median Sentinel-1 GRD backscatter (one polarisation) over a time window.

    Median over the window's passes is the speckle-suppression step: SAR speckle
    is multiplicative and roughly zero-median in dB, so a temporal median of a few
    passes is a robust, edge-preserving denoiser — cheaper and less destructive
    than a spatial Lee/Frost filter, and it is what the UN-SPIDER recipe uses.
    """
    col = (ee.ImageCollection(S1_COLLECTION)
           .filterBounds(geom)
           .filterDate(_iso(start), _iso(end))
           .filter(ee.Filter.eq("instrumentMode", "IW"))
           .filter(ee.Filter.listContains(
               "transmitterReceiverPolarisation", spec.polarization))
           .select(spec.polarization))
    if spec.orbit_pass:
        col = col.filter(ee.Filter.eq("orbitProperties_pass", spec.orbit_pass))
    return col.median().clip(geom), col


def _slope_mask(ee: Any, geom: Any, max_slope_deg: float):
    """1 where terrain is flat enough to hold standing water, else 0.

    Steep Himalayan valley walls create SAR layover and shadow that mimic the low
    backscatter of water. Masking slopes above a few degrees removes the single
    largest false-positive source; it is physically justified too, because flood
    water does not stand on a steep slope.
    """
    dem = ee.Image(HYDROSHEDS_DEM).clip(geom)
    slope = ee.Terrain.slope(dem)
    return slope.lte(max_slope_deg)


def _permanent_water_mask(ee: Any, geom: Any, min_occurrence: int):
    """0 on permanent water (rivers, lakes), 1 elsewhere.

    JRC Global Surface Water 'occurrence' is the % of observations 1984-2021 a
    pixel was water. A permanent river channel is not a flood, so anything above
    a high occurrence threshold is removed from the flood layer.
    """
    occ = ee.Image(JRC_WATER).select("occurrence").clip(geom).unmask(0)
    return occ.lt(min_occurrence)


def flood_image(ee: Any, spec: FloodObsSpec):
    """Build the (unrealised) Earth Engine flood-extent image for a spec.

    Returns an ee.Image of 1 = SAR-observed inundation/wetting, masked elsewhere.
    No network call happens until the result is exported or .getInfo() is called;
    this function only composes the server-side computation graph.
    """
    geom = spec.aoi.to_ee_geometry(ee)
    pre, _ = _s1_median(ee, geom, spec.pre_start, spec.pre_end, spec)
    post, _ = _s1_median(ee, geom, spec.post_start, spec.post_end, spec)

    # Smooth both a touch to further tame speckle before differencing.
    smooth = ee.Kernel.circle(radius=SPECKLE_SMOOTH_RADIUS_M, units="meters")
    pre_s = pre.focal_median(kernel=smooth)
    post_s = post.focal_median(kernel=smooth)

    # pre/post ratio. GRD is in dB, so a linear ratio of dB-valued images is a
    # difference; either monotonic form works for a threshold and the divide keeps
    # it scale-free. A big positive ratio = got much darker = newly water.
    ratio = pre_s.divide(post_s)
    flooded = ratio.gt(spec.diff_threshold_db)

    # refine
    flooded = flooded.updateMask(flooded)  # drop the zeros
    flooded = flooded.updateMask(
        _permanent_water_mask(ee, geom, spec.permanent_water_min_occurrence))
    flooded = flooded.updateMask(_slope_mask(ee, geom, spec.max_slope_deg))

    # remove speckle-sized blobs
    connected = flooded.connectedPixelCount(spec.connected_pixel_min + 1, True)
    flooded = flooded.updateMask(connected.gte(spec.connected_pixel_min))

    return flooded.rename("flood").clip(geom).toByte()


# --------------------------------------------------------------------------- #
# export (toDrive ONLY — see module docstring)
# --------------------------------------------------------------------------- #
def export_to_drive(
    ee: Any,
    spec: FloodObsSpec,
    *,
    description: str = "jaldrishti_sar_flood",
    folder: str = "jaldrishti",
    file_name_prefix: Optional[str] = None,
    start: bool = True,
) -> Any:
    """Queue a Drive export of the flood-extent image and return the ee task.

    Uses Export.image.toDrive exclusively. Cloud Storage export is intentionally
    NOT offered: the Community EE tier has no billing account and it would fail.
    """
    img = flood_image(ee, spec)
    geom = spec.aoi.to_ee_geometry(ee)
    task = ee.batch.Export.image.toDrive(
        image=img,
        description=description,
        folder=folder,
        fileNamePrefix=file_name_prefix or description,
        region=geom,
        scale=spec.export_scale_m,
        crs="EPSG:4326",
        maxPixels=1_000_000_000,
        fileFormat="GeoTIFF",
    )
    if start:
        task.start()
    return task


def observed_area_km2(ee: Any, spec: FloodObsSpec) -> float:
    """Realise the flood image and return its total area in km^2 (a getInfo call).

    This is the one function here that hits the network. It is handy as a smoke
    test — a plausible non-zero, non-absurd area means the pipeline ran — and as
    a scalar to print next to the modelled flooded area for the deck.
    """
    img = flood_image(ee, spec)
    geom = spec.aoi.to_ee_geometry(ee)
    area_img = img.multiply(ee.Image.pixelArea())
    stat = area_img.reduceRegion(
        reducer=ee.Reducer.sum(), geometry=geom,
        scale=spec.export_scale_m, maxPixels=1_000_000_000)
    m2 = stat.get("flood").getInfo()
    return float(m2 or 0.0) / 1e6

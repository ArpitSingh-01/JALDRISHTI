"""
Terrain: DEM acquisition, hydrological conditioning, and roughness.

The bed elevation is the single most influential input to a dam-break model. It
sets where the water goes, how fast it gets there, and therefore every number the
product reports. Everything in this package exists to get a defensible bed array
into the solver and to keep a record of what was done to it.

Three layers, in the order a scenario uses them:

  dem.py        fetch Copernicus DEM, reproject to square metric cells, fill
                voids, remove speckle pits -> TerrainGrid (the solver's bed)
  hydrology.py  D8 flow routing on an internally-filled scaffold -> drainage
                network, contributing area, HAND, valley mask, stream snapping
  roughness.py  ESA WorldCover land cover -> Manning's n per cell, with the
                published range carried alongside as a sensitivity bound

The split between dem.py's capped depression filling and hydrology.py's full
filling is deliberate and load-bearing; see the two-DEMs note in hydrology.py.
"""

from .dem import (
    COP30_BASE,
    TerrainGrid,
    bounds_from_points,
    fetch_dem,
    fill_depressions,
    fill_voids,
    geographic_bounds_for,
    metric_extent_for,
    prepare_terrain,
    tile_id,
    tiles_for_bounds,
    to_metric_grid,
    utm_crs_for,
)
from .hydrology import (
    FILL_EPS,
    HydroGrid,
    analyse_flow,
)
from .roughness import (
    DEBRIS_FLOW_N_FACTOR,
    FALLBACK_N,
    WORLDCOVER_BASE,
    WORLDCOVER_CLASSES,
    RoughnessField,
    fetch_landcover,
    manning_from_landcover,
    roughness_for,
    worldcover_tile_id,
    worldcover_tiles_for_bounds,
)

__all__ = [
    # dem
    "COP30_BASE",
    "TerrainGrid",
    "bounds_from_points",
    "fetch_dem",
    "fill_depressions",
    "fill_voids",
    "geographic_bounds_for",
    "metric_extent_for",
    "prepare_terrain",
    "tile_id",
    "tiles_for_bounds",
    "to_metric_grid",
    "utm_crs_for",
    # hydrology
    "FILL_EPS",
    "HydroGrid",
    "analyse_flow",
    # roughness
    "DEBRIS_FLOW_N_FACTOR",
    "FALLBACK_N",
    "WORLDCOVER_BASE",
    "WORLDCOVER_CLASSES",
    "RoughnessField",
    "fetch_landcover",
    "manning_from_landcover",
    "roughness_for",
    "worldcover_tile_id",
    "worldcover_tiles_for_bounds",
]

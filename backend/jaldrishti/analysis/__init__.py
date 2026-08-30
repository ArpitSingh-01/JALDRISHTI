"""
Analysis — turning solver output into a response plan.

The solver produces depth, velocity and arrival-time rasters. On their own those
are a physics result. This package turns them into the four things a district
official needs, in dependency order:

    hazard.py    depth + velocity -> a published danger classification
    arrival.py   first-crossing time -> isochrone bands and polygons
    exposure.py  population and infrastructure inside those bands
    damage.py    order-of-magnitude economic loss, as a range
    summary.py   all of the above in one object, with its caveats attached

`summary.ScenarioSummary` is the only thing `export/` and `api/` should import.
Everything else here is machinery it calls.

Nothing in this package imports rasterio, geopandas or osmnx at module scope —
those imports live inside the functions that need them, so `import
jaldrishti.analysis` stays cheap and testable without the geospatial stack
loaded.
"""

from __future__ import annotations

from .arrival import (
    ArrivalResult,
    BAND_COLOURS,
    DEFAULT_BANDS_MIN,
    INITIALLY_WET,
    NEVER_FLOODED,
    analyse as analyse_arrival,
    band_index,
    band_labels,
    front_speed,
    isochrone_polygons,
    to_minutes,
)
from .damage import (
    ASSET_VALUE_INR,
    CURVES,
    DAMAGE_SOURCES,
    DamageRange,
    DamageResult,
    area_damage,
    building_damage,
    damage_fraction,
    road_damage,
    standard_limitations as damage_limitations,
)
from .exposure import (
    EXPOSURE_SOURCES,
    ExposureResult,
    analyse as analyse_exposure,
    count_features_in_flood,
    flooded_length_km,
    geographic_cell_area_m2,
    osm_features,
    population_by_class,
    population_cross_tab,
    resample_population,
    standard_limitations as exposure_limitations,
)
from .hazard import (
    AIDR_CLASSES,
    AIDR_CLASS_COLOURS,
    DEFRA_BANDS,
    DEFRA_CLASS_COLOURS,
    DEFRA_CLASS_MEANING,
    DEFRA_CLASS_NAMES,
    HAZARD_SOURCES,
    HazardResult,
    aidr_hazard_class,
    classify as classify_hazard,
    debris_factor,
    defra_hazard_class,
    defra_hazard_rating,
)
from .summary import ScenarioSummary

__all__ = [
    # hazard
    "AIDR_CLASSES", "AIDR_CLASS_COLOURS", "DEFRA_BANDS",
    "DEFRA_CLASS_COLOURS", "DEFRA_CLASS_MEANING", "DEFRA_CLASS_NAMES",
    "HAZARD_SOURCES", "HazardResult", "aidr_hazard_class", "classify_hazard",
    "debris_factor", "defra_hazard_class", "defra_hazard_rating",
    # arrival
    "ArrivalResult", "BAND_COLOURS", "DEFAULT_BANDS_MIN", "INITIALLY_WET",
    "NEVER_FLOODED", "analyse_arrival", "band_index", "band_labels",
    "front_speed", "isochrone_polygons", "to_minutes",
    # exposure
    "EXPOSURE_SOURCES", "ExposureResult", "analyse_exposure",
    "count_features_in_flood", "exposure_limitations", "flooded_length_km",
    "geographic_cell_area_m2", "osm_features", "population_by_class",
    "population_cross_tab", "resample_population",
    # damage
    "ASSET_VALUE_INR", "CURVES", "DAMAGE_SOURCES", "DamageRange",
    "DamageResult", "area_damage", "building_damage", "damage_fraction",
    "damage_limitations", "road_damage",
    # the object everything downstream consumes
    "ScenarioSummary",
]

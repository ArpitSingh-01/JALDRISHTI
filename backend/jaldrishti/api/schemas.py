"""Request/response models for the JALDRISHTI API.

Kept deliberately permissive (plain typed fields, defaults, no version-specific
validators) so the module works under either Pydantic v1 or v2 — the FastAPI
stack shipped in the conda env picks the matching one. Bounds and membership are
enforced in the route handlers, where a violation becomes a clean HTTP 400/404.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class StudyInfo(BaseModel):
    """One study area, as the frontend picker needs it."""
    key: str
    title: str
    scenario_kind: str                      # 'dam_break' | 'blockage'
    purpose: str
    river: Optional[str] = None
    feature_name: Optional[str] = None      # dam or blockage name
    lat: Optional[float] = None
    lon: Optional[float] = None
    crs: str
    dx_interactive_m: float
    dx_highres_m: float
    dam: Optional[dict[str, Any]] = None
    blockage: Optional[dict[str, Any]] = None
    limitations: list[str] = Field(default_factory=list)


class RunRequest(BaseModel):
    """Submit a scenario. `dx=None` uses the domain's interactive resolution."""
    area: str
    dx: Optional[float] = None
    duration_hours: float = 2.0
    exposure: bool = True
    damage: bool = False
    setup_only: bool = False
    export_bundle: bool = True


class RunSubmitted(BaseModel):
    run_id: str
    status: str
    detail: str


class RunStatus(BaseModel):
    """Lightweight status for list + poll. The full result is /result."""
    run_id: str
    status: str                             # queued|running|done|failed|setup_only|unknown
    area: Optional[str] = None
    dx_m: Optional[float] = None
    duration_s: Optional[float] = None
    submitted_utc: Optional[str] = None
    started_utc: Optional[str] = None
    finished_utc: Optional[str] = None
    wall_time_s: Optional[float] = None
    headline: Optional[str] = None
    presentable: Optional[bool] = None
    peak_depth_m: Optional[float] = None
    flooded_area_km2: Optional[float] = None
    first_arrival_min: Optional[float] = None
    exposed_people: Optional[float] = None
    error: Optional[str] = None
    has_bundle: bool = False


class ArtifactInfo(BaseModel):
    name: str                               # path relative to the run directory
    size_bytes: int
    kind: str                               # geotiff|shapefile|kml|pdf|json|qml|other

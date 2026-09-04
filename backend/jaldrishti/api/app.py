"""FastAPI application for JALDRISHTI.

Thin HTTP surface over the job runner. It never runs the solver itself — it
validates a request, spawns a job subprocess, and serves the status/metadata/
artifact files that job writes. That keeps every endpoint fast and the API
restartable without killing an in-flight run.

    uvicorn jaldrishti.api.app:app --reload --port 8000
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse

# Load backend/.env so the Supabase mirror (and any future credential) is picked
# up when the API runs. Silent no-op if python-dotenv or the file is absent; the
# mirror then simply stays off. backend/ is parents[2] of this file.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

from ..config import STUDY_AREAS, provenance_report
from . import jobs, store
from .schemas import ArtifactInfo, RunRequest, RunStatus, RunSubmitted, StudyInfo

# duration / resolution guard rails (a mis-typed dx of 1 m would try to allocate
# a terabyte grid; 0 h would divide by zero downstream)
_MIN_HOURS, _MAX_HOURS = 0.01, 48.0
_MIN_DX, _MAX_DX = 10.0, 1000.0

_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


def _json_safe(obj: Any) -> Any:
    """Coerce dataclass fields that JSON can't take (Path, set, ...) to str."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def _study_info(area: Any) -> dict[str, Any]:
    feat = area.dam or area.blockage
    return {
        "key": area.key,
        "title": area.title,
        "scenario_kind": area.scenario_kind,
        "purpose": area.purpose,
        "river": getattr(feat, "river", None),
        "feature_name": getattr(feat, "name", None),
        "lat": getattr(feat, "lat", None),
        "lon": getattr(feat, "lon", None),
        "crs": area.domain.crs,
        "dx_interactive_m": area.domain.dx_interactive_m,
        "dx_highres_m": area.domain.dx_highres_m,
        "dam": _json_safe(dataclasses.asdict(area.dam)) if area.dam else None,
        "blockage": (
            _json_safe(dataclasses.asdict(area.blockage)) if area.blockage else None
        ),
        "limitations": list(area.limitations),
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title="JALDRISHTI API",
        version="0.1.0",
        description=(
            "Dam-break and river-blockage flood simulation for HADR "
            "(SIH 2026, PS 26161). 2D shallow-water solver; arrival time and "
            "exposure are the primary outputs."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- meta ------------------------------------------------------------- #
    @app.get("/")
    def root() -> dict[str, Any]:
        return {
            "service": "JALDRISHTI API",
            "docs": "/docs",
            "studies": "/api/studies",
            "runs": "/api/runs",
        }

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "runs_dir": str(jobs.RUNS_DIR),
            "cloud_mirror": store.is_configured(),
        }

    # -- study areas ------------------------------------------------------ #
    @app.get("/api/studies", response_model=list[StudyInfo])
    def list_studies() -> list[dict[str, Any]]:
        return [_study_info(a) for a in STUDY_AREAS.values()]

    @app.get("/api/studies/{key}", response_model=StudyInfo)
    def get_study(key: str) -> dict[str, Any]:
        area = STUDY_AREAS.get(key)
        if area is None:
            raise HTTPException(404, f"unknown study area '{key}'")
        return _study_info(area)

    @app.get("/api/studies/{key}/provenance", response_class=PlainTextResponse)
    def study_provenance(key: str) -> str:
        if key not in STUDY_AREAS:
            raise HTTPException(404, f"unknown study area '{key}'")
        return provenance_report(key)

    # -- runs ------------------------------------------------------------- #
    @app.post("/api/runs", response_model=RunSubmitted, status_code=202)
    def submit_run(req: RunRequest) -> dict[str, Any]:
        area = STUDY_AREAS.get(req.area)
        if area is None:
            raise HTTPException(404, f"unknown study area '{req.area}'")
        if not (_MIN_HOURS <= req.duration_hours <= _MAX_HOURS):
            raise HTTPException(
                400, f"duration_hours must be in [{_MIN_HOURS}, {_MAX_HOURS}]"
            )
        dx: Optional[float] = req.dx
        if dx is None:
            dx = area.domain.dx_interactive_m
        if not (_MIN_DX <= dx <= _MAX_DX):
            raise HTTPException(400, f"dx must be in [{_MIN_DX}, {_MAX_DX}] m")

        run_id = jobs.make_run_id(req.area, dx)
        jobs.spawn_job(
            run_id,
            req.area,
            dx,
            req.duration_hours,
            exposure=req.exposure,
            damage=req.damage,
            setup_only=req.setup_only,
            export_bundle=req.export_bundle,
        )
        return {
            "run_id": run_id,
            "status": "queued",
            "detail": (
                f"scenario '{req.area}' at {dx:g} m for {req.duration_hours:g} h; "
                f"poll GET /api/runs/{run_id}"
            ),
        }

    @app.get("/api/runs", response_model=list[RunStatus])
    def list_runs() -> list[dict[str, Any]]:
        """Local runs plus any cloud-mirrored runs this host doesn't have on disk.

        Local disk is authoritative for runs present locally; the Supabase mirror
        only contributes runs launched on another host (or since wiped locally),
        so a shared frontend sees the full fleet. No-op merge when unconfigured.
        """
        local = jobs.list_runs()
        seen = {s.get("run_id") for s in local}
        for s in store.list_runs():
            if s.get("run_id") not in seen:
                s.setdefault("source", "supabase (remote)")
                local.append(s)
        return local

    @app.get("/api/runs/{run_id}", response_model=RunStatus)
    def get_run(run_id: str) -> dict[str, Any]:
        st = jobs.get_status(run_id)
        if st is None:
            # not on this host — fall back to the cloud mirror before 404ing
            st = store.get_run(run_id)
            if st is not None:
                st.setdefault("source", "supabase (remote)")
        if st is None:
            raise HTTPException(404, f"no run '{run_id}'")
        return st

    @app.get("/api/runs/{run_id}/result")
    def get_result(run_id: str) -> dict[str, Any]:
        st = jobs.get_status(run_id)
        if st is None:
            raise HTTPException(404, f"no run '{run_id}'")
        meta = jobs.read_metadata(run_id)
        if meta is None:
            raise HTTPException(
                409,
                f"no result for '{run_id}' yet (status: {st.get('status')}); "
                f"poll GET /api/runs/{run_id}",
            )
        return meta

    @app.get("/api/runs/{run_id}/artifacts", response_model=list[ArtifactInfo])
    def get_artifacts(run_id: str) -> list[dict[str, Any]]:
        if jobs.get_status(run_id) is None:
            raise HTTPException(404, f"no run '{run_id}'")
        return jobs.list_artifacts(run_id)

    @app.get("/api/runs/{run_id}/artifacts/{artifact_path:path}")
    def get_artifact(run_id: str, artifact_path: str) -> FileResponse:
        if jobs.get_status(run_id) is None:
            raise HTTPException(404, f"no run '{run_id}'")
        try:
            path = jobs.safe_artifact_path(run_id, artifact_path)
        except ValueError:
            raise HTTPException(400, "invalid artifact path")
        if not path.is_file():
            raise HTTPException(404, f"no artifact '{artifact_path}'")
        return FileResponse(str(path), filename=path.name)

    @app.get("/api/runs/{run_id}/log", response_class=PlainTextResponse)
    def get_log(run_id: str, tail: int = 200) -> str:
        if jobs.get_status(run_id) is None:
            raise HTTPException(404, f"no run '{run_id}'")
        return jobs.tail_log(run_id, n=max(1, min(tail, 5000)))

    @app.get("/api/runs/{run_id}/manifest")
    def get_manifest(run_id: str) -> dict[str, Any]:
        """The bundle's MANIFEST.json — every artifact with sha256 and size."""
        if jobs.get_status(run_id) is None:
            raise HTTPException(404, f"no run '{run_id}'")
        path = jobs.run_dir(run_id) / "MANIFEST.json"
        if not path.is_file():
            raise HTTPException(404, f"no MANIFEST.json for '{run_id}'")
        import json

        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/api/runs/{run_id}/isochrones.geojson")
    def get_isochrones(run_id: str) -> dict[str, Any]:
        """Arrival-band isochrones, derived on the fly from arrival_band.tif."""
        if jobs.get_status(run_id) is None:
            raise HTTPException(404, f"no run '{run_id}'")
        from ..export.geojson import isochrones_fc

        try:
            return isochrones_fc(jobs.run_dir(run_id))
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))

    @app.get("/api/runs/{run_id}/settlements.geojson")
    def get_settlements(run_id: str) -> dict[str, Any]:
        """Named downstream settlements, sampled from the run's own rasters."""
        if jobs.get_status(run_id) is None:
            raise HTTPException(404, f"no run '{run_id}'")
        from ..export.geojson import settlements_fc

        try:
            meta = jobs.read_metadata(run_id)
        except Exception:
            meta = None
        if meta is None:
            raise HTTPException(
                409, f"no result for '{run_id}' yet; poll GET /api/runs/{run_id}")
        area = STUDY_AREAS.get(
            meta.get("scenario", {}).get("study_area", ""))
        if area is None:
            raise HTTPException(404, "run's study area is not configured")
        try:
            return settlements_fc(jobs.run_dir(run_id), area)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))

    @app.delete("/api/runs/{run_id}")
    def delete_run(run_id: str) -> dict[str, Any]:
        if jobs.get_status(run_id) is None:
            raise HTTPException(404, f"no run '{run_id}'")
        try:
            ok = jobs.delete_run(run_id)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"run_id": run_id, "deleted": ok}

    return app


app = create_app()

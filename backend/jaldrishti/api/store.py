"""
Supabase mirror for the run store — a DURABLE INDEX, not the source of truth.

WHY THIS IS A MIRROR AND NOT THE PRIMARY STORE
----------------------------------------------
A scenario run executes in a detached subprocess (see `jobs.py`) precisely so a
NaN blow-up or OOM in the Numba kernels cannot take the API down with it, and so
the API can be restarted mid-run without orphaning it. That isolation is the most
valuable property the job system has. If the solver subprocess wrote its status
straight to Postgres, every progress update would become a network call that can
fail mid-run, and the crash-recovery logic (atomic status.json + PID liveness
reconcile) would lose its footing.

So local disk stays the source of truth DURING a run. Supabase is written to at
two safe moments only:
  * when a job is submitted (the initial 'queued' row appears in the cloud index),
  * when a job reaches a TERMINAL status (done/failed/setup_only) — the row is
    upserted and the export artifacts are uploaded to Storage.
Both are best-effort: every call here catches its own exceptions and logs them,
so a Supabase outage degrades the system to "local-only" rather than failing an
otherwise-successful run. This is the same discipline as the GEE module's
toDrive-only rule — the cloud is additive, never load-bearing.

FEATURE FLAG
------------
If SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are absent from the environment,
`client()` returns None and every function here is a no-op. That is what keeps
the existing API test-suite behaving byte-identically when Supabase is not
configured — the mirror simply isn't there.

CREDENTIALS
-----------
Read from the environment (loaded from backend/.env by the API/driver). The
service-role key bypasses Row-Level Security and is server-side ONLY; it must
never be shipped to a browser. We reference it by env-var name and never log its
value.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

# Table + bucket names. Kept as constants so the SQL migration and the code agree.
RUNS_TABLE = "runs"
ARTIFACTS_BUCKET = "jaldrishti"

# Which artifact suffixes are worth pushing to Storage. The deck deliverables the
# problem statement names (GeoTIFF / Shapefile / KML / PDF) plus the metadata and
# preview images. We deliberately skip job.log and *.tmp.
_UPLOAD_SUFFIXES = {
    ".tif", ".tiff", ".shp", ".shx", ".dbf", ".prj", ".cpg",
    ".kml", ".kmz", ".pdf", ".json", ".qml", ".png", ".jpg",
}

_client: Optional[Any] = None
_client_resolved = False


def _log(msg: str) -> None:
    """Best-effort progress line. Goes to the worker's job.log / API stdout."""
    print(f"[store] {msg}", flush=True)


def is_configured() -> bool:
    return bool(os.environ.get("SUPABASE_URL")
                and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))


def client(force: bool = False) -> Optional[Any]:
    """Lazy Supabase client singleton, or None if unconfigured / unavailable.

    Returns None (never raises) when the env vars are missing or supabase-py is
    not installed, so callers can stay a plain `if client() is None: return`.
    """
    global _client, _client_resolved
    if _client_resolved and not force:
        return _client
    _client_resolved = True
    _client = None

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not (url and key):
        return None
    try:
        from supabase import create_client

        _client = create_client(url, key)
    except Exception as exc:  # import error, bad url, etc. — degrade to local-only
        _log(f"disabled (client init failed): {type(exc).__name__}: {exc}")
        _client = None
    return _client


def reset_client() -> None:
    """Drop the cached client so the next call re-reads the environment.

    Used by tests that toggle the env vars, and after a credential rotation.
    """
    global _client, _client_resolved
    _client = None
    _client_resolved = False


# --------------------------------------------------------------------------- #
# row shaping
# --------------------------------------------------------------------------- #
# The columns the runs table carries. A status.json holds more than this (params,
# traceback, pid); we mirror the headline/index fields and stash the rest in a
# jsonb `raw` column so nothing is lost but the table stays queryable.
_ROW_SCALARS = (
    "run_id", "status", "area", "dx_m", "duration_s", "wall_time_s",
    "submitted_utc", "started_utc", "finished_utc",
    "headline", "presentable", "peak_depth_m", "flooded_area_km2",
    "first_arrival_min", "exposed_people", "has_bundle",
)


def _row_from_status(status: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {k: status.get(k) for k in _ROW_SCALARS
                           if status.get(k) is not None}
    # run_id is the primary key — always present.
    row["run_id"] = status["run_id"]
    row["raw"] = status
    return row


# --------------------------------------------------------------------------- #
# writes (best-effort — never raise)
# --------------------------------------------------------------------------- #
def sync_run(status: dict[str, Any]) -> bool:
    """Upsert one run row into Postgres. Returns True on success, False if the
    mirror is off or the call failed. Never raises."""
    if "run_id" not in status:
        return False
    c = client()
    if c is None:
        return False
    try:
        row = _row_from_status(status)
        c.table(RUNS_TABLE).upsert(row, on_conflict="run_id").execute()
        return True
    except Exception as exc:  # noqa: BLE001 — mirror must never break a run
        _log(f"sync_run({status.get('run_id')}) failed: "
             f"{type(exc).__name__}: {exc}")
        return False


def _storage_key(run_id: str, rel: str) -> str:
    # Storage object path: one "folder" per run, forward slashes always.
    return f"{run_id}/{rel}"


def upload_artifacts(run_id: str, run_directory: Path) -> int:
    """Upload a run's export deliverables to the Storage bucket. Returns the count
    uploaded (0 if the mirror is off or nothing matched). Never raises."""
    c = client()
    if c is None:
        return 0
    if not run_directory.is_dir():
        return 0
    try:
        bucket = c.storage.from_(ARTIFACTS_BUCKET)
    except Exception as exc:  # noqa: BLE001
        _log(f"upload_artifacts({run_id}) bucket handle failed: "
             f"{type(exc).__name__}: {exc}")
        return 0

    n = 0
    for p in sorted(run_directory.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in _UPLOAD_SUFFIXES:
            continue
        rel = p.relative_to(run_directory).as_posix()
        key = _storage_key(run_id, rel)
        try:
            data = p.read_bytes()
            # upsert=true so re-uploading a run overwrites rather than 409-ing.
            bucket.upload(
                key, data,
                {"content-type": _content_type(p.suffix), "upsert": "true"},
            )
            n += 1
        except Exception as exc:  # noqa: BLE001 — skip the file, keep going
            _log(f"upload {key} failed: {type(exc).__name__}: {exc}")
    if n:
        _log(f"uploaded {n} artifact(s) for {run_id} to {ARTIFACTS_BUCKET}/")
    return n


_CONTENT_TYPES = {
    ".tif": "image/tiff", ".tiff": "image/tiff",
    ".kml": "application/vnd.google-earth.kml+xml",
    ".kmz": "application/vnd.google-earth.kmz",
    ".pdf": "application/pdf",
    ".json": "application/json",
    ".png": "image/png", ".jpg": "image/jpeg",
}


def _content_type(suffix: str) -> str:
    return _CONTENT_TYPES.get(suffix.lower(), "application/octet-stream")


# --------------------------------------------------------------------------- #
# reads (used by the API when the mirror is configured)
# --------------------------------------------------------------------------- #
def get_run(run_id: str) -> Optional[dict[str, Any]]:
    """Read one run's mirrored status back from Postgres, or None."""
    c = client()
    if c is None:
        return None
    try:
        resp = (c.table(RUNS_TABLE).select("raw")
                .eq("run_id", run_id).limit(1).execute())
        data = getattr(resp, "data", None) or []
        if not data:
            return None
        return data[0].get("raw")
    except Exception as exc:  # noqa: BLE001
        _log(f"get_run({run_id}) failed: {type(exc).__name__}: {exc}")
        return None


def list_runs() -> list[dict[str, Any]]:
    """Read all mirrored run statuses back from Postgres, newest first. Empty
    list if the mirror is off or the call failed."""
    c = client()
    if c is None:
        return []
    try:
        resp = (c.table(RUNS_TABLE).select("raw")
                .order("finished_utc", desc=True).execute())
        data = getattr(resp, "data", None) or []
        return [d.get("raw") for d in data if d.get("raw")]
    except Exception as exc:  # noqa: BLE001
        _log(f"list_runs failed: {type(exc).__name__}: {exc}")
        return []


def artifact_url(run_id: str, rel: str, expires_in: int = 3600) -> Optional[str]:
    """A signed, time-limited URL for one uploaded artifact, or None.

    Signed rather than public so the bucket can stay private — the frontend gets
    a short-lived link per artifact instead of the bucket being world-readable.
    """
    c = client()
    if c is None:
        return None
    try:
        bucket = c.storage.from_(ARTIFACTS_BUCKET)
        resp = bucket.create_signed_url(_storage_key(run_id, rel), expires_in)
        if isinstance(resp, dict):
            return resp.get("signedURL") or resp.get("signedUrl")
        return None
    except Exception as exc:  # noqa: BLE001
        _log(f"artifact_url({run_id}/{rel}) failed: {type(exc).__name__}: {exc}")
        return None

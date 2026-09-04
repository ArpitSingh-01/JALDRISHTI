"""Job lifecycle for the API: spawn scenario runs as detached subprocesses and
read their progress back off disk.

Why subprocesses and not a thread pool or `BackgroundTasks`: a run holds the GIL
inside Numba kernels for minutes and can't be cancelled cleanly, and a crash
(NaN blow-up, OOM) would take the API down with it. A separate process is
isolated, observable (its own `job.log`), and lets the API be restarted with
`--reload` without orphaning or losing the run — the child keeps going and its
`status.json` is picked up again on the next poll.

State lives entirely in `outputs/runs/<run_id>/`:
    status.json    written by this module + job_runner (the source of truth)
    job.log        the child's stdout/stderr
    metadata.json  written by the export bundle (rich, only on success)
Legacy bundles that predate status.json (the first Tehri run) are still listed:
`get_status` synthesizes a terminal status from metadata.json when no status
file exists.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..config import OUTPUT_DIR

# backend/  (parents: api -> jaldrishti -> backend)
BACKEND_DIR = Path(__file__).resolve().parents[2]
RUNS_DIR = OUTPUT_DIR / "runs"

STATUS_NAME = "status.json"
LOG_NAME = "job.log"
META_NAME = "metadata.json"

TERMINAL = {"done", "failed", "setup_only"}

# run_id -> Popen for jobs this process launched. Empty after an API restart;
# get_status then falls back to a PID liveness check to reconcile.
_PROCS: dict[str, "subprocess.Popen[Any]"] = {}


# --------------------------------------------------------------------------- #
# paths + time
# --------------------------------------------------------------------------- #
def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_run_id(area: str, dx: float) -> str:
    """Match run_scenario's own scheme: '<area>_<dx>m_<UTCstamp>'."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{area}_{dx:g}m_{stamp}"


def run_dir(run_id: str) -> Path:
    return RUNS_DIR / run_id


def status_path(run_id: str) -> Path:
    return run_dir(run_id) / STATUS_NAME


def metadata_path(run_id: str) -> Path:
    return run_dir(run_id) / META_NAME


# --------------------------------------------------------------------------- #
# status.json read/write (atomic)
# --------------------------------------------------------------------------- #
def write_status(run_id: str, status: dict[str, Any]) -> dict[str, Any]:
    """Write status.json atomically (tmp + os.replace) so a concurrent poll
    never sees a half-written file."""
    d = run_dir(run_id)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / (STATUS_NAME + ".tmp")
    tmp.write_text(json.dumps(status, indent=2), encoding="utf-8")
    os.replace(tmp, d / STATUS_NAME)
    return status


def update_status(run_id: str, **fields: Any) -> dict[str, Any]:
    """Merge fields into the existing status.json (or start a fresh one)."""
    cur = raw_status(run_id) or {"run_id": run_id}
    cur.update(fields)
    return write_status(run_id, cur)


def raw_status(run_id: str) -> Optional[dict[str, Any]]:
    p = status_path(run_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def read_metadata(run_id: str) -> Optional[dict[str, Any]]:
    p = metadata_path(run_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# --------------------------------------------------------------------------- #
# liveness (cross-platform, best-effort)
# --------------------------------------------------------------------------- #
def _pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        if os.name == "nt":
            import ctypes

            PROCESS_QUERY_LIMITED = 0x1000
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED, False, int(pid))
            if not h:
                return False
            code = ctypes.c_ulong()
            ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
            k32.CloseHandle(h)
            # 259 == STILL_ACTIVE
            return bool(ok) and code.value == 259
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, OverflowError):
        return False


# --------------------------------------------------------------------------- #
# status resolution (the read path the API uses)
# --------------------------------------------------------------------------- #
def _synth_from_metadata(run_id: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Build a 'done' status from a legacy bundle's metadata.json."""
    s = meta.get("scenario", {}) or {}
    r = s.get("results", {}) or {}
    h = meta.get("honesty", s.get("honesty", {})) or {}
    exp = r.get("exposure") or {}
    run = s.get("run", {}) or {}
    grid = s.get("grid", {}) or {}
    return {
        "run_id": run_id,
        "status": "done",
        "area": s.get("study_area"),
        "dx_m": grid.get("dx_m"),
        "duration_s": run.get("duration_s"),
        "wall_time_s": run.get("wall_time_s"),
        "finished_utc": meta.get("generated_utc"),
        "headline": s.get("headline"),
        "presentable": h.get("presentable_as_fact"),
        "peak_depth_m": r.get("peak_depth_m"),
        "flooded_area_km2": r.get("flooded_area_km2"),
        "first_arrival_min": r.get("first_arrival_min"),
        "exposed_people": exp.get("reported_population") or exp.get("total_population"),
        "has_bundle": True,
        "source": "metadata (legacy: no status.json)",
    }


def _fill_missing_from_metadata(status: dict[str, Any], meta: dict[str, Any]) -> None:
    """Backfill any scalar the status file lacks from the richer bundle."""
    synth = _synth_from_metadata(status.get("run_id", ""), meta)
    for k, v in synth.items():
        if k in ("status", "source"):
            continue
        if status.get(k) in (None, "") and v is not None:
            status[k] = v


def _reconcile(run_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """A non-terminal status whose process is gone means the job died without
    writing its terminal status. Promote it to 'failed' so it can't hang as
    'running' forever."""
    if raw.get("status") not in ("queued", "running"):
        return raw
    proc = _PROCS.get(run_id)
    if proc is not None:
        alive = proc.poll() is None
    else:
        alive = _pid_alive(raw.get("pid"))
    if alive:
        return raw
    return update_status(
        run_id,
        status="failed",
        error="job process is no longer running but wrote no terminal status "
        "(it crashed, was killed, or the API restarted while it ran)",
        finished_utc=_utcnow(),
    )


def get_status(run_id: str) -> Optional[dict[str, Any]]:
    """Resolve the best-known status for a run, or None if the dir is absent."""
    d = run_dir(run_id)
    if not d.is_dir():
        return None
    raw = raw_status(run_id)
    meta = read_metadata(run_id)
    if raw is None:
        if meta is not None:
            return _synth_from_metadata(run_id, meta)
        return {"run_id": run_id, "status": "unknown", "has_bundle": False}
    raw = _reconcile(run_id, raw)
    raw["has_bundle"] = meta is not None
    if raw.get("status") in ("done", "setup_only") and meta is not None:
        _fill_missing_from_metadata(raw, meta)
    return raw


def list_runs() -> list[dict[str, Any]]:
    """Every run directory, newest first (best-effort by finished/submitted time)."""
    if not RUNS_DIR.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for child in RUNS_DIR.iterdir():
        if not child.is_dir():
            continue
        st = get_status(child.name)
        if st is not None:
            out.append(st)

    def _key(s: dict[str, Any]) -> str:
        return str(
            s.get("finished_utc") or s.get("started_utc") or s.get("submitted_utc") or ""
        )

    out.sort(key=_key, reverse=True)
    return out


# --------------------------------------------------------------------------- #
# spawning
# --------------------------------------------------------------------------- #
def spawn_job(
    run_id: str,
    area: str,
    dx: float,
    duration_hours: float,
    *,
    exposure: bool = True,
    damage: bool = False,
    setup_only: bool = False,
    export_bundle: bool = True,
) -> "subprocess.Popen[Any]":
    """Launch the run as `python -m jaldrishti.api.job_runner`, detached, with its
    stdout/stderr going to job.log. Returns the Popen handle (also cached)."""
    d = run_dir(run_id)
    d.mkdir(parents=True, exist_ok=True)
    write_status(
        run_id,
        {
            "run_id": run_id,
            "status": "queued",
            "area": area,
            "dx_m": dx,
            "duration_s": duration_hours * 3600.0,
            "submitted_utc": _utcnow(),
            "params": {
                "exposure": exposure,
                "damage": damage,
                "setup_only": setup_only,
                "export_bundle": export_bundle,
            },
        },
    )

    cmd = [
        sys.executable,
        "-m",
        "jaldrishti.api.job_runner",
        "--run-id", run_id,
        "--area", area,
        "--dx", f"{dx:g}",
        "--hours", f"{duration_hours:g}",
    ]
    if not exposure:
        cmd.append("--no-exposure")
    if damage:
        cmd.append("--damage")
    if setup_only:
        cmd.append("--setup-only")
    if not export_bundle:
        cmd.append("--no-export")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"

    logf = open(d / LOG_NAME, "w", encoding="utf-8", buffering=1)
    creationflags = 0
    if os.name == "nt":
        # don't pop a console window for the child on Windows
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        cmd,
        cwd=str(BACKEND_DIR),
        stdout=logf,
        stderr=subprocess.STDOUT,
        env=env,
        creationflags=creationflags,
    )
    _PROCS[run_id] = proc
    # Record the child's pid in the queued status right away, before job_runner
    # flips it to 'running'. Without this, an API restart in that startup window
    # would leave a live run with a pid-less 'queued' status, and _reconcile
    # would wrongly declare it failed.
    queued = update_status(run_id, pid=proc.pid)
    # Mirror the queued row so a run appears in the cloud index the instant it is
    # submitted. Best-effort and no-op when unconfigured; import is local to keep
    # jobs.py usable without supabase-py installed.
    try:
        from . import store

        store.sync_run(queued)
    except Exception:  # noqa: BLE001 — the mirror must never break submission
        pass
    return proc


# --------------------------------------------------------------------------- #
# artifacts
# --------------------------------------------------------------------------- #
_KIND_BY_SUFFIX = {
    ".tif": "geotiff",
    ".tiff": "geotiff",
    ".shp": "shapefile",
    ".shx": "shapefile",
    ".dbf": "shapefile",
    ".prj": "shapefile",
    ".cpg": "shapefile",
    ".kml": "kml",
    ".kmz": "kml",
    ".pdf": "pdf",
    ".json": "json",
    ".qml": "qml",
    ".png": "image",
    ".jpg": "image",
    ".txt": "text",
    ".log": "text",
}


def _kind(name: str) -> str:
    return _KIND_BY_SUFFIX.get(Path(name).suffix.lower(), "other")


def list_artifacts(run_id: str) -> list[dict[str, Any]]:
    """All files under the run directory (recursive), as relative POSIX paths."""
    d = run_dir(run_id)
    if not d.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(d.rglob("*")):
        if not p.is_file():
            continue
        if p.name.endswith(".tmp"):
            continue
        rel = p.relative_to(d).as_posix()
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        out.append({"name": rel, "size_bytes": size, "kind": _kind(p.name)})
    return out


def safe_artifact_path(run_id: str, rel: str) -> Path:
    """Resolve a client-supplied relative path inside the run dir, refusing any
    path that escapes it (`..`, absolute, symlink-out)."""
    base = run_dir(run_id).resolve()
    target = (base / rel).resolve()
    if target != base and base not in target.parents:
        raise ValueError("path escapes the run directory")
    return target


def tail_log(run_id: str, n: int = 200) -> str:
    p = run_dir(run_id) / LOG_NAME
    if not p.is_file():
        return ""
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-n:])


def delete_run(run_id: str) -> bool:
    """Remove a run directory. Guarded to stay within RUNS_DIR."""
    import shutil

    d = run_dir(run_id).resolve()
    base = RUNS_DIR.resolve()
    if d != base and base not in d.parents:
        raise ValueError("refusing to delete outside the runs directory")
    if not d.is_dir():
        return False
    proc = _PROCS.get(run_id)
    if proc is not None and proc.poll() is None:
        raise RuntimeError("run is still active; stop it before deleting")
    shutil.rmtree(d)
    _PROCS.pop(run_id, None)
    return True

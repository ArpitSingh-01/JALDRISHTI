"""Worker entrypoint: run one scenario, then write a terminal status.json.

Launched by jobs.spawn_job as `python -m jaldrishti.api.job_runner ...`, never
imported by the API process. Everything it prints goes to the run's job.log
(the parent redirects stdout/stderr there). Its contract with the API is the
status.json it writes: 'running' on start, then exactly one terminal status
('done' | 'setup_only' | 'failed') in a finally block, so the API never sees a
job that silently vanished.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
import traceback
from typing import Any, Optional

from jaldrishti.api import jobs, store
from jaldrishti.scenario.run import run_scenario


def _finite(x: Any) -> Optional[float]:
    """JSON-safe float: inf/nan (e.g. first-arrival when nothing floods) -> None."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _scalars(summary: Any) -> dict[str, Any]:
    """The handful of headline numbers the run list/poll shows."""
    d = summary.to_dict()
    r = d.get("results", {}) or {}
    h = d.get("honesty", {}) or {}
    exp = r.get("exposure") or {}
    return {
        "headline": d.get("headline"),
        "presentable": bool(h.get("presentable_as_fact")),
        "peak_depth_m": _finite(r.get("peak_depth_m")),
        "flooded_area_km2": _finite(r.get("flooded_area_km2")),
        "first_arrival_min": _finite(r.get("first_arrival_min")),
        "exposed_people": exp.get("reported_population") or exp.get("total_population"),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="JALDRISHTI scenario job worker")
    p.add_argument("--run-id", required=True)
    p.add_argument("--area", required=True)
    p.add_argument("--dx", type=float, default=None)
    p.add_argument("--hours", type=float, default=2.0)
    p.add_argument("--setup-only", action="store_true")
    p.add_argument("--no-exposure", action="store_true")
    p.add_argument("--damage", action="store_true")
    p.add_argument("--no-export", action="store_true")
    a = p.parse_args()

    run_id = a.run_id
    jobs.update_status(
        run_id,
        status="running",
        started_utc=jobs._utcnow(),
        pid=os.getpid(),
        area=a.area,
        dx_m=a.dx,
        duration_s=a.hours * 3600.0,
    )

    t0 = time.perf_counter()
    try:
        res = run_scenario(
            a.area,
            dx=a.dx,
            duration_s=a.hours * 3600.0,
            run_id=run_id,
            out_dir=jobs.run_dir(run_id),
            exposure=not a.no_exposure,
            damage=a.damage,
            export_bundle=not a.no_export,
            setup_only=a.setup_only,
            verbose=True,
        )
        wall = time.perf_counter() - t0
        fields: dict[str, Any] = {
            "finished_utc": jobs._utcnow(),
            "wall_time_s": wall,
        }
        if getattr(res, "summary", None) is not None:
            fields.update(_scalars(res.summary))
            fields["status"] = "setup_only" if a.setup_only else "done"
        else:
            # setup_only returns no summary by design
            fields["status"] = "setup_only"
        final = jobs.update_status(run_id, **fields)
        print(f"[job_runner] {run_id} -> {fields['status']} in {wall:.1f}s")
        _mirror_terminal(run_id, final)
        return 0
    except BaseException as exc:  # noqa: BLE001 — must record every failure mode
        wall = time.perf_counter() - t0
        final = jobs.update_status(
            run_id,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc(),
            finished_utc=jobs._utcnow(),
            wall_time_s=wall,
        )
        print("[job_runner] FAILED:\n" + traceback.format_exc(), file=sys.stderr)
        _mirror_terminal(run_id, final)
        return 1


def _mirror_terminal(run_id: str, status: dict[str, Any]) -> None:
    """Best-effort Supabase mirror at the one safe moment: the terminal status.

    No-op when the mirror is unconfigured. Wrapped so a Supabase outage can never
    turn a successful (or already-failed) run into a crash — the local status.json
    written just above remains the source of truth either way.
    """
    try:
        store.sync_run(status)
        if status.get("status") in ("done", "setup_only"):
            store.upload_artifacts(run_id, jobs.run_dir(run_id))
    except Exception as exc:  # noqa: BLE001 — mirror is additive, never fatal
        print(f"[job_runner] mirror skipped: {type(exc).__name__}: {exc}",
              file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())

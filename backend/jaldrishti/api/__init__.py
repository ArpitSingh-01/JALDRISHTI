"""
JALDRISHTI HTTP API.

The service layer that the Next.js/deck.gl frontend talks to. A scenario run is
CPU-bound and long (a Tehri 90 m run is ~24 min of wall time), so the API never
runs the solver in-process: `POST /api/runs` spawns a detached job subprocess
(`python -m jaldrishti.api.job_runner`) that writes `status.json` and the export
bundle into `outputs/runs/<run_id>/`, and the API reads those files back. This
keeps the event loop responsive, survives an API `--reload`, and means a crashed
run is visible as a failed status rather than a hung request.

Run it (from the backend/ directory, inside the conda env):

    uvicorn jaldrishti.api.app:app --reload --port 8000

Interactive docs at http://localhost:8000/docs.
"""

__all__ = ["jobs", "schemas", "store"]

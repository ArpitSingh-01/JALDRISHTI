"""API smoke tests: exercise the HTTP surface and the job bookkeeping without
launching a real (minutes-long, network-bound) solver subprocess.

Two boundaries are stubbed:
  * jobs.RUNS_DIR is redirected to a tmp dir so nothing touches outputs/runs/;
  * jobs.spawn_job is replaced by a no-op that writes the same 'queued' status
    the real one does, so POST /api/runs is tested for validation + wiring only.
Everything else (status round-trip, legacy-metadata synthesis, artifact serving,
path-traversal guard) runs for real against the tmp dir.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from jaldrishti.api import app as app_mod
from jaldrishti.api import jobs


@pytest.fixture()
def runs_dir(tmp_path, monkeypatch):
    d = tmp_path / "runs"
    d.mkdir()
    monkeypatch.setattr(jobs, "RUNS_DIR", d)
    return d


@pytest.fixture()
def client(runs_dir):
    return TestClient(app_mod.app)


def _write_legacy_bundle(runs_dir: Path, run_id: str) -> Path:
    """A bundle that predates status.json — only metadata.json, like the first
    Tehri run. get_status must synthesize a terminal 'done' from it."""
    d = runs_dir / run_id
    d.mkdir()
    meta = {
        "generated_utc": "2026-09-02T04:11:10Z",
        "honesty": {"presentable_as_fact": False},
        "scenario": {
            "study_area": "tehri",
            "headline": "Tehri dam break; floods 66 km2; first arrival 3 min.",
            "grid": {"dx_m": 90.0},
            "run": {"duration_s": 7200.0, "wall_time_s": 1440.0},
            "results": {
                "peak_depth_m": 233.23,
                "flooded_area_km2": 65.95,
                "first_arrival_min": 2.58,
                "exposure": {"reported_population": 32000, "total_population": 31507},
            },
        },
    }
    (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (d / "max_depth_m.tif").write_bytes(b"II*\x00fake-geotiff")
    return d


# --------------------------------------------------------------------------- #
# meta + studies
# --------------------------------------------------------------------------- #
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_studies_list_has_the_three_scenarios(client):
    r = client.get("/api/studies")
    assert r.status_code == 200
    keys = {s["key"] for s in r.json()}
    assert {"malpasset", "tehri", "rishi_ganga"} <= keys


def test_study_detail_and_404(client):
    r = client.get("/api/studies/tehri")
    assert r.status_code == 200
    body = r.json()
    assert body["scenario_kind"] == "dam_break"
    assert body["dx_interactive_m"] > 0
    assert client.get("/api/studies/nope").status_code == 404


def test_blockage_study_exposes_a_barrier_not_a_dam(client):
    body = client.get("/api/studies/rishi_ganga").json()
    assert body["scenario_kind"] == "blockage"
    assert body["blockage"] is not None
    assert body["dam"] is None


def test_provenance_is_plain_text(client):
    r = client.get("/api/studies/tehri/provenance")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert len(r.text) > 0


# --------------------------------------------------------------------------- #
# runs: submission wiring (spawn stubbed)
# --------------------------------------------------------------------------- #
def test_submit_run_validates_and_queues(client, runs_dir, monkeypatch):
    spawned = {}

    def fake_spawn(run_id, area, dx, hours, **kw):
        spawned.update(run_id=run_id, area=area, dx=dx, hours=hours, **kw)
        # mimic the real spawn: a queued status carrying a live pid, so
        # get_status's liveness reconcile keeps it queued rather than failing it
        jobs.write_status(
            run_id,
            {
                "run_id": run_id,
                "status": "queued",
                "area": area,
                "dx_m": dx,
                "pid": os.getpid(),
            },
        )

    monkeypatch.setattr(jobs, "spawn_job", fake_spawn)

    r = client.post("/api/runs", json={"area": "tehri", "duration_hours": 1.0})
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    assert run_id.startswith("tehri_")
    # dx defaulted to the domain's interactive resolution
    assert spawned["area"] == "tehri"
    assert spawned["dx"] > 0

    poll = client.get(f"/api/runs/{run_id}")
    assert poll.status_code == 200
    assert poll.json()["status"] == "queued"


def test_submit_run_rejects_unknown_area(client):
    r = client.post("/api/runs", json={"area": "atlantis"})
    assert r.status_code == 404


def test_submit_run_rejects_bad_bounds(client, monkeypatch):
    monkeypatch.setattr(jobs, "spawn_job", lambda *a, **k: None)
    assert client.post(
        "/api/runs", json={"area": "tehri", "duration_hours": 999}
    ).status_code == 400
    assert client.post(
        "/api/runs", json={"area": "tehri", "dx": 1.0}
    ).status_code == 400


# --------------------------------------------------------------------------- #
# runs: reading status + artifacts (real, against tmp dir)
# --------------------------------------------------------------------------- #
def test_legacy_bundle_is_listed_as_done(client, runs_dir):
    _write_legacy_bundle(runs_dir, "tehri_legacy")
    listed = client.get("/api/runs").json()
    ids = {s["run_id"] for s in listed}
    assert "tehri_legacy" in ids

    st = client.get("/api/runs/tehri_legacy").json()
    assert st["status"] == "done"
    assert st["presentable"] is False
    assert st["exposed_people"] == 32000
    assert st["has_bundle"] is True


def test_result_returns_full_metadata(client, runs_dir):
    _write_legacy_bundle(runs_dir, "tehri_legacy")
    r = client.get("/api/runs/tehri_legacy/result")
    assert r.status_code == 200
    assert r.json()["scenario"]["study_area"] == "tehri"


def test_result_409_before_bundle_exists(client, runs_dir):
    jobs.write_status("pending", {"run_id": "pending", "status": "running"})
    r = client.get("/api/runs/pending/result")
    assert r.status_code == 409


def test_artifacts_list_and_download(client, runs_dir):
    _write_legacy_bundle(runs_dir, "tehri_legacy")
    arts = client.get("/api/runs/tehri_legacy/artifacts").json()
    names = {a["name"] for a in arts}
    assert "max_depth_m.tif" in names
    assert "metadata.json" in names

    dl = client.get("/api/runs/tehri_legacy/artifacts/max_depth_m.tif")
    assert dl.status_code == 200
    assert dl.content == b"II*\x00fake-geotiff"


def test_artifact_path_traversal_is_blocked(client, runs_dir):
    _write_legacy_bundle(runs_dir, "tehri_legacy")
    # a path that tries to escape the run dir must be refused, not served
    r = client.get("/api/runs/tehri_legacy/artifacts/..%2f..%2fmetadata.json")
    assert r.status_code in (400, 404)


def test_unknown_run_is_404(client, runs_dir):
    assert client.get("/api/runs/ghost").status_code == 404
    assert client.get("/api/runs/ghost/artifacts").status_code == 404
    assert client.get("/api/runs/ghost/log").status_code == 404


def test_delete_run(client, runs_dir):
    _write_legacy_bundle(runs_dir, "tehri_legacy")
    assert client.delete("/api/runs/tehri_legacy").status_code == 200
    assert client.get("/api/runs/tehri_legacy").status_code == 404

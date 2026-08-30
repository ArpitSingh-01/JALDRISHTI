"""
Provenance metadata — the record of how a result was made and what it can bear.

WHY THIS FILE EXISTS AT ALL
---------------------------
A GeoTIFF of flood depth is a claim. Without a record of the DEM vintage, the
Manning coefficients, the breach parameters, the CFL number and which of those
were guessed rather than sourced, it is an unfalsifiable claim — and an
unfalsifiable claim is worthless to a district officer deciding whether to
evacuate a village, and fatal in front of a technical jury that asks "where did
the reservoir volume come from?"

`ScenarioSummary.to_dict()` already assembles the numbers. This module's job is
narrower and more specific:

  1. Write them to disk as strict, parseable JSON (`allow_nan=False`, so a NaN
     that slipped through raises here rather than in the browser).
  2. Emit a MANIFEST that lists every file in the run directory with its size and
     SHA-256, so a recipient can verify they received what was sent and a
     reviewer can tell whether two runs produced identical output.
  3. Emit a human-readable README.txt in the run directory, because the person
     who opens the ZIP six months from now will not read the JSON.

WHY SHA-256 AND NOT A TIMESTAMP
-------------------------------
The reproducibility question a jury asks is "if I run it again, do I get the same
answer?" A timestamp cannot answer that. A content hash can: same inputs, same
code, same hash. It also catches the specific embarrassment of presenting a map
generated from a stale run, because the manifest hash will not match the one in
the deck.

WHAT IS DELIBERATELY NOT CLAIMED HERE
-------------------------------------
The metadata records that a Delft3D-compatible I/O adapter exists and that
comparison is made against PUBLISHED Delft3D benchmark output. It never records
that Delft3D was executed, because it was not. That distinction is load-bearing:
overstating it once destroys the credibility of every other number in the file.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

# Bumped when the *meaning* of a field changes, not when a field is added. A
# consumer that understands schema 1 must keep working against a schema-1 file
# forever, because files outlive code.
METADATA_SCHEMA_VERSION = 1

# The one sentence that must appear identically in every artefact — JSON,
# README, PDF, API response, slide. Written once here and imported everywhere so
# it cannot drift into something softer under presentation pressure.
SOLVER_ATTRIBUTION = (
    "Hydrodynamics computed by JALDRISHTI's own 2D shallow-water solver "
    "(finite volume, HLLC approximate Riemann solver, MUSCL reconstruction, "
    "well-balanced bed-slope source term, Manning friction, explicit CFL-limited "
    "time stepping). Delft3D was NOT run to produce this output. Where Delft3D "
    "is referenced, the comparison is against PUBLISHED benchmark results from "
    "the literature, and the interoperability claim is limited to a "
    "Delft3D-compatible input/output adapter."
)

MODEL_DISCLAIMER = (
    "This is simulation output, not a survey and not an official flood hazard "
    "map. It is intended for humanitarian planning and exercise use. Arrival "
    "time is measured from the moment of failure and is NOT warning time — "
    "warning time additionally requires detection, decision and dissemination, "
    "which this model does not represent. Statutory dam-break inundation "
    "mapping in India is governed by the Dam Safety Act, 2021 and CWC "
    "guidelines; this tool supports such work, it does not substitute for it."
)


def sha256_of(path, *, chunk=1 << 20) -> str:
    """Streaming hash — the population raster is 531 MB and must not be slurped."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def environment_record() -> dict:
    """
    What produced this run — versions of everything that can change an answer.

    Recorded because numerical output is version-sensitive in ways that are not
    obvious: a scipy release changed a default interpolation order once and moved
    a flood boundary by a cell. Without this block, "we cannot reproduce your
    figure" has no diagnosis.
    """
    out = {
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
    }
    for mod in ("numpy", "numba", "rasterio", "geopandas", "shapely", "pyproj",
                "scipy", "pandas", "simplekml", "reportlab"):
        try:
            out[mod] = __import__(mod).__version__
        except Exception:
            out[mod] = None
    try:
        import rasterio
        out["gdal"] = rasterio.__gdal_version__
    except Exception:
        out["gdal"] = None
    return out


def git_record(repo_root=None) -> dict:
    """
    The commit the run came from, and whether the tree was dirty.

    `dirty: true` is not a failure — it is the normal state during development —
    but it must be recorded, because a dirty tree means the commit hash does not
    fully identify the code that ran, and therefore the result is not reproducible
    from the hash alone. A figure on a slide should come from a clean tree.
    """
    import subprocess

    root = Path(repo_root or Path(__file__).resolve().parents[3])
    def _git(*args):
        try:
            return subprocess.run(
                ["git", "-C", str(root), *args], capture_output=True,
                text=True, timeout=10).stdout.strip() or None
        except Exception:
            return None

    status = _git("status", "--porcelain")
    return {
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(status) if status is not None else None,
        "reproducible_from_commit": (status == "") if status is not None
                                    else None,
    }


def build_metadata(summary, *, extra=None, repo_root=None) -> dict:
    """
    Assemble the full provenance document.

    The `honesty` block from `ScenarioSummary.to_dict()` is promoted to a
    top-level key rather than left nested, because a consumer looking for "can I
    quote this?" should not have to know the document layout to find out.
    """
    d = summary.to_dict()
    doc = {
        "schema_version": METADATA_SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "generator": "JALDRISHTI — SIH 2026, Problem Statement 26161 (NTRO)",
        "attribution": SOLVER_ATTRIBUTION,
        "disclaimer": MODEL_DISCLAIMER,
        "scenario": d,
        "honesty": d.get("honesty", {}),
        "environment": environment_record(),
        "git": git_record(repo_root),
        "legal_context": [
            "Dam Safety Act, 2021 — mandates dam-break studies and Emergency "
            "Action Plans for specified dams.",
            "NDMA Guidelines on Management of Glacial Lake Outburst Floods.",
            "CWC guidelines for dam-break analysis and inundation mapping.",
            "Sendai Framework for Disaster Risk Reduction, Priority 4 — "
            "enhancing disaster preparedness for effective response.",
        ],
    }
    if extra:
        doc["extra"] = extra
    return doc


def write_metadata(summary, path, *, extra=None, repo_root=None) -> Path:
    """
    Write the provenance JSON, strictly.

    `allow_nan=False` is the point of this function. Python's json module emits
    bare `NaN` by default, which is not valid JSON and which `JSON.parse` rejects
    — so a scenario that flooded nothing (first arrival = NaN) would produce a
    file that every downstream reader chokes on. `ScenarioSummary.to_dict()`
    already sanitises; this asserts that it did, at the boundary, where the
    failure is diagnosable.
    """
    doc = build_metadata(summary, extra=extra, repo_root=repo_root)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, indent=2, ensure_ascii=False, allow_nan=False,
                      sort_keys=False)
    path.write_text(text, encoding="utf-8")
    return path


def write_manifest(run_dir, path=None, *, hash_files=True) -> Path:
    """
    Inventory every file in the run directory with size and content hash.

    Excludes itself, which would otherwise be a file whose hash depends on its
    own hash.
    """
    run_dir = Path(run_dir)
    path = Path(path) if path else run_dir / "MANIFEST.json"

    entries = []
    for f in sorted(run_dir.rglob("*")):
        if not f.is_file() or f.resolve() == path.resolve():
            continue
        rec = {
            "path": f.relative_to(run_dir).as_posix(),
            "bytes": f.stat().st_size,
        }
        if hash_files:
            rec["sha256"] = sha256_of(f)
        entries.append(rec)

    doc = {
        "schema_version": METADATA_SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "run_dir": run_dir.name,
        "file_count": len(entries),
        "total_bytes": sum(e["bytes"] for e in entries),
        "files": entries,
        "note": "SHA-256 lets a recipient verify integrity and lets a reviewer "
                "confirm two runs produced identical output. Same inputs and "
                "same code give the same hashes.",
    }
    path.write_text(json.dumps(doc, indent=2, allow_nan=False),
                    encoding="utf-8")
    return path


def write_readme(summary, path) -> Path:
    """
    A plain-text README in the run directory.

    Not decoration. The realistic delivery path for this output is a ZIP on a
    pen drive or in an email, opened months later by someone who was not in the
    room. Everything needed to interpret the files correctly — and everything
    needed to avoid over-reading them — has to be in a file that opens in
    Notepad.
    """
    ok, reasons = summary.is_presentable()
    lines = [
        "JALDRISHTI — dam-break inundation simulation output",
        "Smart India Hackathon 2026 · Problem Statement 26161 · NTRO",
        "=" * 72,
        "",
        f"Run           : {summary.run_id}",
        f"Study area    : {summary.study_area}",
        f"Scenario      : {summary.scenario}",
        f"Grid          : {summary.shape[1]} x {summary.shape[0]} "
        f"cells at {summary.dx:g} m",
        f"Simulated     : {summary.duration_s / 3600.0:.2f} hours",
        f"Generated     : {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        "HEADLINE",
        "-" * 72,
        summary.headline(),
        "",
        "CAN THIS BE QUOTED AS FACT?",
        "-" * 72,
    ]
    if ok:
        lines.append(
            "Yes, within the limitations listed below. All input citations are "
            "verified against primary sources.")
    else:
        lines.append("NO — not without the qualifications below:")
        lines += [f"  ! {r}" for r in reasons]
    lines += [
        "",
        "FILES",
        "-" * 72,
        "  arrival_time_min.tif     minutes from failure to first wetting.",
        "                           NODATA = never reached. THE key product.",
        "  arrival_band.tif         isochrone band index; -1 never flooded,",
        "                           -2 already water before failure.",
        "  max_depth_m.tif          peak water depth, metres.",
        "  max_speed_ms.tif         peak flow speed, m/s.",
        "  max_depth_velocity.tif   peak of depth x speed (NOT the product of",
        "                           the two peaks, which occur at different",
        "                           times and would overstate hazard).",
        "  hazard_rating.tif        Defra/EA HR = d(v + 0.5) + debris factor.",
        "  hazard_class_*.tif       Defra and AIDR hazard classes.",
        "  dem_valid.tif            0 where elevation was interpolated across",
        "                           a void — depths there are weaker evidence.",
        "  shapefile/               same content as ESRI Shapefile (zipped).",
        "  kml/                     same content as KMZ for Google Earth.",
        "  metadata.json            full provenance: DEM vintage, roughness,",
        "                           breach parameters, versions, git commit.",
        "  MANIFEST.json            SHA-256 of every file above.",
        "  report.pdf               response-ready briefing document.",
        "",
        "HOW TO READ ARRIVAL TIME",
        "-" * 72,
        "Arrival time is measured from the moment of dam failure. It is NOT",
        "warning time. Warning time = arrival time minus (detection + decision",
        "+ dissemination), and those three are institutional quantities this",
        "model knows nothing about. Subtract your own EAP timings before using",
        "these numbers to plan an evacuation.",
        "",
        "ATTRIBUTION",
        "-" * 72,
    ]
    lines += _wrap(SOLVER_ATTRIBUTION)
    lines += ["", "DISCLAIMER", "-" * 72]
    lines += _wrap(MODEL_DISCLAIMER)

    if summary.unverified_inputs:
        lines += ["", "UNVERIFIED INPUTS", "-" * 72,
                  "These figures are not yet confirmed against a primary "
                  "source and", "must not be presented as fact:"]
        for t in summary.unverified_inputs:
            lines += _wrap(t, bullet="  - ")

    lines += ["", "LIMITATIONS", "-" * 72]
    for t in summary.limitations:
        lines += _wrap(t, bullet="  - ")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _wrap(text, width=72, bullet=""):
    import textwrap
    return textwrap.wrap(text, width=width, initial_indent=bullet,
                         subsequent_indent=" " * len(bullet)) or [bullet]

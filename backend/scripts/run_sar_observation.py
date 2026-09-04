"""
Live Sentinel-1 SAR flood observation via Google Earth Engine.

This is the ONE piece of JALDRISHTI that hits Earth Engine over the network.
Everything in `jaldrishti/gee/flood_observe.py` is pure graph-building and is
covered offline by `tests/test_gee.py`; the numbers can only be checked here,
against the live archive, by eye against the deck overlay.

    # one-time, interactive, provisions local credentials:
    earthengine authenticate

    # smoke test — realise the flood image and print its area (a getInfo call):
    python scripts/run_sar_observation.py --project MY_EE_PROJECT --area rishi_ganga

    # queue the GeoTIFF export to Google Drive (folder "jaldrishti"):
    python scripts/run_sar_observation.py --project MY_EE_PROJECT --export

    # override the change-detection window or threshold for tuning:
    python scripts/run_sar_observation.py --project P --pre-days 36 --post-days 24
    python scripts/run_sar_observation.py --project P --threshold 1.4

Export goes to Google Drive ONLY (Community EE tier has no billing account, so
Cloud Storage export fails). Pick the GeoTIFF up from Drive/jaldrishti/ and drop
it on the deck as the "what Sentinel-1 saw" overlay against our modelled routing.
"""
import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# Load backend/.env so EE_PROJECT (and later Supabase keys) need not be exported
# by hand every shell. Silent no-op if python-dotenv or the file is absent.
try:
    from dotenv import load_dotenv

    load_dotenv(BACKEND / ".env")
except ImportError:
    pass

from jaldrishti.config import STUDY_AREAS
from jaldrishti.gee import flood_observe as F

p = argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("--area", default="rishi_ganga",
               help="study-area key; must carry a blockage event date")
p.add_argument("--project", default=None,
               help="Cloud project registered with Earth Engine (usually "
                    "required); falls back to EE_PROJECT in backend/.env")
p.add_argument("--export", action="store_true",
               help="queue a Drive GeoTIFF export instead of just reporting area")
p.add_argument("--no-start", action="store_true",
               help="build the export task but do not start it")
p.add_argument("--pre-days", type=int, default=None, help="pre-event window length")
p.add_argument("--post-days", type=int, default=None, help="post-event window length")
p.add_argument("--threshold", type=float, default=None,
               help="pre/post ratio flood threshold (dB), default %.2f"
                    % F.DIFF_THRESHOLD_DB)
p.add_argument("--orbit", default=None, choices=["ASCENDING", "DESCENDING"],
               help="restrict to one orbit pass (default: either)")
a = p.parse_args()

if a.area not in STUDY_AREAS:
    p.error(f"unknown area '{a.area}'; choose from {sorted(STUDY_AREAS)}")
area = STUDY_AREAS[a.area]

overrides = {}
if a.pre_days is not None:
    overrides["pre_window_days"] = a.pre_days
if a.post_days is not None:
    overrides["post_window_days"] = a.post_days
if a.threshold is not None:
    overrides["diff_threshold_db"] = a.threshold
if a.orbit is not None:
    overrides["orbit_pass"] = a.orbit

try:
    spec = F.FloodObsSpec.for_study_area(area, **overrides)
except ValueError as exc:
    p.error(str(exc))

print("=" * 74)
print(f"SAR flood observation — {area.title}")
print("=" * 74)
print(f"  event date     {spec.event_date}")
print(f"  pre window     {spec.pre_start} .. {spec.pre_end} "
      f"({spec.pre_window_days} d)")
print(f"  post window    {spec.post_start} .. {spec.post_end} "
      f"({spec.post_window_days} d)")
print(f"  AOI (lon/lat)  W {spec.aoi.west:.4f}  S {spec.aoi.south:.4f}  "
      f"E {spec.aoi.east:.4f}  N {spec.aoi.north:.4f}")
print(f"  polarisation   {spec.polarization}   orbit {spec.orbit_pass or 'either'}")
print(f"  threshold      {spec.diff_threshold_db} dB   "
      f"slope <= {spec.max_slope_deg} deg   "
      f"scale {spec.export_scale_m} m")
print()

ee = F.initialize(project=a.project)

if a.export:
    desc = f"jaldrishti_sar_{area.key}"
    task = F.export_to_drive(ee, spec, description=desc,
                             start=not a.no_start)
    started = "started" if getattr(task, "started", False) else "built (not started)"
    print(f"  export task {started}: Drive/jaldrishti/{desc}.tif  (GeoTIFF)")
    print("  monitor at https://code.earthengine.google.com/tasks or "
          "`earthengine task list`")
else:
    print("  realising flood image (getInfo) ...")
    km2 = F.observed_area_km2(ee, spec)
    print(f"  SAR-observed surface change consistent with inundation/wetting: "
          f"{km2:.2f} km^2")
    print("  (standing water only; a fast debris flow may have passed between "
          "passes — see module docstring)")

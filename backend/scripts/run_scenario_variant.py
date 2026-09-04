"""
End-to-end scenario runs for the PS deliverables that are not the headline
dam-break demo:

  --mode blockage  : Chamoli/Rishi Ganga river blockage (Scenario C)
  --mode release   : Tehri gated water release (the PS's "water release" case)

Both write the full export bundle (GeoTIFF, KMZ, shapefiles, PDF report,
metadata) under outputs/runs/, exactly like the headline Tehri breach run.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jaldrishti.scenario.run import run_scenario

p = argparse.ArgumentParser()
p.add_argument("--mode", choices=["blockage", "release"], required=True)
p.add_argument("--dx", type=float, default=90.0)
p.add_argument("--hours", type=float, default=None)
p.add_argument("--head", type=float, default=15.0, help="release acting head, m")
p.add_argument("--width", type=float, default=80.0, help="release width, m")
a = p.parse_args()

if a.mode == "blockage":
    res = run_scenario(
        "rishi_ganga",
        dx=a.dx,
        duration_s=(a.hours or 1.5) * 3600.0,
        exposure=True,
        damage=False,
        export_bundle=True,
    )
else:
    res = run_scenario(
        "tehri",
        dx=a.dx,
        duration_s=(a.hours or 3.0) * 3600.0,
        failure_mode="water_release",
        release_head_m=a.head,
        release_width_m=a.width,
        exposure=True,
        damage=False,
        export_bundle=True,
    )

if res.summary is not None:
    d = res.summary.to_dict()
    print(json.dumps(d["results"], indent=2, default=str))
    print("bundle:", res.run_dir)

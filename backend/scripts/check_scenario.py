"""
Build check for the scenario orchestrator.

Not a test — a build check. `setup_only` mode runs terrain, roughness, hydrology,
reservoir detection and the breach model, then STOPS before the first timestep.
That is where scenarios actually go wrong, and checking it costs seconds instead
of minutes.

    python scripts/check_scenario.py            # setup only, dx = 90 m
    python scripts/check_scenario.py --run       # step it too
    python scripts/check_scenario.py --dx 30     # high-res setup
    python scripts/check_scenario.py --hours 2   # shorter run
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jaldrishti.scenario.run import run_scenario

p = argparse.ArgumentParser()
p.add_argument("--area", default="tehri")
p.add_argument("--dx", type=float, default=90.0)
p.add_argument("--hours", type=float, default=6.0)
p.add_argument("--run", action="store_true", help="step the solver, not setup only")
p.add_argument("--no-export", action="store_true")
p.add_argument("--no-exposure", action="store_true")
p.add_argument("--damage", action="store_true")
a = p.parse_args()

res = run_scenario(
    a.area,
    dx=a.dx,
    duration_s=a.hours * 3600.0,
    setup_only=not a.run,
    exposure=not a.no_exposure,
    damage=a.damage,
    export_bundle=not a.no_export,
)

print("\n" + "=" * 74)
print("SETUP RECORD")
print("=" * 74)
print(json.dumps(res.setup, indent=2, default=str))

if res.summary is not None:
    print("\n" + "=" * 74)
    print("HONESTY BLOCK — the part a jury reads")
    print("=" * 74)
    d = res.summary.to_dict()
    print(json.dumps(d["honesty"], indent=2, default=str))
    print("\nRESULTS")
    print(json.dumps(d["results"], indent=2, default=str))
    if res.run_dir:
        print(f"\nbundle: {res.run_dir}")

"""Live GEE connectivity probe: authenticate, list a Sentinel-1 collection."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from jaldrishti.gee import flood_observe  # noqa: E402

try:
    ee = flood_observe.initialize()
    print("GEE: initialized OK")
    n = (ee.ImageCollection("COPERNICUS/S1_GRD")
         .filterDate("2021-02-01", "2021-02-28")
         .filterBounds(ee.Geometry.Point([79.73, 30.38]))
         .size()
         .getInfo())
    print(f"Sentinel-1 GRD scenes over Chamoli, Feb 2021: {n}")
except Exception as exc:
    print(f"GEE live check FAILED: {type(exc).__name__}: {exc}")
    print("fallback position: batch export code path is ready; run "
          "`earthengine authenticate` then retry.")

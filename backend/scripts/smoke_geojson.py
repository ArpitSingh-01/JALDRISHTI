"""Smoke: derive isochrone + settlement GeoJSON from the real Tehri bundle."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jaldrishti.config import STUDY_AREAS  # noqa: E402
from jaldrishti.export.geojson import settlements_fc, isochrones_fc  # noqa: E402

bundle = Path(__file__).resolve().parents[2] / "outputs" / "runs" \
    / "tehri_90m_20260902T041110Z"

t0 = time.perf_counter()
iso = isochrones_fc(bundle)
n_polys = len(iso["features"])
print(f"isochrones: {n_polys} polygons in {time.perf_counter() - t0:.1f}s")
for f in iso["features"][:6]:
    print("  ", f["properties"]["label"],
          "ring pts:", len(f["geometry"]["coordinates"][0]),
          "lon0:", round(f["geometry"]["coordinates"][0][0][0], 4),
          "lat0:", round(f["geometry"]["coordinates"][0][0][1], 4))

t0 = time.perf_counter()
st = settlements_fc(bundle, STUDY_AREAS["tehri"])
print(f"settlements: {len(st['features'])} in {time.perf_counter() - t0:.1f}s")
for f in st["features"]:
    print("  ", f["properties"])

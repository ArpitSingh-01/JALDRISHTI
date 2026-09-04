"""Throwaway: does the Rishi Ganga event point fall inside its own domain box?

Also proposes a corrected box that brackets the event + all downstream POIs
with a margin, snapped to the interactive grid spacing.
"""
import math

from pyproj import Transformer

from jaldrishti.config import RISHI_GANGA as r

d = r.domain
b = r.blockage
t = Transformer.from_crs("EPSG:4326", d.crs, always_xy=True)
ex, ey = t.transform(b.lon, b.lat)
print("event lon/lat  ", b.lon, b.lat)
print("event UTM44N   ", round(ex), round(ey))
print("domain x range ", d.xmin, d.xmax, " in?", d.xmin <= ex <= d.xmax)
print("domain y range ", d.ymin, d.ymax, " in?", d.ymin <= ey <= d.ymax)
print()

pts = [("EVENT (avalanche source)", ex, ey)]
for p in r.downstream:
    px, py = t.transform(p.lon, p.lat)
    inside = d.xmin <= px <= d.xmax and d.ymin <= py <= d.ymay if False \
        else (d.xmin <= px <= d.xmax and d.ymin <= py <= d.ymax)
    print(f"  {p.name:28s} UTM ({round(px)},{round(py)})  in? {inside}")
    pts.append((p.name, px, py))

# --- propose a corrected box ---------------------------------------------- #
xs = [p[1] for p in pts]
ys = [p[2] for p in pts]
margin = 4_000.0          # ~4 km buffer around the extreme points
snap = d.dx_interactive_m  # snap to interactive grid spacing (90 m)


def floor_to(v, s):
    return math.floor((v - margin) / s) * s


def ceil_to(v, s):
    return math.ceil((v + margin) / s) * s


nxmin = floor_to(min(xs), snap)
nxmax = ceil_to(max(xs), snap)
nymin = floor_to(min(ys), snap)
nymax = ceil_to(max(ys), snap)
print()
print("point easting  span", round(min(xs)), "->", round(max(xs)))
print("point northing span", round(min(ys)), "->", round(max(ys)))
print()
print("PROPOSED corrected Domain (margin 4 km, snapped to 90 m):")
print(f"    xmin={nxmin:_.0f}, ymin={nymin:_.0f},")
print(f"    xmax={nxmax:_.0f}, ymax={nymax:_.0f},")
print(f"    width  {(nxmax - nxmin) / 1000:.1f} km  x  "
      f"height {(nymax - nymin) / 1000:.1f} km")

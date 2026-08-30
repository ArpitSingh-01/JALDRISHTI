"""
Flood hazard classification — turning depth and velocity into a danger rating.

WHY A PUBLISHED SCHEME AND NOT OUR OWN
--------------------------------------
Depth alone does not measure danger. 0.5 m of standing water is a nuisance; 0.5 m
moving at 4 m/s sweeps an adult off their feet and rolls a car. The product of
depth and velocity is what the flood-safety literature actually correlates with
harm, and `SWE2D.max_dv` tracks it as a running maximum inside the time loop for
exactly this reason.

The thresholds separating "wade through it" from "fatal" are empirical — they come
from flume experiments on human subjects, vehicle stability tests and post-event
casualty studies. We are not in a position to derive them, and inventing round
numbers that look authoritative would be the worst kind of overclaim. So this
module implements two PUBLISHED schemes and cites both:

  DEFRA/EA (UK)  — a continuous hazard rating, HR = d(v + 0.5) + DF. Continuous
                   output makes a smooth raster and a legible legend, and the
                   debris factor lets land cover raise the rating where floating
                   debris is likely. Used as the default.

  AIDR (Australia) — six discrete classes H1-H6 defined by combined limits on
                   d*v, d and v. Its class descriptions are written in terms of
                   what fails (people, small vehicles, all vehicles, timber
                   buildings, all buildings), which is the vocabulary a disaster
                   response officer already thinks in.

They are complementary rather than redundant: DEFRA answers "how dangerous is this
cell", AIDR answers "what specifically breaks here". The report prints both.

WHY BOTH ARE CAPPED BY THE MODEL'S OWN RESOLUTION
-------------------------------------------------
At 90 m a cell averages depth over 8100 m^2. Real hazard at a doorstep is a
metre-scale quantity. A hazard class is therefore a statement about a
neighbourhood, never about a building, and `HazardResult` carries that caveat as
a field rather than leaving it to a footnote.

SOURCES
-------
See `HAZARD_SOURCES`. Both entries are currently `verified=False`: the schemes are
standard and widely reproduced, but nobody on this project has yet opened the
primary documents and checked the tables line by line. Per `config.py`'s
convention that is not good enough to put on a slide, and
`export/metadata.py` is expected to surface it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------
# Same convention as scenario/breach.py: (citation, verified).
HAZARD_SOURCES = {
    "defra_hazard_rating": (
        "Ramsbottom, D., Floyd, P. & Penning-Rowsell, E. (2003-2006), "
        "'Flood Risks to People' Phase 2, Defra/Environment Agency R&D "
        "Technical Report FD2321/FD2320. Hazard rating HR = d(v + 0.5) + DF "
        "with the debris factor table and the four danger bands.", False),
    "aidr_hazard_classes": (
        "Australian Institute for Disaster Resilience (2017), 'Guideline 7-3: "
        "Flood Hazard', Australian Disaster Resilience Handbook Collection; "
        "after Smith, G. et al. (2014) UNSW Water Research Laboratory. "
        "Combined hazard curves H1-H6.", False),
}


# ---------------------------------------------------------------------------
# DEFRA / Environment Agency hazard rating
# ---------------------------------------------------------------------------
# HR = d * (v + 0.5) + DF
#
# The 0.5 offset is what stops still water from scoring zero: standing water is
# still a hazard through drowning depth alone, independent of velocity.
DEFRA_VELOCITY_OFFSET = 0.5

# Band edges, in HR units. From FD2320/FD2321.
DEFRA_BANDS = (0.75, 1.25, 2.5)

DEFRA_CLASS_NAMES = (
    "Low",
    "Moderate",
    "Significant",
    "Extreme",
)

# The plain-language meaning of each band, as published. These strings go
# straight into the PDF legend, so they are kept verbatim in spirit rather than
# paraphrased into something softer.
DEFRA_CLASS_MEANING = (
    "Caution — shallow flowing water or deep standing water",
    "Dangerous for some — children and the infirm at risk",
    "Dangerous for most people — evacuation on foot unsafe",
    "Dangerous for all — including emergency services",
)

# Colours for the legend. A SEQUENTIAL yellow-to-dark-red ramp, deliberately
# distinct from the Indian-flag palette used for UI chrome: hazard must read as
# a measured quantity, not as branding.
DEFRA_CLASS_COLOURS = (
    "#ffeda0",
    "#feb24c",
    "#f03b20",
    "#7f0000",
)

# Debris factor, FD2320. Rows are depth bands, columns are land-cover classes.
# Debris matters because most flood fatalities in fast water involve impact, not
# drowning: a 0.5 m flow carrying fenceposts is not the same hazard as 0.5 m of
# clean water.
DEBRIS_LANDCOVER = ("pasture_arable", "woodland", "urban")
DEBRIS_FACTOR = {
    #                        pasture  woodland  urban
    "shallow": (0.0, 0.0, 0.0),      # d < 0.25 m
    "medium": (0.0, 0.5, 1.0),       # 0.25 <= d < 0.75 m
    "deep": (0.5, 1.0, 1.0),         # d >= 0.75 m, or v > 2 m/s
}
DEBRIS_DEEP_VELOCITY = 2.0


def debris_factor(depth, speed, landcover="urban"):
    """
    Per-cell debris factor DF.

    `landcover` is either one of DEBRIS_LANDCOVER, or an integer array of indices
    into it — so a real land-cover raster can drive it cell by cell while a
    single-scenario run can pass one conservative string.

    Defaulting to "urban" is the conservative choice, and deliberate: an
    underestimated hazard rating in an evacuation product is the dangerous
    direction of error.
    """
    depth = np.asarray(depth, dtype=np.float64)
    speed = np.asarray(speed, dtype=np.float64)

    if isinstance(landcover, str):
        if landcover not in DEBRIS_LANDCOVER:
            raise ValueError(
                f"landcover must be one of {DEBRIS_LANDCOVER} or an index "
                f"array, got {landcover!r}")
        col = np.full(depth.shape, DEBRIS_LANDCOVER.index(landcover), dtype=int)
    else:
        col = np.asarray(landcover, dtype=int)
        if col.shape != depth.shape:
            raise ValueError(
                f"landcover index array {col.shape} must match depth "
                f"{depth.shape}")
        if col.min() < 0 or col.max() >= len(DEBRIS_LANDCOVER):
            raise ValueError("landcover indices out of range")

    # Row selection. The velocity clause is an OR, not an AND: fast water is
    # treated as debris-carrying regardless of how shallow it is.
    deep = (depth >= 0.75) | (speed > DEBRIS_DEEP_VELOCITY)
    medium = (~deep) & (depth >= 0.25)

    table = np.array([DEBRIS_FACTOR["shallow"],
                      DEBRIS_FACTOR["medium"],
                      DEBRIS_FACTOR["deep"]], dtype=np.float64)
    row = np.where(deep, 2, np.where(medium, 1, 0))
    return table[row, col]


def defra_hazard_rating(depth, speed, *, landcover="urban", dv=None):
    """
    HR = d * (v + 0.5) + DF, the Defra/EA flood hazard rating.

    Pass `dv` (from `SWE2D.max_dv`) when it is available, and it is used in place
    of depth*speed. This is not a micro-optimisation — it is a correctness point.
    `max_depth * max_speed` multiplies two peaks that occur at DIFFERENT times
    and overstates the hazard: a dam-break front is fast and shallow, its body is
    deep and slow. `max_dv` is the running maximum of the product itself.

    The additive `0.5*d` term must still use max_depth, since drowning depth is a
    hazard in its own right and is not captured by the product.
    """
    depth = np.asarray(depth, dtype=np.float64)
    speed = np.asarray(speed, dtype=np.float64)
    product = np.asarray(dv, dtype=np.float64) if dv is not None else depth * speed
    hr = product + DEFRA_VELOCITY_OFFSET * depth
    return hr + debris_factor(depth, speed, landcover=landcover)


def defra_hazard_class(hazard_rating, *, dry_mask=None):
    """
    Bin a hazard rating into 0..3 (Low/Moderate/Significant/Extreme).

    Returns int8 with -1 for dry cells, so "not flooded" is never confused with
    "flooded but low hazard" — a distinction that matters enormously when the
    output is counted into an exposure table.
    """
    hr = np.asarray(hazard_rating, dtype=np.float64)
    cls = np.digitize(hr, DEFRA_BANDS).astype(np.int8)
    if dry_mask is not None:
        cls = np.where(np.asarray(dry_mask, dtype=bool), np.int8(-1), cls)
    return cls.astype(np.int8)


# ---------------------------------------------------------------------------
# AIDR combined hazard curves
# ---------------------------------------------------------------------------
# Each class is the FIRST whose three limits are all satisfied. Ordered from
# least to most hazardous; anything exceeding H5 is H6.
#
#            (label, dv_max, d_max, v_max, description)
AIDR_CLASSES = (
    ("H1", 0.3, 0.3, 2.0,
     "Generally safe for people, vehicles and buildings"),
    ("H2", 0.6, 0.5, 2.0,
     "Unsafe for small vehicles"),
    ("H3", 0.6, 1.2, 2.0,
     "Unsafe for vehicles, children and the elderly"),
    ("H4", 1.0, 2.0, 2.0,
     "Unsafe for people and all vehicles"),
    ("H5", 4.0, 4.0, 4.0,
     "Unsafe for people and vehicles; buildings vulnerable to structural "
     "damage; some less robust buildings fail"),
    ("H6", np.inf, np.inf, np.inf,
     "Unsafe for people and vehicles; all buildings vulnerable to failure"),
)

AIDR_CLASS_COLOURS = (
    "#ffffb2", "#fed976", "#feb24c", "#fd8d3c", "#e31a1c", "#800026",
)


def aidr_hazard_class(depth, speed, *, dv=None, dry_mask=None):
    """
    Classify into AIDR H1-H6 (returned as 0..5; -1 for dry).

    Assignment is by the first class whose limits are ALL met, which is what
    makes the scheme conservative: a cell that is only 0.2 m deep but moving at
    3 m/s fails H1-H4's velocity limit and lands in H5, correctly, because the
    danger is the velocity.
    """
    depth = np.asarray(depth, dtype=np.float64)
    speed = np.asarray(speed, dtype=np.float64)
    product = np.asarray(dv, dtype=np.float64) if dv is not None else depth * speed

    out = np.full(depth.shape, len(AIDR_CLASSES) - 1, dtype=np.int8)
    # Walk from most to least hazardous so earlier (safer) classes win.
    for idx in range(len(AIDR_CLASSES) - 2, -1, -1):
        _label, dv_lim, d_lim, v_lim, _desc = AIDR_CLASSES[idx]
        fits = (product <= dv_lim) & (depth <= d_lim) & (speed <= v_lim)
        out = np.where(fits, np.int8(idx), out)

    if dry_mask is not None:
        out = np.where(np.asarray(dry_mask, dtype=bool), np.int8(-1), out)
    return out.astype(np.int8)


# ---------------------------------------------------------------------------
# result object
# ---------------------------------------------------------------------------
@dataclass
class HazardResult:
    """
    Hazard rasters plus the areas they cover and the caveats they carry.

    `limitations` is a first-class field, not documentation. Every consumer —
    PDF, API, frontend — is expected to render it, because the PS asks for
    "probable" and "confidence-based" output and a hazard map presented without
    its resolution caveat is not that.
    """
    rating: np.ndarray                  # continuous Defra HR
    defra_class: np.ndarray             # int8, -1 dry, 0..3
    aidr_class: np.ndarray              # int8, -1 dry, 0..5
    cell_area_m2: float
    dry_mask: np.ndarray
    initially_wet: np.ndarray | None = None
    limitations: list[str] = field(default_factory=list)
    sources: dict = field(default_factory=lambda: dict(HAZARD_SOURCES))

    @property
    def flooded_cells(self) -> int:
        """Cells holding water at peak — the reservoir included."""
        return int((~self.dry_mask).sum())

    @property
    def flooded_area_km2(self) -> float:
        return self.flooded_cells * self.cell_area_m2 / 1.0e6

    @property
    def newly_flooded_area_km2(self) -> float:
        """
        Area inundated that was dry before the failure.

        This is the number that belongs in a headline. `flooded_area_km2`
        includes the reservoir, which at Tehri is roughly 42 km^2 of water that
        was already there — quoting it as "area flooded" would inflate the
        result by a fixed amount that has nothing to do with the breach.
        """
        if self.initially_wet is None:
            return self.flooded_area_km2
        new = (~self.dry_mask) & ~np.asarray(self.initially_wet, dtype=bool)
        return int(new.sum()) * self.cell_area_m2 / 1.0e6

    def area_by_defra_class_km2(self) -> dict[str, float]:
        """Inundated area in each Defra band, km^2."""
        out = {}
        for idx, name in enumerate(DEFRA_CLASS_NAMES):
            n = int((self.defra_class == idx).sum())
            out[name] = n * self.cell_area_m2 / 1.0e6
        return out

    def area_by_aidr_class_km2(self) -> dict[str, float]:
        out = {}
        for idx, (label, *_rest) in enumerate(AIDR_CLASSES):
            n = int((self.aidr_class == idx).sum())
            out[label] = n * self.cell_area_m2 / 1.0e6
        return out

    def unverified_sources(self) -> list[str]:
        """Citations not yet checked against a primary document."""
        return [f"{k}: {v[0]}" for k, v in self.sources.items() if not v[1]]

    def summary(self) -> str:
        lines = [
            f"flooded area : {self.flooded_area_km2:.2f} km^2 "
            f"({self.flooded_cells:,} cells at {self.cell_area_m2:.0f} m^2)",
        ]
        if self.initially_wet is not None:
            lines.append(
                f"  of which NEW : {self.newly_flooded_area_km2:.2f} km^2 "
                f"(the rest was already water before failure)")
        lines.append("Defra hazard bands:")
        for name, km2 in self.area_by_defra_class_km2().items():
            pct = 100 * km2 / self.flooded_area_km2 if self.flooded_area_km2 else 0
            lines.append(f"  {name:<12} {km2:8.2f} km^2  ({pct:5.1f}%)")
        lines.append("AIDR classes:")
        for label, km2 in self.area_by_aidr_class_km2().items():
            if km2 > 0:
                lines.append(f"  {label:<12} {km2:8.2f} km^2")
        if self.limitations:
            lines.append("limitations:")
            lines += [f"  - {t}" for t in self.limitations]
        return "\n".join(lines)


def classify(max_depth, max_speed, max_dv, *, dx,
             landcover="urban", wet_threshold=0.1,
             initially_wet=None, resolution_note=True) -> HazardResult:
    """
    The one call the orchestrator makes.

    `wet_threshold` must match the threshold passed to `SWE2D.track_maxima` — the
    default 0.1 m in both places — otherwise arrival time and hazard extent
    disagree about which cells flooded, and the exposure table inherits the
    inconsistency.

    `initially_wet` is the reservoir and pre-existing channel. It does not change
    any hazard value — the reservoir genuinely is hazardous — but it lets
    `newly_flooded_area_km2` report the inundation the breach actually caused,
    rather than that plus the lake that was already there.
    """
    max_depth = np.asarray(max_depth, dtype=np.float64)
    max_speed = np.asarray(max_speed, dtype=np.float64)
    max_dv = None if max_dv is None else np.asarray(max_dv, dtype=np.float64)

    if max_depth.shape != max_speed.shape:
        raise ValueError("max_depth and max_speed must have the same shape")
    if initially_wet is not None:
        initially_wet = np.asarray(initially_wet, dtype=bool)
        if initially_wet.shape != max_depth.shape:
            raise ValueError(
                f"initially_wet {initially_wet.shape} must match max_depth "
                f"{max_depth.shape}")

    dry = max_depth < wet_threshold
    rating = defra_hazard_rating(max_depth, max_speed,
                                 landcover=landcover, dv=max_dv)
    rating = np.where(dry, 0.0, rating)

    limitations = []
    if resolution_note:
        limitations.append(
            f"Hazard is computed on {dx:.0f} m cells, so each value is an "
            f"average over {dx * dx / 1.0e4:.2f} ha. It describes a "
            f"neighbourhood, not an individual building or street."
        )
    limitations.append(
        f"Cells shallower than {wet_threshold:.2f} m are reported as dry: below "
        f"that a {dx:.0f} m DEM cannot distinguish real sheet flow from "
        f"interpolation noise."
    )
    if isinstance(landcover, str):
        limitations.append(
            f"A single debris factor for '{landcover}' land cover is applied "
            f"across the whole domain; a land-cover raster would vary it."
        )
    if initially_wet is None:
        limitations.append(
            "No initially-wet mask was supplied, so the reservoir surface and "
            "the pre-existing river channel are counted in the flooded area."
        )

    return HazardResult(
        rating=rating,
        defra_class=defra_hazard_class(rating, dry_mask=dry),
        aidr_class=aidr_hazard_class(max_depth, max_speed, dv=max_dv,
                                     dry_mask=dry),
        cell_area_m2=float(dx) * float(dx),
        dry_mask=dry,
        initially_wet=initially_wet,
        limitations=limitations,
    )

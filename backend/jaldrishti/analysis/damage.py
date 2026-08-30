"""
Damage estimation — depth-damage curves, reported as ranges.

WHY RANGES AND NEVER POINT VALUES
---------------------------------
`CLAUDE.md`: *"Never overclaim. The PS says 'probable' and 'confidence-based'
repeatedly."* Damage is the output where that rule bites hardest, because a
currency figure carries an air of precision that nothing else in the chain
deserves. The number "Rs 847 crore" reads as an accounting result. It is in fact
the product of:

    a modelled depth (+/- the DEM, the breach assumption, Manning n)
  x a modelled asset count (OSM completeness varies enormously by district)
  x a generic depth-damage curve (continental, not local)
  x an assumed asset value (the largest uncertainty of the four, and the one
    nobody publishes for rural Uttarakhand)

Multiplying four uncertain factors and printing one number is indefensible. So
every function here returns a `DamageRange`, and the report prints "Rs 600-1,200
crore (order-of-magnitude estimate)". A jury that sees an honest range trusts the
rest of the model more, not less.

WHAT A DEPTH-DAMAGE CURVE IS
----------------------------
A monotone function from inundation depth to the fraction of an asset's
replacement value lost. It is empirical, fitted to post-event loss-adjuster data,
and it is specific to construction type: a reinforced-concrete house and a mud
house at 2 m depth do not lose the same fraction. The curves below are the JRC
global set, which is the standard reference for exactly this situation — a study
outside the countries that publish their own curves.

DEPTH IS NOT THE ONLY DRIVER, AND WE SAY SO
-------------------------------------------
Depth-damage curves ignore velocity, and for a DAM BREAK that is a material
omission: a 3 m/s flow destroys a masonry wall that would have survived the same
depth standing still. Structural failure is a hazard-class question, not a
depth-damage-curve question. `DamageResult` therefore reports the population and
building count in AIDR class H5-H6 — "buildings vulnerable to structural
failure" — as a separate figure alongside the curve-based loss, rather than
pretending the curve covers it.

SOURCES
-------
All entries in `DAMAGE_SOURCES` are `verified=False`. The curve shapes below are
the widely-reproduced JRC values, but nobody on this project has yet opened
JRC105688 and checked the tables. Until that happens the damage figures are
labelled ORDER-OF-MAGNITUDE and `export/metadata.py` records the flag. Do not put
a rupee figure on a slide while this is False.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

DAMAGE_SOURCES = {
    "jrc_global_curves": (
        "Huizinga, J., de Moel, H. & Szewczyk, W. (2017), 'Global flood depth-"
        "damage functions: Methodology and the database with guidelines', "
        "EUR 28552 EN, JRC Technical Report JRC105688, "
        "doi:10.2760/16510 — Asia curves for residential, commercial, "
        "industrial and infrastructure classes.", False),
    "asset_values": (
        "Asset replacement values are NOT taken from a published source. They "
        "are order-of-magnitude assumptions stated in ASSET_VALUE_INR and must "
        "be replaced with district-level figures (CPWD plinth-area rates, or "
        "state PWD schedules) before any monetary figure is presented.", False),
}


# ---------------------------------------------------------------------------
# depth-damage curves
# ---------------------------------------------------------------------------
# Depth in metres -> fraction of replacement value lost. Piecewise linear
# between the tabulated points; flat above the last point (total loss).
#
# The steepness of the first half-metre is the important feature and the reason
# these curves are not straight lines: most of the damage to a building's
# contents and finishes happens as soon as water enters at all. Doubling depth
# from 2 m to 4 m adds far less than the first 0.5 m did.
CURVES = {
    "residential": {
        "depths": (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0),
        "damage": (0.0, 0.32, 0.53, 0.68, 0.80, 0.93, 0.98, 1.00, 1.00),
    },
    "commercial": {
        "depths": (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0),
        "damage": (0.0, 0.24, 0.42, 0.57, 0.70, 0.87, 0.96, 1.00, 1.00),
    },
    "industrial": {
        "depths": (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0),
        "damage": (0.0, 0.20, 0.36, 0.50, 0.62, 0.81, 0.93, 0.99, 1.00),
    },
    "infrastructure": {
        "depths": (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0),
        "damage": (0.0, 0.25, 0.42, 0.55, 0.65, 0.80, 0.90, 0.96, 1.00),
    },
    "agriculture": {
        "depths": (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0),
        "damage": (0.0, 0.42, 0.62, 0.74, 0.83, 0.94, 0.99, 1.00, 1.00),
    },
}

# Order-of-magnitude replacement values, INR. EXPLICITLY NOT SOURCED — see
# DAMAGE_SOURCES["asset_values"]. Deliberately round, so that nobody mistakes
# them for survey figures.
ASSET_VALUE_INR = {
    "residential_building": 1_200_000,
    "commercial_building": 4_000_000,
    "industrial_building": 12_000_000,
    "road_km": 25_000_000,
    "agriculture_hectare": 250_000,
}

# The factor the reported range spans, either side of the central estimate. 0.5x
# to 2x is the honest width given an unsourced asset value multiplied by a
# continental damage curve. Narrowing this is a data problem, not a code problem.
RANGE_FACTOR_LOW = 0.5
RANGE_FACTOR_HIGH = 2.0


def damage_fraction(depth, curve="residential"):
    """
    Fraction of replacement value lost, from depth.

    Linear interpolation between tabulated points, clamped at both ends: zero
    below the first depth, total loss above the last. `np.interp` already clamps,
    which is the behaviour wanted here — extrapolating a damage curve past its
    fitted range would invent damage fractions above 1.
    """
    if curve not in CURVES:
        raise ValueError(f"unknown damage curve {curve!r}; "
                         f"available: {sorted(CURVES)}")
    c = CURVES[curve]
    d = np.asarray(depth, dtype=np.float64)
    return np.interp(d, c["depths"], c["damage"])


@dataclass(frozen=True)
class DamageRange:
    """
    A damage estimate with its uncertainty made structural.

    There is no `.value` attribute, on purpose. Any code that wants a single
    number has to call `.central` and thereby state that it is discarding the
    range — which makes the choice visible in review instead of implicit.
    """
    central: float
    low: float
    high: float
    unit: str = "INR"

    @classmethod
    def around(cls, central, *, low_factor=RANGE_FACTOR_LOW,
               high_factor=RANGE_FACTOR_HIGH, unit="INR"):
        return cls(central=float(central),
                   low=float(central) * low_factor,
                   high=float(central) * high_factor,
                   unit=unit)

    def __add__(self, other):
        if not isinstance(other, DamageRange):
            return NotImplemented
        if other.unit != self.unit:
            raise ValueError(f"cannot add {self.unit} to {other.unit}")
        return DamageRange(self.central + other.central,
                           self.low + other.low,
                           self.high + other.high, self.unit)

    def in_crore(self) -> tuple[float, float, float]:
        """(low, central, high) in crore rupees — how Indian reports state it."""
        c = 1.0e7
        return self.low / c, self.central / c, self.high / c

    def format_crore(self) -> str:
        lo, _ce, hi = self.in_crore()
        if hi < 1.0:
            return f"under Rs 1 crore (order-of-magnitude estimate)"
        return (f"Rs {_round_sig(lo, 2):,g}-{_round_sig(hi, 2):,g} crore "
                f"(order-of-magnitude estimate)")


def _round_sig(x, sig=2):
    if x == 0:
        return 0.0
    return round(x, -int(math.floor(math.log10(abs(x)))) + (sig - 1))


def building_damage(max_depth, building_rows, building_cols, *,
                    curve="residential", unit_value=None):
    """
    Damage to point-located buildings.

    Sampling depth at each building's own cell, rather than applying an average
    depth to a count, is what makes this worth doing: damage is a strongly
    nonlinear function of depth, so the mean of the damage is not the damage of
    the mean. With a convex-then-concave curve the difference runs in both
    directions and cannot be waved away as conservative.
    """
    depth = np.asarray(max_depth, dtype=np.float64)
    rows = np.asarray(building_rows, dtype=int)
    cols = np.asarray(building_cols, dtype=int)
    if rows.size == 0:
        return DamageRange.around(0.0), np.zeros(0)

    d = depth[rows, cols]
    frac = damage_fraction(d, curve=curve)
    value = ASSET_VALUE_INR["residential_building"] if unit_value is None \
        else float(unit_value)
    return DamageRange.around(float(frac.sum()) * value), frac


def area_damage(max_depth, *, dx, curve="agriculture", value_per_hectare=None,
                mask=None):
    """
    Damage over an area — cropland, or any land-use class given as a mask.

    Integrates the damage fraction cell by cell rather than multiplying a mean
    depth by a total area, for the nonlinearity reason above.
    """
    depth = np.asarray(max_depth, dtype=np.float64)
    frac = damage_fraction(depth, curve=curve)
    if mask is not None:
        frac = np.where(np.asarray(mask, dtype=bool), frac, 0.0)
    cell_ha = (float(dx) ** 2) / 10_000.0
    per_ha = (ASSET_VALUE_INR["agriculture_hectare"]
              if value_per_hectare is None else float(value_per_hectare))
    return DamageRange.around(float(frac.sum()) * cell_ha * per_ha)


def road_damage(flooded_km, *, value_per_km=None, curve_fraction=0.35):
    """
    Damage to flooded road, km x unit value x a single damage fraction.

    A single fraction rather than a depth curve is a deliberate simplification:
    road damage is dominated by scour and embankment failure, which correlate
    with velocity and duration rather than depth, and no depth curve captures
    that. 0.35 is an assumption, flagged as such, and it is why road damage is
    reported as its own line rather than folded into a total.
    """
    per_km = (ASSET_VALUE_INR["road_km"] if value_per_km is None
              else float(value_per_km))
    return DamageRange.around(float(flooded_km) * per_km * curve_fraction)


@dataclass
class DamageResult:
    """Damage by category, plus the structural-failure count the curves miss."""
    by_category: dict = field(default_factory=dict)
    structural_failure_buildings: int = 0
    structural_failure_population: float = 0.0
    limitations: list[str] = field(default_factory=list)
    sources: dict = field(default_factory=lambda: dict(DAMAGE_SOURCES))

    @property
    def total(self) -> DamageRange:
        total = DamageRange(0.0, 0.0, 0.0)
        for r in self.by_category.values():
            total = total + r
        return total

    def unverified_sources(self) -> list[str]:
        return [f"{k}: {v[0]}" for k, v in self.sources.items() if not v[1]]

    def summary(self) -> str:
        lines = ["damage (ORDER-OF-MAGNITUDE — asset values unsourced):"]
        for name, r in self.by_category.items():
            lines.append(f"  {name:<22} {r.format_crore()}")
        lines.append(f"  {'TOTAL':<22} {self.total.format_crore()}")
        if self.structural_failure_buildings:
            lines.append(
                f"buildings in AIDR H5-H6 (structural failure likely, NOT "
                f"covered by depth-damage curves): "
                f"{self.structural_failure_buildings:,}")
        if self.limitations:
            lines.append("limitations:")
            lines += [f"  - {t}" for t in self.limitations]
        return "\n".join(lines)


def standard_limitations() -> list[str]:
    """The caveats that must accompany any damage figure this module produces."""
    return [
        "Damage is an ORDER-OF-MAGNITUDE range, not an assessment. It is the "
        "product of four uncertain factors: modelled depth, asset count from "
        "OpenStreetMap, a continental depth-damage curve, and an assumed "
        "replacement value.",
        "Asset replacement values are assumptions, not published figures. They "
        "must be replaced with district-level rates before any monetary figure "
        "is presented externally.",
        "Depth-damage curves ignore VELOCITY. For a dam break this understates "
        "damage where flow is fast: structural failure of masonry is a "
        "velocity phenomenon. The AIDR H5-H6 building count is reported "
        "separately for that reason.",
        "Curves are the JRC global Asia set, not curves fitted to Indian "
        "construction types. Local construction — particularly non-engineered "
        "masonry and mud — is likely to be more vulnerable than the curve "
        "implies at shallow depth.",
        "No allowance is made for debris impact, contamination, business "
        "interruption, or loss of life. This is direct physical damage only.",
    ]

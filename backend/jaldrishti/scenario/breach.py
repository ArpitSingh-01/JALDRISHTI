"""
Dam-breach growth and the outflow hydrograph it produces.

WHAT THIS MODULE IS FOR
-----------------------
The 2D solver routes water over terrain. It does not know how the water got out
of the reservoir. This module answers that question and produces the single input
the solver actually needs: discharge as a function of time, Q(t).

That interface — a hydrograph — is deliberate. It is the same interface the SPH
near-field model will hand over, the same interface a gauged flood would provide,
and the same interface a published Delft3D or HEC-RAS study reports. So the
far-field routing never has to care which of those produced it.

THE THREE PHYSICAL PIECES
-------------------------
1. BREACH GROWTH. A real embankment does not vanish. It erodes: a notch forms,
   deepens towards the original streambed, and widens. We model the breach as a
   trapezoid whose bottom width grows and whose invert lowers over a formation
   time. Formation time is an ASSUMPTION — it is not measurable in advance for a
   dam that has not failed — which is why every result must be presented as a
   range over it rather than as a single number.

2. OUTFLOW THROUGH THE BREACH. Treated as a broad-crested weir. For a trapezoid
   with bottom width b, head H above the invert and side slope m (horizontal per
   vertical):

       Q = c_weir * b * H^(3/2)  +  c_side * m * H^(5/2)

   The first term is the rectangular part, the second the two triangular side
   wedges. Both exponents follow from integrating the weir velocity profile over
   depth, which is why they are 3/2 and 5/2 and not something fitted.

3. RESERVOIR DRAWDOWN. Water leaving lowers the level, which lowers the head,
   which reduces the outflow. That feedback is what gives a dam-break hydrograph
   its characteristic shape: a steep rise as the breach opens, a sharp peak, then
   a long recession. Level-pool routing:

       dh/dt = (Q_in - Q_out(h, t)) / A(h)

WHY THE HYDROGRAPH IS PRECOMPUTED, NOT COUPLED
----------------------------------------------
We solve the reservoir separately and hand the finished hydrograph to the solver,
rather than coupling the two every timestep. The justification is that the weir
is free-flowing: during the phase that matters, the tailwater immediately below
the breach sits far below the reservoir level, so the downstream solution does
not influence the outflow. `submergence_factor` below quantifies exactly when
that assumption breaks (tailwater above ~2/3 of the head), and
`simulate_breach` accepts a tailwater series so the assumption can be checked
after the fact rather than merely asserted.

The payoff is large: the hydrograph costs milliseconds, so formation time can be
swept across its plausible range to produce the sensitivity band the results
must carry, without re-running the 2D model for each one.

CALIBRATION HONESTY
-------------------
The weir coefficients and every empirical regression in this file are fitted to
historical failures, mostly of embankment dams far smaller than Tehri. They are
used here as a SANITY ENVELOPE for the physically-routed peak, not as the
answer. A routed peak far outside the envelope means a bug; agreement inside it
is corroboration, not proof.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

# Shared with the solver so the two can never disagree about g. A 0.01 m/s^2
# mismatch would be invisible in any single number and would quietly break the
# self-consistency between the breach discharge and the momentum injected.
from ..solver.swe2d import GRAVITY

# -----------------------------------------------------------------------------
# Weir coefficients
# -----------------------------------------------------------------------------
# Rectangular broad-crested weir:  Q = (2/3)*C_d*sqrt(2g)*L*H^(3/2).
# With C_d ~ 0.55-0.6 this gives 1.6-1.8; 1.7 is the conventional SI value and
# corresponds to the 3.1 (ft^0.5/s) used by NWS DAMBRK, since 3.1*sqrt(0.3048)
# = 1.71.
C_WEIR = 1.7
# Triangular side wedges:  Q = (8/15)*C_d*sqrt(2g)*m*H^(5/2), ~1.35 for the same
# C_d. DAMBRK's 2.45 imperial equals 2.45*sqrt(0.3048) = 1.353.
C_SIDE = 1.35

# Modular limit of a broad-crested weir. Below this ratio of tailwater head to
# upstream head the weir is free-flowing and the downstream water level does not
# affect discharge at all.
SUBMERGENCE_LIMIT = 0.67

GROWTH_MODES = ("instant", "linear", "erosion")


# =============================================================================
# geometry and growth
# =============================================================================

@dataclass(frozen=True)
class BreachGeometry:
    """
    The FINAL breach, once growth has finished.

    `invert_m` is the elevation the breach bottom erodes down to — not the dam
    toe. A breach rarely scours below the original streambed, so the streambed
    elevation at the dam axis is the physically defensible floor. Setting it to
    the toe elevation of a 260 m dam would release storage that is not there.

    `side_slope` is horizontal run per unit vertical rise, so 1.0 is a 45-degree
    face. Values of 0.5-1.5 cover the observed range for embankment failures;
    a concrete gravity dam fails in blocks and is better represented by a
    near-rectangular breach (side_slope -> 0).

    `crest_length_m` is optional but supplying it is strongly recommended: it
    turns "how wide is the breach" from a free parameter into a constrained one.
    A breach cannot be wider than the dam is long, and for a tall dam with
    sloping sides that constraint is severe. Tehri is 260.5 m high with a 575 m
    crest, so 1:1 sides leave only 575 - 2(260.5) = 54 m of bottom width. Left
    unchecked, a plausible-looking 200 m bottom width implies a 721 m opening in
    a 575 m dam and overstates the peak by roughly a factor of three.
    """
    bottom_width_m: float
    invert_m: float
    side_slope: float = 1.0
    formation_time_s: float = 3600.0
    growth: str = "linear"
    crest_length_m: float | None = None

    def __post_init__(self):
        if self.bottom_width_m <= 0.0:
            raise ValueError("bottom_width_m must be positive")
        if self.side_slope < 0.0:
            raise ValueError("side_slope must be >= 0")
        if self.formation_time_s < 0.0:
            raise ValueError("formation_time_s must be >= 0")
        if self.growth not in GROWTH_MODES:
            raise ValueError(f"growth must be one of {GROWTH_MODES}")
        if self.crest_length_m is not None and self.crest_length_m <= 0.0:
            raise ValueError("crest_length_m must be positive if given")

    def top_width_m(self, head: float) -> float:
        """Water-surface width of the breach at a given head above the invert."""
        return self.bottom_width_m + 2.0 * self.side_slope * max(head, 0.0)

    def fits_within_crest(self, crest_m: float) -> bool:
        """Does the fully-developed breach fit inside the dam?"""
        if self.crest_length_m is None:
            return True
        return (self.top_width_m(crest_m - self.invert_m)
                <= self.crest_length_m + 1e-9)

    def check_fits(self, crest_m: float) -> None:
        """
        Raise if the fully-developed breach would be wider than the dam.

        Deliberately an exception rather than a silent clamp. Clamping the top
        width would leave `weir_outflow` integrating a trapezoid that no longer
        matches the geometry, so the discharge would be computed for a section
        that was never opened. Refusing the geometry keeps the trapezoid formula
        exactly valid everywhere it is used.
        """
        if self.fits_within_crest(crest_m):
            return
        head = crest_m - self.invert_m
        top = self.top_width_m(head)
        fit = max_bottom_width(self.crest_length_m, head, self.side_slope)
        raise ValueError(
            f"breach is wider than the dam: bottom {self.bottom_width_m:.0f} m "
            f"with {self.side_slope:g}:1 sides over {head:.1f} m of head gives a "
            f"{top:.0f} m opening in a {self.crest_length_m:.0f} m crest. "
            + (f"Largest bottom width that fits is {fit:.0f} m."
               if fit > 0.0 else
               f"No trapezoid with {self.side_slope:g}:1 sides fits; the sides "
               f"alone need {2.0 * self.side_slope * head:.0f} m. Use a steeper "
               f"side_slope or a shallower invert."))

    @classmethod
    def fit_within_crest(cls, *, crest_m: float, invert_m: float,
                         crest_length_m: float, side_slope: float = 1.0,
                         width_fraction: float = 1.0,
                         formation_time_s: float = 3600.0,
                         growth: str = "linear") -> "BreachGeometry":
        """
        The widest breach that fits in this dam, optionally scaled down.

        `width_fraction` scales the resulting TOP width, so 1.0 is a full-crest
        failure (the worst case an embankment can physically produce) and 0.5 is
        a breach that takes out half the dam. Scaling the top width rather than
        the bottom keeps the side slope fixed, which is the parameter that
        actually reflects the fill material.
        """
        if not 0.0 < width_fraction <= 1.0:
            raise ValueError("width_fraction must be in (0, 1]")
        head = crest_m - invert_m
        if head <= 0.0:
            raise ValueError("crest_m must be above invert_m")
        top = crest_length_m * width_fraction
        bottom = max_bottom_width(top, head, side_slope)
        if bottom <= 0.0:
            raise ValueError(
                f"a {head:.1f} m deep breach with {side_slope:g}:1 sides needs "
                f"{2.0 * side_slope * head:.0f} m of crest but only {top:.0f} m "
                f"is available; use a steeper side_slope")
        return cls(bottom_width_m=bottom, invert_m=invert_m,
                   side_slope=side_slope, formation_time_s=formation_time_s,
                   growth=growth, crest_length_m=crest_length_m)


def max_bottom_width(crest_length_m: float, head_m: float,
                     side_slope: float) -> float:
    """
    Bottom width of the largest trapezoid of this depth that fits in this crest.

        b = L - 2 * m * h

    Returns 0.0 (not a negative width) when the side slopes alone already
    consume the whole crest, which is the caller's cue that the requested side
    slope is impossible for a dam this tall.
    """
    return max(0.0, crest_length_m - 2.0 * side_slope * max(head_m, 0.0))


def growth_fraction(t: float, formation_time_s: float, mode: str) -> float:
    """
    How far breach development has progressed at time t, in [0, 1].

    Three shapes, and the choice matters more than people expect because it sets
    how fast the peak arrives:

      instant  -- fully open at t = 0. Not physical for an embankment, but it is
                  the standard upper bound and it is what the Ritter analytical
                  solution assumes, which makes it the case we can validate
                  against theory.
      linear   -- constant rate. The NWS DAMBRK default, and the honest choice
                  when nothing is known about the erodibility of the fill.
      erosion  -- slow start, accelerating, then tailing off as the breach runs
                  out of material to remove. Closer to observed embankment
                  failures, where a small notch takes a while to establish and
                  then widens rapidly once flow concentrates in it. Implemented
                  as a smoothstep, which is not derived from sediment transport;
                  it is a shape, chosen because it has the right qualitative
                  behaviour and zero free parameters.
    """
    if mode == "instant" or formation_time_s <= 0.0:
        return 1.0
    x = t / formation_time_s
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    if mode == "linear":
        return x
    if mode == "erosion":
        return x * x * (3.0 - 2.0 * x)          # smoothstep
    raise ValueError(f"unknown growth mode {mode!r}")


def breach_state(t: float, geom: BreachGeometry, crest_m: float
                 ) -> tuple[float, float]:
    """
    Breach bottom width and invert elevation at time t.

    Width grows from zero and the invert descends from the crest, both driven by
    the same growth fraction. Tying them together is the standard simplification:
    in reality vertical erosion tends to lead horizontal widening, but the
    formation time itself is a far larger uncertainty than the phasing within it,
    so a second assumed parameter would add no information.
    """
    f = growth_fraction(t, geom.formation_time_s, geom.growth)
    width = geom.bottom_width_m * f
    invert = crest_m - (crest_m - geom.invert_m) * f
    return width, invert


# =============================================================================
# outflow
# =============================================================================

def submergence_factor(head: float, tailwater_head: float) -> float:
    """
    Reduction in weir discharge when the tailwater drowns the crest (Villemonte).

        Ks = [1 - (h_t/H)^(3/2)]^0.385

    Returns 1.0 while the ratio is below the modular limit — a free-flowing weir
    genuinely does not care what is happening downstream, because the control
    section is critical and information cannot travel back upstream through it.

    This is also the diagnostic for whether precomputing the hydrograph was
    legitimate: if this factor ever departs from 1.0 during a run, the reservoir
    and the far field were coupled after all and the result needs a caveat.
    """
    if head <= 0.0:
        return 0.0
    ratio = tailwater_head / head
    if ratio <= SUBMERGENCE_LIMIT:
        return 1.0
    if ratio >= 1.0:
        return 0.0
    return (1.0 - ratio ** 1.5) ** 0.385


def weir_outflow(level_m: float, invert_m: float, width_m: float,
                 side_slope: float, *, tailwater_m: float | None = None,
                 c_weir: float = C_WEIR, c_side: float = C_SIDE) -> float:
    """
    Discharge through a trapezoidal breach, m^3/s.

        Q = c_weir * b * H^(3/2) + c_side * m * H^(5/2)

    Returns 0 when the reservoir has fallen to the breach invert or the breach
    has not yet opened. Both guards matter: the first is reached at the end of
    every run, and H^(3/2) of a negative number is a NaN that would propagate
    into the hydrograph and then into the solver.
    """
    head = level_m - invert_m
    if head <= 0.0 or width_m <= 0.0:
        return 0.0

    q = c_weir * width_m * head ** 1.5
    if side_slope > 0.0:
        q += c_side * side_slope * head ** 2.5

    if tailwater_m is not None:
        q *= submergence_factor(head, max(tailwater_m - invert_m, 0.0))
    return q


# =============================================================================
# empirical checks
# =============================================================================

def froehlich_peak_outflow(volume_m3: float, head_m: float) -> float:
    """
    Froehlich (1995) peak-outflow regression:  Qp = 0.607 * Vw^0.295 * hw^1.24

    Vw is the reservoir volume at failure (m^3) and hw the depth of water above
    the final breach invert (m). Fitted to 22 documented embankment failures.

    NOTE THE EXTRAPOLATION. The dams in that dataset are mostly tens of metres
    high impounding millions of cubic metres. Tehri is 260 m impounding 3.5
    billion. Applying this regression there is an extrapolation of one to two
    orders of magnitude in both variables, so it bounds nothing rigorously — it
    is a smell test. Disagreement by a factor of two is unremarkable;
    disagreement by a factor of fifty means our routing has a bug.
    """
    if volume_m3 <= 0.0 or head_m <= 0.0:
        return 0.0
    return 0.607 * volume_m3 ** 0.295 * head_m ** 1.24


def usbr_peak_outflow(head_m: float) -> float:
    """
    USBR (1982):  Qp = 19.1 * hw^1.85, with hw in metres.

    Depends on head alone, which is its weakness and also why it is a useful
    independent check: it cannot be wrong for the same reason a volume-based
    regression is wrong.
    """
    if head_m <= 0.0:
        return 0.0
    return 19.1 * head_m ** 1.85


def mlm_peak_outflow(volume_m3: float, head_m: float) -> float:
    """
    MacDonald & Langridge-Monopolis (1984):  Qp = 1.154 * (Vw * hw)^0.412
    """
    if volume_m3 <= 0.0 or head_m <= 0.0:
        return 0.0
    return 1.154 * (volume_m3 * head_m) ** 0.412


def froehlich_breach_geometry(volume_m3: float, head_m: float,
                              mode: str = "overtopping"
                              ) -> tuple[float, float]:
    """
    Froehlich (1995) predictors for average breach width and formation time.

        Bavg = 0.1803 * Ko * Vw^0.32 * hb^0.19
        tf   = 0.00254 * Vw^0.53 * hb^-0.90          [hours]

    Ko is 1.4 for overtopping and 1.0 for piping. Returns (width_m, time_s).

    Used only to supply a DEFAULT when no breach geometry has been specified, so
    that a scenario is never silently run with an invented number. An explicitly
    chosen geometry always wins.
    """
    if volume_m3 <= 0.0 or head_m <= 0.0:
        raise ValueError("volume and head must be positive")
    ko = 1.4 if mode == "overtopping" else 1.0
    width = 0.1803 * ko * volume_m3 ** 0.32 * head_m ** 0.19
    hours = 0.00254 * volume_m3 ** 0.53 * head_m ** -0.90
    return width, hours * 3600.0


# Provenance for the regressions above. They are dimensional fits, so a
# transposed digit is not detectable by inspection — unlike the weir exponents,
# which follow from the physics and can be re-derived. Anything False here must
# not appear as a number in the report; it may only be used internally as a
# smell test, which is what the code above does.
EMPIRICAL_SOURCES = {
    "froehlich_peak_outflow": (
        "Froehlich, D.C. (1995), 'Peak outflow from breached embankment dam', "
        "J. Water Resources Planning and Management 121(1):90-97", False),
    "usbr_peak_outflow": (
        "US Bureau of Reclamation (1982), 'Guidelines for defining inundated "
        "areas downstream from Bureau of Reclamation dams', ACER Technical "
        "Memorandum No. 3", False),
    "mlm_peak_outflow": (
        "MacDonald, T.C. & Langridge-Monopolis, J. (1984), 'Breaching "
        "characteristics of dam failures', J. Hydraulic Engineering "
        "110(5):567-586", False),
    "froehlich_breach_geometry": (
        "Froehlich, D.C. (1995), 'Embankment dam breach parameters revisited', "
        "Water Resources Engineering, ASCE, pp.887-891", False),
}


# =============================================================================
# reservoir storage
# =============================================================================

@dataclass
class ReservoirStorage:
    """
    Surface area as a function of water level — the reservoir's level-area-
    capacity relation.

    WHY THIS CLASS EXISTS
    ---------------------
    Level-pool routing integrates dh/dt = (Q_in - Q_out)/A(h). The first version
    of this module held A constant at its full-supply value, and on Tehri that
    produced a run which released 13.2 x 10^9 m3 from a reservoir holding
    3.54 x 10^9 — 3.7 times the water that is actually there. A constant area of
    52 km^2 over 253 m of drawdown simply is not the same reservoir.

    That is not a tolerable "stated limitation". It is a factor of nearly four on
    the volume handed downstream, in the direction that exaggerates the disaster,
    which is precisely the direction this project has committed to avoiding.

    THE POWER-LAW MODEL, AND WHY IT IS NOT A FIT
    --------------------------------------------
    Published sources give two numbers for almost every large dam: gross storage
    V0 at full reservoir level, and water-spread area A0 at the same level. A
    one-parameter storage law is exactly determined by those two:

        V(h) = V0 * (h/H)**b            h measured up from the streambed
        A(h) = dV/dh = b*V0*h**(b-1) / H**b

    Setting A(H) = A0 gives

        b = A0 * H / V0

    So b is COMPUTED from two published figures, not calibrated. Nothing here is
    tuned, and the model has a property the constant area lacks: by construction
    the integral of A dh from 0 to H is exactly V0, so a full drawdown releases
    exactly the gross storage and cannot invent water.

    The exponent is also interpretable, which makes it defensible out loud:
    b = 1 is a vertical-sided tank, b = 2 a wedge-shaped valley, b = 3 a cone.
    Tehri gives b = 52e6 * 260.5 / 3.54e9 = 3.83 — a deep, narrow gorge whose
    area collapses quickly with depth. That is what Tehri is.

    WHAT IT STILL GETS WRONG
    ------------------------
    A single exponent cannot reproduce the kinks a real level-capacity curve has
    where the reservoir spills into a side valley. If a published curve is ever
    obtained, pass it as `levels`/`areas` and this class interpolates it instead.
    Until then the power law is the most that two numbers honestly support, and
    `mode` records which of the three was used so no chart can misrepresent it.
    """
    mode: str                       # "power", "constant" or "table"
    bed_m: float
    crest_m: float
    volume_m3: float | None = None
    area_m2: float | None = None
    exponent: float | None = None
    levels: np.ndarray | None = None
    areas: np.ndarray | None = None

    # ---- constructors ----------------------------------------------------
    @classmethod
    def power_law(cls, *, bed_m: float, full_level_m: float,
                  volume_m3: float, area_m2: float) -> "ReservoirStorage":
        """Build from gross storage and full-supply area. Preferred."""
        h = full_level_m - bed_m
        if h <= 0.0:
            raise ValueError("full supply level must be above the streambed")
        if volume_m3 <= 0.0 or area_m2 <= 0.0:
            raise ValueError("volume and area must be positive")
        b = area_m2 * h / volume_m3
        if b < 1.0:
            # b < 1 means A(h) -> infinity as h -> 0: the reservoir would be
            # WIDER at the bottom than at the top. No valley does that, so the
            # two published figures are inconsistent with each other and the
            # caller needs to know rather than be handed a smooth wrong curve.
            raise ValueError(
                f"gross storage {volume_m3:.3e} m3 and area {area_m2:.3e} m2 "
                f"over a {h:.1f} m head imply a storage exponent of {b:.3f} < 1, "
                "i.e. a reservoir wider at depth than at the surface. One of the "
                "two figures is wrong or they are quoted at different datums.")
        return cls(mode="power", bed_m=bed_m, crest_m=full_level_m,
                   volume_m3=volume_m3, area_m2=area_m2, exponent=b)

    @classmethod
    def constant(cls, *, bed_m: float, full_level_m: float,
                 area_m2: float) -> "ReservoirStorage":
        """
        Constant area. Retained for two honest uses: reproducing the older
        behaviour for comparison, and the case where only an area is published.
        Its bias is documented in `simulate_breach`.
        """
        if area_m2 <= 0.0:
            raise ValueError("area must be positive")
        h = full_level_m - bed_m
        return cls(mode="constant", bed_m=bed_m, crest_m=full_level_m,
                   area_m2=area_m2, volume_m3=area_m2 * h, exponent=1.0)

    @classmethod
    def table(cls, *, levels, areas, bed_m=None) -> "ReservoirStorage":
        """A published level-area curve, interpolated. The best case."""
        lv = np.asarray(levels, dtype=np.float64)
        ar = np.asarray(areas, dtype=np.float64)
        if lv.size != ar.size or lv.size < 2:
            raise ValueError("levels and areas must be equal-length, >= 2 points")
        order = np.argsort(lv)
        lv, ar = lv[order], ar[order]
        if (ar <= 0).any():
            raise ValueError("areas must be positive")
        if (np.diff(ar) < -1e-9).any():
            raise ValueError("area must increase with level")
        bed = float(lv[0]) if bed_m is None else float(bed_m)
        obj = cls(mode="table", bed_m=bed, crest_m=float(lv[-1]),
                  levels=lv, areas=ar)
        obj.volume_m3 = obj.storage_at(float(lv[-1]))
        obj.area_m2 = float(ar[-1])
        return obj

    # ---- the two things the router needs ---------------------------------
    def area_at(self, level_m: float) -> float:
        """Surface area at a given water-surface elevation, m^2."""
        h = level_m - self.bed_m
        if self.mode == "constant":
            return float(self.area_m2)
        if self.mode == "table":
            return float(np.interp(level_m, self.levels, self.areas))
        # power law
        full = self.crest_m - self.bed_m
        # A(0) is genuinely zero for b > 1 — a point at the bottom of the gorge.
        # Dividing by it in the router would be a division by zero, so the area
        # is floored at its value one metre above the bed. The floor covers the
        # whole sub-metre interval, not just h == 0: flooring only the single
        # point would make A(h) step DOWN as the level rose off the bed, and a
        # non-monotone area function is exactly the kind of latent inconsistency
        # that survives a smoke check and then breaks an implicit solver. By the
        # time the level is inside this interval the reservoir holds ~2 m^3 of a
        # 3.54e9 m^3 storage, so the guard biases nothing measurable.
        h = max(h, min(1.0, full))
        b = self.exponent
        return float(b * self.volume_m3 * h ** (b - 1.0) / full ** b)

    def storage_at(self, level_m: float) -> float:
        """Volume stored below a given level, m^3."""
        h = max(level_m - self.bed_m, 0.0)
        if self.mode == "constant":
            return float(self.area_m2 * h)
        if self.mode == "table":
            lv = np.clip(self.levels, None, level_m)
            keep = self.levels <= level_m
            if keep.sum() < 2:
                return float(0.5 * (self.areas[0] + np.interp(
                    level_m, self.levels, self.areas)) * h)
            v = float(np.trapezoid(self.areas[keep], self.levels[keep]))
            top = float(lv[keep].max())
            if level_m > top:
                a_top = float(np.interp(top, self.levels, self.areas))
                a_lvl = float(np.interp(level_m, self.levels, self.areas))
                v += 0.5 * (a_top + a_lvl) * (level_m - top)
            return v
        full = self.crest_m - self.bed_m
        return float(self.volume_m3 * (h / full) ** self.exponent)

    def summary(self) -> str:
        full = self.crest_m - self.bed_m
        lines = [f"storage model     : {self.mode}",
                 f"streambed / FRL   : {self.bed_m:.1f} / {self.crest_m:.1f} m "
                 f"({full:.1f} m head)"]
        if self.volume_m3:
            lines.append(f"gross storage     : {self.volume_m3 / 1e9:.3f} x 10^9 m3")
        if self.area_m2:
            lines.append(f"area at FRL       : {self.area_m2 / 1e6:.1f} km2")
        if self.mode == "power":
            lines.append(f"storage exponent  : b = {self.exponent:.3f}  "
                         f"({_shape_word(self.exponent)})")
            lines.append(f"area at half head : "
                         f"{self.area_at(self.bed_m + 0.5 * full) / 1e6:.1f} km2 "
                         f"(constant-area model would say "
                         f"{self.area_m2 / 1e6:.1f})")
        return "\n".join(lines)


def _shape_word(b: float) -> str:
    """Plain-English reading of the storage exponent, for the report."""
    if b < 1.3:
        return "near vertical-sided"
    if b < 2.3:
        return "wedge-shaped valley"
    if b < 3.3:
        return "conical / steep valley"
    return "deep narrow gorge"


# =============================================================================
def critical_velocity(head: float) -> float:
    """
    Flow velocity at the breach crest, m/s. Derived, not assumed.

    Flow over a broad-crested weir passes through critical depth, where the
    Froude number is exactly 1. That fixes the depth at h_c = (2/3)H and hence
    the velocity at U_c = sqrt(g*h_c) = sqrt(2*g*H/3) — no coefficient, no
    calibration, just the definition of critical flow.

    This is worth stating carefully because it is what makes the solver's
    momentum injection self-consistent: (2/3)^1.5 * sqrt(g) = 1.7049, which is
    what C_WEIR above is a rounding of, so discharge and velocity come from the
    same assumption to within 0.3%. Continuity confirms it:
    Q/(b*h_c) = 1.705*b*H^1.5 / ((2/3)*b*H) = 2.557*sqrt(H) = sqrt(2*g*H/3).
    The two agree identically.
    """
    if head <= 0.0:
        return 0.0
    return math.sqrt(2.0 * GRAVITY * head / 3.0)


def breach_velocity(discharge: float, head: float, width: float,
                    side_slope: float) -> float:
    """
    Breach outlet velocity from continuity, m/s.

    Q divided by the flow area at critical depth. For a rectangular breach this
    is exactly `critical_velocity(head)`; the trapezoidal side flow makes it
    marginally different, and using Q/A rather than the closed form means the
    velocity automatically falls when a submergence factor has cut the discharge.

    Under genuine submergence the real flow depth exceeds critical, so the area
    here is too small and this over-reports velocity — but submergence already
    invalidates the free-weir discharge, and `simulate_breach` flags it. The
    velocity is not the assumption that fails first.
    """
    if discharge <= 0.0 or head <= 0.0 or width <= 0.0:
        return 0.0
    h_c = 2.0 * head / 3.0
    area = width * h_c + side_slope * h_c * h_c
    if area <= 0.0:
        return 0.0
    return discharge / area


# =============================================================================
# reservoir routing
# =============================================================================

@dataclass
class BreachHydrograph:
    """
    The finished outflow hydrograph plus everything needed to defend it.

    Stored as plain arrays because that is what both the solver and the chart
    generator want, and because it serialises to JSON for the API without a
    custom encoder.
    """
    t: np.ndarray                  # s
    q: np.ndarray                  # m^3/s
    level: np.ndarray              # reservoir water surface, m
    width: np.ndarray              # breach bottom width, m
    invert: np.ndarray             # breach invert elevation, m
    submergence: np.ndarray        # Villemonte factor actually applied
    velocity: np.ndarray | None = None   # breach outlet velocity, m/s
    meta: dict = field(default_factory=dict)

    @property
    def peak_q(self) -> float:
        return float(self.q.max())

    @property
    def t_peak(self) -> float:
        return float(self.t[int(np.argmax(self.q))])

    @property
    def peak_velocity(self) -> float:
        return 0.0 if self.velocity is None else float(self.velocity.max())

    @property
    def released_volume_m3(self) -> float:
        """Trapezoidal integral of the hydrograph — the volume handed downstream."""
        return float(np.trapezoid(self.q, self.t))

    def q_at(self, t: float) -> float:
        """Linear interpolation, clamped. Zero once the hydrograph has ended."""
        if t <= self.t[0]:
            return float(self.q[0])
        if t >= self.t[-1]:
            return float(self.q[-1])
        return float(np.interp(t, self.t, self.q))

    def u_at(self, t: float) -> float:
        """
        Breach outlet velocity at time t, m/s — the companion to `q_at`.

        Together these two are exactly what `SWE2D.add_inflow` wants, which is
        the point: the solver gets a discharge AND a momentum, both traceable to
        weir hydraulics rather than to a chosen number.
        """
        if self.velocity is None:
            return 0.0
        if t <= self.t[0]:
            return float(self.velocity[0])
        if t >= self.t[-1]:
            return float(self.velocity[-1])
        return float(np.interp(t, self.t, self.velocity))

    def summary(self) -> str:
        m = self.meta
        lines = [
            f"peak outflow      : {self.peak_q:,.0f} m3/s at t = "
            f"{self.t_peak / 60.0:.1f} min",
            f"released volume   : {self.released_volume_m3 / 1e6:,.1f} x 10^6 m3",
            f"level             : {self.level[0]:.1f} -> {self.level[-1]:.1f} m",
            f"duration          : {self.t[-1] / 3600.0:.2f} h",
        ]
        if "top_width_m" in m:
            line = (f"breach            : {m['bottom_width_m']:.0f} m bottom, "
                    f"{m['side_slope']:g}:1 sides, "
                    f"{m['top_width_m']:.0f} m at full head")
            if m.get("crest_length_m"):
                pct = 100.0 * m["top_width_m"] / m["crest_length_m"]
                line += (f" = {pct:.0f}% of the {m['crest_length_m']:.0f} m crest")
            lines.append(line)
        if self.velocity is not None:
            lines.append(
                f"peak breach vel.  : {self.peak_velocity:.1f} m/s "
                f"(critical flow, derived)")
        if "storage_model" in m:
            mode = m["storage_model"]
            b = m.get("storage_exponent")
            tag = f"{mode}" + (f", b = {b:.3f}" if mode == "power" and b else "")
            lines.append(f"storage model     : {tag}")
        if "released_fraction_of_storage" in m:
            frac = m["released_fraction_of_storage"]
            note = ""
            if frac > 1.02:
                note = ("   *** MORE THAN THE RESERVOIR HOLDS — the storage "
                        "model is wrong ***")
            lines.append(
                f"released / storage: {frac:.2f}{note}")
        if "storage_drop_m3" in m:
            lines.append(
                f"mass balance      : released - storage drop = "
                f"{m['mass_balance_rel']:.2e} (relative)")
        if "empirical" in m:
            lines.append("empirical peak-outflow envelope (smell test only):")
            for k, v in m["empirical"].items():
                ratio = self.peak_q / v if v > 0 else float("nan")
                lines.append(f"    {k:<28} {v:>12,.0f} m3/s   routed/this = {ratio:.2f}")
        if m.get("max_submergence", 0.0) < 1.0:
            lines.append(
                f"NOTE: weir was submerged (min factor "
                f"{m['max_submergence']:.3f}); free-outflow assumption violated")
        return "\n".join(lines)


def simulate_breach(*, crest_m: float, initial_level_m: float,
                    geom: BreachGeometry,
                    storage: "ReservoirStorage | None" = None,
                    reservoir_area_m2: float | None = None,
                    bed_m: float | None = None,
                    inflow_m3s: float = 0.0,
                    tailwater_m: float | None = None,
                    dt: float = 1.0, t_max: float = 24 * 3600.0,
                    stop_fraction: float = 1e-3,
                    reservoir_volume_m3: float | None = None
                    ) -> BreachHydrograph:
    """
    Route the reservoir down through a growing breach.

    Integrates dh/dt = (Q_in - Q_out(h, t)) / A(h) with classical RK4. RK4 rather
    than forward Euler because Q_out goes as H^(3/2) to H^(5/2): during the
    steep rise the derivative changes substantially within one step, and Euler
    visibly overshoots the peak — which is the one number everything downstream
    depends on.

    Parameters
    ----------
    crest_m          : dam crest elevation; the breach starts here and cuts down
    initial_level_m  : reservoir surface at failure (FRL for a normal-operation
                       scenario, MWL for a flood-overtopping scenario)
    storage          : a ReservoirStorage giving A(h). Strongly preferred — build
                       it with `ReservoirStorage.power_law(...)` from published
                       gross storage and full-supply area.
    reservoir_area_m2: shorthand for a CONSTANT-area reservoir, used only when
                       `storage` is not given. See the bias note below; this is
                       a fallback for dams where only an area is published, not
                       the recommended path.
    bed_m            : original streambed at the dam axis. Routing stops here;
                       storage below it is not released by a breach.
    inflow_m3s       : steady inflow from the catchment during the failure
    tailwater_m      : constant tailwater elevation, or None for free outflow
    stop_fraction    : end the run once outflow falls below this fraction of the
                       peak. The recession is asymptotic, so without a cutoff
                       the integration runs to t_max computing nothing useful.

    THE CONSTANT-AREA BIAS, STATED PLAINLY
    --------------------------------------
    A real reservoir narrows with depth, so its surface area shrinks as it
    drains. Holding the area at its full-supply value means each metre of
    drawdown releases more water than it really would.

    On Tehri this is not a small correction. 52 km^2 held constant over 253 m of
    drawdown releases 13.2 x 10^9 m^3 from a reservoir whose gross storage is
    3.54 x 10^9 — 3.7 times the water that exists. The peak is barely affected,
    because at the peak the level is still near full supply where the constant IS
    right; but the volume handed downstream, and therefore the extent of the
    inundation, is wrong by nearly a factor of four in the alarmist direction.

    So `ReservoirStorage.power_law` is the default path and this argument is the
    fallback. When it is used, `meta["storage_model"]` says so, and
    `meta["released_fraction_of_storage"]` will exceed 1.0 to make it obvious.

    THE BREACH-WIDTH CONSTRAINT
    ---------------------------
    If `geom.crest_length_m` is set, a breach wider than the dam is rejected
    outright rather than clamped. See `BreachGeometry.check_fits`. Setting it is
    strongly recommended: it is the difference between a breach width that is a
    free parameter and one the dam's own proportions pin down.
    """
    geom.check_fits(crest_m)

    if storage is None:
        if reservoir_area_m2 is None:
            raise ValueError(
                "pass either storage=ReservoirStorage(...) or "
                "reservoir_area_m2=<float>")
        floor_guess = geom.invert_m if bed_m is None else max(geom.invert_m, bed_m)
        if reservoir_volume_m3:
            # Both figures available: build the honest curve rather than the
            # constant, even though the caller used the shorthand.
            storage = ReservoirStorage.power_law(
                bed_m=floor_guess, full_level_m=initial_level_m,
                volume_m3=reservoir_volume_m3, area_m2=reservoir_area_m2)
        else:
            storage = ReservoirStorage.constant(
                bed_m=floor_guess, full_level_m=initial_level_m,
                area_m2=reservoir_area_m2)

    if initial_level_m > crest_m + 1e-9:
        raise ValueError(
            f"initial level {initial_level_m} is above the crest {crest_m}; "
            "the dam is already overtopping, which this routine does not model")
    if geom.invert_m > initial_level_m:
        raise ValueError("breach invert is above the initial reservoir level")

    floor = geom.invert_m if bed_m is None else max(geom.invert_m, bed_m)

    def q_of(tt: float, hh: float) -> tuple[float, float]:
        """(discharge, submergence factor) at time tt and level hh."""
        w, inv = breach_state(tt, geom, crest_m)
        head = hh - inv
        if head <= 0.0 or w <= 0.0:
            return 0.0, 1.0
        ks = 1.0
        if tailwater_m is not None:
            ks = submergence_factor(head, max(tailwater_m - inv, 0.0))
        return weir_outflow(hh, inv, w, geom.side_slope,
                            tailwater_m=tailwater_m), ks

    def deriv(tt: float, hh: float) -> float:
        q, _ = q_of(tt, hh)
        # A(h), not a constant. This is the whole point of ReservoirStorage: a
        # narrowing reservoir drops FASTER per unit outflow as it empties, which
        # shortens the recession and caps the released volume at the storage that
        # is actually there.
        a = storage.area_at(hh)
        if a <= 0.0:
            return 0.0
        return (inflow_m3s - q) / a

    ts, qs, hs, ws, invs, kss, us = [], [], [], [], [], [], []
    t, level = 0.0, float(initial_level_m)
    peak = 0.0
    n_max = int(t_max / dt) + 1

    for _ in range(n_max):
        q, ks = q_of(t, level)
        w, inv = breach_state(t, geom, crest_m)
        ts.append(t); qs.append(q); hs.append(level)
        ws.append(w); invs.append(inv); kss.append(ks)
        us.append(breach_velocity(q, level - inv, w, geom.side_slope))
        peak = max(peak, q)

        # Stop on the recession, but only after the breach has fully formed —
        # otherwise a run with a slow-growing breach would terminate at t=0,
        # where the outflow is legitimately still zero.
        if (t > geom.formation_time_s and peak > 0.0
                and q < stop_fraction * peak):
            break
        if level <= floor + 1e-9:
            break

        # RK4 on the level. Clamped at the floor inside each stage so a large
        # stage never evaluates the weir below the invert, where the head would
        # be negative.
        k1 = deriv(t, level)
        k2 = deriv(t + 0.5 * dt, max(level + 0.5 * dt * k1, floor))
        k3 = deriv(t + 0.5 * dt, max(level + 0.5 * dt * k2, floor))
        k4 = deriv(t + dt, max(level + dt * k3, floor))
        level = level + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
        if level < floor:
            level = floor
        t += dt

    hyd = BreachHydrograph(
        t=np.asarray(ts), q=np.asarray(qs), level=np.asarray(hs),
        width=np.asarray(ws), invert=np.asarray(invs),
        submergence=np.asarray(kss), velocity=np.asarray(us))

    # ---- diagnostics --------------------------------------------------------
    # Storage lost from the CURVE, not level drop times a constant area. With a
    # power-law reservoir these differ by a large factor, and using the wrong one
    # would make the mass-balance check pass on an incorrect run.
    drop = storage.storage_at(hyd.level[0]) - storage.storage_at(hyd.level[-1])
    released = hyd.released_volume_m3
    inflow_total = inflow_m3s * hyd.t[-1]
    # Mass balance: what left through the breach must equal the storage lost
    # plus whatever flowed in. This checks the RK4 integration against the
    # trapezoidal integral of its own output, so it catches a routing error but
    # not a wrong weir coefficient. It is a numerical check, not a physical one.
    expected = drop + inflow_total
    rel = abs(released - expected) / expected if expected > 0 else 0.0

    head_final = hyd.level[0] - floor
    storage_total = reservoir_volume_m3 or storage.volume_m3
    hyd.meta = {
        "crest_m": crest_m,
        "initial_level_m": initial_level_m,
        "floor_m": floor,
        "storage_model": storage.mode,
        "storage_exponent": storage.exponent,
        "reservoir_area_m2": storage.area_m2,
        "reservoir_volume_m3": storage_total,
        "head_m": head_final,
        "inflow_m3s": inflow_m3s,
        "growth": geom.growth,
        "formation_time_s": geom.formation_time_s,
        "bottom_width_m": geom.bottom_width_m,
        "side_slope": geom.side_slope,
        "top_width_m": geom.top_width_m(head_final),
        "crest_length_m": geom.crest_length_m,
        "storage_drop_m3": drop,
        "inflow_volume_m3": inflow_total,
        "mass_balance_rel": rel,
        "max_submergence": float(hyd.submergence.min()),
        "peak_velocity_ms": hyd.peak_velocity,
        "truncated": bool(hyd.t[-1] >= t_max - dt),
    }
    if storage_total:
        hyd.meta["released_fraction_of_storage"] = released / storage_total
    vol_for_empirical = storage_total or drop
    hyd.meta["empirical"] = {
        "Froehlich 1995": froehlich_peak_outflow(vol_for_empirical, head_final),
        "USBR 1982": usbr_peak_outflow(head_final),
        "MacDonald & L-M 1984": mlm_peak_outflow(vol_for_empirical, head_final),
    }
    return hyd


def formation_time_band(*, times_s, **kwargs) -> dict[float, BreachHydrograph]:
    """
    Run the same breach at several formation times.

    This exists because formation time is unknowable in advance, and the project
    rule is that results depending on an assumption must be reported as a band
    over that assumption rather than as a single number. The hydrograph costs
    milliseconds, so there is no excuse for not producing the band.

    Returns {formation_time_s: hydrograph}, so the caller can plot the envelope
    and quote a peak range.

    Uses `dataclasses.replace` rather than rebuilding the geometry field by
    field. Rebuilding it by hand silently dropped `crest_length_m`, which
    disabled the "a breach cannot be wider than the dam" check for every member
    of the band — and the band is what gets quoted. `replace` carries every
    field by construction, including any added later.
    """
    geom = kwargs.pop("geom")
    out = {}
    for tf in times_s:
        g = replace(geom, formation_time_s=float(tf))
        out[float(tf)] = simulate_breach(geom=g, **kwargs)
    return out

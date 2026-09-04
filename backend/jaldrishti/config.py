"""
Study areas, dam specifications and scenario definitions for JALDRISHTI.

WHY THIS FILE CARRIES PROVENANCE METADATA
-----------------------------------------
A dam-break model is only as trustworthy as the reservoir volume you fed it. Get
the full reservoir level wrong by 5 m on Tehri and the released volume — and
therefore every downstream depth, arrival time and exposure count — is wrong,
with no symptom anywhere in the output. The number just looks like a number.

So every physical quantity that could end up on a slide or in a report is
registered in `SOURCES` with where it came from and whether it has been checked
against a primary source. `unverified()` lists what has not been, and the export
layer is expected to consult it and refuse to present unverified figures as fact.
This is deliberately a hard mechanism rather than a comment, because "I'll check
that later" does not survive a hackathon week.

The primary sources that count for Indian dams:
  * Central Water Commission (CWC), National Register of Large Dams (NRLD)
  * The dam owner's own published DPR / Emergency Action Plan
  * Central Electricity Authority for installed capacity
Wikipedia and news reports do NOT count, and neither does the model's memory.

COORDINATE FRAMES
-----------------
Each study area declares its own working CRS, chosen so the solver operates on a
metric grid with near-unity scale distortion over the domain:
  * Malpasset uses the EDF local planimetric frame that its survey data is
    published in. There is no EPSG code for it; it is metres, and self-consistent.
  * Indian domains use UTM. Uttarakhand spans UTM zone 44N (EPSG:32644).
The solver is CRS-agnostic — it needs square cells in metres — but the export
layer needs the CRS to write GeoTIFF/Shapefile/KML correctly, and KML in
particular must be reprojected to EPSG:4326.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "outputs"
REFERENCE_DIR = Path(__file__).resolve().parents[1] / "tests" / "reference"

WGS84 = "EPSG:4326"
UTM44N = "EPSG:32644"       # Uttarakhand: Bhagirathi, Alaknanda, Dhauliganga
UTM43N = "EPSG:32643"       # western India, kept for later study areas


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------

# Primary source documents held on disk under data/reference/, so a citation can
# be re-checked rather than re-searched. Search engines rot; a downloaded PDF
# does not. Fetched 2026-08-29.
#
# Reproduce with:
#   curl -sL -o data/reference/nrld_2019.pdf \
#        https://cwc.gov.in/sites/default/files/nrld06042019.pdf
# and read with:
#   python scripts/nrld_lookup.py TEHRI KOTESHWAR
#   python scripts/pdf_grep.py <file.pdf> <terms...>

NRLD_2019 = ("CWC National Register of Large Dams 2019, Uttarakhand table, p.279 "
             "(data/reference/nrld_2019.pdf)")
THDC_FAQ = ("THDC India Limited (dam owner), FAQ, https://thdc.co.in/en/faq, "
            "read 2026-08-29")
THDC_PROGRESS = ("THDC India Limited, Tehri Progress Report December 2024 "
                 "(data/reference/thdc_tehri_progress_dec2024.pdf)")
SHUGAR_2021 = ("Shugar, D.H. et al. (2021), 'A massive rock and ice avalanche "
               "caused the 2021 disaster at Chamoli, Indian Himalaya', Science "
               "373(6552):300-306, doi:10.1126/science.abh4455 "
               "(data/reference/shugar2021_chamoli.pdf, green OA copy via White "
               "Rose Research Online)")


@dataclass(frozen=True)
class Source:
    """
    Where a physical number came from, and whether it has been checked.

    `verified=True` is a claim that a human opened the cited source and read the
    number off it. It is not a claim that the number is plausible.
    """
    citation: str
    verified: bool = False
    note: str = ""

    def __str__(self) -> str:
        mark = "verified" if self.verified else "UNVERIFIED"
        return f"[{mark}] {self.citation}" + (f" ({self.note})" if self.note else "")


# ---------------------------------------------------------------------------
# dam / blockage / breach
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DamSpec:
    """
    The reservoir and structure. Only what the model actually consumes.

    `gross_storage_m3` and `frl_m` are the two numbers that dominate the answer:
    together they set how much water there is and how much head drives it out.

    Three fields exist for specific downstream consumers rather than for
    completeness:
      * `mwl_m` is the trigger level for an overtopping breach. Without it an
        overtopping scenario has no threshold to cross.
      * `reservoir_area_m2` is what turns a falling water level into a volume:
        the drawdown routing steps dV = -A(h) dh, and with no level-area curve
        available the area at FRL is the first-order stand-in. It makes the
        reservoir emptying rate a *computed* quantity instead of an assumed one.
      * `spillway_capacity_m3s` is never used by the solver. It is in the report:
        stating that a modelled breach peak is N times the design spillway
        discharge gives a district officer a reference they already understand,
        and gives us a sanity bound — a breach peak *below* spillway capacity
        would mean we had made an arithmetic error somewhere.

    VERTICAL DATUM. `frl_m`, `mddl_m` and `mwl_m` are elevations, and elevations
    are meaningless without a datum. Indian dam levels are quoted above mean sea
    level; Copernicus DEM heights are relative to the EGM2008 geoid, which
    approximates MSL to well within our error budget.

    That agreement is NOT confirmed by reading the DEM at the dam coordinate, and
    an earlier version of this docstring wrongly claimed it was ("the DEM reads
    830.3 m at the Tehri dam axis against a published FRL of 830.0 m"). It does
    not: `scripts/check_terrain.py` reads 819.4 m at 90 m and 816.6 m at 30 m
    there. The NRLD coordinate lands on the reservoir side of the structure, not
    on the crest, so it never could have matched FRL.

    What DOES corroborate the datum is the crest ridge one to two cells south of
    that coordinate, which reads 832.1 m at 90 m and 834.7 m at 30 m. A dam held
    at FRL 830.0 m must have a crest above 830.0 m by its freeboard, and that is
    what the DEM shows. Treat the crest, not the coordinate, as the check.

    Do not put "matches FRL to 0.3 m" on a slide. If a future study area
    disagrees at the CREST, suspect the datum before suspecting the DEM.
    """
    name: str
    river: str
    lat: float
    lon: float
    dam_type: str
    height_m: float                 # structural height above lowest foundation
    crest_length_m: float
    frl_m: float                    # full reservoir level, m above datum
    gross_storage_m3: float
    live_storage_m3: float | None = None
    mddl_m: float | None = None     # minimum draw-down level
    mwl_m: float | None = None      # maximum water level (flood); overtopping trigger
    reservoir_area_m2: float | None = None      # water spread at FRL
    spillway_capacity_m3s: float | None = None  # design flood discharge
    catchment_km2: float | None = None
    commissioned: str | None = None
    installed_mw: float | None = None


@dataclass(frozen=True)
class BreachSpec:
    """
    How the structure fails. This is the scenario's central assumption and it is
    NOT a measured quantity — it is a choice, and the report must say so.

    mode:
      'instantaneous'  the whole barrier vanishes at t=0. Physically extreme, but
                       it is what happened at Malpasset (arch dam, brittle,
                       failed in seconds) and it is the conservative upper bound
                       every guideline asks you to bracket with.
      'parametric'     the breach opens over `formation_time_s` to a trapezoidal
                       gap. Correct for embankment dams, which erode rather than
                       shatter — Tehri is earth-core rockfill, so this is its
                       realistic mode.
      'overtopping'    parametric, but triggered by inflow raising the level over
                       the crest rather than by assumption.

    `formation_time_s` is the parameter juries probe hardest, because a slow
    breach attenuates the peak dramatically. Always report the range, never a
    single value.
    """
    mode: str
    breach_width_m: float | None = None
    breach_depth_m: float | None = None
    side_slope: float = 1.0                  # horizontal:vertical
    formation_time_s: float | None = None
    formation_time_range_s: tuple[float, float] | None = None
    trigger_note: str = ""


@dataclass(frozen=True)
class Blockage:
    """
    A landslide / rock-ice avalanche dam. The PS explicitly asks for river
    blockage, and it differs from a dam break in three ways that matter:

      1. The barrier geometry is unsurveyed and must be assumed.
      2. It fails by overtopping and headward erosion, not structurally.
      3. The released flow is a DEBRIS FLOW, not water. It carries sediment at
         concentrations high enough to change the density and the rheology.

    On (3) the shallow water equations are being used outside their strict
    validity. We approximate with a bulking factor on the volume and an elevated
    Manning n, and the report must state this plainly rather than presenting a
    debris flow as if it were a clearwater flood.
    """
    name: str
    river: str
    lat: float
    lon: float
    source_volume_m3: float
    impounded_volume_m3: float | None = None
    barrier_height_m: float | None = None
    bulking_factor: float = 1.0          # 1.0 = clearwater; >1 accounts for solids
    # How much of source_volume_m3 was ice rather than rock. Ice can melt and
    # become part of the flowing water; rock cannot. This bounds how much water
    # the source itself could contribute, which is what keeps bulking_factor
    # from being a free parameter tuned until the answer looks right.
    ice_volume_m3: float | None = None
    debris_flow: bool = False
    event_date: str | None = None


# ---------------------------------------------------------------------------
# domain
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Domain:
    """
    The computational rectangle, in the study area's own CRS.

    Two resolutions per CLAUDE.md, and the split is a design decision rather than
    a compromise: `dx_interactive_m` has to return inside a user's attention span
    for the live demo, `dx_highres_m` is what we precompute for the figures. The
    honest framing is that resolution is a stated model limitation either way,
    which is why both numbers travel with the domain instead of being buried in a
    call site.
    """
    crs: str
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    dx_interactive_m: float
    dx_highres_m: float

    @property
    def width_m(self) -> float:
        return self.xmax - self.xmin

    @property
    def height_m(self) -> float:
        return self.ymax - self.ymin

    def shape(self, dx: float) -> tuple[int, int]:
        """(ny, nx) cell count at cell size `dx`."""
        return (int(round(self.height_m / dx)), int(round(self.width_m / dx)))

    def cost_estimate(self, dx: float) -> str:
        """
        Rough size report, so a bad resolution choice is caught before a run
        rather than after twenty minutes of waiting.
        """
        ny, nx = self.shape(dx)
        cells = ny * nx
        return f"{nx} x {ny} = {cells:,} cells at dx = {dx:g} m"


@dataclass(frozen=True)
class PointOfInterest:
    """
    A place we report arrival time and depth for. This is the product.

    `population` is a planning figure for the exposure table, not a census
    result; the real exposure numbers come from raster zonal statistics over
    WorldPop/GHSL in the analysis stage. It is kept here only so the demo has
    labelled settlements before the population raster is wired in, and every use
    must be traceable to SOURCES.
    """
    name: str
    lat: float
    lon: float
    kind: str = "settlement"        # settlement | dam | bridge | powerplant | gauge
    population: int | None = None
    note: str = ""


@dataclass(frozen=True)
class StudyArea:
    key: str
    title: str
    domain: Domain
    scenario_kind: str              # 'dam_break' | 'blockage'
    purpose: str
    dam: DamSpec | None = None
    blockage: Blockage | None = None
    breach: BreachSpec | None = None
    manning_default: float = 0.035
    initial_water_level_m: float | None = None
    downstream: list[PointOfInterest] = field(default_factory=list)
    reference_data: dict[str, Path] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# A. MALPASSET 1959 — validation
# ---------------------------------------------------------------------------
# The reference case for dam-break modelling, and the only one of our three where
# the answer is known from the field. 423 people died; the survey that followed is
# why the case exists as a benchmark at all.
#
# The domain rectangle below is derived from the observation points plus margin.
# It is NOT authoritative: the canonical extent comes with the EDF/TELEMAC mesh,
# which we still have to obtain. Flagged in `limitations`.

_MALPASSET_REF = REFERENCE_DIR / "malpasset"

MALPASSET = StudyArea(
    key="malpasset",
    title="Malpasset Dam, Reyran valley, France — 2 December 1959",
    scenario_kind="dam_break",
    purpose=(
        "Validation against surveyed field data. This is the rung of the ladder "
        "that turns 'our solver passes analytical tests' into 'our solver "
        "reproduces a real flood that really happened'."
    ),
    domain=Domain(
        # Local EDF planimetric frame, metres. No EPSG code exists for it.
        crs="LOCAL:malpasset_edf",
        xmin=3000.0, ymin=1500.0,
        xmax=13500.0, ymax=5500.0,
        # 20 m for validation: finer than our operational grids because the
        # reference data resolves the valley at that scale and a coarser grid
        # would blur the very gorge geometry the comparison tests. Published
        # Malpasset meshes sit in the 15-30 m range.
        dx_interactive_m=20.0,
        dx_highres_m=10.0,
    ),
    dam=DamSpec(
        name="Malpasset",
        river="Reyran",
        lat=43.5119, lon=6.7561,
        dam_type="double-curvature concrete arch",
        height_m=66.5,
        crest_length_m=223.0,
        frl_m=100.0,
        gross_storage_m3=55.0e6,
        commissioned="1954",
    ),
    breach=BreachSpec(
        mode="instantaneous",
        trigger_note=(
            "The left abutment failed in the underlying gneiss and the arch "
            "unzipped in seconds. Instantaneous total removal is the accepted "
            "idealisation for this case and is what every published benchmark "
            "uses, so it is also what makes our numbers comparable to theirs."
        ),
    ),
    # Uniform Manning n. In the Malpasset literature roughness is THE calibrated
    # parameter, so this is a fitted value and not a measurement — worth saying
    # out loud, because a jury that spots an unacknowledged calibration knob will
    # discount everything else.
    manning_default=0.025,
    initial_water_level_m=100.0,
    downstream=[
        PointOfInterest("Fréjus", 43.4330, 6.7370, kind="settlement",
                        note="the wave reached the Mediterranean here"),
    ],
    reference_data={
        "police_survey": _MALPASSET_REF / "police_survey_p1_p17.csv",
        "gauges": _MALPASSET_REF / "gauges_g6_g14.csv",
        "transformers": _MALPASSET_REF / "transformers_abc.csv",
        "readme": _MALPASSET_REF / "README.md",
    },
    limitations=[
        "Domain rectangle is inferred from the observation points plus margin; "
        "the authoritative extent ships with the EDF/TELEMAC mesh, still to be "
        "obtained.",
        "Reference values are water-surface ELEVATIONS on the same datum as the "
        "100 m reservoir level, not depths. Bed elevation must be added to "
        "modelled depth before comparing.",
        "Transformer arrival times carry an unknown absolute offset, so only the "
        "relative times B-A = 1140 s and C-A = 1320 s are usable.",
        "Gauge values G6-G14 come from a 1:400 physical scale model, not the "
        "field, and therefore carry scale effects of their own.",
        "Manning n = 0.025 is calibrated, not measured.",
    ],
)


# ---------------------------------------------------------------------------
# B. TEHRI DAM — the live demo on a real Indian dam
# ---------------------------------------------------------------------------
# EVERY number in this block is UNVERIFIED and must be read off CWC/NRLD before
# it appears on a slide. They are recorded now so the pipeline has something to
# run against, and they are wrong until checked.
#
# Note the cascade: Koteshwar dam sits a short distance downstream and would be
# overtopped by any significant Tehri release. A dam-break study that stops at
# the first structure downstream is incomplete, and saying so is a point in our
# favour rather than against.

TEHRI = StudyArea(
    key="tehri",
    title="Tehri Dam, Bhagirathi river, Uttarakhand",
    scenario_kind="dam_break",
    purpose=(
        "Headline demonstration on a real Indian dam. India's tallest, on a "
        "Himalayan river, upstream of dense settlement and of the Ganga "
        "confluence — and squarely within the Dam Safety Act 2021 requirement "
        "for a dam-break study and Emergency Action Plan."
    ),
    domain=Domain(
        crs=UTM44N,
        # DEM-derived, not guessed: `terrain.metric_extent_for` takes the dam plus
        # every downstream point we report on, adds an 8 km margin, and snaps to a
        # whole multiple of dx so the 90 m and 30 m grids are nested and directly
        # comparable. Deriving it from the reported points rather than drawing a
        # box by hand is what guarantees no POI falls outside the grid — and a POI
        # outside the grid produces "flood never arrived", which reads as a result
        # rather than as a bug.
        #
        # 58.4 x 63.2 km. At 90 m that is 649 x 702 = 455,598 cells; at 30 m it is
        # 1946 x 2106 = 4,098,276 cells. See `limitations`: most of those cells are
        # ridgeline that never wets, which is why the valley mask is a feasibility
        # requirement at 30 m and not an optimisation.
        xmin=218_280.0, ymin=3_308_130.0,
        xmax=276_660.0, ymax=3_371_310.0,
        dx_interactive_m=90.0,
        dx_highres_m=30.0,
    ),
    dam=DamSpec(
        name="Tehri",
        river="Bhagirathi",
        # 30 deg 22' 43" N, 78 deg 28' 48" E, read off the NRLD 2019 Uttarakhand
        # table (PIC UA34VH0012).
        #
        # DEM CROSS-CHECK (scripts/check_terrain.py, values as measured):
        # the bed AT this coordinate is 819.4 m at 90 m and 816.6 m at 30 m --
        # about 11-13 m BELOW the published FRL of 830.0 m. That is expected, not
        # a discrepancy: the coordinate sits on the reservoir side of the
        # structure, so it reads the upstream face, never the crest.
        #
        # The 5x5 window is what validates the coordinate, and it does so
        # strongly. North of the point the DEM is flat at exactly 814.0 m -- a
        # water surface, which is how Copernicus renders reservoirs, and a
        # plausible operating level for a dam cycling between MDDL 740 m and FRL
        # 830 m. One to two cells SOUTH the bed rises to a ridge at 832.1 m
        # (90 m) / 834.7 m (30 m): the crest, correctly above FRL by roughly its
        # freeboard. Beyond it the bed collapses to 792-810 m, the tailrace. No
        # wrong coordinate produces reservoir-then-crest-then-tailrace in the
        # right order.
        #
        # Two consequences for any run, both load-bearing:
        #   1. The DEM's reservoir is at 814.0 m, NOT at FRL. A scenario that
        #      wants water at FRL must say so; it cannot read it off the terrain.
        #   2. At 90 m the crest is only partly above FRL (cells at 829.8 and
        #      828.6 m). Initialising a live pool at 830.0 m therefore SPILLS at
        #      90 m while holding at 30 m -- a setup whose behaviour changes with
        #      resolution. See scenario/run.py, which initialises the pool at the
        #      DEM's own 814.0 m surface (a well-balanced lake at rest) and takes
        #      breach mass from the lumped reservoir model instead.
        lat=30.378611, lon=78.480000,
        dam_type="earth-core rockfill embankment",
        height_m=260.5,
        crest_length_m=575.0,
        frl_m=830.0,
        mddl_m=740.0,
        mwl_m=835.0,
        gross_storage_m3=3.54e9,
        live_storage_m3=2.615e9,
        reservoir_area_m2=52.0e6,
        spillway_capacity_m3s=13_040.0,
        catchment_km2=7511.0,
        commissioned="2006",
        installed_mw=1000.0,
    ),
    breach=BreachSpec(
        mode="parametric",
        # An embankment does not vanish; it erodes. Breach width is commonly
        # scaled from dam height, and the formation time is the dominant
        # uncertainty, so it is carried as a RANGE and the report must show the
        # sensitivity rather than one flattering number.
        breach_width_m=600.0,
        breach_depth_m=230.0,
        side_slope=1.0,
        formation_time_s=3600.0,
        formation_time_range_s=(1800.0, 10800.0),
        trigger_note=(
            "Hypothetical. Assumed piping/overtopping failure at full reservoir "
            "level. There is no suggestion that Tehri is unsafe — a dam-break "
            "study is a legal requirement under the Dam Safety Act 2021 and is "
            "performed precisely for dams that are being operated responsibly."
        ),
    ),
    manning_default=0.045,      # steep boulder-bed Himalayan channel, not a plain
    initial_water_level_m=830.0,
    downstream=[
        # Koteshwar: 30 deg 15' 37" N, 78 deg 29' 51" E from NRLD 2019
        # (PIC UA34HH0015). The previous value carried here, 78.4650 E, was wrong
        # by ~3.0 km to the west and put the point on a hillside: the DEM read a
        # bed of 963.8 m there, which is impossible for a structure whose FRL is
        # around 612 m and which sits DOWNSTREAM of a reservoir held at 830 m.
        # Caught by cross-checking every POI elevation against the DEM, which is
        # now a standing check in scripts/check_terrain.py — this class of error
        # has no other symptom. It would simply have reported that the flood
        # never arrived at Koteshwar, and that would have looked like a result.
        PointOfInterest("Koteshwar Dam", 30.260278, 78.497500, kind="dam",
                        note="cascade risk: 22 km downstream of Tehri; 97.5 m "
                             "gravity dam, FRL ~612.5 m, gross storage 88.9 Mm3. "
                             "Any significant Tehri release overtops it."),
        PointOfInterest("Devprayag", 30.1460, 78.5980, kind="settlement",
                        note="Bhagirathi + Alaknanda confluence; Ganga begins"),
        PointOfInterest("Rishikesh", 30.0869, 78.2676, kind="settlement"),
        PointOfInterest("Haridwar", 29.9457, 78.1642, kind="settlement"),
    ],
    limitations=[
        "Reservoir geometry is a two-number approximation. Drawdown routing uses "
        "the water-spread area at FRL as a constant; the real level-area-capacity "
        "curve is not public. Gross storage 3.54 BCM over a 52 km2 spread implies "
        "a mean depth of ~68 m, so treating the area as constant over a 90 m "
        "drawdown overestimates late-stage outflow. The early hydrograph peak, "
        "which is what sets arrival times downstream, is barely affected.",
        "Bathymetry is absent. The DEM records the reservoir as a flat water "
        "surface, not as bed, so the impounded volume can never be measured from "
        "terrain — it is imposed from the published storage figure. Reservoir "
        "cells are excluded from the solver domain rather than modelled.",
        "Breach formation time is an assumption, not a measurement. Results must "
        "be presented as a range over formation_time_range_s.",
        "Reservoir drawdown is modelled as a boundary hydrograph, not as a "
        "coupled reservoir routing problem.",
        "Koteshwar dam, 22 km downstream, is modelled as terrain. Its own "
        "failure under overtopping is not simulated, so depths below Koteshwar "
        "are conservative in one direction and optimistic in the other: we "
        "neither add its 88.9 Mm3 nor account for its temporary attenuation.",
        "Most cells in the domain rectangle are ridgeline that never wets. The "
        "30 m grid is 4.1 million cells and is only tractable behind a valley "
        "mask; the 15-30 minute runtime quoted elsewhere assumes that mask.",
    ],
)


# ---------------------------------------------------------------------------
# C. RISHI GANGA / CHAMOLI, 7 February 2021 — river blockage
# ---------------------------------------------------------------------------
# The PS names this event itself, which makes it the right third scenario. It is
# also the one where we are furthest outside the model's comfort zone, and saying
# so is the point: this was a debris flow, not a flood.

RISHI_GANGA = StudyArea(
    key="rishi_ganga",
    title="Rishi Ganga / Ronti Gad, Chamoli, Uttarakhand — 7 February 2021",
    scenario_kind="blockage",
    purpose=(
        "Satisfies the problem statement's river-blockage requirement, on the "
        "event the problem statement itself cites. Demonstrates the same "
        "machinery applied to a landslide/avalanche dam rather than a structure."
    ),
    domain=Domain(
        crs=UTM44N,
        # The box previously carried here (x 280-340 km) did NOT contain the
        # event or any downstream POI: the avalanche source sits at UTM
        # (377_980, 3_361_910) and Joshimath at (362_367, 3_381_163), all east
        # of the old xmax=340_000. That was the SAME class of copy-paste slip
        # the latitude comment below records — a box for some other place. This
        # box brackets the source and all three POIs (Raini, Tapovan, Joshimath)
        # with a ~4 km buffer, snapped to the 90 m interactive grid. Verified by
        # scripts/diag_rishi_domain.py; no DEM had been fetched against the old
        # box, so nothing downstream was contaminated.
        xmin=358_290.0, ymin=3_357_900.0,
        xmax=382_050.0, ymax=3_385_170.0,
        dx_interactive_m=90.0,
        dx_highres_m=30.0,
    ),
    blockage=Blockage(
        name="Ronti Peak rock-ice avalanche",
        river="Ronti Gad -> Rishiganga -> Dhauliganga",
        # North face of Ronti Peak, detachment at ~5,500 m asl on a 6,063 m peak
        # (Shugar et al. 2021). The value carried here previously was
        # 30.3775 N — byte-identical to the Tehri dam latitude 100 km away, so it
        # was a copy-paste artefact rather than a location. Corrected to the
        # Ronti Peak massif; still to be refined against the paper's figures,
        # which is why it stays UNVERIFIED in SOURCES.
        lat=30.3830, lon=79.7300,
        source_volume_m3=26.9e6,
        # Sediment-laden flow behaves as a denser, more resistant fluid. The
        # bulking factor inflates the water-equivalent volume to represent the
        # solid fraction; it is a crude surrogate for a two-phase model and is
        # the single largest source of uncertainty in this scenario.
        #
        # Note what the source volume is NOT: it is rock plus ice, of which only
        # ~5-6e6 m3 was glacier ice, and only that ice fraction became water. The
        # flow gained its water downstream from snow, ice melt by frictional
        # heating, and river water it entrained. So 26.9e6 m3 is a mass-flow
        # volume, not a water volume, and feeding it to a clearwater solver as
        # though it were a reservoir release is an approximation the report must
        # name explicitly.
        bulking_factor=1.6,
        # Midpoint of the paper's 5-6 x 10^6 m3 ice estimate.
        ice_volume_m3=5.5e6,
        debris_flow=True,
        event_date="2021-02-07",
    ),
    breach=BreachSpec(
        mode="overtopping",
        trigger_note=(
            "The 2021 event was a direct rock-ice avalanche into the channel, "
            "NOT the failure of a long-lived landslide lake. Shugar et al. (2021) "
            "record a ~700 m long lake forming BEHIND the deposits in the "
            "Rishiganga valley in the days AFTER the event, still present two "
            "months later and growing — it did not breach as part of the "
            "disaster. We therefore model the generic blockage-and-breach "
            "sequence the problem statement asks for and state the difference "
            "plainly; we do not claim to reproduce the 2021 hydrograph."
        ),
    ),
    # Elevated roughness stands in for debris-flow resistance. This is a
    # surrogate, not a measurement.
    manning_default=0.10,
    downstream=[
        PointOfInterest("Raini / Rishiganga HEP", 30.4408, 79.6790,
                        kind="powerplant",
                        note="13.2 MW; destroyed 2021. ~15 km downstream of the "
                             "avalanche source; observed front velocity ~25 m/s, "
                             "estimated mean discharge 8,200-14,200 m3/s"),
        PointOfInterest("Tapovan-Vishnugad (NTPC)", 30.4936, 79.6119,
                        kind="powerplant",
                        note="520 MW barrage; destroyed 2021. ~10 km below Raini; "
                             "front velocity fell to ~16 m/s, discharge "
                             "2,900-4,900 m3/s downstream of the project"),
        PointOfInterest("Joshimath", 30.5550, 79.5650, kind="settlement",
                        note="16 km below Raini; mean frontal velocity over that "
                             "reach ~10 m/s"),
    ],
    limitations=[
        "THIS WAS A DEBRIS FLOW, NOT A FLOOD. The shallow water equations assume "
        "a constant-density Newtonian fluid. The real flow carried boulders over "
        "20 m across, scoured valley walls up to 220 m above the floor, and "
        "superelevated ~130 m around bends. We approximate the sediment load "
        "with a bulking factor and an elevated Manning n; we do not solve the "
        "two-phase problem, and peak depths in the steep upper reach should be "
        "read as indicative only.",
        "The published simulation of this event (Shugar et al. 2021) used "
        "r.avaflow, a multi-phase mass-flow model that tracks rock, ice and "
        "water fractions separately. Our single-phase solver cannot represent "
        "the phase transitions that paper documents, and we do not claim it can.",
        "Source volume 26.9e6 m3 is rock AND ice, not water. Only ~5-6e6 m3 was "
        "glacier ice available to melt. The water that made the flow mobile was "
        "entrained downstream, so the release volume is a modelling construct.",
        "Barrier geometry was never surveyed and is assumed.",
        "Steep-slope validity: the shallow water equations assume small bed "
        "slopes, and the upper Ronti Gad exceeds that assumption. Reported "
        "mobility was H/L = 0.16 at Tapovan.",
        "Avalanche source coordinates are approximate, pending the coordinates "
        "given in the paper's figures and supplement.",
    ],
)


STUDY_AREAS: dict[str, StudyArea] = {
    a.key: a for a in (MALPASSET, TEHRI, RISHI_GANGA)
}


# ---------------------------------------------------------------------------
# provenance register
# ---------------------------------------------------------------------------
# Keyed "<study_area>.<field>". Everything here that is not verified=True is a
# number the model wrote down and nobody has checked.

SOURCES: dict[str, Source] = {
    # --- Malpasset: peer-reviewed benchmark literature -----------------------
    "malpasset.dam.height_m": Source(
        "Malpasset benchmark literature; commonly quoted as 66.5 m",
        verified=False,
        note="cross-check against Hervouet & Petitjean (1999), J. Hydraulic Res."),
    "malpasset.dam.crest_length_m": Source(
        "Malpasset benchmark literature; commonly quoted as 223 m",
        verified=False),
    "malpasset.dam.gross_storage_m3": Source(
        "Reservoir volume at failure, commonly quoted 48-55 x 10^6 m^3",
        verified=False,
        note="the spread matters: it is the released volume"),
    "malpasset.initial_water_level_m": Source(
        "100.0 m, the value used by the openTELEMAC benchmark case and by "
        "Biscarini et al. (2016) Water 8(11):545",
        verified=True,
        note="some studies use 100.12 m; we match the benchmark"),
    "malpasset.manning_default": Source(
        "Strickler K = 40 -> n = 0.025, openTELEMAC malpasset case",
        verified=False,
        note="CALIBRATED parameter, not measured; published values span n = "
             "0.025-0.033"),
    "malpasset.reference_data": Source(
        "Biscarini, Di Francesco, Ridolfi & Manciola (2016), Water 8(11):545, "
        "Tables 2-4, doi:10.3390/w8110545 (CC-BY); openTELEMAC malpasset case",
        verified=True,
        note="CSVs in backend/tests/reference/malpasset/ carry full provenance"),

    # --- Tehri: read off CWC NRLD 2019 and THDC's own publications -----------
    # Two independent sources agree exactly on storage: the regulator (NRLD) and
    # the owner (THDC). That agreement is the reason these are marked verified.
    "tehri.dam.lat_lon": Source(
        f"30 deg 22' 43\" N, 78 deg 28' 48\" E — {NRLD_2019}",
        verified=True,
        note="cross-checked against the DEM: bed 830.3 m at the dam axis vs FRL "
             "830.0 m, and the 5x5 window resolves reservoir / crest / tailrace"),
    "tehri.dam.height_m": Source(
        f"260.50 m above lowest foundation — {NRLD_2019}",
        verified=True,
        note=f"corroborated verbatim by {THDC_FAQ}: 'Tehri Dam is a 260.5 M high "
             f"Earth & Rock fill Dam'"),
    "tehri.dam.crest_length_m": Source(
        f"575 m dam length — {NRLD_2019}", verified=True,
        note="a THDC training document circulating on third-party sites quotes "
             "crest length 592.25 m and dam top EL 839.5 m; unresolved, and the "
             "solver does not consume this figure, so NRLD's value stands"),
    "tehri.dam.frl_m": Source(
        f"FRL EL 830 m — {THDC_FAQ}", verified=True,
        note=f"THIS NUMBER SETS THE DRIVING HEAD. Corroborated by "
             f"{THDC_PROGRESS}: 'permission to fill Tehri Reservoir up to 830m "
             f"(FRL) has been granted ... achieved its full reservoir potential "
             f"(EL830m) on 24.09.2021'"),
    "tehri.dam.mddl_m": Source(
        f"MDDL EL 740 m — {THDC_FAQ}", verified=True,
        note="'between Minimum Draw Down Level (MDDL-El 740 M) and Full "
             "Reservoir Level (FRL-EL 830 M)'"),
    "tehri.dam.mwl_m": Source(
        f"MWL 835 m — {THDC_FAQ}", verified=True,
        note="'between FRL (830 M) & MWL (835 M)'; the 5 m band above FRL is the "
             "flood cushion and the trigger level for an overtopping scenario"),
    "tehri.dam.gross_storage_m3": Source(
        f"3,540,000,000 m^3 — {NRLD_2019}", verified=True,
        note=f"THIS NUMBER SETS THE RELEASED VOLUME. Independently confirmed by "
             f"{THDC_FAQ}: 'gross storage capacity of 3540 Million Cubic Meter "
             f"(MCM)'. The 3.2 / 4.0 BCM figures seen in secondary sources are "
             f"not supported by either primary source and are discarded"),
    "tehri.dam.live_storage_m3": Source(
        f"2,615,000,000 m^3 effective storage — {NRLD_2019}", verified=True,
        note=f"confirmed by {THDC_FAQ}: 'live storage capacity of 2615 MCM'"),
    "tehri.dam.reservoir_area_m2": Source(
        f"52,000,000 m^2 reservoir area — {NRLD_2019}", verified=True,
        note="water spread at FRL; used as a constant area in drawdown routing "
             "because no level-area-capacity curve is public"),
    "tehri.dam.spillway_capacity_m3s": Source(
        f"13,040 m^3/s designed spillway capacity — {NRLD_2019}", verified=True,
        note="reporting reference only, never an input; a modelled breach peak "
             "below this figure would indicate an arithmetic error"),
    "tehri.dam.commissioned": Source(
        f"2006 year of completion — {NRLD_2019}", verified=True),
    "tehri.dam.catchment_km2": Source(
        "7,511 km^2, recalled not read", verified=False,
        note="NRLD 2019 has NO catchment column, so this is still open. Note "
             "Koteshwar 22 km downstream is quoted at 7,691 km^2 by secondary "
             "sources, which is consistent in sign (downstream catchment must be "
             "larger) and makes ~7,500 plausible — but plausible is not verified. "
             "Only used for context; the model consumes no inflow hydrograph"),
    "tehri.dam.installed_mw": Source(
        f"1,000 MW (4 x 250 MW) for Tehri HPP Stage-I — {THDC_FAQ}",
        verified=True,
        note="MUST NOT be added to the separate 1,000 MW Tehri Pumped Storage "
             "Plant or the 400 MW Koteshwar HEP. THDC describes the whole "
             "complex as 2,400 MW; the dam-break scenario concerns Stage-I only"),
    "tehri.manning_default": Source(
        "n = 0.045 assumed for a steep boulder-bed Himalayan channel",
        verified=False,
        note="engineering judgement; to be replaced by landcover-derived n"),
    "tehri.breach": Source(
        "Breach geometry and formation time are ASSUMPTIONS, not data",
        verified=False,
        note="bracket with formation_time_range_s and publish the sensitivity"),
    "tehri.domain": Source(
        "Extent derived by terrain.metric_extent_for from the dam plus the four "
        "reported downstream points, 8 km margin, snapped to dx",
        verified=True,
        note="reproduce with scripts/check_terrain.py; every POI confirmed inside "
             "the grid and at a plausible bed elevation"),

    # --- Koteshwar: cascade structure immediately downstream of Tehri ---------
    "tehri.downstream.koteshwar": Source(
        f"30 deg 15' 37\" N, 78 deg 29' 51\" E; 97.50 m high; gross storage "
        f"88,900,000 m^3; effective 35,000,000 m^3; completed 2011 — "
        f"{NRLD_2019} (PIC UA34HH0015)",
        verified=True,
        note="FRL ~612.5 m is from a secondary source and remains UNVERIFIED; "
             "the storage figures there do match NRLD exactly. Fixed a 3.0 km "
             "coordinate error on 2026-08-29 that had placed this point on a "
             "hillside at 963.8 m"),

    # --- Rishi Ganga --------------------------------------------------------
    # Every figure below was read off the paper on disk on 2026-08-29 with
    #   python scripts/pdf_grep.py shugar2021_chamoli.pdf <term>
    "rishi_ganga.blockage.source_volume_m3": Source(
        f"\"26.9 x 10^6 m3 (95% CI 26.5-27.3 x 10^6 m3)\" of rock and ice "
        f"detached from the north face of Ronti Peak — {SHUGAR_2021}",
        verified=True,
        note="Rock AND ice, of which ~5-6 x 10^6 m3 was glacier ice. This is a "
             "mass-flow volume, not a water volume, so it is not directly "
             "comparable to a reservoir release; see the scenario limitations"),
    "rishi_ganga.blockage.ice_fraction_m3": Source(
        f"\"~5 x 10^6 to 6 x 10^6 m3\" of the detached mass was glacier ice, "
        f"melted by frictional heating from about -8 degC to 0 degC — "
        f"{SHUGAR_2021}",
        verified=True,
        note="This is the physical basis for bulking rather than a free "
             "parameter: it bounds how much water the source itself could "
             "supply, the rest being entrained downstream"),
    "rishi_ganga.blockage.lat_lon": Source(
        "Ronti Peak north face, detachment at approximately 5,500 m asl on a "
        f"6,063 m peak — {SHUGAR_2021}",
        verified=False,
        note="The peak and detachment altitude are verified; the decimal "
             "coordinate here is read off the paper's map figures by eye and is "
             "approximate. The previous value, 30.3775 N, was a copy-paste of "
             "the Tehri latitude 100 km away and was corrected on 2026-08-29"),
    "rishi_ganga.blockage.bulking_factor": Source(
        "1.6 assumed to represent the solid fraction of the debris flow",
        verified=False,
        note="LARGEST single uncertainty in this scenario; a surrogate for a "
             "two-phase model, not a measurement. Shugar et al. modelled the "
             "event with r.avaflow, which tracks rock, ice and water phases "
             "separately; we cannot and do not claim equivalence"),
    "rishi_ganga.manning_default": Source(
        "n = 0.10 assumed as a debris-flow resistance surrogate", verified=False,
        note="Defensible only as an order-of-magnitude choice. The observed flow "
             "scoured valley walls to 220 m above the floor and superelevated "
             "~130 m at bends, neither of which a Manning term can reproduce"),
    "rishi_ganga.breach.mode": Source(
        f"\"a lake ~700 m long formed behind these deposits in the Rishiganga "
        f"valley... The lake was still present two months later and had grown "
        f"since the initial formation\" — {SHUGAR_2021}",
        verified=True,
        note="Settles the framing: the lake formed AFTER the event, from its own "
             "deposits, and did not breach. Our blockage-breach run answers the "
             "problem statement's requirement; it does not reproduce 2021"),

    # Validation targets. These are field-derived estimates, not measurements at
    # a gauge, so they bound a plausible answer rather than defining a correct
    # one. Useful as an order-of-magnitude check on any Rishi Ganga run.
    "rishi_ganga.observed.discharge_m3s": Source(
        f"\"8200 to 14,200 m3/s\" at the Rishiganga HEP and \"2900 to 4900 "
        f"m3/s\" downstream of Tapovan — {SHUGAR_2021}",
        verified=True,
        note="Estimated from superelevation and trimline geometry, not gauged"),
    "rishi_ganga.observed.velocity_ms": Source(
        f"front velocity ~25 m/s near Rishiganga (15 km from source), ~16 m/s "
        f"above Tapovan (+10 km), ~10 m/s over the 16 km Raini-Joshimath reach; "
        f"mobility H/L = 0.16 at Tapovan — {SHUGAR_2021}",
        verified=True),
    "rishi_ganga.downstream": Source(
        "Rishiganga 13.2 MW and Tapovan-Vishnugad 520 MW capacities recalled; "
        "both were destroyed on 2021-02-07 per Shugar et al. (2021)",
        verified=False,
        note="Destruction and relative positions are verified from the paper; "
             "the MW ratings and the POI decimal coordinates are not. Nothing "
             "in the model consumes the MW figure — it appears only in the "
             "exposure narrative, so it must not reach a slide unverified"),
}


def get(key: str) -> StudyArea:
    """Look up a study area, with a useful error rather than a KeyError."""
    try:
        return STUDY_AREAS[key]
    except KeyError:
        raise KeyError(
            f"unknown study area {key!r}; available: "
            f"{', '.join(sorted(STUDY_AREAS))}") from None


def unverified(prefix: str | None = None) -> list[tuple[str, Source]]:
    """
    Every quantity not yet checked against a primary source.

    The export and report layers are expected to call this and either omit the
    figure or mark it provisional. Presenting an unverified reservoir volume as
    fact to a district officer is the failure mode this exists to prevent.
    """
    items = [(k, s) for k, s in SOURCES.items() if not s.verified]
    if prefix is not None:
        items = [(k, s) for k, s in items if k.startswith(prefix)]
    return sorted(items)


def provenance_report(key: str | None = None) -> str:
    """Human-readable provenance dump, for the console and the report appendix."""
    lines: list[str] = []
    areas = [get(key)] if key else list(STUDY_AREAS.values())
    for area in areas:
        lines.append(f"=== {area.title}")
        lines.append(f"    purpose: {area.purpose}")
        lines.append(f"    domain:  {area.domain.crs}  "
                     f"{area.domain.width_m / 1000:.1f} x "
                     f"{area.domain.height_m / 1000:.1f} km")
        for dx in (area.domain.dx_interactive_m, area.domain.dx_highres_m):
            lines.append(f"             {area.domain.cost_estimate(dx)}")
        pending = unverified(area.key)
        if pending:
            lines.append(f"    UNVERIFIED ({len(pending)}):")
            lines.extend(f"      - {k}: {s.citation}"
                         + (f"  [{s.note}]" if s.note else "")
                         for k, s in pending)
        else:
            lines.append("    all registered quantities verified")
        if area.limitations:
            lines.append("    stated limitations:")
            lines.extend(f"      - {lim}" for lim in area.limitations)
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    print(provenance_report())
    print(f"{len(unverified())} quantities still unverified across all areas.")

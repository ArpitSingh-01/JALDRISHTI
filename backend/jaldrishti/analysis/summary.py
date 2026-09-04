"""
The scenario result object — everything a response plan needs, in one place.

WHY A SINGLE OBJECT RATHER THAN A PILE OF ARRAYS
------------------------------------------------
Four consumers need this data: the GeoTIFF/COG writer, the Shapefile/KML writer,
the PDF report, and the API. If each one reaches into the solver and the analysis
modules independently, four subtly different definitions of "flooded" appear, and
the exposure table stops agreeing with the map. `ScenarioSummary` is the single
definition. Everything downstream reads it and nothing downstream recomputes.

WHY LIMITATIONS AND PROVENANCE ARE FIELDS, NOT DOCUMENTATION
------------------------------------------------------------
The PS asks for "probable" and "confidence-based" output. `CLAUDE.md` requires
that unverified figures never reach a slide. Neither is achievable if the caveats
live in a docstring, because the PDF generator cannot read a docstring. So:

  * `limitations` accumulates every caveat from every stage, deduplicated.
  * `unverified_inputs` accumulates every `verified=False` citation that fed the
    run — from `config.py`, `breach.py`, and the analysis modules.
  * `is_presentable()` is the release gate. It returns False, with reasons, when
    the result contains figures that must not be presented as fact.

The PDF prints the limitations page from these fields. If they are empty, the page
is empty, and that is a visible failure rather than a silent one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import math

import numpy as np

from . import arrival as arrival_mod
from . import hazard as hazard_mod


def _json_safe(x):
    """
    Replace NaN and infinity with None, recursively.

    `json.dumps` happily emits bare `NaN` and `Infinity`, which are NOT valid
    JSON: `JSON.parse` in the browser throws on both. Arrival time is NaN
    wherever water never arrived, so `first_arrival_min` is NaN for any run in
    which nothing flooded — and that would take down the API response and the
    frontend rather than reporting "not reached". Every number leaving this module
    goes through here.
    """
    if isinstance(x, dict):
        return {k: _json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_safe(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return None if not math.isfinite(float(x)) else float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    return x


@dataclass
class ScenarioSummary:
    """
    One simulated scenario, fully analysed.

    Rasters are all on the same grid, so `transform` and `crs` apply to every one
    of them, and a consumer never has to ask which grid a given array is on.
    """
    # identity
    run_id: str
    study_area: str
    scenario: str                       # e.g. "instantaneous full breach"

    # grid
    transform: Any
    crs: str
    dx: float
    shape: tuple

    # physics rasters
    max_depth: np.ndarray
    max_speed: np.ndarray
    max_dv: np.ndarray

    # analysis products
    hazard: hazard_mod.HazardResult
    arrival: arrival_mod.ArrivalResult
    exposure: Any = None                # exposure.ExposureResult | None
    damage: Any = None                  # damage.DamageResult | None

    # run bookkeeping
    duration_s: float = 0.0
    wall_time_s: float = 0.0
    steps: int = 0
    volume_error: float = 0.0
    dem_valid_mask: np.ndarray | None = None
    reportable_mask: np.ndarray | None = None
    solver_settings: dict = field(default_factory=dict)
    terrain_provenance: dict = field(default_factory=dict)
    breach_provenance: dict = field(default_factory=dict)
    extra_limitations: list[str] = field(default_factory=list)
    extra_unverified: list[str] = field(default_factory=list)

    # ---- derived views ---------------------------------------------------
    @property
    def flood_mask(self) -> np.ndarray:
        """
        The single definition of 'flooded'. Everything downstream uses this.

        Includes the reservoir, because those cells do hold water. Use
        `new_flood_mask` for the inundation the breach caused.
        """
        return ~self.hazard.dry_mask

    @property
    def new_flood_mask(self) -> np.ndarray:
        """Cells the breach put water into — dry before the failure."""
        iw = self.hazard.initially_wet
        if iw is None:
            return self.flood_mask
        return self.flood_mask & ~np.asarray(iw, dtype=bool)

    @property
    def flooded_area_km2(self) -> float:
        """
        Newly inundated area, km^2 — what "area flooded" means in a report.

        Deliberately the NEW area rather than the total wetted area. Quoting the
        total would add the reservoir's own surface to every result, and at a
        large dam that is tens of square kilometres of water that was already
        there before anything failed.
        """
        return self.hazard.newly_flooded_area_km2

    @property
    def total_wetted_area_km2(self) -> float:
        """Everything holding water at peak, reservoir included."""
        return self.hazard.flooded_area_km2

    @property
    def report_mask(self) -> np.ndarray:
        """
        Flooded cells whose depth and velocity may be quoted as a result.

        Excludes two zones that are dominated by how the MODEL is set up rather
        than by the terrain, and that the limitations already disclaim:

          * the near-field breach source, where a finite hydrograph forced into
            a handful of cells produces depths and speeds that are a property of
            the source spreading, not of the flood; and
          * the open-boundary buffer, where the transmissive condition perturbs
            the solution.

        A peak taken over the whole flood mask is, at Tehri, a pile-up cell at
        the injection point standing higher than the dam crest — the single most
        eye-catching number in the run and the one number the limitations say
        must not be quoted. This mask is what keeps the headline honest. If no
        reportable mask was supplied, every flooded cell is quotable, so older
        callers are unaffected.
        """
        fm = self.flood_mask
        if self.reportable_mask is None:
            return fm
        return fm & np.asarray(self.reportable_mask, dtype=bool)

    @property
    def _excluded_flood_mask(self) -> np.ndarray | None:
        """Flooded cells that are NOT reportable — the near-field/edge zone."""
        if self.reportable_mask is None:
            return None
        return self.flood_mask & ~np.asarray(self.reportable_mask, dtype=bool)

    @property
    def peak_depth_m(self) -> float:
        m = self.max_depth[self.report_mask]
        return float(m.max()) if m.size else 0.0

    @property
    def peak_speed_ms(self) -> float:
        m = self.max_speed[self.report_mask]
        return float(m.max()) if m.size else 0.0

    @property
    def peak_depth_nearfield_m(self) -> float:
        """
        The raw peak depth in the excluded zone — reported, not hidden.

        Surfacing it is the honest move: a reader can see how large the source
        artefact is and why it is set aside, instead of wondering whether a
        suspiciously round headline number was quietly trimmed.
        """
        nf = self._excluded_flood_mask
        if nf is None:
            return 0.0
        m = self.max_depth[nf]
        return float(m.max()) if m.size else 0.0

    @property
    def peak_speed_nearfield_ms(self) -> float:
        """The raw peak speed in the excluded zone — reported, not hidden."""
        nf = self._excluded_flood_mask
        if nf is None:
            return 0.0
        m = self.max_speed[nf]
        return float(m.max()) if m.size else 0.0

    @property
    def interpolated_flooded_cells(self) -> int:
        """
        Flooded cells whose elevation was interpolated over a DEM void.

        Reported because a result over filled terrain is weaker evidence than a
        result over surveyed terrain, and the map cannot show the difference.
        """
        if self.dem_valid_mask is None:
            return 0
        return int((self.flood_mask & ~np.asarray(self.dem_valid_mask,
                                                  dtype=bool)).sum())

    # ---- honesty machinery ----------------------------------------------
    @property
    def _has_open_boundary(self) -> bool:
        """
        True if any solver boundary was 'open'.

        A NEGATIVE volume error on an open domain is legitimate outflow — the
        flood exiting the far end of the domain — not a conservation failure, so
        the release gate must not treat it as one. `run.py` already applies this
        one-sided logic; this keeps the summary consistent with it. When the bc
        is unrecorded the domain is assumed WALLED, the conservative reading: an
        unexplained loss is not excused just because the setup was not recorded.
        """
        bc = self.solver_settings.get("bc") if self.solver_settings else None
        return bool(bc) and "open" in bc

    @property
    def limitations(self) -> list[str]:
        """Every caveat from every stage, order-preserving and deduplicated."""
        out: list[str] = []
        for src in (self.hazard.limitations,
                    self.arrival.limitations,
                    getattr(self.exposure, "limitations", None) or [],
                    getattr(self.damage, "limitations", None) or [],
                    self.extra_limitations):
            for text in src:
                if text not in out:
                    out.append(text)

        ve = self.volume_error
        if ve and abs(ve) > 1.0e-6:
            if ve < 0.0 and self._has_open_boundary:
                out.append(
                    f"Over the run {-ve * 100.0:.1f}% of total throughput left "
                    f"through the open boundary (relative volume change "
                    f"{ve:+.2e}). For a routing run whose flood is meant to exit "
                    f"the domain this is expected outflow, not a conservation "
                    f"error.")
            else:
                out.append(
                    f"Mass conservation error over the run was {ve:+.2e} "
                    f"(relative). Anything above 1e-6 warrants investigation "
                    f"before the result is used.")

        interp = self.interpolated_flooded_cells
        if interp:
            pct = 100.0 * interp / max(1, int(self.flood_mask.sum()))
            out.append(
                f"{interp:,} flooded cells ({pct:.1f}%) sit on terrain "
                f"interpolated across a DEM void. Depths there are weaker "
                f"evidence than elsewhere.")
        return out

    @property
    def unverified_inputs(self) -> list[str]:
        """Every `verified=False` citation that fed this run."""
        out: list[str] = []
        for obj in (self.hazard, self.exposure, self.damage):
            fn = getattr(obj, "unverified_sources", None)
            if fn is None:
                continue
            for text in fn():
                if text not in out:
                    out.append(text)
        for text in self.extra_unverified:
            if text not in out:
                out.append(text)
        return out

    def is_presentable(self) -> tuple[bool, list[str]]:
        """
        The release gate.

        Returns `(ok, reasons)`. `ok` is False when the result contains something
        that must not be shown to a jury or an official as fact. This is checked
        by `export/report.py`, which stamps an UNVERIFIED watermark rather than
        refusing outright — a blocked export in a live demo is worse than a
        labelled one, but an unlabelled one is worst of all.

        NOTE: a run with damage figures ALWAYS returns False, permanently and by
        design. Monetary loss here is the product of four uncertain factors (see
        `damage.py`) and no amount of source verification makes a rupee figure a
        fact. Do not "fix" this by dropping that reason; drop the damage estimate
        if the label is unwanted.
        """
        reasons = []
        if self.unverified_inputs:
            reasons.append(
                f"{len(self.unverified_inputs)} input citation(s) are not "
                f"verified against a primary source")
        if self.damage is not None:
            reasons.append(
                "monetary damage figures are order-of-magnitude only")
        ve = self.volume_error
        if ve > 1.0e-6:
            reasons.append(
                f"mass conservation error {ve:+.2e} is a spurious volume GAIN "
                f"(exceeds 1e-6); water cannot appear from nowhere")
        elif ve < -1.0e-6 and not self._has_open_boundary:
            reasons.append(
                f"mass conservation error {ve:+.2e} on a fully walled domain "
                f"(exceeds 1e-6), where no water can leave")
        if self.exposure is not None:
            rep = getattr(self.exposure, "resample_report", {}) or {}
            if rep and not rep.get("conserved", True):
                reasons.append(
                    f"population resampling did not conserve totals "
                    f"(residual {rep.get('residual_fraction', 0):+.1%})")
        return (not reasons), reasons

    # ---- reporting -------------------------------------------------------
    def headline(self) -> str:
        """
        The one sentence the whole platform exists to produce.

        Kept as a method so there is exactly one place this sentence is
        constructed, and so the numbers in it can never drift from the numbers in
        the tables.
        """
        first = self.arrival.first_arrival_minutes()
        pop = (self.exposure.rounded_population()
               if self.exposure is not None else None)
        area = self.flooded_area_km2
        # Below 10 km^2 an integer would round 1.62 to "2", which reads as a
        # measurement to one significant figure of a number we know better than.
        area_txt = f"{area:,.0f}" if area >= 10.0 else f"{area:.1f}"
        parts = [
            f"{self.scenario} at {self.study_area}",
            f"floods {area_txt} km2",
        ]
        if np.isfinite(first):
            parts.append(f"first arrival {first:.0f} min after failure")
        if pop:
            parts.append(f"about {pop:,} people exposed")
        return "; ".join(parts) + "."

    def summary(self) -> str:
        ok, reasons = self.is_presentable()
        lines = [
            f"=== {self.run_id} — {self.study_area} ===",
            self.headline(),
            "",
            f"grid          : {self.shape[1]} x {self.shape[0]} at {self.dx:g} m",
            f"simulated     : {self.duration_s / 3600.0:.2f} h "
            f"in {self.steps:,} steps ({self.wall_time_s:.1f} s wall)",
            f"new flooding  : {self.flooded_area_km2:.2f} km^2 "
            f"(total wetted {self.total_wetted_area_km2:.2f} km^2)",
            f"peak depth    : {self.peak_depth_m:.2f} m",
            f"peak speed    : {self.peak_speed_ms:.2f} m/s",
            (f"near-field    : {self.peak_depth_nearfield_m:.2f} m / "
             f"{self.peak_speed_nearfield_ms:.2f} m/s  (source zone — NOT "
             f"reportable)")
            if self.reportable_mask is not None else "",
            f"mass error    : {self.volume_error:+.2e}",
            "",
            self.hazard.summary(),
            "",
            self.arrival.summary(),
        ]
        if self.exposure is not None:
            lines += ["", self.exposure.summary()]
        if self.damage is not None:
            lines += ["", self.damage.summary()]

        lines += ["", "--- honesty ledger ---"]
        lines.append(f"presentable as fact: {'YES' if ok else 'NO'}")
        for r in reasons:
            lines.append(f"  ! {r}")
        if self.unverified_inputs:
            lines.append("unverified inputs:")
            lines += [f"  - {t}" for t in self.unverified_inputs]
        lines.append("limitations:")
        lines += [f"  - {t}" for t in self.limitations]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """
        JSON-serialisable metadata — everything except the rasters.

        This is what `export/metadata.py` writes as the provenance sidecar and
        what the API returns. Rasters go out as GeoTIFF; this is the record of how
        they were made and what they can be trusted for.
        """
        ok, reasons = self.is_presentable()
        d = {
            "run_id": self.run_id,
            "study_area": self.study_area,
            "scenario": self.scenario,
            "headline": self.headline(),
            "grid": {
                "shape": list(self.shape),
                "dx_m": self.dx,
                "crs": str(self.crs),
                "transform": list(self.transform)[:6]
                if self.transform is not None else None,
            },
            "run": {
                "duration_s": self.duration_s,
                "wall_time_s": self.wall_time_s,
                "steps": self.steps,
                "volume_error": self.volume_error,
                "solver": dict(self.solver_settings),
            },
            "results": {
                "flooded_area_km2": self.flooded_area_km2,
                "total_wetted_area_km2": self.total_wetted_area_km2,
                "peak_depth_m": self.peak_depth_m,
                "peak_speed_ms": self.peak_speed_ms,
                "peak_depth_nearfield_m": self.peak_depth_nearfield_m,
                "peak_speed_nearfield_ms": self.peak_speed_nearfield_ms,
                "first_arrival_min": self.arrival.first_arrival_minutes(),
                "last_arrival_min": self.arrival.last_arrival_minutes(),
                "area_by_hazard_km2": self.hazard.area_by_defra_class_km2(),
                "area_by_aidr_class_km2": self.hazard.area_by_aidr_class_km2(),
                "area_by_arrival_band_km2": self.arrival.area_by_band_km2(),
                "interpolated_flooded_cells": self.interpolated_flooded_cells,
            },
            "provenance": {
                "terrain": dict(self.terrain_provenance),
                "breach": dict(self.breach_provenance),
            },
            "honesty": {
                "presentable_as_fact": ok,
                "blocking_reasons": reasons,
                "unverified_inputs": self.unverified_inputs,
                "limitations": self.limitations,
            },
        }
        if self.exposure is not None:
            d["results"]["exposure"] = {
                "total_population": self.exposure.total_population,
                "reported_population": self.exposure.rounded_population(),
                "by_hazard": self.exposure.population_by_hazard,
                "by_arrival_band": self.exposure.population_by_arrival_band,
                "cross_tab": self.exposure.population_cross_tab,
                "infrastructure": self.exposure.infrastructure,
                "resample_report": self.exposure.resample_report,
            }
        if self.damage is not None:
            total = self.damage.total
            d["results"]["damage"] = {
                "unit": total.unit,
                "low": total.low,
                "central": total.central,
                "high": total.high,
                "formatted": total.format_crore(),
                "by_category": {
                    k: {"low": v.low, "central": v.central, "high": v.high}
                    for k, v in self.damage.by_category.items()
                },
                "structural_failure_buildings":
                    self.damage.structural_failure_buildings,
            }
        return _json_safe(d)

"""
The PDF briefing — the artefact a district officer actually reads.

WHY A PDF AT ALL, WHEN WE HAVE GeoTIFFs
---------------------------------------
The GeoTIFF is for the GIS cell. The PDF is for the person who signs the
evacuation order. It has to be readable on a phone in a control room at 2 a.m.,
printable in black and white, and complete on its own — because it will be
forwarded without its attachments.

That constrains the design in specific ways:

  * The headline number goes in the largest type on page 1. Not the methodology,
    not the grid resolution — the sentence "water reaches X in N minutes, M
    people must move".
  * Tables before maps. A map needs a legend and a colour-calibrated screen; a
    table of "band / population / action" does not.
  * The limitations page is not an appendix. It is page 2, before the results are
    elaborated, because a reader who stops after two pages must have seen it.

WHY THE UNVERIFIED WATERMARK IS DIAGONAL AND UGLY
-------------------------------------------------
`ScenarioSummary.is_presentable()` returns False whenever the run contains a
figure that must not be quoted as fact — an unverified reservoir volume, a
monetary damage estimate, a mass-conservation error above tolerance. When it does,
this module stamps every page with a diagonal watermark.

It is deliberately impossible to miss and impossible to remove by cropping. The
failure mode being prevented is real and common: a screenshot of a demo output
gets pasted into a briefing note, loses its context, and becomes a number someone
plans around. A watermark survives the screenshot. A footnote does not.

The correct fix for an unwanted watermark is to verify the inputs or drop the
damage estimate — not to bypass the gate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# Indian-flag palette for document chrome only — saffron rules, navy headings,
# green for the "safe/verified" state. Deliberately NOT used for any data:
# hazard and depth carry their own perceptual ramps (see `analysis/hazard.py`),
# because a reader must never have to work out whether a colour means "India" or
# "danger".
SAFFRON = (1.0, 0.6, 0.2)
INDIA_GREEN = (0.07, 0.53, 0.03)
NAVY = (0.0, 0.0, 0.5)
WARN_RED = (0.7, 0.0, 0.0)

PAGE_MARGIN_MM = 15.0


def _mm(v):
    from reportlab.lib.units import mm
    return v * mm


class _Stamper:
    """
    Page decorator: header rule, footer, page number, and the watermark.

    Held as a class rather than a closure so the flag and the run id are explicit
    state — an `onPage` callback that silently captures the wrong `summary` from
    an enclosing scope is a bug that produces a correctly-formatted report about
    a different run.
    """

    def __init__(self, run_id, study_area, watermark_text=None):
        self.run_id = run_id
        self.study_area = study_area
        self.watermark_text = watermark_text

    def __call__(self, canvas, doc):
        canvas.saveState()
        w, h = canvas._pagesize

        # Saffron rule at the top, green at the bottom — flag chrome, no data.
        canvas.setStrokeColorRGB(*SAFFRON)
        canvas.setLineWidth(2)
        canvas.line(_mm(PAGE_MARGIN_MM), h - _mm(PAGE_MARGIN_MM),
                    w - _mm(PAGE_MARGIN_MM), h - _mm(PAGE_MARGIN_MM))
        canvas.setStrokeColorRGB(*INDIA_GREEN)
        canvas.setLineWidth(1)
        canvas.line(_mm(PAGE_MARGIN_MM), _mm(PAGE_MARGIN_MM + 8),
                    w - _mm(PAGE_MARGIN_MM), _mm(PAGE_MARGIN_MM + 8))

        canvas.setFont("Helvetica", 7)
        canvas.setFillColorRGB(0.35, 0.35, 0.35)
        canvas.drawString(_mm(PAGE_MARGIN_MM), _mm(PAGE_MARGIN_MM + 2),
                          f"JALDRISHTI · {self.study_area} · {self.run_id}")
        canvas.drawRightString(
            w - _mm(PAGE_MARGIN_MM), _mm(PAGE_MARGIN_MM + 2),
            f"Simulation output — not a survey · page {canvas.getPageNumber()}")

        if self.watermark_text:
            canvas.saveState()
            canvas.translate(w / 2.0, h / 2.0)
            canvas.rotate(38)
            canvas.setFont("Helvetica-Bold", 52)
            # Low alpha so the text under it stays readable: an unreadable page
            # gets retyped by hand, which strips the warning entirely.
            canvas.setFillColorRGB(*WARN_RED, alpha=0.16)
            canvas.drawCentredString(0, 0, self.watermark_text)
            canvas.setFont("Helvetica-Bold", 14)
            canvas.drawCentredString(0, -_mm(14), "see limitations, page 2")
            canvas.restoreState()

        canvas.restoreState()


def _styles():
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.colors import Color

    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle(
        "JTitle", parent=ss["Title"], fontSize=20, leading=24,
        textColor=Color(*NAVY), spaceAfter=4))
    ss.add(ParagraphStyle(
        "JSubtitle", parent=ss["Normal"], fontSize=10, leading=13,
        textColor=Color(0.3, 0.3, 0.3), alignment=TA_CENTER, spaceAfter=10))
    ss.add(ParagraphStyle(
        "JHeadline", parent=ss["Normal"], fontSize=15, leading=20,
        textColor=Color(*NAVY), alignment=TA_LEFT, spaceBefore=6,
        spaceAfter=8, borderPadding=6, backColor=Color(1.0, 0.95, 0.86)))
    ss.add(ParagraphStyle(
        "JSection", parent=ss["Heading2"], fontSize=12, leading=15,
        textColor=Color(*NAVY), spaceBefore=12, spaceAfter=4))
    ss.add(ParagraphStyle(
        "JBody", parent=ss["Normal"], fontSize=9, leading=12, spaceAfter=4))
    ss.add(ParagraphStyle(
        "JSmall", parent=ss["Normal"], fontSize=7.5, leading=9.5,
        textColor=Color(0.3, 0.3, 0.3)))
    ss.add(ParagraphStyle(
        "JWarn", parent=ss["Normal"], fontSize=9, leading=12,
        textColor=Color(*WARN_RED), spaceAfter=3))
    return ss


def _table(data, col_widths, *, header_bg=NAVY, zebra=True, font_size=8):
    from reportlab.lib import colors
    from reportlab.lib.colors import Color
    from reportlab.platypus import Table, TableStyle

    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), Color(*header_bg)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("LEADING", (0, 0), (-1, -1), font_size + 2.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.25, Color(0.7, 0.7, 0.7)),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    if zebra:
        for r in range(1, len(data)):
            if r % 2 == 0:
                style.append(("BACKGROUND", (0, r), (-1, r),
                              Color(0.96, 0.96, 0.96)))
    t.setStyle(TableStyle(style))
    return t


# --------------------------------------------------------------------------
# figures
# --------------------------------------------------------------------------
def render_arrival_map(summary, path, *, dpi=160, hillshade=None):
    """
    The arrival-band map, rendered with matplotlib for embedding.

    Bands are drawn as discrete filled classes, not a continuous ramp, for the
    same reason the raster is banded: a smooth gradient invites reading "43
    minutes" off a colour, which the model cannot support.

    The pre-existing water body is drawn in a distinct flat grey-blue and
    labelled as such in the legend. This is the single most important cartographic
    decision in the whole project — without it the reservoir is the darkest,
    most urgent-looking thing on the map, and the reader concludes the lake is
    where the danger is.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.patches import Patch

    from ..analysis.arrival import (BAND_COLOURS,
                                    PRE_EXISTING_WATER_COLOUR, band_labels)

    band = np.asarray(summary.arrival.band)
    labels = band_labels(summary.arrival.bands_min)
    n = len(labels)

    # Value layout for the colormap: 0..n-1 are the bands; the two negative
    # sentinels are mapped to their own explicit colours rather than left to
    # `under`/`over`, which would put "never flooded" and "already water" in the
    # same bucket.
    disp = np.full(band.shape, np.nan)
    for i in range(n):
        disp[band == i] = i
    disp[band == -2] = n            # pre-existing water
    # band == -1 (never flooded) stays NaN => transparent, showing terrain.

    cmap = ListedColormap(list(BAND_COLOURS[:n])
                          + [PRE_EXISTING_WATER_COLOUR])
    cmap = cmap.with_extremes(bad=(0.0, 0.0, 0.0, 0.0))
    norm = BoundaryNorm(np.arange(-0.5, n + 1.5, 1.0), cmap.N)

    fig, ax = plt.subplots(figsize=(7.0, 5.6), dpi=dpi)

    # Flat neutral backdrop for land the water never reached. Deliberately NOT
    # derived from the DEM-void mask: the last isochrone colour is near-white,
    # and a white void rectangle sitting next to a near-white ">120 min" swatch
    # is a legend collision that reads as "this area floods late" when it
    # actually means "we do not have terrain here".
    ax.imshow(np.ones(band.shape), cmap="gray", vmin=0.0, vmax=1.35,
              interpolation="nearest")
    if hillshade is not None:
        ax.imshow(np.asarray(hillshade), cmap="gray", vmin=0, vmax=1,
                  interpolation="bilinear", alpha=0.85)

    ax.imshow(disp, cmap=cmap, norm=norm, interpolation="nearest")

    void_drawn = False
    if summary.dem_valid_mask is not None:
        void = ~np.asarray(summary.dem_valid_mask, dtype=bool)
        if void.any():
            # Hatched, not filled: a fill would compete with the data classes
            # for the reader's attention, and the message is "trust this area
            # less", not "this area is a category".
            ax.contourf(void.astype(float), levels=[0.5, 1.5],
                        colors="none", hatches=["////"])
            ax.contour(void.astype(float), levels=[0.5], colors="#b30000",
                       linewidths=0.8)
            void_drawn = True

    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(f"Flood arrival time — {summary.study_area}\n{summary.scenario}",
                 fontsize=10)

    handles = [Patch(facecolor=BAND_COLOURS[i], edgecolor="#444",
                     label=labels[i]) for i in range(n)]
    handles.append(Patch(facecolor=PRE_EXISTING_WATER_COLOUR,
                         edgecolor="#444",
                         label="water before failure"))
    handles.append(Patch(facecolor="#d9d9d9", edgecolor="#444",
                         label="not reached"))
    if void_drawn:
        handles.append(Patch(facecolor="white", edgecolor="#b30000",
                             hatch="////", label="DEM void — interpolated"))
    ax.legend(handles=handles, loc="lower left", fontsize=6.5,
              framealpha=0.95, title="minutes from failure",
              title_fontsize=7)

    # Scale bar, in cells converted to kilometres. A map without one cannot be
    # used to judge a distance, and every reader will try.
    km = 5.0 if summary.dx * summary.shape[1] > 30000 else 1.0
    cells = km * 1000.0 / summary.dx
    x0 = summary.shape[1] * 0.72
    y0 = summary.shape[0] * 0.94
    ax.plot([x0, x0 + cells], [y0, y0], color="black", lw=2.5,
            solid_capstyle="butt")
    ax.text(x0 + cells / 2.0, y0 - summary.shape[0] * 0.02, f"{km:g} km",
            ha="center", va="bottom", fontsize=7)

    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def render_hazard_map(summary, path, *, dpi=160):
    """Defra hazard classes, same cartographic rules as the arrival map."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.patches import Patch

    from ..analysis.hazard import (DEFRA_CLASS_COLOURS, DEFRA_CLASS_MEANING,
                                   DEFRA_CLASS_NAMES)

    cls = np.asarray(summary.hazard.defra_class).astype(float)
    iw = summary.hazard.initially_wet
    disp = np.where(cls >= 0, cls, np.nan)
    n = len(DEFRA_CLASS_NAMES)
    if iw is not None:
        disp = np.where(np.asarray(iw, dtype=bool), float(n), disp)

    from ..analysis.arrival import PRE_EXISTING_WATER_COLOUR
    cmap = ListedColormap(list(DEFRA_CLASS_COLOURS)
                          + [PRE_EXISTING_WATER_COLOUR])
    cmap = cmap.with_extremes(bad=(0.0, 0.0, 0.0, 0.0))
    norm = BoundaryNorm(np.arange(-0.5, n + 1.5, 1.0), cmap.N)

    fig, ax = plt.subplots(figsize=(7.0, 5.6), dpi=dpi)
    ax.imshow(disp, cmap=cmap, norm=norm, interpolation="nearest")
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title(f"Flood hazard rating (Defra/EA) — {summary.study_area}",
                 fontsize=10)
    handles = [Patch(facecolor=DEFRA_CLASS_COLOURS[i], edgecolor="#444",
                     label=f"{DEFRA_CLASS_NAMES[i]} — "
                           f"{DEFRA_CLASS_MEANING[i][:44]}")
               for i in range(n)]
    handles.append(Patch(facecolor=PRE_EXISTING_WATER_COLOUR,
                         edgecolor="#444",
                         label="water before failure"))
    ax.legend(handles=handles, loc="lower left", fontsize=6,
              framealpha=0.9)
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


# --------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------
def _p(text, style):
    from reportlab.platypus import Paragraph
    return Paragraph(str(text).replace("&", "&amp;").replace("<", "&lt;"), style)


def _fmt(v, nd=2, dash="—"):
    if v is None:
        return dash
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return dash if not np.isfinite(f) else f"{f:,.{nd}f}"


def write_report(summary, path, *, figures_dir=None, include_maps=True,
                 hillshade=None) -> Path:
    """
    Build the PDF. Returns the path written.

    Consults `summary.is_presentable()` and stamps the watermark when it returns
    False. It does not refuse to write: a blocked export during a live demo is
    worse than a clearly-labelled one, and an unlabelled one is worst of all.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import (Image, KeepTogether, PageBreak,
                                    SimpleDocTemplate, Spacer)

    from .metadata import MODEL_DISCLAIMER, SOLVER_ATTRIBUTION

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    figures_dir = Path(figures_dir) if figures_dir else path.parent / "figures"

    ok, reasons = summary.is_presentable()
    ss = _styles()
    story = []
    avail = A4[0] - 2 * _mm(PAGE_MARGIN_MM)

    # ---- page 1: the answer -------------------------------------------
    story.append(_p("Dam-Break Inundation Assessment", ss["JTitle"]))
    story.append(_p(
        f"{summary.study_area} &nbsp;·&nbsp; {summary.scenario}<br/>"
        f"JALDRISHTI · Smart India Hackathon 2026 · Problem Statement 26161 "
        f"(NTRO)<br/>"
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        f" · run {summary.run_id}", ss["JSubtitle"]))

    story.append(_p(summary.headline(), ss["JHeadline"]))

    if not ok:
        story.append(_p(
            "<b>THIS RESULT IS NOT PRESENTABLE AS FACT.</b> "
            + "; ".join(reasons) + ".", ss["JWarn"]))
    else:
        story.append(_p(
            "All input citations for this run are verified against primary "
            "sources. The limitations on page 2 still apply.", ss["JBody"]))

    # The operational table — the reason the platform exists. First table, above
    # everything about physics or grids.
    story.append(_p("Evacuation priority by arrival band", ss["JSection"]))
    story.append(_table(_arrival_rows(summary),
                        [avail * f for f in (0.16, 0.15, 0.16, 0.53)]))
    story.append(_p(
        "Arrival time is measured from the moment of failure. It is NOT warning "
        "time — subtract your own detection, decision and dissemination "
        "timings from the Emergency Action Plan before planning on these "
        "numbers.", ss["JSmall"]))

    story.append(_p("Simulation summary", ss["JSection"]))
    story.append(_table(_run_rows(summary), [avail * 0.42, avail * 0.58],
                        zebra=False))

    # ---- page 2: limitations, deliberately early ----------------------
    story.append(PageBreak())
    story.append(_p("What this result can and cannot support", ss["JTitle"]))
    story.append(_p(
        "This page is page 2 rather than an appendix on purpose. A reader who "
        "stops early must still have seen it.", ss["JSmall"]))

    if reasons:
        story.append(_p("Blocking qualifications", ss["JSection"]))
        for r in reasons:
            story.append(_p(f"■ {r}", ss["JWarn"]))

    if summary.unverified_inputs:
        story.append(_p("Inputs not yet verified against a primary source",
                        ss["JSection"]))
        for t in summary.unverified_inputs:
            story.append(_p(f"• {t}", ss["JWarn"]))

    story.append(_p("Limitations", ss["JSection"]))
    for t in summary.limitations:
        story.append(_p(f"• {t}", ss["JBody"]))

    story.append(_p("Method and attribution", ss["JSection"]))
    story.append(_p(SOLVER_ATTRIBUTION, ss["JBody"]))
    story.append(_p(MODEL_DISCLAIMER, ss["JBody"]))

    story.append(_p("Statutory and policy context", ss["JSection"]))
    for t in ("Dam Safety Act, 2021 — legally mandates dam-break studies and "
              "Emergency Action Plans for specified dams in India.",
              "NDMA Guidelines on Management of Glacial Lake Outburst Floods.",
              "CWC guidelines for dam-break analysis and inundation mapping.",
              "Sendai Framework for Disaster Risk Reduction, Priority 4."):
        story.append(_p(f"• {t}", ss["JBody"]))

    # ---- page 3: exposure ---------------------------------------------
    if summary.exposure is not None:
        story.append(PageBreak())
        story.append(_p("Population and infrastructure exposure", ss["JTitle"]))
        story.append(_p(
            f"About <b>{summary.exposure.rounded_population():,}</b> people are "
            f"within the modelled inundation extent. Reported to two "
            f"significant figures: the population raster is a modelled surface, "
            f"not an enumeration, and a more precise number would be a "
            f"fabrication.", ss["JBody"]))
        story.append(_p("By arrival band", ss["JSection"]))
        story.append(_table(_exposure_band_rows(summary),
                            [avail * 0.30, avail * 0.22, avail * 0.48]))
        story.append(_p("By hazard class", ss["JSection"]))
        story.append(_table(_exposure_hazard_rows(summary),
                            [avail * 0.24, avail * 0.20, avail * 0.56]))
        if summary.exposure.infrastructure:
            story.append(_p("Infrastructure in the flood extent",
                            ss["JSection"]))
            story.append(_table(_infra_rows(summary),
                                [avail * 0.55, avail * 0.45]))

    # ---- damage, if present -------------------------------------------
    if summary.damage is not None:
        story.append(_p("Indicative economic loss", ss["JSection"]))
        total = summary.damage.total
        story.append(_p(
            f"<b>{total.format_crore()}</b> — an order-of-magnitude range, not "
            f"an estimate. It is the product of four independently uncertain "
            f"factors (asset count, unit value, depth-damage curve, depth "
            f"itself) and is reported as a range because collapsing it to one "
            f"number would misrepresent what is known.", ss["JBody"]))
        story.append(_table(_damage_rows(summary),
                            [avail * 0.34, avail * 0.22, avail * 0.22,
                             avail * 0.22]))

    # ---- maps last ----------------------------------------------------
    if include_maps:
        story.append(PageBreak())
        story.append(_p("Maps", ss["JTitle"]))
        story.append(_p(
            "Cell boundaries are not smoothed. The model has no sub-cell "
            f"information at {summary.dx:g} m, and a smooth contour would imply "
            "that it does.", ss["JSmall"]))
        try:
            amap = render_arrival_map(summary, figures_dir / "arrival_map.png",
                                      hillshade=hillshade)
            story.append(KeepTogether([
                Image(str(amap), width=avail, height=avail * 0.79),
                _p("Arrival time bands. Pale blue is water present before the "
                   "failure — it is not flooding and is excluded from every "
                   "figure in this report.", ss["JSmall"])]))
            story.append(Spacer(1, _mm(4)))
            hmap = render_hazard_map(summary, figures_dir / "hazard_map.png")
            story.append(KeepTogether([
                Image(str(hmap), width=avail, height=avail * 0.79),
                _p("Defra/EA hazard rating HR = d(v + 0.5) + debris factor, "
                   "computed from the running maximum of depth x velocity.",
                   ss["JSmall"])]))
        except Exception as exc:                              # pragma: no cover
            # A missing figure must not cost the reader the tables. Say so in
            # the document rather than failing the export.
            story.append(_p(
                f"[Map rendering unavailable in this run: {exc}. The GeoTIFF "
                f"and Shapefile/KML deliverables are unaffected.]",
                ss["JWarn"]))

    doc = SimpleDocTemplate(
        str(path), pagesize=A4,
        leftMargin=_mm(PAGE_MARGIN_MM), rightMargin=_mm(PAGE_MARGIN_MM),
        topMargin=_mm(PAGE_MARGIN_MM + 6),
        bottomMargin=_mm(PAGE_MARGIN_MM + 12),
        title=f"JALDRISHTI — {summary.study_area} — {summary.scenario}",
        author="JALDRISHTI (SIH 2026, PS 26161)",
        subject="Dam-break inundation simulation output — not a survey")

    stamper = _Stamper(summary.run_id, summary.study_area,
                       watermark_text=None if ok else "UNVERIFIED")
    doc.build(story, onFirstPage=stamper, onLaterPages=stamper)
    return path


# --------------------------------------------------------------------------
# table builders
# --------------------------------------------------------------------------
def _arrival_rows(summary):
    from ..analysis.arrival import band_labels
    from .vector import _evacuation_action

    labels = band_labels(summary.arrival.bands_min)
    areas = summary.arrival.area_by_band_km2()
    pops = (summary.exposure.population_by_arrival_band
            if summary.exposure is not None else {})

    rows = [["Band", "Area (km²)", "People", "Feasible action"]]
    for i, lab in enumerate(labels):
        pop = pops.get(lab)
        rows.append([
            lab,
            _fmt(areas.get(lab, 0.0), 2),
            "—" if pop is None else f"{summary.exposure.rounded_population(pop):,}",
            _evacuation_action(i, labels),
        ])
    return rows


def _run_rows(summary):
    first = summary.arrival.first_arrival_minutes()
    last = summary.arrival.last_arrival_minutes()
    rows = [
        ["Quantity", "Value"],
        ["Newly inundated area",
         f"{_fmt(summary.flooded_area_km2)} km²"],
        ["Total wetted area (incl. reservoir)",
         f"{_fmt(summary.total_wetted_area_km2)} km²"],
        ["Peak depth", f"{_fmt(summary.peak_depth_m)} m"],
        ["Peak speed", f"{_fmt(summary.peak_speed_ms)} m/s"],
        ["First arrival outside pre-existing water",
         f"{_fmt(first, 0, dash='not reached')} min"
         if np.isfinite(first) else "not reached"],
        ["Last arrival",
         f"{_fmt(last, 0)} min" if np.isfinite(last) else "not reached"],
        ["Grid",
         f"{summary.shape[1]} × {summary.shape[0]} cells at {summary.dx:g} m"],
        ["Simulated duration", f"{summary.duration_s / 3600.0:.2f} h "
                               f"({summary.steps:,} steps)"],
        ["Wall-clock time", f"{summary.wall_time_s:.1f} s"],
        ["Mass conservation error", f"{summary.volume_error:+.2e} (relative)"],
    ]
    if summary.dem_valid_mask is not None:
        rows.append(["Flooded cells over interpolated DEM voids",
                     f"{summary.interpolated_flooded_cells:,}"])
    return rows


def _exposure_band_rows(summary):
    from ..analysis.arrival import band_labels
    from .vector import _evacuation_action

    labels = band_labels(summary.arrival.bands_min)
    pops = summary.exposure.population_by_arrival_band
    rows = [["Arrival band", "People", "Feasible action"]]
    for i, lab in enumerate(labels):
        rows.append([lab,
                     f"{summary.exposure.rounded_population(pops.get(lab, 0.0)):,}",
                     _evacuation_action(i, labels)])
    rows.append(["Total",
                 f"{summary.exposure.rounded_population():,}",
                 "—"])
    return rows


def _exposure_hazard_rows(summary):
    from ..analysis.hazard import DEFRA_CLASS_MEANING, DEFRA_CLASS_NAMES

    pops = summary.exposure.population_by_hazard
    rows = [["Hazard class", "People", "Published meaning"]]
    for i, name in enumerate(DEFRA_CLASS_NAMES):
        rows.append([name,
                     f"{summary.exposure.rounded_population(pops.get(name, 0.0)):,}",
                     DEFRA_CLASS_MEANING[i]])
    return rows


def _infra_rows(summary):
    rows = [["Feature", "Count / length"]]
    for k, v in sorted(summary.exposure.infrastructure.items()):
        if isinstance(v, (int, np.integer)):
            rows.append([k.replace("_", " "), f"{int(v):,}"])
        else:
            rows.append([k.replace("_", " "), f"{_fmt(v, 1)}"])
    return rows


def _damage_rows(summary):
    rows = [["Category", "Low", "Central", "High"]]
    for k, v in summary.damage.by_category.items():
        lo, ce, hi = v.in_crore()
        rows.append([k.replace("_", " "), f"₹{lo:,.1f} cr",
                     f"₹{ce:,.1f} cr", f"₹{hi:,.1f} cr"])
    lo, ce, hi = summary.damage.total.in_crore()
    rows.append(["TOTAL", f"₹{lo:,.1f} cr", f"₹{ce:,.1f} cr", f"₹{hi:,.1f} cr"])
    return rows

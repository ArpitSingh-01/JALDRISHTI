/**
 * Verbatim backend strings and sentinel values.
 *
 * These are legally-framed strings from backend/jaldrishti/export/metadata.py.
 * The frontend must render them exactly — do not paraphrase.
 * See frontend.md §6.9.
 */

// ---- Solver attribution (§6.9) ----
// Appears on: /methodology, anywhere Delft3D is mentioned.
// NEVER add UI copy implying Delft3D was run.
export const SOLVER_ATTRIBUTION = `Hydrodynamics computed by JALDRISHTI's own 2D shallow-water solver (finite volume, HLLC approximate Riemann solver, MUSCL reconstruction, well-balanced bed-slope source term, Manning friction, explicit CFL-limited time stepping). Delft3D was NOT run to produce this output. Where Delft3D is referenced, the comparison is against PUBLISHED benchmark results from the literature, and the interoperability claim is limited to a Delft3D-compatible input/output adapter.`;

// ---- Model disclaimer (§6.9) ----
// Appears on: landing (§4.1 §6), console honesty drawer, and the report.
export const MODEL_DISCLAIMER = `This is simulation output, not a survey and not an official flood hazard map. It is intended for humanitarian planning and exercise use. Arrival time is measured from the moment of failure and is NOT warning time — warning time additionally requires detection, decision and dissemination, which this model does not represent. Statutory dam-break inundation mapping in India is governed by the Dam Safety Act, 2021 and CWC guidelines; this tool supports such work, it does not substitute for it.`;

// ---- Float raster nodata ----
export const RASTER_NODATA_FLOAT = -9999.0;
export const RASTER_NODATA_INT = -1;

// ---- Study area human titles ----
// The key is the canonical backend identifier. The title is for display only.
export const STUDY_AREA_TITLES: Record<string, string> = {
  malpasset: "Malpasset Dam, Reyran valley, France — 2 December 1959",
  tehri: "Tehri Dam, Bhagirathi river, Uttarakhand",
  rishi_ganga:
    "Rishi Ganga / Ronti Gad, Chamoli, Uttarakhand — 7 February 2021",
};

// ---- Short display names (for nav, cards) ----
export const STUDY_AREA_SHORT_NAMES: Record<string, string> = {
  malpasset: "Malpasset 1959",
  tehri: "Tehri Dam",
  rishi_ganga: "Chamoli 2021",
};

// ---- Scenario kind labels ----
export const SCENARIO_KIND_LABELS: Record<string, string> = {
  dam_break: "Dam Break",
  blockage: "River Blockage",
};

// ---- Statutory citations (landing footer, about page) ----
export const STATUTORY_CITATIONS = [
  "Dam Safety Act, 2021 (India)",
  "NDMA Guidelines on Management of Glacial Lake Outburst Floods (GLOFs), 2020",
  "CWC Guidelines for Dam Break Inundation Mapping",
  "Sendai Framework for Disaster Risk Reduction 2015–2030, Priority 4",
] as const;

// ---- SIH context ----
export const SIH_CONTEXT = {
  year: 2026,
  ps_number: "26161",
  organisation: "National Technical Research Organisation (NTRO)",
  theme: "Disaster Management",
} as const;

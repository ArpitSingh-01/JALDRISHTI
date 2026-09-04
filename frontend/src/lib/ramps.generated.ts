/**
 * AUTO-GENERATED from backend constants — run export_ramps.py to regenerate.
 *
 * Source:
 *   backend/jaldrishti/analysis/hazard.py   DEFRA_CLASS_COLOURS, AIDR_CLASS_COLOURS
 *   backend/jaldrishti/analysis/arrival.py  BAND_COLOURS, PRE_EXISTING_WATER_COLOUR
 *
 * Do not hand-edit. Do not interpolate extra stops. Do not reorder.
 * Arrival ramp: darkest-is-fastest (#08306b = 0-15 min).
 *
 * A CI check will fail the build if this file drifts from the backend constants.
 */

// DEFRA/EA hazard rating — Low · Moderate · Significant · Extreme
export const DEFRA_CLASS_NAMES = [
  "Low",
  "Moderate",
  "Significant",
  "Extreme",
] as const;

export const DEFRA_CLASS_COLOURS = [
  "#ffeda0",
  "#feb24c",
  "#f03b20",
  "#7f0000",
] as const;

// Full DEFRA class meanings (from hazard.py DEFRA_CLASS_MEANING)
export const DEFRA_CLASS_MEANINGS = [
  "Caution — shallow flowing or deep standing water",
  "Dangerous for some — children, the elderly, the infirm",
  "Dangerous for most people",
  "Dangerous for all — including emergency services",
] as const;

// DEFRA thresholds on HR = d(v + 0.5) + DF
export const DEFRA_BANDS = [0.75, 1.25, 2.5] as const;

// AIDR/AR&R combined hazard class H1..H6
export const AIDR_CLASS_NAMES = [
  "H1",
  "H2",
  "H3",
  "H4",
  "H5",
  "H6",
] as const;

export const AIDR_CLASS_COLOURS = [
  "#ffffb2",
  "#fed976",
  "#feb24c",
  "#fd8d3c",
  "#e31a1c",
  "#800026",
] as const;

// Arrival isochrone bands
// Fastest is DARKEST so the eye lands first on the places with least time.
export const DEFAULT_BANDS_MIN = [15.0, 30.0, 60.0, 120.0] as const;

export const ARRIVAL_BAND_LABELS = [
  "0-15 min",
  "15-30 min",
  "30-60 min",
  "60-120 min",
  ">120 min",
] as const;

export const ARRIVAL_BAND_COLOURS = [
  "#08306b",
  "#2171b5",
  "#4292c6",
  "#7fb8d9",
  "#bdd7e7",
] as const;

// Pre-existing water (reservoir/channel before failure) — off the urgency
// ramp entirely so it can never be misread as an arrival band.
export const PRE_EXISTING_WATER_COLOUR = "#8c96a8";

// Sentinels — never summed, never averaged, always distinct in the legend.
export const NEVER_FLOODED = -1;
export const INITIALLY_WET = -2;

/**
 * JALDRISHTI frontend data contract.
 *
 * Every type here mirrors the backend's ScenarioSummary.to_dict() output
 * (backend/jaldrishti/analysis/summary.py). Field names are copied from
 * live source — do not rename, do not invent.
 *
 * See frontend.md §6 for the full specification.
 */

// ---- Grid ----
export interface Grid {
  shape: [number, number]; // [rows, cols]
  dx_m: number;
  crs: string;
  transform: [number, number, number, number, number, number] | null;
}

// ---- Run metadata ----
export interface RunMeta {
  duration_s: number;
  wall_time_s: number;
  steps: number;
  volume_error: number;
  solver: Record<string, unknown>;
}

// ---- Exposure (optional — present only if computed) ----
export interface Exposure {
  total_population: number;
  reported_population: number; // DISPLAY THIS ONE (2 sig figs) — §6.7, §11.3
  by_hazard: Record<string, number>;
  by_arrival_band: Record<string, number>;
  cross_tab: Record<string, number>; // "Extreme|0-15 min" → count
  infrastructure: Record<string, number>;
  resample_report: { conserved: boolean; residual_fraction: number };
}

// ---- Damage (optional; forces not-presentable — §6.7) ----
export interface Damage {
  unit: string; // "INR"
  low: number;
  central: number;
  high: number;
  formatted: string; // e.g. "₹120–480 crore" — use verbatim
  by_category: Record<
    string,
    { low: number; central: number; high: number }
  >;
  structural_failure_buildings: number;
}

// ---- Results ----
export interface Results {
  flooded_area_km2: number; // NEW flooding only — NOT total wetted (§6.3)
  total_wetted_area_km2: number; // includes reservoir
  peak_depth_m: number;
  peak_speed_ms: number;
  first_arrival_min: number | null; // null = never reached (§6.3)
  last_arrival_min: number | null;
  area_by_hazard_km2: Record<string, number>; // DEFRA class name → km²
  area_by_aidr_class_km2: Record<string, number>; // AIDR class → km²
  area_by_arrival_band_km2: Record<string, number>; // band label → km²
  interpolated_flooded_cells: number;
  exposure?: Exposure;
  damage?: Damage;
}

// ---- Honesty ----
export interface Honesty {
  presentable_as_fact: boolean;
  blocking_reasons: string[];
  unverified_inputs: string[];
  limitations: string[];
}

// ---- Provenance ----
export interface Provenance {
  terrain: Record<string, unknown>;
  breach: Record<string, unknown>;
}

// ---- THE contract: ScenarioSummary.to_dict() ----
export interface ScenarioSummary {
  run_id: string;
  study_area: string; // "tehri" | "malpasset" | "rishi_ganga"
  scenario: string;
  headline: string; // THE sentence — render prominently (§1.2)
  grid: Grid;
  run: RunMeta;
  results: Results;
  provenance: Provenance;
  honesty: Honesty;
}

// ---- Run status (for polling / realtime) ----
export type RunStatus = "pending" | "running" | "done" | "failed";

// ---- Study area (for /scenarios) ----
export interface StudyAreaSummary {
  key: string; // "malpasset" | "tehri" | "rishi_ganga"
  title: string;
  scenario_kind: "dam_break" | "blockage";
  purpose: string;
  thumbnail?: string;
}

// ---- Source/Verification ----
export interface SourceInfo {
  citation: string;
  verified: boolean;
  note?: string;
}

// ---- Settlement feature properties (§6.8) ----
export interface SettlementProperties {
  name: string;
  arr_min: number; // -1 = not reached
  flooded: boolean;
  depth_m: number;
  speed_ms: number;
  haz_class: string;
  band: number;
  population?: number;
}

// ---- Isochrone feature properties (§6.6) ----
export interface IsochroneProperties {
  band: number;
  label: string;
  min_minutes: number;
  max_minutes: number;
  area_km2: number;
}

// ---- Progress stream (§7) ----
export interface ProgressEvent {
  step: number;
  pct: number;
  t_sim: number;
  volume_error: number;
  msg: string;
}

// ---- Breach config form submission ----
export interface FailureSpec {
  mode: "instantaneous" | "parametric" | "overtopping";
  breach_width_m?: number;
  breach_depth_m?: number;
  side_slope?: number;
  formation_time_s?: number;
  formation_time_range_s?: [number, number];
}

// ---- Manifest (§6.10) ----
// Corrected against backend/jaldrishti/export/metadata.py::write_manifest
export interface ManifestFile {
  path: string;
  bytes: number;
  sha256: string;
}

export interface Manifest {
  schema_version: number;
  generated_utc: string;
  run_dir: string;
  file_count: number;
  total_bytes: number;
  files: ManifestFile[];
  note?: string;
}

// ---- Run list item (for /runs history) ----
export interface RunListItem {
  run_id: string;
  study_area: string;
  scenario: string;
  status: RunStatus;
  headline?: string;
  flooded_area_km2?: number;
  first_arrival_min?: number | null;
  presentable_as_fact?: boolean;
  created_at: string;
  completed_at?: string;
}

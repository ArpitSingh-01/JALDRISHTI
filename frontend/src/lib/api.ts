/**
 * API client — mock-swappable.
 *
 * In development, reads from src/mocks/*.json.
 * In production, fetches from NEXT_PUBLIC_API_BASE.
 *
 * The switch is a single env var. No other changes needed.
 */

import type {
  ScenarioSummary,
  StudyAreaSummary,
  Manifest,
  RunListItem,
} from "./types";
import type { FeatureCollection } from "geojson";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";
const USE_MOCKS = !API_BASE;

// ---- Mock imports (tree-shaken in production when API_BASE is set) ----
async function loadMock<T>(name: string): Promise<T> {
  const mod = await import(`@/mocks/${name}`);
  return mod.default as T;
}

// ---- Study areas ----
export async function getStudyAreas(): Promise<StudyAreaSummary[]> {
  if (USE_MOCKS) return loadMock<StudyAreaSummary[]>("study-areas.json");
  const res = await fetch(`${API_BASE}/api/study-areas`);
  if (!res.ok) throw new Error(`Failed to fetch study areas: ${res.status}`);
  return res.json();
}

export async function getStudyArea(key: string): Promise<StudyAreaSummary> {
  if (USE_MOCKS) {
    const areas = await getStudyAreas();
    const area = areas.find((a) => a.key === key);
    if (!area) throw new Error(`Study area not found: ${key}`);
    return area;
  }
  const res = await fetch(`${API_BASE}/api/study-areas/${key}`);
  if (!res.ok) throw new Error(`Failed to fetch study area: ${res.status}`);
  return res.json();
}

// ---- Runs ----
export async function getRuns(): Promise<RunListItem[]> {
  if (USE_MOCKS) {
    const run = await loadMock<ScenarioSummary>("run-tehri-90m.json");
    return [
      {
        run_id: run.run_id,
        study_area: run.study_area,
        scenario: run.scenario,
        status: "done",
        headline: run.headline,
        flooded_area_km2: run.results.flooded_area_km2,
        first_arrival_min: run.results.first_arrival_min,
        presentable_as_fact: run.honesty.presentable_as_fact,
        created_at: new Date().toISOString(),
      },
    ];
  }
  const res = await fetch(`${API_BASE}/api/runs`);
  if (!res.ok) throw new Error(`Failed to fetch runs: ${res.status}`);
  return res.json();
}

export async function getRun(runId: string): Promise<ScenarioSummary> {
  if (USE_MOCKS) return loadMock<ScenarioSummary>("run-tehri-90m.json");
  const res = await fetch(`${API_BASE}/api/runs/${runId}`);
  if (!res.ok) throw new Error(`Failed to fetch run: ${res.status}`);
  return res.json();
}

export async function getManifest(runId: string): Promise<Manifest> {
  if (USE_MOCKS) return loadMock<Manifest>("manifest-tehri.json");
  const res = await fetch(`${API_BASE}/api/runs/${runId}/manifest`);
  if (!res.ok) throw new Error(`Failed to fetch manifest: ${res.status}`);
  return res.json();
}

// ---- Isochrones GeoJSON ----
export async function getIsochrones(runId: string): Promise<FeatureCollection> {
  if (USE_MOCKS) return loadMock<FeatureCollection>("isochrones-tehri.json");
  const res = await fetch(`${API_BASE}/api/runs/${runId}/isochrones.geojson`);
  if (!res.ok) throw new Error(`Failed to fetch isochrones: ${res.status}`);
  return res.json();
}

// ---- Settlements GeoJSON ----
export async function getSettlements(runId: string): Promise<FeatureCollection> {
  if (USE_MOCKS) return loadMock<FeatureCollection>("settlements-tehri.json");
  const res = await fetch(`${API_BASE}/api/runs/${runId}/settlements.geojson`);
  if (!res.ok) throw new Error(`Failed to fetch settlements: ${res.status}`);
  return res.json();
}

// ---- Create run ----
export async function createRun(body: {
  area: string;
  failure_spec: Record<string, unknown>;
  resolution: number;
}): Promise<{ run_id: string }> {
  if (USE_MOCKS) return { run_id: "mock-tehri-90m-0001" };
  const res = await fetch(`${API_BASE}/api/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Failed to create run: ${res.status}`);
  return res.json();
}

// ---- Download artifact ----
export function getArtifactUrl(runId: string, key: string): string {
  if (USE_MOCKS) return "#";
  return `${API_BASE}/api/runs/${runId}/artifacts/${encodeURIComponent(key)}`;
}

// ---- Tile URL template ----
export function getTileUrl(runId: string, band: string): string {
  if (USE_MOCKS) return "";
  return `${API_BASE}/api/runs/${runId}/tiles/${band}/{z}/{x}/{y}.png`;
}

/**
 * API client — LIVE FIRST.
 *
 * Every call hits the real FastAPI backend at NEXT_PUBLIC_API_BASE and
 * returns REAL simulation output. The mock JSON in src/mocks/ is a
 * development convenience ONLY: it is reachable exclusively when
 * NEXT_PUBLIC_ENABLE_MOCKS=1 is set explicitly in the environment, and any
 * page served from mocks carries a "DEMO DATA" marker so it can never be
 * mistaken for a simulation result.
 *
 * There is no silent fallback to mocks. If the backend is unreachable, the
 * UI shows an error state — an honest failure, not fabricated data.
 */

import type {
  ScenarioSummary,
  StudyAreaSummary,
  Manifest,
  RunListItem,
} from "./types";
import type { FeatureCollection } from "geojson";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";
const MOCKS_ENABLED =
  !API_BASE && process.env.NEXT_PUBLIC_ENABLE_MOCKS === "1";

if (MOCKS_ENABLED && typeof window !== "undefined") {
  // Loud, once, in the console: nobody should screenshot a mocks-driven
  // page without knowing it.
  console.warn(
    "[JALDRISHTI] NEXT_PUBLIC_ENABLE_MOCKS=1 and no NEXT_PUBLIC_API_BASE: " +
      "this page is showing DEVELOPMENT MOCK DATA, not simulation output."
  );
}

/** True when the current page is backed by mock JSON (dev flag only). */
export const USING_MOCKS = MOCKS_ENABLED;

// ---- Mock imports (only reachable when MOCKS_ENABLED above) ----
async function loadMock<T>(name: string): Promise<T> {
  const mod = await import(`@/mocks/${name}`);
  return mod.default as T;
}

function requireBase(): string {
  if (!API_BASE) {
    throw new Error(
      "NEXT_PUBLIC_API_BASE is not set — the JALDRISHTI API location is " +
        "unknown. Set it in the environment to the FastAPI base URL."
    );
  }
  return API_BASE;
}

// ---- Study areas ----
export async function getStudyAreas(): Promise<StudyAreaSummary[]> {
  if (MOCKS_ENABLED) return loadMock<StudyAreaSummary[]>("study-areas.json");
  const res = await fetch(`${requireBase()}/api/study-areas`);
  if (!res.ok) throw new Error(`Failed to fetch study areas: ${res.status}`);
  return res.json();
}

export async function getStudyArea(key: string): Promise<StudyAreaSummary> {
  if (MOCKS_ENABLED) {
    const areas = await getStudyAreas();
    const area = areas.find((a) => a.key === key);
    if (!area) throw new Error(`Study area not found: ${key}`);
    return area;
  }
  const res = await fetch(`${requireBase()}/api/study-areas/${key}`);
  if (!res.ok) throw new Error(`Failed to fetch study area: ${res.status}`);
  return res.json();
}

// ---- Runs ----
export async function getRuns(): Promise<RunListItem[]> {
  if (MOCKS_ENABLED) {
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
  const res = await fetch(`${requireBase()}/api/runs`);
  if (!res.ok) throw new Error(`Failed to fetch runs: ${res.status}`);
  return res.json();
}

export async function getRun(runId: string): Promise<ScenarioSummary> {
  if (MOCKS_ENABLED) return loadMock<ScenarioSummary>("run-tehri-90m.json");
  const res = await fetch(`${requireBase()}/api/runs/${runId}`);
  if (!res.ok) throw new Error(`Failed to fetch run: ${res.status}`);
  return res.json();
}

export async function getManifest(runId: string): Promise<Manifest> {
  if (MOCKS_ENABLED) return loadMock<Manifest>("manifest-tehri.json");
  const res = await fetch(`${requireBase()}/api/runs/${runId}/manifest`);
  if (!res.ok) throw new Error(`Failed to fetch manifest: ${res.status}`);
  return res.json();
}

// ---- Isochrones GeoJSON ----
export async function getIsochrones(runId: string): Promise<FeatureCollection> {
  if (MOCKS_ENABLED) return loadMock<FeatureCollection>("isochrones-tehri.json");
  const res = await fetch(`${requireBase()}/api/runs/${runId}/isochrones.geojson`);
  if (!res.ok) throw new Error(`Failed to fetch isochrones: ${res.status}`);
  return res.json();
}

// ---- Settlements GeoJSON ----
export async function getSettlements(runId: string): Promise<FeatureCollection> {
  if (MOCKS_ENABLED) return loadMock<FeatureCollection>("settlements-tehri.json");
  const res = await fetch(`${requireBase()}/api/runs/${runId}/settlements.geojson`);
  if (!res.ok) throw new Error(`Failed to fetch settlements: ${res.status}`);
  return res.json();
}

// ---- Create run ----
export async function createRun(body: {
  area: string;
  failure_spec: Record<string, unknown>;
  resolution: number;
}): Promise<{ run_id: string }> {
  if (MOCKS_ENABLED) return { run_id: "mock-tehri-90m-0001" };
  const res = await fetch(`${requireBase()}/api/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Failed to create run: ${res.status}`);
  return res.json();
}

// ---- Download artifact ----
export function getArtifactUrl(runId: string, key: string): string {
  if (MOCKS_ENABLED) return "#";
  return `${requireBase()}/api/runs/${runId}/artifacts/${encodeURIComponent(key)}`;
}

// ---- Tile URL template ----
export function getTileUrl(runId: string, band: string): string {
  if (MOCKS_ENABLED) return "";
  return `${requireBase()}/api/runs/${runId}/tiles/${band}/{z}/{x}/{y}.png`;
}

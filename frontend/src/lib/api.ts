/**
 * API client — live only.
 *
 * Every call hits the real FastAPI backend at NEXT_PUBLIC_API_BASE and
 * returns REAL simulation output read from the run bundles. There are no
 * mocks in this client: if the backend is unreachable, the UI shows an
 * error state — an honest failure, never fabricated data.
 *
 * Dev workflow: run `uvicorn jaldrishti.api.app:app --port 8000` in
 * backend/ and set NEXT_PUBLIC_API_BASE=http://localhost:8000.
 */

import type {
  ScenarioSummary,
  StudyAreaSummary,
  Manifest,
  RunListItem,
} from "./types";
import type { FeatureCollection } from "geojson";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

function requireBase(): string {
  if (!API_BASE) {
    throw new Error(
      "NEXT_PUBLIC_API_BASE is not set — the JALDRISHTI API location is " +
        "unknown. Set it in the environment to the FastAPI base URL."
    );
  }
  return API_BASE;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${requireBase()}${path}`);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

// ---- Study areas (backend StudyInfo is a superset of the UI summary) ----
export async function getStudyAreas(): Promise<StudyAreaSummary[]> {
  const infos = await getJson<Record<string, unknown>[]>("/api/studies");
  return infos.map((info) => ({
    key: String(info.key),
    title: String(info.title),
    scenario_kind: String(info.scenario_kind) as "dam_break" | "blockage",
    purpose: String(info.purpose),
  }));
}

export async function getStudyArea(key: string): Promise<StudyAreaSummary> {
  const info = await getJson<Record<string, unknown>>(`/api/studies/${key}`);
  return {
    key: String(info.key),
    title: String(info.title),
    scenario_kind: String(info.scenario_kind) as "dam_break" | "blockage",
    purpose: String(info.purpose),
  };
}

// ---- Runs (backend RunStatus mapped to the UI's RunListItem) ----
export async function getRuns(): Promise<RunListItem[]> {
  const statuses = await getJson<Record<string, unknown>[]>("/api/runs");
  return statuses.map(mapRunListItem);
}

export async function getRun(runId: string): Promise<ScenarioSummary> {
  // /result carries the run's full metadata.json — the contract type in
  // types.ts mirrors exactly this document.
  return getJson<ScenarioSummary>(`/api/runs/${runId}/result`);
}

function mapRunListItem(s: Record<string, unknown>): RunListItem {
  return {
    run_id: String(s.run_id),
    study_area: String(s.area ?? ""),
    scenario: "simulated run",
    status: String(s.status ?? "unknown") as RunListItem["status"],
    headline: typeof s.headline === "string" ? s.headline : undefined,
    flooded_area_km2:
      typeof s.flooded_area_km2 === "number" ? s.flooded_area_km2 : undefined,
    first_arrival_min:
      typeof s.first_arrival_min === "number" ? s.first_arrival_min : null,
    presentable_as_fact:
      typeof s.presentable === "boolean" ? s.presentable : undefined,
    created_at: String(s.submitted_utc ?? s.started_utc ?? ""),
    completed_at:
      typeof s.finished_utc === "string" ? s.finished_utc : undefined,
  };
}

export async function getManifest(runId: string): Promise<Manifest> {
  return getJson<Manifest>(`/api/runs/${runId}/manifest`);
}

// ---- Isochrones GeoJSON (derived live from the run's arrival raster) ----
export async function getIsochrones(runId: string): Promise<FeatureCollection> {
  return getJson<FeatureCollection>(`/api/runs/${runId}/isochrones.geojson`);
}

// ---- Settlements GeoJSON (named places, sampled from the run rasters) ----
export async function getSettlements(runId: string): Promise<FeatureCollection> {
  return getJson<FeatureCollection>(`/api/runs/${runId}/settlements.geojson`);
}

// ---- Create run (FastAPI RunRequest: area / dx / duration_hours) ----
export async function createRun(body: {
  area: string;
  resolution?: number;
  duration_hours?: number;
}): Promise<{ run_id: string }> {
  const res = await fetch(`${requireBase()}/api/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      area: body.area,
      dx: body.resolution ?? null,
      duration_hours: body.duration_hours ?? 2.0,
      exposure: true,
      damage: false,
      export_bundle: true,
    }),
  });
  if (!res.ok) throw new Error(`Failed to create run: ${res.status}`);
  return res.json();
}

// ---- Download artifact ----
export function getArtifactUrl(runId: string, key: string): string {
  return `${requireBase()}/api/runs/${runId}/artifacts/${encodeURIComponent(key)}`;
}

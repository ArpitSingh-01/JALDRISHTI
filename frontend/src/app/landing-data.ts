import {
  ARRIVAL_BAND_LABELS,
  ARRIVAL_BAND_COLOURS,
} from "@/lib/ramps.generated";

export const ARRIVALS_RAMP_DEMO = [
  { label: ARRIVAL_BAND_LABELS[0], colour: ARRIVAL_BAND_COLOURS[0], widthPct: 30 },
  { label: ARRIVAL_BAND_LABELS[1], colour: ARRIVAL_BAND_COLOURS[1], widthPct: 48 },
  { label: ARRIVAL_BAND_LABELS[2], colour: ARRIVAL_BAND_COLOURS[2], widthPct: 65 },
  { label: ARRIVAL_BAND_LABELS[3], colour: ARRIVAL_BAND_COLOURS[3], widthPct: 82 },
  { label: ARRIVAL_BAND_LABELS[4], colour: ARRIVAL_BAND_COLOURS[4], widthPct: 100 },
];

export const SCENARIOS_PREVIEW = [
  {
    key: "tehri",
    title: "Tehri Dam, Uttarakhand",
    kindLabel: "Dam Break",
    crs: "EPSG:32644 (UTM 44N)",
    purpose:
      "Demonstration on India's tallest dam (260.5 m rockfill). Simulates catastrophic breach release down the Bhagirathi river to Devprayag, Rishikesh, and Haridwar.",
  },
  {
    key: "rishi_ganga",
    title: "Chamoli / Rishi Ganga 2021",
    kindLabel: "River Blockage",
    crs: "EPSG:32644 (UTM 44N)",
    purpose:
      "Direct response to the problem statement requirement. Models the rock-ice avalanche blockage and breach sequence along the Ronti Gad and Dhauliganga valleys.",
  },
  {
    key: "malpasset",
    title: "Malpasset 1959, France",
    kindLabel: "Validation Case",
    crs: "LOCAL:malpasset_edf",
    purpose:
      "Validation against surveyed high-water marks, transformer cutoff times, and physical scale models from the 1959 historical arch dam failure.",
  },
];

export const VALIDATION_STEPS_PREVIEW = [
  { name: "1 · Lake at Rest (Well-balancedness)", metric: "Residual v ≈ 2×10⁻¹⁴ m/s" },
  { name: "2 · Ritter Dry-Bed Dam Break", metric: "Analytical exact fit" },
  { name: "3 · Stoker Wet-Bed Dam Break", metric: "Shock front exact match" },
  { name: "4 · Manning Normal Depth & Friction", metric: "Grid convergence verified" },
  { name: "5 · Malpasset 1959 Field Survey", metric: "Surveyed HWM benchmark" },
];

export interface SpecRow {
  label: string;
  value: string;
  verified: boolean;
  citation: string;
  note?: string;
}

export interface ScenarioDetailInfo {
  key: string;
  title: string;
  kindLabel: string;
  purpose: string;
  specTitle: string;
  specs: SpecRow[];
  domain: {
    crs: string;
    bounds: string;
    resInteractive: string;
    resHighRes: string;
  };
  limitations: string[];
  unverifiedInputs: string[];
  defaultBreach: {
    mode: string;
    width_m?: number;
    depth_m?: number;
    formation_time_s?: number;
  };
}

export const SCENARIOS_DETAIL_DATA: Record<string, ScenarioDetailInfo> = {
  tehri: {
    key: "tehri",
    title: "Tehri Dam, Bhagirathi River, Uttarakhand",
    kindLabel: "Dam Break",
    purpose:
      "Headline operational demonstration for the Dam Safety Act 2021 mandate. Simulates the failure of India's tallest structure and computes arrival times and exposure for downstream settlements.",
    specTitle: "Dam & Reservoir Specifications (Tehri Stage-I)",
    specs: [
      {
        label: "Dam Type",
        value: "Earth-core rockfill embankment",
        verified: true,
        citation: "CWC NRLD 2019 p.279 & THDC FAQ",
      },
      {
        label: "Structural Height",
        value: "260.50 m above foundation",
        verified: true,
        citation: "CWC NRLD 2019 & THDC FAQ",
      },
      {
        label: "Crest Length",
        value: "575.0 m",
        verified: true,
        citation: "CWC NRLD 2019 (NRLD table)",
      },
      {
        label: "Full Reservoir Level (FRL)",
        value: "830.0 m EL",
        verified: true,
        citation: "THDC FAQ & THDC Progress Report Dec 2024",
      },
      {
        label: "Gross Storage Capacity",
        value: "3,540,000,000 m³ (3.54 BCM)",
        verified: true,
        citation: "CWC NRLD 2019 & THDC FAQ",
        note: "Sets total impounded volume",
      },
      {
        label: "Live / Effective Storage",
        value: "2,615,000,000 m³ (2.615 BCM)",
        verified: true,
        citation: "CWC NRLD 2019 & THDC FAQ",
      },
      {
        label: "Water Spread Area at FRL",
        value: "52.0 km²",
        verified: true,
        citation: "CWC NRLD 2019",
      },
      {
        label: "Design Spillway Capacity",
        value: "13,040 m³/s",
        verified: true,
        citation: "CWC NRLD 2019",
        note: "Reporting sanity benchmark",
      },
      {
        label: "Installed Power Capacity",
        value: "1,000 MW (4 × 250 MW)",
        verified: true,
        citation: "THDC FAQ (Stage-I HPP)",
      },
      {
        label: "Catchment Area",
        value: "7,511 km²",
        verified: false,
        citation: "Secondary literature / recalled estimate",
        note: "NRLD 2019 does not report catchment",
      },
      {
        label: "Manning Roughness (n)",
        value: "0.045 s/m^(1/3)",
        verified: false,
        citation: "Engineering judgement for steep Himalayan boulder bed",
      },
    ],
    domain: {
      crs: "EPSG:32644 (UTM Zone 44N)",
      bounds: "X: 218,280 – 276,660 m | Y: 3,308,130 – 3,371,310 m",
      resInteractive: "90 m (649 × 702 = 455,598 cells, ~1–2 min)",
      resHighRes: "30 m (1,946 × 2,106 = 4,098,276 cells, ~15–30 min estimated)",
    },
    limitations: [
      "Reservoir geometry is a two-number approximation (52 km² constant area; actual level-area-capacity curve is proprietary). Drawdown assumes constant surface area.",
      "Bathymetry is absent from Copernicus DEM; reservoir bed is imposed from published gross storage (3.54 BCM) rather than measured from topography.",
      "Breach formation time is an assumption, not a measurement. Results must be presented across the 30–180 minute sensitivity range.",
      "Reservoir drawdown is modelled as an inflow boundary hydrograph rather than fully coupled 3D reservoir routing.",
      "Koteshwar Dam (22 km downstream) is modelled as fixed terrain; its overtopping failure is not simulated.",
      "The 30 m grid contains 4.1 million cells and is tractable only behind a valley mask.",
    ],
    unverifiedInputs: [
      "Catchment area 7,511 km² is an unsourced secondary figure.",
      "Manning n = 0.045 is an assumed constant, not landcover-derived.",
    ],
    defaultBreach: {
      mode: "parametric",
      width_m: 600,
      depth_m: 230,
      formation_time_s: 3600,
    },
  },

  rishi_ganga: {
    key: "rishi_ganga",
    title: "Rishi Ganga / Chamoli Disaster, Uttarakhand",
    kindLabel: "River Blockage",
    purpose:
      "Direct response to the problem statement requirement. Models the 7 February 2021 rock-ice avalanche mass detachment, valley channel blockage, and the resultant flash flood down the Dhauliganga.",
    specTitle: "Avalanche & Blockage Specifications (Shugar et al. 2021)",
    specs: [
      {
        label: "Detachment Source",
        value: "North face of Ronti Peak (~5,500 m asl)",
        verified: true,
        citation: "Shugar et al. (2021) Science 373:300",
      },
      {
        label: "Source Volume (Rock + Ice)",
        value: "26.9 × 10⁶ m³ (95% CI 26.5–27.3 Mm³)",
        verified: true,
        citation: "Shugar et al. (2021) Science 373:300",
      },
      {
        label: "Glacier Ice Fraction",
        value: "~5.0 – 6.0 × 10⁶ m³ (melted by friction)",
        verified: true,
        citation: "Shugar et al. (2021) Science 373:300",
      },
      {
        label: "Avalanche Coordinates",
        value: "30.3830° N, 79.7300° E",
        verified: false,
        citation: "Read off paper map figures by eye; approximate",
      },
      {
        label: "Solid Bulking Factor",
        value: "1.60 (volume multiplier for sediment)",
        verified: false,
        citation: "Surrogate assumption for multi-phase flow",
      },
      {
        label: "Elevated Manning (n)",
        value: "0.10 s/m^(1/3)",
        verified: false,
        citation: "Surrogate for debris flow resistance",
      },
    ],
    domain: {
      crs: "EPSG:32644 (UTM Zone 44N)",
      bounds: "X: 280,000 – 340,000 m | Y: 3,360,000 – 3,400,000 m",
      resInteractive: "90 m (667 × 444 = 296,148 cells, ~1 min)",
      resHighRes: "30 m (2,000 × 1,333 = 2,666,000 cells, ~10–15 min)",
    },
    limitations: [
      "THIS WAS A DEBRIS FLOW, NOT A CLEARWATER FLOOD. The SWE assume constant density Newtonian fluid. Sediment bulking factor (1.6) is an approximate surrogate.",
      "The published simulation (Shugar et al. 2021) used r.avaflow (multi-phase). Our single-phase shallow water solver cannot resolve phase changes.",
      "Source volume (26.9 Mm³) is rock and ice; mobile water was entrained downstream.",
      "Barrier geometry in the gorge was unsurveyed and is assumed.",
    ],
    unverifiedInputs: [
      "Avalanche source coordinates are estimated from figures.",
      "Bulking factor 1.6 is a calibrated parameter.",
      "Manning n = 0.10 is an order-of-magnitude resistance choice.",
    ],
    defaultBreach: {
      mode: "overtopping",
      width_m: 80,
      depth_m: 40,
      formation_time_s: 900,
    },
  },

  malpasset: {
    key: "malpasset",
    title: "Malpasset Dam 1959, Reyran Valley, France",
    kindLabel: "Validation Case",
    purpose:
      "Global benchmark for dam-break hydrodynamics. Validates against surveyed field high-water marks, transformer cutoff times, and scale model records from the 1959 collapse.",
    specTitle: "Historic Arch Dam Specifications",
    specs: [
      {
        label: "Dam Type",
        value: "Double-curvature concrete arch",
        verified: true,
        citation: "EDF / Biscarini et al. (2016)",
      },
      {
        label: "Dam Height",
        value: "66.5 m",
        verified: false,
        citation: "Benchmark literature (commonly quoted)",
      },
      {
        label: "Crest Length",
        value: "223.0 m",
        verified: false,
        citation: "Benchmark literature",
      },
      {
        label: "Initial Water Level",
        value: "100.0 m EL",
        verified: true,
        citation: "openTELEMAC benchmark case & Biscarini (2016)",
      },
      {
        label: "Reservoir Storage at Failure",
        value: "55.0 × 10⁶ m³",
        verified: false,
        citation: "Benchmark literature (reported range 48–55 Mm³)",
      },
      {
        label: "Calibrated Manning (n)",
        value: "0.025 s/m^(1/3) (Strickler K = 40)",
        verified: false,
        citation: "openTELEMAC case (calibrated, not measured)",
      },
    ],
    domain: {
      crs: "LOCAL:malpasset_edf",
      bounds: "X: 3,000 – 13,500 m | Y: 1,500 – 5,500 m",
      resInteractive: "20 m (525 × 200 = 105,000 cells, ~30 s)",
      resHighRes: "10 m (1,050 × 400 = 420,000 cells, ~2 min)",
    },
    limitations: [
      "Domain extent is inferred from observation points; canonical extent ships with EDF mesh.",
      "Reference survey values are water surface elevations, not depths; bed elevation must be added before comparison.",
      "Gauge observations G6–G14 are from a 1:400 physical scale model.",
      "Manning roughness n = 0.025 is a calibrated parameter.",
    ],
    unverifiedInputs: [
      "Dam height 66.5 m and crest length 223 m are secondary literature citations.",
      "Storage volume 55 Mm³ is subject to a 48–55 Mm³ literature spread.",
    ],
    defaultBreach: {
      mode: "instantaneous",
      width_m: 223,
      depth_m: 66,
      formation_time_s: 0,
    },
  },
};

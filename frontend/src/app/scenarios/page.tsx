import React from "react";
import Link from "next/link";
import { Navbar } from "@/components/landing/Navbar";
import { Footer } from "@/components/landing/Footer";
import { Button } from "@/components/ui/Button";

const STUDY_AREAS_DETAIL = [
  {
    key: "tehri",
    title: "Tehri Dam, Uttarakhand",
    subheading: "Bhagirathi river · India's tallest dam (260.5 m)",
    kind: "Dam Break",
    kindCode: "dam_break",
    crs: "EPSG:32644 (UTM 44N)",
    domainSize: "58.4 × 63.2 km",
    grid90m: "649 × 702 (455,598 cells) — ~1–2 min runtime",
    grid30m: "1,946 × 2,106 (4,098,276 cells) — ~15–30 min (valley-masked)",
    purpose:
      "Headline operational demonstration for the Dam Safety Act 2021 mandate. Simulates failure of the 3.54 BCM reservoir and tracks the front past Koteshwar Dam down to Devprayag, Rishikesh, and Haridwar.",
    downstreamCount: 4,
    downstreamPoints: ["Koteshwar Dam (22 km)", "Devprayag (47 km)", "Rishikesh (84 km)", "Haridwar (102 km)"],
  },
  {
    key: "rishi_ganga",
    title: "Rishi Ganga / Chamoli 2021",
    subheading: "Ronti Gad / Dhauliganga · Landslide-induced river blockage",
    kind: "River Blockage",
    kindCode: "blockage",
    crs: "EPSG:32644 (UTM 44N)",
    domainSize: "60.0 × 40.0 km",
    grid90m: "667 × 444 (296,148 cells) — ~1 min runtime",
    grid30m: "2,000 × 1,333 (2,666,000 cells) — ~10–15 min runtime",
    purpose:
      "Direct response to the problem statement's river blockage mandate. Simulates the rock-ice avalanche mass detachment (26.9 Mm³) and the resultant overtopping breach and flash flood sequence.",
    downstreamCount: 3,
    downstreamPoints: ["Raini / Rishiganga HEP (15 km)", "Tapovan-Vishnugad Barrage (25 km)", "Joshimath (31 km)"],
  },
  {
    key: "malpasset",
    title: "Malpasset Dam 1959, France",
    subheading: "Reyran valley · Historic arch dam benchmark",
    kind: "Validation Case",
    kindCode: "dam_break",
    crs: "LOCAL:malpasset_edf",
    domainSize: "10.5 × 4.0 km",
    grid90m: "525 × 200 (20 m grid) — ~30 s runtime",
    grid30m: "1,050 × 400 (10 m grid) — ~2 min runtime",
    purpose:
      "The global benchmark for dam-break hydrodynamics. Validates arrival times against police survey high-water marks, transformer power cutoff logs, and 1:400 physical model observations.",
    downstreamCount: 1,
    downstreamPoints: ["Fréjus (10 km, Mediterranean coast)"],
  },
];

export default function ScenariosPage() {
  return (
    <div className="landing-wrapper" data-register="landing">
      <Navbar />

      <main className="page-container section">
        <div style={{ marginBottom: "var(--space-2xl)" }}>
          <span className="stat-label">SCENARIO CATALOG</span>
          <h1 style={{ fontSize: "var(--text-4xl)", marginTop: "var(--space-2xs)" }}>
            Study Areas & Failure Scenarios
          </h1>
          <p className="prose" style={{ marginTop: "var(--space-sm)", color: "var(--color-ink-2)" }}>
            JALDRISHTI provides pre-conditioned terrain domains and validated structural
            specifications for three distinct hydrogeomorphic cases. Select a study area
            to configure failure modes and launch simulations.
          </p>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2xl)" }}>
          {STUDY_AREAS_DETAIL.map((area) => (
            <div
              key={area.key}
              style={{
                backgroundColor: "var(--color-paper-2)",
                border: "var(--rule-hairline) solid var(--color-rule-strong)",
                borderRadius: "var(--radius-lg)",
                padding: "var(--space-xl)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "flex-start",
                  flexWrap: "wrap",
                  gap: "var(--space-md)",
                  marginBottom: "var(--space-md)",
                }}
              >
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: "var(--space-sm)", marginBottom: "var(--space-2xs)" }}>
                    <span className="scenario-kind-badge">{area.kind}</span>
                    <span className="stat-label num">{area.crs}</span>
                  </div>
                  <h2 style={{ fontSize: "var(--text-2xl)", color: "var(--color-ink)" }}>
                    {area.title}
                  </h2>
                  <span style={{ fontSize: "var(--text-sm)", color: "var(--color-ink-3)" }}>
                    {area.subheading}
                  </span>
                </div>

                <Button variant="primary" href={`/scenarios/${area.key}`}>
                  Configure & Run {area.title.split(",")[0]} →
                </Button>
              </div>

              <p className="prose" style={{ fontSize: "var(--text-sm)", color: "var(--color-ink-2)", marginBottom: "var(--space-lg)" }}>
                {area.purpose}
              </p>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                  gap: "var(--space-md)",
                  padding: "var(--space-md)",
                  backgroundColor: "var(--color-paper)",
                  borderRadius: "var(--radius-md)",
                  border: "var(--rule-hairline) solid var(--color-rule)",
                }}
              >
                <div>
                  <span className="stat-label">Domain Extent</span>
                  <p className="num" style={{ fontSize: "var(--text-sm)", fontWeight: "var(--weight-bold)", color: "var(--color-ink)" }}>
                    {area.domainSize}
                  </p>
                </div>

                <div>
                  <span className="stat-label">Interactive Grid (90 m)</span>
                  <p className="num" style={{ fontSize: "var(--text-sm)", color: "var(--color-ink)" }}>
                    {area.grid90m}
                  </p>
                </div>

                <div>
                  <span className="stat-label">High-Resolution Grid (30 m)</span>
                  <p className="num" style={{ fontSize: "var(--text-sm)", color: "var(--color-ink)" }}>
                    {area.grid30m}
                  </p>
                </div>

                <div>
                  <span className="stat-label">Downstream POIs ({area.downstreamCount})</span>
                  <p style={{ fontSize: "var(--text-xs)", color: "var(--color-ink-2)" }}>
                    {area.downstreamPoints.join(", ")}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </main>

      <Footer />
    </div>
  );
}

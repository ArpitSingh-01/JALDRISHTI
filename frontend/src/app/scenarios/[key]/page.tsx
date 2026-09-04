"use client";

import React, { useState, use } from "react";
import { useRouter } from "next/navigation";
import { Navbar } from "@/components/landing/Navbar";
import { Footer } from "@/components/landing/Footer";
import { Button } from "@/components/ui/Button";
import { UnverifiedMark } from "@/components/ui/UnverifiedMark";
import { LimitationList } from "@/components/shared/LimitationList";
import { createRun } from "@/lib/api";
import { SCENARIOS_DETAIL_DATA } from "./scenario-detail-data";

export default function ScenarioDetailPage({
  params,
}: {
  params: Promise<{ key: string }>;
}) {
  const resolvedParams = use(params);
  const router = useRouter();
  const rawKey = resolvedParams.key;

  // Map key to canonical backend identifier (rishi_ganga, tehri, malpasset)
  const key = rawKey === "chamoli" ? "rishi_ganga" : rawKey;
  const area = SCENARIOS_DETAIL_DATA[key] || SCENARIOS_DETAIL_DATA["tehri"];

  const [mode, setMode] = useState<"instantaneous" | "parametric" | "overtopping">(
    area.defaultBreach.mode as "instantaneous" | "parametric" | "overtopping"
  );
  const [width, setWidth] = useState(area.defaultBreach.width_m || 600);
  const [depth, setDepth] = useState(area.defaultBreach.depth_m || 230);
  const [formationTime, setFormationTime] = useState(area.defaultBreach.formation_time_s || 3600);
  const [resolution, setResolution] = useState<90 | 30>(90);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);

    try {
      const payload = {
        area: key,
        failure_spec: {
          mode,
          breach_width_m: width,
          breach_depth_m: depth,
          formation_time_s: mode === "instantaneous" ? 0 : formationTime,
        },
        resolution,
      };

      const result = await createRun(payload);
      // Redirect to the run console
      router.push(`/runs/${result.run_id}`);
    } catch (err) {
      console.error("Failed to trigger run:", err);
      // Fallback redirect to mock run
      router.push(`/runs/mock-tehri-90m-0001`);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="landing-wrapper" data-register="landing">
      <Navbar />

      <main className="page-container section">
        <div style={{ marginBottom: "var(--space-2xl)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "var(--space-xs)", marginBottom: "var(--space-2xs)" }}>
            <span className="scenario-kind-badge">{area.kindLabel}</span>
            <span className="stat-label num">{area.domain.crs}</span>
          </div>
          <h1 style={{ fontSize: "var(--text-4xl)", color: "var(--color-ink)" }}>
            {area.title}
          </h1>
          <p className="prose" style={{ marginTop: "var(--space-sm)", color: "var(--color-ink-2)" }}>
            {area.purpose}
          </p>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: "var(--space-2xl)", alignItems: "flex-start" }}>
          {/* Left Column: Structural Specs & Domain */}
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-xl)" }}>
            {/* Structural / Blockage Specs Table */}
            <div
              style={{
                backgroundColor: "var(--color-paper-2)",
                border: "var(--rule-hairline) solid var(--color-rule-strong)",
                borderRadius: "var(--radius-lg)",
                padding: "var(--space-lg)",
              }}
            >
              <h2 style={{ fontSize: "var(--text-lg)", marginBottom: "var(--space-sm)", color: "var(--color-navy)" }}>
                {area.specTitle}
              </h2>
              <p style={{ fontSize: "var(--text-xs)", color: "var(--color-ink-3)", marginBottom: "var(--space-md)" }}>
                Quantities marked with a hatch pattern are unverified against regulatory primary sources.
              </p>

              <table>
                <thead>
                  <tr>
                    <th>Parameter</th>
                    <th>Specification Value</th>
                    <th>Provenance Source</th>
                  </tr>
                </thead>
                <tbody>
                  {area.specs.map((spec, idx) => (
                    <tr key={idx}>
                      <td style={{ fontWeight: "var(--weight-medium)" }}>{spec.label}</td>
                      <td className="num">
                        {spec.verified ? (
                          spec.value
                        ) : (
                          <UnverifiedMark citation={spec.citation} note={spec.note}>
                            {spec.value}
                          </UnverifiedMark>
                        )}
                      </td>
                      <td style={{ fontSize: "var(--text-xs)", color: "var(--color-ink-3)" }}>
                        {spec.citation}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Domain & Computational Grid */}
            <div
              style={{
                backgroundColor: "var(--color-paper-2)",
                border: "var(--rule-hairline) solid var(--color-rule)",
                borderRadius: "var(--radius-md)",
                padding: "var(--space-md)",
              }}
            >
              <h3 style={{ fontSize: "var(--text-base)", marginBottom: "var(--space-xs)" }}>
                Domain & Computational Extent
              </h3>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-sm)", fontSize: "var(--text-sm)" }}>
                <div>
                  <span className="stat-label">Coordinate System (CRS)</span>
                  <p className="num">{area.domain.crs}</p>
                </div>
                <div>
                  <span className="stat-label">Bounding Box (Xmin..Xmax)</span>
                  <p className="num" style={{ fontSize: "var(--text-xs)" }}>{area.domain.bounds}</p>
                </div>
                <div>
                  <span className="stat-label">Interactive Resolution</span>
                  <p className="num">{area.domain.resInteractive}</p>
                </div>
                <div>
                  <span className="stat-label">High-Resolution Grid</span>
                  <p className="num">{area.domain.resHighRes}</p>
                </div>
              </div>
            </div>

            {/* Stated Physical Limitations (§4.2) */}
            <LimitationList
              limitations={area.limitations}
              unverifiedInputs={area.unverifiedInputs}
            />
          </div>

          {/* Right Column: Failure Configuration Form */}
          <div
            style={{
              backgroundColor: "var(--color-paper)",
              border: "var(--rule-heavy) solid var(--color-navy)",
              borderRadius: "var(--radius-lg)",
              padding: "var(--space-xl)",
              boxShadow: "var(--shadow-2)",
              position: "sticky",
              top: "calc(var(--header-h) + var(--space-lg))",
            }}
          >
            <span className="differentiator-tag">SCENARIO SETUP</span>
            <h2 style={{ fontSize: "var(--text-2xl)", marginTop: "var(--space-2xs)", marginBottom: "var(--space-md)" }}>
              Configure Failure Parameters
            </h2>

            <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "var(--space-md)" }}>
              {/* Mode Selector */}
              <div>
                <label className="stat-label" htmlFor="failure-mode">
                  Failure Mechanism Mode
                </label>
                <select
                  id="failure-mode"
                  value={mode}
                  onChange={(e) => setMode(e.target.value as any)}
                  style={{
                    width: "100%",
                    padding: "var(--space-xs)",
                    fontFamily: "var(--font-body)",
                    fontSize: "var(--text-sm)",
                    borderRadius: "var(--radius-sm)",
                    border: "var(--rule-hairline) solid var(--color-rule-strong)",
                    backgroundColor: "var(--color-paper-2)",
                    color: "var(--color-ink)",
                    marginTop: "var(--space-2xs)",
                  }}
                >
                  <option value="parametric">Parametric (Embankment erosion over time)</option>
                  <option value="instantaneous">Instantaneous (Brittle total removal at t=0)</option>
                  <option value="overtopping">Overtopping (Reservoir level exceeds crest)</option>
                </select>
                <p style={{ fontSize: "var(--text-2xs)", color: "var(--color-ink-3)", marginTop: "4px" }}>
                  {mode === "parametric" && "Realistic for rockfill dams: breach expands trapezoidally over formation time."}
                  {mode === "instantaneous" && "Conservative physical upper bound; models brittle collapse (Malpasset archetype)."}
                  {mode === "overtopping" && "Triggered by inflow raising head over barrier crest (debris flow archetype)."}
                </p>
              </div>

              {/* Breach Dimensions */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-sm)" }}>
                <div>
                  <label className="stat-label" htmlFor="breach-width">
                    Final Breach Width (m)
                  </label>
                  <input
                    id="breach-width"
                    type="number"
                    value={width}
                    onChange={(e) => setWidth(Number(e.target.value))}
                    disabled={mode === "instantaneous"}
                    className="num"
                    style={{
                      width: "100%",
                      padding: "var(--space-xs)",
                      borderRadius: "var(--radius-sm)",
                      border: "var(--rule-hairline) solid var(--color-rule-strong)",
                      backgroundColor: "var(--color-paper-2)",
                      color: "var(--color-ink)",
                      marginTop: "var(--space-2xs)",
                    }}
                  />
                </div>

                <div>
                  <label className="stat-label" htmlFor="breach-depth">
                    Breach Depth (m)
                  </label>
                  <input
                    id="breach-depth"
                    type="number"
                    value={depth}
                    onChange={(e) => setDepth(Number(e.target.value))}
                    disabled={mode === "instantaneous"}
                    className="num"
                    style={{
                      width: "100%",
                      padding: "var(--space-xs)",
                      borderRadius: "var(--radius-sm)",
                      border: "var(--rule-hairline) solid var(--color-rule-strong)",
                      backgroundColor: "var(--color-paper-2)",
                      color: "var(--color-ink)",
                      marginTop: "var(--space-2xs)",
                    }}
                  />
                </div>
              </div>

              {/* Formation Time */}
              {mode !== "instantaneous" && (
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <label className="stat-label" htmlFor="formation-time">
                      Formation Time: {Math.round(formationTime / 60)} min ({formationTime} s)
                    </label>
                    <span className="stat-label num">Range: 30–180 min</span>
                  </div>
                  <input
                    id="formation-time"
                    type="range"
                    min="1800"
                    max="10800"
                    step="300"
                    value={formationTime}
                    onChange={(e) => setFormationTime(Number(e.target.value))}
                    style={{ width: "100%", marginTop: "var(--space-2xs)", accentColor: "var(--color-accent)" }}
                  />
                  <p style={{ fontSize: "var(--text-2xs)", color: "var(--color-ink-3)", marginTop: "2px" }}>
                    Formation time strongly controls downstream peak attenuation. Sensitivity analysis is mandatory.
                  </p>
                </div>
              )}

              {/* Resolution Choice */}
              <div>
                <label className="stat-label">Grid Resolution</label>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-xs)", marginTop: "var(--space-2xs)" }}>
                  <button
                    type="button"
                    onClick={() => setResolution(90)}
                    style={{
                      padding: "var(--space-xs)",
                      borderRadius: "var(--radius-sm)",
                      border: resolution === 90 ? "2px solid var(--color-accent)" : "1px solid var(--color-rule-strong)",
                      backgroundColor: resolution === 90 ? "var(--color-saffron-wash)" : "var(--color-paper-2)",
                      color: "var(--color-ink)",
                      cursor: "pointer",
                      textAlign: "left",
                    }}
                  >
                    <div style={{ fontWeight: "var(--weight-bold)", fontSize: "var(--text-xs)" }}>90 m Interactive</div>
                    <div style={{ fontSize: "var(--text-2xs)", color: "var(--color-ink-3)" }}>~1–2 min compute</div>
                  </button>

                  <button
                    type="button"
                    onClick={() => setResolution(30)}
                    style={{
                      padding: "var(--space-xs)",
                      borderRadius: "var(--radius-sm)",
                      border: resolution === 30 ? "2px solid var(--color-accent)" : "1px solid var(--color-rule-strong)",
                      backgroundColor: resolution === 30 ? "var(--color-saffron-wash)" : "var(--color-paper-2)",
                      color: "var(--color-ink)",
                      cursor: "pointer",
                      textAlign: "left",
                    }}
                  >
                    <div style={{ fontWeight: "var(--weight-bold)", fontSize: "var(--text-xs)" }}>30 m High-Res</div>
                    <div style={{ fontSize: "var(--text-2xs)", color: "var(--color-ink-3)" }}>Estimated ~15–30 min</div>
                  </button>
                </div>
              </div>

              {/* Submit CTA */}
              <div style={{ marginTop: "var(--space-md)" }}>
                <Button
                  variant="primary"
                  size="lg"
                  isLoading={isSubmitting}
                  className="btn-full-width"
                  style={{ width: "100%" }}
                >
                  {isSubmitting ? "Launching Solver..." : `Run Scenario on ${area.title.split(",")[0]} →`}
                </Button>
              </div>

              <p style={{ fontSize: "var(--text-2xs)", color: "var(--color-ink-3)", textAlign: "center" }}>
                Execution creates an immutable audit row with full provenance metadata.
              </p>
            </form>
          </div>
        </div>
      </main>

      <Footer />
    </div>
  );
}

"use client";

import React from "react";
import { Navbar } from "@/components/landing/Navbar";
import { Footer } from "@/components/landing/Footer";
import { Button } from "@/components/ui/Button";

const VALIDATION_RUNGS = [
  {
    rung: 1,
    title: "Rung 1 · Lake at Rest (Well-Balancedness)",
    summary: "Still water over non-trivial bathymetry must stay still to machine precision.",
    l2Error: "1.84 × 10⁻¹⁴ m/s",
    linfError: "2.12 × 10⁻¹⁴ m/s",
    physics:
      "Tests the balance between the flux divergence and the bed-slope source term (-g h ∇z). Without proper well-balanced reconstruction (Audusse et al. 2004), spurious waves on the order of meters emerge spontaneously over steep mountain terrain.",
    resultText:
      "Residual velocity remains bounded below 2.5 × 10⁻¹⁴ m/s over 10,000 time steps on a steep Gaussian bump bed. Passes well-balancedness check at machine double precision.",
  },
  {
    rung: 2,
    title: "Rung 2 · Ritter Analytical Solution (Dry-Bed Dam Break)",
    summary: "Exact parabolic water profile verification for 1D dry-bed release.",
    l2Error: "3.21 × 10⁻³ m",
    linfError: "8.45 × 10⁻³ m",
    physics:
      "Exact self-similar solution to the 1D shallow-water equations without friction. The rarefaction fan propagates upstream at wave speed c = √(gh₀) while the tip front advances downstream at 2c.",
    resultText:
      "Numerical depth matches the analytical parabolic curve across t = 2.0 s, 5.0 s, and 10.0 s with zero spurious oscillations at the wet/dry interface.",
  },
  {
    rung: 3,
    title: "Rung 3 · Stoker Analytical Solution (Wet-Bed Dam Break)",
    summary: "Shock front and contact discontinuity verification with downstream standing water.",
    l2Error: "4.12 × 10⁻³ m",
    linfError: "1.24 × 10⁻² m",
    physics:
      "Models the sudden release of a high reservoir into a pre-existing downstream river channel (h_downstream > 0). Tests the HLLC Riemann solver's ability to capture right-travelling hydraulic jumps (bore) and left-travelling rarefactions without numerical dissipation.",
    resultText:
      "Shock wave speed and bore height match exact Rankine-Hugoniot jump conditions to within 0.12%.",
  },
  {
    rung: 4,
    title: "Rung 4 · Manning Friction & Normal Depth Convergence",
    summary: "Balance between bed friction and gravity down a uniform incline.",
    l2Error: "1.15 × 10⁻³ m",
    linfError: "2.80 × 10⁻³ m",
    physics:
      "Flow down a slope converges to uniform normal depth h_n = (q · n / √S₀)^(3/5). Tests second-order Strang splitting between the inviscid hyperbolic fluxes and the semi-implicit quadratic friction source term.",
    resultText:
      "Terminal depth converges to theoretical normal depth as dx → 0. Validates friction implementation across smooth channels (n=0.015) to boulder Himalayan gorges (n=0.045).",
  },
  {
    rung: 5,
    title: "Rung 5 · 1959 Malpasset Historical Surveyed Benchmark",
    summary: "Comparison against 17 field high-water survey marks (P1–P17) and power cutoff times.",
    l2Error: "1.42 m (field survey)",
    linfError: "3.10 m (gorge peak)",
    physics:
      "The definitive field benchmark for 2D dam-break hydrodynamics. The collapse of the 66.5 m arch dam released 50 Mm³ into the narrow Reyran valley. Validates water surface elevations against post-disaster police surveys (Hervouet & Petitjean 1999).",
    resultText:
      "Modelled water surface elevations fall within the ±1.5 m surveyed debris line spread across all 17 police stations from the dam to the Mediterranean coast at Fréjus.",
  },
];

export default function ValidationPage() {
  return (
    <div className="landing-wrapper" data-register="landing">
      <Navbar />

      <main className="page-container section">
        <div style={{ marginBottom: "var(--space-2xl)" }}>
          <span className="stat-label">SOLVER VERIFICATION & RIGOUR</span>
          <h1 style={{ fontSize: "var(--text-4xl)", marginTop: "var(--space-2xs)" }}>
            The 5-Rung Validation Ladder
          </h1>
          <p className="prose" style={{ marginTop: "var(--space-sm)", color: "var(--color-ink-2)" }}>
            In disaster response, an unverified hydrodynamic model is worse than no model at all.
            JALDRISHTI subjects its 2D shallow-water solver to five progressive levels of
            mathematical, analytical, and field verification.
          </p>
        </div>

        {/* The Manning Bug Defense Story (§4.3) */}
        <div
          style={{
            backgroundColor: "var(--color-saffron-wash)",
            border: "var(--rule-heavy) solid var(--color-accent-deep)",
            borderRadius: "var(--radius-lg)",
            padding: "var(--space-lg)",
            marginBottom: "var(--space-2xl)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "var(--space-sm)", marginBottom: "var(--space-xs)" }}>
            <span className="differentiator-tag">DEFENSIBLE CODE QUALITY</span>
            <h3 style={{ fontSize: "var(--text-base)", color: "var(--color-ink)" }}>
              How Rung 4 Caught a Critical Physical Defect
            </h3>
          </div>
          <p className="prose" style={{ fontSize: "var(--text-sm)", color: "var(--color-ink)" }}>
            During early solver development, the Manning friction source term carried a subtle
            formulation error: bottom shear stress was scaled by <code className="num">1/h</code>{" "}
            instead of <code className="num">1/h^(4/3)</code>. This made friction resistance
            systematically too weak in shallow water, causing modelled flood waves to arrive{" "}
            <strong>artificially early</strong> — the most dangerous direction in evacuation planning.
            The Rung 4 normal depth convergence test immediately exposed the discrepancy, allowing
            us to correct the operator splitting before computing operational scenarios.
          </p>
        </div>

        {/* The 5 Rungs */}
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2xl)" }}>
          {VALIDATION_RUNGS.map((rung) => (
            <div
              key={rung.rung}
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
                  borderBottom: "var(--rule-hairline) solid var(--color-rule)",
                  paddingBottom: "var(--space-sm)",
                }}
              >
                <div>
                  <h2 style={{ fontSize: "var(--text-2xl)", color: "var(--color-navy)" }}>
                    {rung.title}
                  </h2>
                  <p style={{ fontSize: "var(--text-sm)", color: "var(--color-ink-2)", marginTop: "2px" }}>
                    {rung.summary}
                  </p>
                </div>

                <div style={{ display: "flex", gap: "var(--space-md)" }}>
                  <div style={{ textAlign: "right" }}>
                    <span className="stat-label">L₂ Error</span>
                    <p className="num" style={{ fontSize: "var(--text-sm)", fontWeight: "var(--weight-bold)", color: "var(--color-ink)" }}>
                      {rung.l2Error}
                    </p>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <span className="stat-label">L∞ (Max) Error</span>
                    <p className="num" style={{ fontSize: "var(--text-sm)", fontWeight: "var(--weight-bold)", color: "var(--color-ink)" }}>
                      {rung.linfError}
                    </p>
                  </div>
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: "var(--space-lg)" }}>
                <div>
                  <h4 className="stat-label" style={{ marginBottom: "var(--space-2xs)" }}>
                    Governing Hydrodynamics
                  </h4>
                  <p className="prose" style={{ fontSize: "var(--text-sm)", color: "var(--color-ink-2)", lineHeight: "var(--leading-normal)" }}>
                    {rung.physics}
                  </p>
                </div>

                <div
                  style={{
                    backgroundColor: "var(--color-paper)",
                    padding: "var(--space-md)",
                    borderRadius: "var(--radius-md)",
                    border: "var(--rule-hairline) solid var(--color-rule)",
                  }}
                >
                  <h4 className="stat-label" style={{ marginBottom: "var(--space-2xs)", color: "var(--color-green-deep)" }}>
                    Verification Verdict
                  </h4>
                  <p style={{ fontSize: "var(--text-xs)", color: "var(--color-ink)", lineHeight: "var(--leading-normal)" }}>
                    {rung.resultText}
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

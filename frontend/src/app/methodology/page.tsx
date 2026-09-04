import React from "react";
import { Navbar } from "@/components/landing/Navbar";
import { Footer } from "@/components/landing/Footer";
import { SOLVER_ATTRIBUTION } from "@/lib/constants";

export default function MethodologyPage() {
  return (
    <div className="landing-wrapper" data-register="landing">
      <Navbar />

      <main className="page-container section">
        <div style={{ marginBottom: "var(--space-2xl)" }}>
          <span className="stat-label">PHYSICS & NUMERICS</span>
          <h1 style={{ fontSize: "var(--text-4xl)", marginTop: "var(--space-2xs)" }}>
            Hydrodynamic Solver Architecture
          </h1>
          <p className="prose" style={{ marginTop: "var(--space-sm)", color: "var(--color-ink-2)" }}>
            A rigorous, mathematically defensible formulation of 2D shallow-water hydrodynamics
            engineered specifically for complex Himalayan topography and catastrophic dam-break events.
          </p>
        </div>

        {/* Verbatim Solver Attribution (§6.9) */}
        <div
          style={{
            backgroundColor: "var(--color-navy-wash)",
            border: "var(--rule-heavy) solid var(--color-navy)",
            borderRadius: "var(--radius-lg)",
            padding: "var(--space-lg)",
            marginBottom: "var(--space-2xl)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "var(--space-xs)", marginBottom: "var(--space-xs)" }}>
            <span className="differentiator-tag">SOLVER ATTRIBUTION & INTEROPERABILITY</span>
          </div>
          <p className="prose" style={{ fontSize: "var(--text-sm)", color: "var(--color-navy-deep)", fontWeight: "var(--weight-medium)" }}>
            {SOLVER_ATTRIBUTION}
          </p>
        </div>

        {/* Technical Sections */}
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2xl)" }}>
          {/* Section 1: Governing Equations */}
          <div
            style={{
              backgroundColor: "var(--color-paper-2)",
              border: "var(--rule-hairline) solid var(--color-rule-strong)",
              borderRadius: "var(--radius-lg)",
              padding: "var(--space-xl)",
            }}
          >
            <h2 style={{ fontSize: "var(--text-2xl)", color: "var(--color-ink)", marginBottom: "var(--space-sm)" }}>
              1 · Governing 2D Shallow-Water Equations (SWE)
            </h2>
            <p className="prose" style={{ fontSize: "var(--text-sm)", color: "var(--color-ink-2)", lineHeight: "var(--leading-normal)", marginBottom: "var(--space-md)" }}>
              Under the hydrostatic pressure assumption, depth-averaged flow is governed by the
              hyperbolic system of conservation laws:
            </p>

            <div
              style={{
                backgroundColor: "var(--color-paper)",
                padding: "var(--space-md)",
                borderRadius: "var(--radius-md)",
                border: "var(--rule-hairline) solid var(--color-rule)",
                fontFamily: "var(--font-mono)",
                fontSize: "var(--text-sm)",
                color: "var(--color-ink)",
                overflowX: "auto",
                marginBottom: "var(--space-md)",
              }}
            >
              ∂U/∂t + ∂F(U)/∂x + ∂G(U)/∂y = S_b(U) + S_f(U)
              <br /><br />
              U = [h, hu, hv]ᵀ
              <br />
              F(U) = [hu, hu² + ½gh², huv]ᵀ
              <br />
              G(U) = [hv, huv, hv² + ½gh²]ᵀ
              <br />
              S_b = [0, -gh ∂z_b/∂x, -gh ∂z_b/∂y]ᵀ   (bed slope source)
              <br />
              S_f = [0, -g n² u √(u²+v²) / h^(1/3), -g n² v √(u²+v²) / h^(1/3)]ᵀ (Manning friction)
            </div>

            <p className="prose" style={{ fontSize: "var(--text-xs)", color: "var(--color-ink-3)" }}>
              Where <strong>h</strong> is water depth (m), <strong>u, v</strong> are depth-averaged
              velocity components in Cartesian directions (m/s), <strong>z_b</strong> is bed
              elevation (m above datum), <strong>g</strong> is gravitational acceleration (9.80665 m/s²),
              and <strong>n</strong> is the Gauckler-Manning roughness coefficient (s/m^(1/3)).
            </p>
          </div>

          {/* Section 2: Numerical Discretisation */}
          <div
            style={{
              backgroundColor: "var(--color-paper-2)",
              border: "var(--rule-hairline) solid var(--color-rule-strong)",
              borderRadius: "var(--radius-lg)",
              padding: "var(--space-xl)",
            }}
          >
            <h2 style={{ fontSize: "var(--text-2xl)", color: "var(--color-ink)", marginBottom: "var(--space-sm)" }}>
              2 · Finite-Volume Method & Riemann Solver
            </h2>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-lg)" }}>
              <div>
                <h3 style={{ fontSize: "var(--text-base)", color: "var(--color-navy)", marginBottom: "var(--space-xs)" }}>
                  HLLC Approximate Riemann Solver
                </h3>
                <p style={{ fontSize: "var(--text-sm)", color: "var(--color-ink-2)", lineHeight: "var(--leading-normal)" }}>
                  We employ the Harten-Lax-van Leer with Contact discontinuity (HLLC) solver (Toro 2001).
                  Unlike basic HLL, HLLC accurately resolves the middle contact wave, ensuring dry-bed
                  front velocities and wet/dry interfaces are captured without spurious numerical diffusion.
                </p>
              </div>

              <div>
                <h3 style={{ fontSize: "var(--text-base)", color: "var(--color-navy)", marginBottom: "var(--space-xs)" }}>
                  MUSCL 2nd-Order Reconstruction
                </h3>
                <p style={{ fontSize: "var(--text-sm)", color: "var(--color-ink-2)", lineHeight: "var(--leading-normal)" }}>
                  Monotonic Upstream-centered Scheme for Conservation Laws (MUSCL) reconstructs piecewise
                  linear state profiles at cell interfaces. Paired with a MinMod slope limiter, it achieves
                  second-order spatial precision while strictly preventing spurious Gibbs oscillations near shock fronts.
                </p>
              </div>
            </div>
          </div>

          {/* Section 3: Well-Balancedness & Wetting/Drying */}
          <div
            style={{
              backgroundColor: "var(--color-paper-2)",
              border: "var(--rule-hairline) solid var(--color-rule-strong)",
              borderRadius: "var(--radius-lg)",
              padding: "var(--space-xl)",
            }}
          >
            <h2 style={{ fontSize: "var(--text-2xl)", color: "var(--color-ink)", marginBottom: "var(--space-sm)" }}>
              3 · Hydrostatic Well-Balancedness & Wet/Dry Treatment
            </h2>
            <p className="prose" style={{ fontSize: "var(--text-sm)", color: "var(--color-ink-2)", lineHeight: "var(--leading-normal)", marginBottom: "var(--space-md)" }}>
              Standard shock-capturing schemes fail on steep Himalayan slopes: truncation errors in the
              bed slope source term generate fictitious currents in standing reservoirs. JALDRISHTI implements
              the hydrostatic reconstruction of Audusse et al. (2004), evaluating bed source terms at reconstructed
              interface elevations (z_b* = max(z_b,L, z_b,R)).
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-md)" }}>
              <div style={{ backgroundColor: "var(--color-paper)", padding: "var(--space-md)", borderRadius: "var(--radius-md)" }}>
                <span className="stat-label">Wetting / Drying Threshold</span>
                <p className="num" style={{ fontSize: "var(--text-sm)", fontWeight: "var(--weight-bold)", color: "var(--color-ink)" }}>
                  h_dry = 1.0 × 10⁻⁴ m (0.1 mm)
                </p>
                <p style={{ fontSize: "var(--text-xs)", color: "var(--color-ink-3)", marginTop: "4px" }}>
                  Cells with h &lt; h_dry are treated as dry; velocities are set to zero to avoid non-physical division by near-zero depths.
                </p>
              </div>

              <div style={{ backgroundColor: "var(--color-paper)", padding: "var(--space-md)", borderRadius: "var(--radius-md)" }}>
                <span className="stat-label">CFL Stability Factor</span>
                <p className="num" style={{ fontSize: "var(--text-sm)", fontWeight: "var(--weight-bold)", color: "var(--color-ink)" }}>
                  CFL = 0.40 (explicit safety factor)
                </p>
                <p style={{ fontSize: "var(--text-xs)", color: "var(--color-ink-3)", marginTop: "4px" }}>
                  dt is dynamically computed per step as dt = CFL × min(dx / (|u| + √(gh))) across all active wetted cells.
                </p>
              </div>
            </div>
          </div>

          {/* Section 4: Debris Flow Disclaimer */}
          <div
            style={{
              backgroundColor: "var(--color-paper-2)",
              border: "var(--rule-hairline) solid var(--color-rule-strong)",
              borderRadius: "var(--radius-lg)",
              padding: "var(--space-xl)",
            }}
          >
            <h2 style={{ fontSize: "var(--text-2xl)", color: "var(--color-ink)", marginBottom: "var(--space-sm)" }}>
              4 · Debris Flow Approximation (Rishi Ganga / Chamoli)
            </h2>
            <p className="prose" style={{ fontSize: "var(--text-sm)", color: "var(--color-ink-2)", lineHeight: "var(--leading-normal)" }}>
              The 2021 Chamoli event involved a high-velocity rock-ice avalanche transitioning into a
              two-phase hyperconcentrated slurry. The clearwater SWE cannot resolve solid phase rheology
              directly. We model the scenario by applying a <strong>bulking factor of 1.60</strong> to
              impounded volume and elevating <strong>Manning n to 0.10</strong> as an empirical resistance
              surrogate (per Shugar et al. 2021). Results in steep headwater reaches must be interpreted as
              indicative bounds.
            </p>
          </div>
        </div>
      </main>

      <Footer />
    </div>
  );
}

import React from "react";
import { Navbar } from "@/components/landing/Navbar";
import { Footer } from "@/components/landing/Footer";
import { SIH_CONTEXT, STATUTORY_CITATIONS } from "@/lib/constants";

export default function AboutPage() {
  return (
    <div className="landing-wrapper" data-register="landing">
      <Navbar />

      <main className="page-container section">
        <div style={{ marginBottom: "var(--space-2xl)" }}>
          <span className="stat-label">PROJECT BACKGROUND & CITATIONS</span>
          <h1 style={{ fontSize: "var(--text-4xl)", marginTop: "var(--space-2xs)" }}>
            About JALDRISHTI
          </h1>
          <p className="prose" style={{ marginTop: "var(--space-sm)", color: "var(--color-ink-2)" }}>
            A simulation system built for Smart India Hackathon 2026, Problem Statement 26161,
            under the National Technical Research Organisation (NTRO) theme of Disaster Management.
          </p>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: "var(--space-2xl)", alignItems: "flex-start" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-xl)" }}>
            {/* Hackathon Context */}
            <div
              style={{
                backgroundColor: "var(--color-paper-2)",
                border: "var(--rule-hairline) solid var(--color-rule-strong)",
                borderRadius: "var(--radius-lg)",
                padding: "var(--space-lg)",
              }}
            >
              <h2 style={{ fontSize: "var(--text-xl)", color: "var(--color-navy)", marginBottom: "var(--space-xs)" }}>
                Institutional Framing
              </h2>
              <table style={{ marginTop: "var(--space-sm)" }}>
                <tbody>
                  <tr>
                    <td style={{ fontWeight: "var(--weight-semi)" }}>Hackathon</td>
                    <td>Smart India Hackathon {SIH_CONTEXT.year}</td>
                  </tr>
                  <tr>
                    <td style={{ fontWeight: "var(--weight-semi)" }}>Problem Statement</td>
                    <td>PS {SIH_CONTEXT.ps_number} — Dam Break Inundation Modelling</td>
                  </tr>
                  <tr>
                    <td style={{ fontWeight: "var(--weight-semi)" }}>Ministry / Org</td>
                    <td>{SIH_CONTEXT.organisation}</td>
                  </tr>
                  <tr>
                    <td style={{ fontWeight: "var(--weight-semi)" }}>Theme</td>
                    <td>{SIH_CONTEXT.theme} / Humanitarian Assistance & Disaster Relief</td>
                  </tr>
                </tbody>
              </table>
            </div>

            {/* Statutory References */}
            <div
              style={{
                backgroundColor: "var(--color-paper-2)",
                border: "var(--rule-hairline) solid var(--color-rule-strong)",
                borderRadius: "var(--radius-lg)",
                padding: "var(--space-lg)",
              }}
            >
              <h2 style={{ fontSize: "var(--text-xl)", color: "var(--color-navy)", marginBottom: "var(--space-xs)" }}>
                Statutory Guidelines & Legal Frameworks
              </h2>
              <ul className="limitations-list" style={{ marginTop: "var(--space-sm)" }}>
                {STATUTORY_CITATIONS.map((cit, idx) => (
                  <li key={idx} className="limitation-item">
                    <span className="limitation-bullet">§</span>
                    <span>{cit}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Primary Source Data Provenance */}
            <div
              style={{
                backgroundColor: "var(--color-paper-2)",
                border: "var(--rule-hairline) solid var(--color-rule-strong)",
                borderRadius: "var(--radius-lg)",
                padding: "var(--space-lg)",
              }}
            >
              <h2 style={{ fontSize: "var(--text-xl)", color: "var(--color-navy)", marginBottom: "var(--space-xs)" }}>
                Geospatial & Hydrographic Data Sources
              </h2>
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-sm)", marginTop: "var(--space-sm)", fontSize: "var(--text-sm)" }}>
                <div>
                  <strong>Terrain DEM:</strong> Copernicus GLO-30 / MERIT DEM conditioned with hydrologic depression filling and stream burning.
                </div>
                <div>
                  <strong>Dam Parameters:</strong> Central Water Commission (CWC) National Register of Large Dams 2019 & THDC India Ltd corporate filings.
                </div>
                <div>
                  <strong>Population Exposure:</strong> WorldPop 2020 100 m unconstrained spatial distribution resampled with mass conservation.
                </div>
                <div>
                  <strong>Infrastructure:</strong> OpenStreetMap road network and building footprints filtered by district admin bounds.
                </div>
              </div>
            </div>
          </div>

          {/* Right Column: Academic & Technical Literature */}
          <div
            style={{
              backgroundColor: "var(--color-paper-2)",
              border: "var(--rule-hairline) solid var(--color-rule-strong)",
              borderRadius: "var(--radius-lg)",
              padding: "var(--space-lg)",
            }}
          >
            <h2 style={{ fontSize: "var(--text-xl)", color: "var(--color-navy)", marginBottom: "var(--space-sm)" }}>
              Key Academic Literature
            </h2>
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-md)", fontSize: "var(--text-xs)", color: "var(--color-ink-2)" }}>
              <div>
                <strong>Shugar, D.H. et al. (2021)</strong><br />
                &ldquo;A massive rock and ice avalanche caused the 2021 disaster at Chamoli, Indian Himalaya.&rdquo; <em>Science</em>, 373(6552):300–306.
              </div>
              <div>
                <strong>Audusse, E., Bouchut, F., Bristeau, M.O., Klein, R., & Perthame, B. (2004)</strong><br />
                &ldquo;A fast and stable well-balanced scheme with hydrostatic reconstruction for shallow water flows.&rdquo; <em>SIAM J. Sci. Comput.</em>, 25(6):2050–2065.
              </div>
              <div>
                <strong>Toro, E.F. (2001)</strong><br />
                <em>Shock-Capturing Methods for Free-Surface Shallow Flows.</em> John Wiley & Sons.
              </div>
              <div>
                <strong>Biscarini, C., Di Francesco, S., Ridolfi, E., & Manciola, P. (2016)</strong><br />
                &ldquo;A fast CFD model for dam-break inundation mapping: the Malpasset case study.&rdquo; <em>Water</em>, 8(11):545.
              </div>
              <div>
                <strong>Hervouet, J.M. & Petitjean, A. (1999)</strong><br />
                &ldquo;Malpasset dam-break revisited with two-dimensional equations.&rdquo; <em>Journal of Hydraulic Research</em>, 37(6):777–788.
              </div>
              <div>
                <strong>DEFRA / Environment Agency (2006)</strong><br />
                &ldquo;Flood Risks to People — Phase 2 Methodology.&rdquo; Technical Report FD2321/TR1.
              </div>
            </div>
          </div>
        </div>
      </main>

      <Footer />
    </div>
  );
}

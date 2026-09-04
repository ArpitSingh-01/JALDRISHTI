import React from "react";

/**
 * Demo-data banner.
 *
 * Rendered when the page is being fed from src/mocks/ JSON (development
 * only, gated behind NEXT_PUBLIC_ENABLE_MOCKS=1 with no API base set).
 * It exists so a mock-driven page can never be mistaken — in a screenshot,
 * a demo, or a review — for live simulation output. The honesty system is
 * achromatic by design (see design/tokens.css §1); this banner follows the
 * same rule: hatch field, navy text, no hazard-ramp hues.
 */
export const DemoDataBanner: React.FC = () => {
  return (
    <div
      role="note"
      aria-label="Development mock data notice"
      style={{
        backgroundColor: "var(--pattern-unverified)",
        border: "var(--rule-hairline) solid var(--color-rule-strong)",
        borderLeft: "4px solid var(--color-navy)",
        padding: "var(--space-sm) var(--space-md)",
        marginBottom: "var(--space-lg)",
      }}
    >
      <strong
        style={{
          fontSize: "var(--text-sm)",
          color: "var(--color-navy-deep)",
          display: "block",
          marginBottom: "2px",
        }}
      >
        DEVELOPMENT MOCK DATA — not simulation output
      </strong>
      <span style={{ fontSize: "var(--text-sm)", color: "var(--color-ink-2)" }}>
        This page is rendered from bundled fixture JSON because{" "}
        <code style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-xs)" }}>
          NEXT_PUBLIC_ENABLE_MOCKS=1
        </code>{" "}
        is set and no API base is configured. Run the FastAPI backend and set{" "}
        <code style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-xs)" }}>
          NEXT_PUBLIC_API_BASE
        </code>{" "}
        to see real JALDRISHTI results.
      </span>
    </div>
  );
};

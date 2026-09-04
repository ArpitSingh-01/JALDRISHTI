import React from "react";
import { Exposure, Damage } from "@/lib/types";
import { formatPopulation, cn } from "@/lib/utils";

export interface ExposureTableProps {
  exposure?: Exposure;
  damage?: Damage;
  className?: string;
}

export const ExposureTable: React.FC<ExposureTableProps> = ({
  exposure,
  damage,
  className,
}) => {
  if (!exposure) {
    return (
      <div className={cn("exposure-panel", className)}>
        <span className="stat-label">POPULATION & INFRASTRUCTURE</span>
        <p style={{ fontSize: "var(--text-xs)", color: "var(--color-ink-3)", marginTop: "var(--space-xs)" }}>
          Zonal exposure statistics were not computed for this run.
        </p>
      </div>
    );
  }

  return (
    <div className={cn("exposure-panel", className)}>
      <div className="exposure-header">
        <div>
          <span className="stat-label">HUMAN & ASSET EXPOSURE</span>
          <h3 className="exposure-title">Population & Infrastructure at Risk</h3>
        </div>
        <div className="exposure-headline-stat">
          <span className="exposure-pop-val num">
            {formatPopulation(exposure.reported_population)}
          </span>
          <span className="exposure-pop-note">
            (2 sig. figs. planning figure; raw: {exposure.total_population.toLocaleString()})
          </span>
        </div>
      </div>

      {/* Population by Hazard Class */}
      <div className="exposure-subgrid">
        <div>
          <h4 className="exposure-section-title">By DEFRA Hazard Class</h4>
          <div className="exposure-stat-rows">
            {Object.entries(exposure.by_hazard).map(([hazClass, count]) => (
              <div key={hazClass} className="exposure-row">
                <span className="exposure-row-label">{hazClass} Hazard</span>
                <span className="exposure-row-val num">{count.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Population by Arrival Band */}
        <div>
          <h4 className="exposure-section-title">By Arrival Time Band</h4>
          <div className="exposure-stat-rows">
            {Object.entries(exposure.by_arrival_band).map(([band, count]) => (
              <div key={band} className="exposure-row">
                <span className="exposure-row-label">{band}</span>
                <span className="exposure-row-val num">{count.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Infrastructure Counts */}
      {exposure.infrastructure && (
        <div className="exposure-infra-strip">
          <h4 className="exposure-section-title">Downstream Infrastructure Intersected</h4>
          <div className="exposure-infra-grid">
            {Object.entries(exposure.infrastructure).map(([key, val]) => (
              <div key={key} className="infra-stat-card">
                <span className="infra-val num">{typeof val === "number" ? val.toLocaleString() : val}</span>
                <span className="infra-key">{key.replace("_", " ")}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Damage Range (if computed, with order-of-magnitude warning §6.7) */}
      {damage && (
        <div className="exposure-damage-box">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span className="stat-label" style={{ color: "var(--color-navy)" }}>
              ESTIMATED DAMAGE RANGE (ORDER OF MAGNITUDE)
            </span>
            <span className="unverified-tag">Unverified Estimate</span>
          </div>
          <p className="exposure-damage-val num" style={{ fontSize: "var(--text-xl)", fontWeight: "var(--weight-bold)", color: "var(--color-ink)", marginBlock: "var(--space-2xs)" }}>
            {damage.formatted}
          </p>
          <p style={{ fontSize: "var(--text-2xs)", color: "var(--color-ink-3)" }}>
            Derived from depth-damage vulnerability curves. Non-statutory indicator for relief scoping only.
          </p>
        </div>
      )}
    </div>
  );
};

"use client";

import React from "react";
import { ScenarioSummary } from "@/lib/types";
import { formatArrival, formatArea, formatPopulation, formatDepth, formatSpeed } from "@/lib/utils";
import { MODEL_DISCLAIMER, STATUTORY_CITATIONS } from "@/lib/constants";

export interface ReportClientViewProps {
  summary: ScenarioSummary;
  settlements: any[];
}

export const ReportClientView: React.FC<ReportClientViewProps> = ({
  summary,
  settlements,
}) => {
  const isVerified = summary.honesty.presentable_as_fact;

  return (
    <div className="report-print-container" style={{ maxWidth: "54rem", margin: "0 auto", padding: "2rem", color: "#111827", backgroundColor: "#ffffff" }}>
      {/* Print Trigger Header (hidden in print) */}
      <div className="report-print-controls hide-print" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "2rem", paddingBottom: "1rem", borderBottom: "2px solid #e5e7eb" }}>
        <div>
          <span style={{ fontSize: "0.75rem", textTransform: "uppercase", letterSpacing: "0.05em", color: "#6b7280", fontWeight: "bold" }}>
            JALDRISHTI EMERGENCY RESPONSE DOSSIER
          </span>
          <h2 style={{ fontSize: "1.25rem", color: "#000080" }}>Official Simulation Output Report</h2>
        </div>
        <button
          type="button"
          onClick={() => window.print()}
          style={{
            backgroundColor: "#FF9933",
            color: "#000080",
            border: "1px solid #e68a00",
            borderRadius: "4px",
            padding: "0.5rem 1rem",
            fontSize: "0.875rem",
            fontWeight: "bold",
            cursor: "pointer",
          }}
        >
          🖨 Print / Save as PDF
        </button>
      </div>

      {/* Official Header */}
      <header style={{ borderBottom: "3px double #111827", paddingBottom: "1rem", marginBottom: "1.5rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem" }}>
              <span style={{ fontSize: "1.5rem", fontWeight: "bold", color: "#000080" }}>जलदृष्टि</span>
              <span style={{ fontSize: "1.25rem", fontWeight: "bold", letterSpacing: "0.05em" }}>JALDRISHTI</span>
            </div>
            <p style={{ fontSize: "0.75rem", color: "#4b5563", marginTop: "2px" }}>
              Dam Break Hydrodynamic Inundation Dossier · Problem Statement 26161 (NTRO)
            </p>
          </div>

          <div style={{ textAlign: "right" }}>
            <span style={{ fontFamily: "monospace", fontSize: "0.75rem", fontWeight: "bold" }}>
              RUN REF: {summary.run_id}
            </span>
            <div style={{ fontSize: "0.75rem", color: "#4b5563" }}>
              Date: {new Date().toLocaleDateString("en-IN", { year: "numeric", month: "short", day: "numeric" })}
            </div>
          </div>
        </div>

        {/* Verification Status Watermark Banner */}
        <div
          style={{
            marginTop: "0.75rem",
            padding: "0.5rem 0.75rem",
            backgroundColor: isVerified ? "#f0fdf4" : "#f3f4f6",
            border: `1px solid ${isVerified ? "#16a34a" : "#9ca3af"}`,
            borderRadius: "4px",
            fontSize: "0.75rem",
            display: "flex",
            justifyContent: "space-between",
          }}
        >
          <span>
            <strong>Release Status:</strong> {isVerified ? "VERIFIED — Presentable as Fact" : "PLANNING EXERCISE USE ONLY (Unverified inputs present)"}
          </span>
          <span style={{ fontFamily: "monospace" }}>CRS: {summary.grid.crs}</span>
        </div>
      </header>

      {/* Decision Headline */}
      <section style={{ backgroundColor: "#f9fafb", border: "1px solid #d1d5db", borderRadius: "4px", padding: "1rem", marginBottom: "1.5rem" }}>
        <span style={{ fontSize: "0.6875rem", textTransform: "uppercase", fontWeight: "bold", letterSpacing: "0.05em", color: "#4b5563" }}>
          EXECUTIVE SITUATION SUMMARY
        </span>
        <h3 style={{ fontSize: "1.125rem", fontWeight: "bold", color: "#111827", marginTop: "0.25rem", lineHeight: "1.4" }}>
          {summary.headline}
        </h3>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "0.75rem", marginTop: "1rem", paddingTop: "0.75rem", borderTop: "1px solid #e5e7eb" }}>
          <div>
            <span style={{ fontSize: "0.6875rem", color: "#6b7280", display: "block" }}>New Inundation</span>
            <strong style={{ fontSize: "1rem", fontFamily: "monospace" }}>{formatArea(summary.results.flooded_area_km2)}</strong>
          </div>
          <div>
            <span style={{ fontSize: "0.6875rem", color: "#6b7280", display: "block" }}>First Arrival</span>
            <strong style={{ fontSize: "1rem", fontFamily: "monospace" }}>{formatArrival(summary.results.first_arrival_min)}</strong>
          </div>
          <div>
            <span style={{ fontSize: "0.6875rem", color: "#6b7280", display: "block" }}>Peak Depth</span>
            <strong style={{ fontSize: "1rem", fontFamily: "monospace" }}>{formatDepth(summary.results.peak_depth_m)}</strong>
          </div>
          <div>
            <span style={{ fontSize: "0.6875rem", color: "#6b7280", display: "block" }}>Exposed Population</span>
            <strong style={{ fontSize: "1rem", fontFamily: "monospace" }}>
              {summary.results.exposure ? formatPopulation(summary.results.exposure.reported_population) : "—"}
            </strong>
          </div>
        </div>
      </section>

      {/* Downstream Settlements Table */}
      <section style={{ marginBottom: "1.5rem" }}>
        <h3 style={{ fontSize: "0.9375rem", fontWeight: "bold", textTransform: "uppercase", letterSpacing: "0.05em", borderBottom: "1px solid #111827", paddingBottom: "0.25rem", marginBottom: "0.5rem" }}>
          Downstream Settlements Evacuation Timetable
        </h3>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8125rem" }}>
          <thead>
            <tr style={{ backgroundColor: "#f3f4f6", borderBottom: "2px solid #374151" }}>
              <th style={{ padding: "6px", textAlign: "left" }}>Settlement Location</th>
              <th style={{ padding: "6px", textAlign: "left" }}>Arrival Time (min)</th>
              <th style={{ padding: "6px", textAlign: "left" }}>Peak Depth (m)</th>
              <th style={{ padding: "6px", textAlign: "left" }}>Peak Velocity (m/s)</th>
              <th style={{ padding: "6px", textAlign: "left" }}>DEFRA Hazard Level</th>
            </tr>
          </thead>
          <tbody>
            {settlements.map((s, idx) => (
              <tr key={idx} style={{ borderBottom: "1px solid #e5e7eb" }}>
                <td style={{ padding: "6px", fontWeight: "500" }}>{s.name}</td>
                <td style={{ padding: "6px", fontFamily: "monospace" }}>
                  {s.arr_min === -1 ? "NOT REACHED" : `${s.arr_min} min`}
                </td>
                <td style={{ padding: "6px", fontFamily: "monospace" }}>
                  {s.arr_min === -1 ? "0.0 m" : formatDepth(s.depth_m)}
                </td>
                <td style={{ padding: "6px", fontFamily: "monospace" }}>
                  {s.arr_min === -1 ? "0.0 m/s" : formatSpeed(s.speed_ms)}
                </td>
                <td style={{ padding: "6px", fontWeight: "600" }}>
                  {s.arr_min === -1 ? "Safe (Unflooded)" : s.haz_class}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* Assumptions and Limitations */}
      <section style={{ marginBottom: "1.5rem", pageBreakInside: "avoid" }}>
        <h3 style={{ fontSize: "0.9375rem", fontWeight: "bold", textTransform: "uppercase", letterSpacing: "0.05em", borderBottom: "1px solid #111827", paddingBottom: "0.25rem", marginBottom: "0.5rem" }}>
          Model Limitations & Physical Assumptions
        </h3>
        <ul style={{ paddingLeft: "1.25rem", fontSize: "0.75rem", color: "#374151", lineHeight: "1.5" }}>
          {summary.honesty.limitations.map((lim, idx) => (
            <li key={idx} style={{ marginBottom: "4px" }}>{lim}</li>
          ))}
        </ul>
      </section>

      {/* Statutory Framing & Citations */}
      <footer style={{ borderTop: "2px solid #111827", paddingTop: "0.75rem", fontSize: "0.6875rem", color: "#4b5563" }}>
        <p style={{ marginBottom: "0.5rem" }}>
          <strong>Statutory Disclaimer:</strong> {MODEL_DISCLAIMER}
        </p>
        <div style={{ display: "flex", justifyContent: "space-between", borderTop: "1px solid #e5e7eb", paddingTop: "0.5rem" }}>
          <span>Statutory Authority: Dam Safety Act 2021 · NDMA GLOF Guidelines · CWC EAP Standards</span>
          <span>Hydrodynamics: 2D SWE HLLC FVM (JALDRISHTI)</span>
        </div>
      </footer>
    </div>
  );
};

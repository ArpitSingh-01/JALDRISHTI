"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { PresentableBadge } from "@/components/ui/PresentableBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import { getRuns, USING_MOCKS } from "@/lib/api";
import { DemoDataBanner } from "@/components/ui/DemoDataBanner";
import { RunListItem } from "@/lib/types";
import { formatArrival, formatArea } from "@/lib/utils";

export default function RunsHistoryPage() {
  const router = useRouter();
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getRuns()
      .then((data) => {
        setRuns(data);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to load runs:", err);
        setLoading(false);
      });
  }, []);

  return (
    <div className="console-wrapper" data-register="console" data-theme="dark">
      {/* Top Header */}
      <header className="console-header">
        <div className="console-header-left">
          <Link href="/" className="brand-lockup console-brand" aria-label="JALDRISHTI Home">
            <span className="brand-deva" lang="hi">जलदृष्टि</span>
            <span className="brand-latin" style={{ fontSize: "var(--text-sm)" }}>JALDRISHTI</span>
          </Link>
          <span className="console-divider">/</span>
          <span style={{ fontSize: "var(--text-sm)", fontWeight: "var(--weight-bold)", color: "var(--color-ink)" }}>
            Simulation Run History
          </span>
        </div>

        <div className="console-header-right">
          <Button variant="primary" href="/scenarios" size="sm">
            + New Scenario Run
          </Button>
        </div>
      </header>

      {/* Main Content */}
      <main className="page-container section" style={{ flexGrow: 1, overflowY: "auto" }}>
        {USING_MOCKS && <DemoDataBanner />}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: "var(--space-xl)" }}>
          <div>
            <span className="stat-label">AUDIT TRAIL & LOGS</span>
            <h1 style={{ fontSize: "var(--text-3xl)", color: "var(--color-ink)", marginTop: "var(--space-2xs)" }}>
              Hydrodynamic Simulation Runs
            </h1>
          </div>
        </div>

        {loading ? (
          <div style={{ textAlign: "center", padding: "var(--space-3xl)" }}>
            <span className="btn-spinner" style={{ width: "2rem", height: "2rem" }} />
            <p style={{ marginTop: "var(--space-md)", color: "var(--color-ink-2)" }}>Loading simulation catalog...</p>
          </div>
        ) : runs.length === 0 ? (
          <EmptyState
            title="No Simulation Runs Yet"
            description="Select a pre-conditioned study area and configure breach parameters to launch your first hydrodynamic flood model."
            actionLabel="Browse Scenario Catalog →"
            actionHref="/scenarios"
          />
        ) : (
          <div
            style={{
              backgroundColor: "var(--color-paper-2)",
              border: "var(--rule-hairline) solid var(--color-rule)",
              borderRadius: "var(--radius-lg)",
              overflow: "hidden",
            }}
          >
            <table>
              <thead>
                <tr>
                  <th>Run Identifier</th>
                  <th>Study Area</th>
                  <th>Failure Scenario</th>
                  <th>New Inundation</th>
                  <th>First Arrival</th>
                  <th>Release Gate</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr
                    key={run.run_id}
                    style={{ cursor: "pointer" }}
                    onClick={() => router.push(`/runs/${run.run_id}`)}
                    className="settlement-row-interactive"
                  >
                    <td className="num" style={{ fontWeight: "var(--weight-bold)", color: "var(--color-ink)" }}>
                      {run.run_id}
                    </td>

                    <td style={{ textTransform: "capitalize", fontWeight: "var(--weight-medium)" }}>
                      {run.study_area.replace("_", " ")}
                    </td>

                    <td style={{ fontSize: "var(--text-xs)", color: "var(--color-ink-2)" }}>
                      {run.scenario}
                    </td>

                    <td className="num">
                      {run.flooded_area_km2 !== undefined ? formatArea(run.flooded_area_km2) : "—"}
                    </td>

                    <td className="num">
                      {formatArrival(run.first_arrival_min)}
                    </td>

                    <td>
                      <PresentableBadge
                        presentable={Boolean(run.presentable_as_fact)}
                        size="sm"
                      />
                    </td>

                    <td>
                      <Button variant="secondary" href={`/runs/${run.run_id}`} size="sm">
                        Open Console →
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}

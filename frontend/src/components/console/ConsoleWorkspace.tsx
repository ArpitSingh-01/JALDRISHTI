"use client";

import React, { useState } from "react";
import { ConsoleHeader } from "@/components/console/ConsoleHeader";
import { LayerSwitcher, MapLayerId } from "@/components/console/LayerSwitcher";
import { MapCanvas } from "@/components/console/MapCanvas";
import { SettlementsTable } from "@/components/console/SettlementsTable";
import { ExposureTable } from "@/components/console/ExposureTable";
import { ExportBar } from "@/components/console/ExportBar";
import { Scrubber } from "@/components/console/Scrubber";
import { HeadlineBanner } from "@/components/ui/HeadlineBanner";
import { LimitationList } from "@/components/shared/LimitationList";
import { DisclaimerBlock } from "@/components/shared/DisclaimerBlock";
import { ScenarioSummary, Manifest, SettlementProperties } from "@/lib/types";
import type { FeatureCollection } from "geojson";

export interface ConsoleWorkspaceProps {
  initialSummary: ScenarioSummary;
  initialManifest?: Manifest;
  initialIsochrones?: FeatureCollection;
  initialSettlements?: FeatureCollection;
}

export const ConsoleWorkspace: React.FC<ConsoleWorkspaceProps> = ({
  initialSummary,
  initialManifest,
  initialIsochrones,
  initialSettlements,
}) => {
  const [summary] = useState<ScenarioSummary>(initialSummary);
  const [manifest] = useState<Manifest | undefined>(initialManifest);
  const [isochrones] = useState<FeatureCollection | undefined>(initialIsochrones);
  const [settlements] = useState<FeatureCollection | undefined>(initialSettlements);

  // Active console states
  const [activeLayer, setActiveLayer] = useState<MapLayerId>("arrival");
  const [currentMinute, setCurrentMinute] = useState(summary.results.last_arrival_min || 143);
  const [selectedSettlement, setSelectedSettlement] = useState<string | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [showDrawer, setShowDrawer] = useState(false);

  const settlementList = (settlements?.features.map((f: any) => f.properties) || []) as SettlementProperties[];

  return (
    <div className="console-wrapper" data-register="console" data-theme={theme}>
      {/* 1 · Top Status Bar */}
      <ConsoleHeader
        summary={summary}
        theme={theme}
        onToggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
      />

      {/* 2 · Three-Column Workspace (§4.8) */}
      <div className="console-main-layout">
        {/* Left Column: Layer Switcher Rail */}
        <LayerSwitcher
          activeLayer={activeLayer}
          onChangeLayer={setActiveLayer}
        />

        {/* Center Column: Map Canvas + Scrubber */}
        <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden", position: "relative" }}>
          <div style={{ flexGrow: 1, position: "relative", minHeight: 0 }}>
            <MapCanvas
              layer={activeLayer}
              currentMinute={currentMinute}
              isochrones={isochrones}
              settlements={settlements}
              selectedSettlement={selectedSettlement}
              onSelectSettlement={setSelectedSettlement}
            />
          </div>

          {/* Front-Advance Scrubber (§9.3) */}
          <div style={{ padding: "var(--space-sm) var(--space-md)", backgroundColor: "var(--color-paper-2)", borderTop: "var(--rule-hairline) solid var(--color-rule)" }}>
            <Scrubber
              maxMinutes={summary.results.last_arrival_min || 143}
              currentMinute={currentMinute}
              onChangeMinute={setCurrentMinute}
            />
          </div>
        </div>

        {/* Right Column: Decision Headline, Exposure & Settlements */}
        <aside className="console-right-panel" aria-label="Decision Metrics & Settlements">
          {/* Prominent Decision Headline (§1.2) */}
          <HeadlineBanner
            headline={summary.headline}
            floodedAreaKm2={summary.results.flooded_area_km2}
            reportedPopulation={summary.results.exposure?.reported_population}
            firstArrivalMin={summary.results.first_arrival_min}
          />

          {/* Settlements at Risk Timetable (§6.8) */}
          <SettlementsTable
            settlements={settlementList}
            selectedSettlement={selectedSettlement}
            onSelectSettlement={setSelectedSettlement}
          />

          {/* Population Exposure Breakdown (§6.7) */}
          <ExposureTable
            exposure={summary.results.exposure}
            damage={summary.results.damage}
          />

          {/* Toggle Honesty Drawer Button */}
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setShowDrawer(!showDrawer)}
            style={{ marginTop: "auto" }}
          >
            {showDrawer ? "▲ Hide Model Caveats" : "▼ View Limitations & Provenance"}
          </button>
        </aside>
      </div>

      {/* 3 · Expandable Honesty & Limitations Drawer */}
      {showDrawer && (
        <div
          style={{
            backgroundColor: "var(--color-paper-2)",
            borderTop: "var(--rule-heavy) solid var(--color-rule-strong)",
            padding: "var(--space-lg) var(--gutter)",
            maxHeight: "18rem",
            overflowY: "auto",
            zIndex: 60,
          }}
        >
          <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: "var(--space-xl)" }}>
            <LimitationList
              limitations={summary.honesty.limitations}
              unverifiedInputs={summary.honesty.unverified_inputs}
            />
            <DisclaimerBlock compact />
          </div>
        </div>
      )}

      {/* 4 · Bottom Export Bar */}
      <footer className="console-bottom-bar">
        <ExportBar runId={summary.run_id} manifest={manifest} />
      </footer>
    </div>
  );
};

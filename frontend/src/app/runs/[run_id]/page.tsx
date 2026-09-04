import React from "react";
import { getRun, getManifest, getIsochrones, getSettlements, USING_MOCKS } from "@/lib/api";
import { DemoDataBanner } from "@/components/ui/DemoDataBanner";
import { ConsoleWorkspace } from "@/components/console/ConsoleWorkspace";

export default async function SimulationConsolePage({
  params,
}: {
  params: Promise<{ run_id: string }>;
}) {
  const resolvedParams = await params;
  const runId = resolvedParams.run_id;

  const [summary, manifest, isochrones, settlements] = await Promise.all([
    getRun(runId),
    getManifest(runId).catch(() => undefined),
    getIsochrones(runId).catch(() => undefined),
    getSettlements(runId).catch(() => undefined),
  ]);

  return (
    <>
      {USING_MOCKS && (
        <div className="page-container" style={{ paddingTop: "var(--space-sm)" }}>
          <DemoDataBanner />
        </div>
      )}
      <ConsoleWorkspace
        initialSummary={summary}
        initialManifest={manifest}
        initialIsochrones={isochrones}
        initialSettlements={settlements}
      />
    </>
  );
}

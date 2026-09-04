import React from "react";
import { getRun, getManifest, getIsochrones, getSettlements } from "@/lib/api";
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
      <ConsoleWorkspace
        initialSummary={summary}
        initialManifest={manifest}
        initialIsochrones={isochrones}
        initialSettlements={settlements}
      />
    </>
  );
}

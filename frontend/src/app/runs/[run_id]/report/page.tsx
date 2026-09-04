import React from "react";
import { getRun, getSettlements } from "@/lib/api";
import { formatArrival, formatArea, formatPopulation, formatDepth, formatSpeed } from "@/lib/utils";
import { MODEL_DISCLAIMER, STATUTORY_CITATIONS } from "@/lib/constants";
import { ReportClientView } from "./ReportClientView";

export default async function RunReportPrintPage({
  params,
}: {
  params: Promise<{ run_id: string }>;
}) {
  const resolvedParams = await params;
  const runId = resolvedParams.run_id;

  const [summary, settlementsData] = await Promise.all([
    getRun(runId),
    getSettlements(runId).catch(() => ({ features: [] })),
  ]);

  const settlements = settlementsData.features.map((f: any) => f.properties);

  return (
    <ReportClientView
      summary={summary}
      settlements={settlements}
    />
  );
}

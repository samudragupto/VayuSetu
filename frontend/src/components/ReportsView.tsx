"use client";

import { useState } from "react";

import { useReports } from "@/hooks/useCollection";

import { AppShell } from "./AppShell";
import { ReportsTable } from "./ReportsTable";
import { ErrorState, LoadingState } from "./States";
import { TimeRangeSelector } from "./TimeRangeSelector";

export function ReportsView() {
  const [hours, setHours] = useState(24);
  const reports = useReports(hours, 2000);
  return (
    <AppShell title="Citizen reports" actions={<TimeRangeSelector hours={hours} onChange={setHours} />}>
      {reports.error ? (
        <div className="mb-4">
          <ErrorState message={reports.error} />
        </div>
      ) : null}
      <div className="card overflow-hidden">
        <div className="card-header">
          <h2 className="card-title">WhatsApp submissions with Gemini and Sentinel-5P analysis</h2>
          {reports.loading ? <LoadingState message="Syncing" /> : null}
        </div>
        <ReportsTable reports={reports.items} />
      </div>
    </AppShell>
  );
}

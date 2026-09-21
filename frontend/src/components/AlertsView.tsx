"use client";

import { useMemo, useState } from "react";

import { useAlerts, useHotspots } from "@/hooks/useCollection";
import { latestHotspotsPerCell } from "@/lib/analytics";
import { ALERT_THRESHOLD } from "@/lib/aqi";

import { AlertsTable } from "./AlertsTable";
import { AppShell } from "./AppShell";
import { HotspotTable } from "./HotspotTable";
import { StatCard } from "./StatCard";
import { ErrorState, LoadingState } from "./States";
import { TimeRangeSelector } from "./TimeRangeSelector";

export function AlertsView() {
  const [hours, setHours] = useState(72);
  const alerts = useAlerts(hours);
  const hotspots = useHotspots(hours);
  const critical = useMemo(() => latestHotspotsPerCell(hotspots.items).filter((h) => h.predictedAqi >= ALERT_THRESHOLD), [hotspots.items]);
  const sent = alerts.items.filter((a) => a.status === "sent");
  const failed = alerts.items.filter((a) => a.status === "failed");
  const languages = new Set(sent.map((a) => a.language));

  return (
    <AppShell title="Authority alerts" actions={<TimeRangeSelector hours={hours} onChange={setHours} />}>
      {alerts.error ?? hotspots.error ? (
        <div className="mb-4">
          <ErrorState message={(alerts.error ?? hotspots.error) as string} />
        </div>
      ) : null}
      <section className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Alerts delivered" value={sent.length} hint={`${failed.length} failed; ${alerts.items.length} attempts`} accent={sent.length > 0 ? "text-red-700" : undefined} />
        <StatCard label="Languages used" value={languages.size} hint="Cloud Translation and Text-to-Speech produce voice and WhatsApp alerts in each authority's language" />
        <StatCard label="Cells above threshold" value={critical.length} hint={`Predicted 12 h AQI at or above ${ALERT_THRESHOLD}`} accent={critical.length > 0 ? "text-red-700" : "text-emerald-700"} />
      </section>
      <section className="card mt-6 overflow-hidden">
        <div className="card-header">
          <h2 className="card-title">Dispatch log</h2>
          {alerts.loading ? <LoadingState message="Syncing" /> : null}
        </div>
        <AlertsTable alerts={alerts.items} />
      </section>
      <section className="card mt-6 overflow-hidden">
        <div className="card-header">
          <h2 className="card-title">Cells currently above the alert threshold</h2>
        </div>
        <HotspotTable hotspots={critical} threshold={ALERT_THRESHOLD} limit={25} />
      </section>
    </AppShell>
  );
}

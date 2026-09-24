"use client";

import { useMemo, useState } from "react";

import { useAlerts, useHotspots, useReports } from "@/hooks/useCollection";
import { buildTrend, cityLeaderboard, computeStats, countCategories, countSources, labelForSource, latestHotspotsPerCell } from "@/lib/analytics";
import { ALERT_THRESHOLD, bandForAqi } from "@/lib/aqi";

import { AppShell } from "./AppShell";
import { AqiTrendChart, CategoryDistributionChart, SourceBreakdownChart } from "./Charts";
import { HotspotMap } from "./HotspotMap";
import { HotspotTable } from "./HotspotTable";
import { StatCard } from "./StatCard";
import { ErrorState, LoadingState } from "./States";
import { TimeRangeSelector } from "./TimeRangeSelector";

export function OverviewDashboard() {
  const [hours, setHours] = useState(24);
  const reports = useReports(hours);
  const hotspots = useHotspots(hours);
  const alerts = useAlerts(hours);

  const latestHotspots = useMemo(() => latestHotspotsPerCell(hotspots.items), [hotspots.items]);
  const stats = useMemo(() => computeStats(reports.items, hotspots.items, ALERT_THRESHOLD), [reports.items, hotspots.items]);
  const trend = useMemo(() => buildTrend(reports.items, hotspots.items, hours), [reports.items, hotspots.items, hours]);
  const sources = useMemo(() => countSources(reports.items), [reports.items]);
  const categories = useMemo(() => countCategories(reports.items), [reports.items]);
  const cities = useMemo(() => cityLeaderboard(reports.items), [reports.items]);
  const error = reports.error ?? hotspots.error ?? alerts.error;
  const averageBand = bandForAqi(stats.averageAqi);
  const maxBand = bandForAqi(stats.maxPredictedAqi);
  const focusHotspot = latestHotspots[0] ?? null;
  const focusBand = focusHotspot ? bandForAqi(focusHotspot.predictedAqi) : null;
  const windowLabel = hours >= 168 ? "last 7 days" : hours >= 72 ? "last 3 days" : hours >= 24 ? "last 24 hours" : "last 6 hours";

  return (
    <AppShell title="Air quality overview" actions={<TimeRangeSelector hours={hours} onChange={setHours} />}>
      <section className="mb-6 overflow-hidden rounded-2xl bg-[#0c234b] text-white shadow-[0_12px_32px_rgba(12,35,75,0.16)]" aria-label="Decision brief">
        <div className="grid gap-7 px-5 py-6 sm:px-7 lg:grid-cols-[1fr_290px] lg:items-center lg:py-7">
          <div>
            <p className="eyebrow text-cyan-300">Decision brief · {windowLabel}</p>
            <h2 className="mt-3 max-w-2xl text-2xl font-semibold leading-tight tracking-[-0.03em] sm:text-3xl">Know where to look first, before the spike reaches the street.</h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
              VayuSetu brings the citizen signal, satellite context and model forecast together. Use the confidence and source mix as a guide for the next field decision—not as a substitute for an official station reading.
            </p>
            <div className="mt-5 flex flex-wrap gap-2 text-xs font-medium">
              <span className="rounded-full border border-white/15 bg-white/[0.08] px-3 py-1.5">{stats.analyzedReports} analysed observations</span>
              <span className="rounded-full border border-white/15 bg-white/[0.08] px-3 py-1.5">12 h forecast horizon</span>
              <span className="rounded-full border border-white/15 bg-white/[0.08] px-3 py-1.5">Alert line AQI {ALERT_THRESHOLD}</span>
            </div>
          </div>
          <div className="rounded-xl border border-white/10 bg-white/[0.08] p-4">
            <p className="text-xs font-medium text-slate-300">Highest forecast in view</p>
            {focusHotspot && focusBand ? (
              <>
                <div className="mt-2 flex items-end justify-between gap-3">
                  <div>
                    <p className="text-lg font-semibold">{focusHotspot.city ?? "Unnamed area"}</p>
                    <p className="mt-0.5 text-xs text-slate-400">{focusHotspot.reportCount} reports · {Math.round(focusHotspot.confidence * 100)}% model confidence</p>
                  </div>
                  <span className="rounded-lg px-2.5 py-1.5 text-lg font-bold" style={{ backgroundColor: focusBand.color, color: focusBand.textColor }}>{Math.round(focusHotspot.predictedAqi)}</span>
                </div>
                <p className="mt-3 text-xs leading-5 text-slate-300">{focusBand.label}. Likely sources: {focusHotspot.dominantSources.length ? focusHotspot.dominantSources.map(labelForSource).join(", ") : "mixed local sources"}.</p>
              </>
            ) : (
              <p className="mt-3 text-sm leading-6 text-slate-300">Waiting for the first batch prediction in this time window.</p>
            )}
          </div>
        </div>
      </section>
      {error ? (
        <div className="mb-4">
          <ErrorState message={`Live data unavailable: ${error}`} />
        </div>
      ) : null}

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Key metrics">
        <StatCard label="Citizen reports" value={stats.totalReports} hint={`${stats.analyzedReports} analysed by Gemini; ${stats.activeCitizens} citizens; ${stats.citiesCovered} cities`} />
        <StatCard label="Average observed AQI" value={stats.averageAqi ?? "-"} hint={stats.averageAqi !== null ? averageBand.label : "No analysed reports"} accent={stats.averageAqi !== null ? "" : undefined}>
          {stats.averageAqi !== null ? <span className="badge mt-2" style={{ backgroundColor: averageBand.color, color: averageBand.textColor }}>{averageBand.advice}</span> : null}
        </StatCard>
        <StatCard
          label="Peak 12 h forecast"
          value={stats.maxPredictedAqi ?? "-"}
          hint={stats.maxPredictedAqi !== null ? `${maxBand.label}; ${latestHotspots.length} cells forecast` : "Awaiting batch prediction"}
          accent={stats.maxPredictedAqi !== null && stats.maxPredictedAqi >= ALERT_THRESHOLD ? "text-red-700" : undefined}
        />
        <StatCard
          label="Hotspots above threshold"
          value={stats.hotspotsAboveThreshold}
          hint={`${stats.alertsSent} alert dispatches; ${alerts.items.filter((a) => a.status === "sent").length} authority contacts reached`}
          accent={stats.hotspotsAboveThreshold > 0 ? "text-red-700" : "text-emerald-700"}
        />
      </section>

      <section className="mt-6 grid gap-6 xl:grid-cols-3">
        <div className="card overflow-hidden xl:col-span-2">
          <div className="card-header">
            <h2 className="card-title">Predicted hotspots and live reports</h2>
            {hotspots.loading || reports.loading ? <LoadingState message="Syncing" /> : <span className="text-xs text-slate-500">{latestHotspots.length} cells, {reports.items.length} reports</span>}
          </div>
          <HotspotMap hotspots={latestHotspots} reports={reports.items} loading={hotspots.loading} threshold={ALERT_THRESHOLD} />
        </div>
        <div className="card">
          <div className="card-header">
            <h2 className="card-title">Most reported cities</h2>
          </div>
          {cities.length === 0 ? (
            <p className="px-5 py-8 text-center text-sm text-slate-500">No reports yet</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {cities.map((city) => {
                const band = bandForAqi(city.averageAqi);
                return (
                  <li key={city.city} className="flex items-center justify-between px-5 py-3 text-sm">
                    <div>
                      <p className="font-medium text-slate-900">{city.city}</p>
                      <p className="text-xs text-slate-500">
                        {city.reports} report{city.reports === 1 ? "" : "s"}
                      </p>
                    </div>
                    {city.averageAqi !== null ? (
                      <span className="badge" style={{ backgroundColor: band.color, color: band.textColor }}>
                        {city.averageAqi} {band.label}
                      </span>
                    ) : (
                      <span className="text-xs text-slate-400">Pending</span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </section>

      <section className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="card p-5">
          <h2 className="card-title mb-3">Observed versus predicted AQI (IST)</h2>
          <AqiTrendChart data={trend} threshold={ALERT_THRESHOLD} />
        </div>
        <div className="card p-5">
          <h2 className="card-title mb-3">Pollution sources identified by Gemini</h2>
          <SourceBreakdownChart data={sources} />
        </div>
      </section>

      <section className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="card p-5">
          <h2 className="card-title mb-3">AQI category distribution</h2>
          <CategoryDistributionChart data={categories} />
        </div>
        <div className="card lg:col-span-2">
          <div className="card-header">
            <h2 className="card-title">Forecast hotspots ranked by predicted AQI</h2>
            <span className="text-xs text-slate-500">Model confidence {stats.averageConfidence !== null ? `${Math.round(stats.averageConfidence * 100)}%` : "-"}</span>
          </div>
          <HotspotTable hotspots={latestHotspots} threshold={ALERT_THRESHOLD} />
        </div>
      </section>
    </AppShell>
  );
}

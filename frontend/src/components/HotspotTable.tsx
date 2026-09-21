"use client";

import { format } from "date-fns";

import { labelForSource } from "@/lib/analytics";
import type { PredictedHotspot } from "@/lib/types";

import { AqiBadge } from "./AqiBadge";
import { EmptyState } from "./States";

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-amber-100 text-amber-800",
  processing: "bg-blue-100 text-blue-800",
  sent: "bg-red-100 text-red-800",
  failed: "bg-slate-200 text-slate-800",
  not_required: "bg-slate-100 text-slate-600",
  below_threshold: "bg-slate-100 text-slate-600",
  suppressed_cooldown: "bg-slate-100 text-slate-600",
  no_recipients: "bg-amber-50 text-amber-700",
  skipped: "bg-slate-100 text-slate-600",
};

export function HotspotTable({ hotspots, threshold, limit = 10 }: { hotspots: PredictedHotspot[]; threshold: number; limit?: number }) {
  if (hotspots.length === 0) {
    return <EmptyState title="No forecast hotspots" description="Run the batch prediction job or wait for the hourly schedule." />;
  }
  return (
    <div className="overflow-x-auto">
      <table className="table">
        <thead>
          <tr>
            <th>Area</th>
            <th>Now</th>
            <th>12 h forecast</th>
            <th>Trend</th>
            <th>Reports</th>
            <th>Likely sources</th>
            <th>Forecast for</th>
            <th>Alert</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {hotspots.slice(0, limit).map((hotspot) => {
            const delta = hotspot.currentAqiEstimate !== null ? hotspot.predictedAqi - hotspot.currentAqiEstimate : null;
            return (
              <tr key={hotspot.id} className={hotspot.predictedAqi >= threshold ? "bg-red-50/60" : undefined}>
                <td>
                  <div className="font-medium text-slate-900">{hotspot.city ?? "Unnamed area"}</div>
                  <div className="font-mono text-xs text-slate-500">{hotspot.geohash}</div>
                </td>
                <td>{hotspot.currentAqiEstimate !== null ? Math.round(hotspot.currentAqiEstimate) : "-"}</td>
                <td>
                  <AqiBadge aqi={hotspot.predictedAqi} />
                </td>
                <td className={delta !== null && delta > 0 ? "text-red-700" : "text-emerald-700"}>{delta !== null ? `${delta > 0 ? "+" : ""}${Math.round(delta)}` : "-"}</td>
                <td>{hotspot.reportCount}</td>
                <td className="text-xs">{hotspot.dominantSources.length ? hotspot.dominantSources.map(labelForSource).join(", ") : "-"}</td>
                <td className="whitespace-nowrap text-xs">{hotspot.forecastFor ? format(hotspot.forecastFor, "dd MMM HH:mm") : "-"}</td>
                <td>
                  <span className={`badge ${STATUS_STYLES[hotspot.alertStatus] ?? "bg-slate-100 text-slate-600"}`}>{hotspot.alertStatus.replace(/_/g, " ")}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

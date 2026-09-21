"use client";

import { format } from "date-fns";

import type { AlertLogEntry } from "@/lib/types";

import { AqiBadge } from "./AqiBadge";
import { EmptyState } from "./States";

const LANGUAGE_NAMES: Record<string, string> = {
  en: "English",
  hi: "Hindi",
  bn: "Bengali",
  ta: "Tamil",
  te: "Telugu",
  mr: "Marathi",
  gu: "Gujarati",
  kn: "Kannada",
  ml: "Malayalam",
  pa: "Punjabi",
};

export function AlertsTable({ alerts }: { alerts: AlertLogEntry[] }) {
  if (alerts.length === 0) {
    return <EmptyState title="No alerts dispatched in this window" description="Alerts are sent automatically when a predicted 12-hour AQI exceeds the configured threshold." />;
  }
  return (
    <div className="overflow-x-auto">
      <table className="table">
        <thead>
          <tr>
            <th>Sent</th>
            <th>Authority</th>
            <th>Channel</th>
            <th>Language</th>
            <th>Hotspot</th>
            <th>Predicted AQI</th>
            <th>Status</th>
            <th>Message</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {alerts.map((alert) => (
            <tr key={alert.id}>
              <td className="whitespace-nowrap text-xs">{alert.sentAt ? format(alert.sentAt, "dd MMM HH:mm") : "-"}</td>
              <td className="font-medium text-slate-900">{alert.authorityName}</td>
              <td className="capitalize">{alert.channel}</td>
              <td>{LANGUAGE_NAMES[alert.language] ?? alert.language}</td>
              <td className="font-mono text-xs">{alert.geohash || alert.hotspotId}</td>
              <td>
                <AqiBadge aqi={alert.predictedAqi} />
              </td>
              <td>
                <span className={`badge ${alert.status === "sent" ? "bg-emerald-100 text-emerald-800" : alert.status === "failed" ? "bg-red-100 text-red-800" : "bg-slate-100 text-slate-700"}`}>{alert.status}</span>
                {alert.error ? <p className="mt-1 max-w-xs text-xs text-red-600">{alert.error}</p> : null}
              </td>
              <td className="max-w-md text-xs text-slate-600">{alert.messageText}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

"use client";

import { formatDistanceToNowStrict } from "date-fns";
import { useMemo, useState } from "react";

import { labelForSource } from "@/lib/analytics";
import type { CitizenReport } from "@/lib/types";

import { AqiBadge } from "./AqiBadge";
import { EmptyState } from "./States";

const STATUS_STYLES: Record<string, string> = {
  received: "bg-slate-100 text-slate-700",
  analyzing: "bg-blue-100 text-blue-800",
  analyzed: "bg-emerald-100 text-emerald-800",
  failed: "bg-red-100 text-red-800",
};

export function ReportsTable({ reports, pageSize = 25 }: { reports: CitizenReport[]; pageSize?: number }) {
  const [page, setPage] = useState(0);
  const [cityFilter, setCityFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [expanded, setExpanded] = useState<string | null>(null);

  const cities = useMemo(() => Array.from(new Set(reports.map((r) => r.city).filter((c): c is string => Boolean(c)))).sort(), [reports]);
  const filtered = useMemo(
    () => reports.filter((r) => (cityFilter === "all" || r.city === cityFilter) && (statusFilter === "all" || r.status === statusFilter)),
    [reports, cityFilter, statusFilter]
  );
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pageCount - 1);
  const visible = filtered.slice(currentPage * pageSize, (currentPage + 1) * pageSize);

  if (reports.length === 0) {
    return <EmptyState title="No citizen reports in this window" description="Reports arrive through the WhatsApp channel and appear here in real time." />;
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 px-4 py-3 text-sm">
        <label className="flex items-center gap-2">
          <span className="text-slate-600">City</span>
          <select className="rounded-md border border-slate-300 px-2 py-1 text-sm" value={cityFilter} onChange={(e) => { setCityFilter(e.target.value); setPage(0); }}>
            <option value="all">All</option>
            {cities.map((city) => (
              <option key={city} value={city}>
                {city}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span className="text-slate-600">Status</span>
          <select className="rounded-md border border-slate-300 px-2 py-1 text-sm" value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(0); }}>
            <option value="all">All</option>
            <option value="analyzed">Analysed</option>
            <option value="analyzing">Analysing</option>
            <option value="received">Received</option>
            <option value="failed">Failed</option>
          </select>
        </label>
        <span className="ml-auto text-xs text-slate-500">
          {filtered.length} report{filtered.length === 1 ? "" : "s"}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>Report</th>
              <th>Received</th>
              <th>City</th>
              <th>Status</th>
              <th>Estimated AQI</th>
              <th>Haze</th>
              <th>Visibility</th>
              <th>Sources</th>
              <th>Satellite</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {visible.map((report) => (
              <ReportRow key={report.id} report={report} expanded={expanded === report.id} onToggle={() => setExpanded(expanded === report.id ? null : report.id)} />
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2 text-xs text-slate-600">
        <span>
          Page {currentPage + 1} of {pageCount}
        </span>
        <div className="flex gap-2">
          <button type="button" className="btn-secondary" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>
            Previous
          </button>
          <button type="button" className="btn-secondary" disabled={currentPage >= pageCount - 1} onClick={() => setPage(currentPage + 1)}>
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

function ReportRow({ report, expanded, onToggle }: { report: CitizenReport; expanded: boolean; onToggle: () => void }) {
  const analysis = report.geminiAnalysis;
  return (
    <>
      <tr className="cursor-pointer hover:bg-slate-50" onClick={onToggle}>
        <td className="font-mono text-xs">{report.id.slice(0, 8).toUpperCase()}</td>
        <td className="whitespace-nowrap text-xs">{report.createdAt ? `${formatDistanceToNowStrict(report.createdAt)} ago` : "-"}</td>
        <td>{report.city ?? (report.location ? `${report.location.latitude.toFixed(3)}, ${report.location.longitude.toFixed(3)}` : "No location")}</td>
        <td>
          <span className={`badge ${STATUS_STYLES[report.status] ?? "bg-slate-100 text-slate-700"}`}>{report.status}</span>
        </td>
        <td>{report.status === "analyzed" ? <AqiBadge aqi={report.estimatedAqi} category={report.estimatedAqiCategory} /> : "-"}</td>
        <td>{report.hazeIndex !== null ? report.hazeIndex.toFixed(2) : "-"}</td>
        <td>{report.visibilityKm !== null ? `${report.visibilityKm.toFixed(1)} km` : "-"}</td>
        <td className="text-xs">{report.pollutionSources.length ? report.pollutionSources.map(labelForSource).join(", ") : "-"}</td>
        <td className="text-xs">
          {report.satelliteMetrics?.aerAi !== null && report.satelliteMetrics?.aerAi !== undefined
            ? `AER AI ${report.satelliteMetrics.aerAi.toFixed(2)}`
            : report.satelliteMetrics
              ? "Fetched"
              : "-"}
        </td>
      </tr>
      {expanded ? (
        <tr className="bg-slate-50">
          <td colSpan={9} className="px-6 py-3 text-xs text-slate-700">
            <div className="grid gap-3 md:grid-cols-3">
              <div>
                <p className="font-semibold text-slate-800">Gemini analysis</p>
                {analysis ? (
                  <ul className="mt-1 space-y-0.5">
                    <li>Outdoor scene: {analysis.is_outdoor_scene ? "yes" : "no"}</li>
                    <li>Sky: {analysis.sky_condition ?? "-"}; visibility {analysis.visibility_category ?? "-"}</li>
                    <li>
                      Smoke {analysis.smoke_detected ? "yes" : "no"}; dust {analysis.dust_detected ? "yes" : "no"}; open burning {analysis.open_burning_detected ? "yes" : "no"}; fog {analysis.fog_or_mist_detected ? "yes" : "no"}
                    </li>
                    <li>
                      Vehicle {analysis.vehicle_density_score?.toFixed(2) ?? "-"}; construction {analysis.construction_activity_score?.toFixed(2) ?? "-"}; industrial {analysis.industrial_emission_score?.toFixed(2) ?? "-"}
                    </li>
                    <li>Confidence {analysis.confidence !== undefined ? `${Math.round(analysis.confidence * 100)}%` : "-"}; model {report.modelName ?? "-"}</li>
                  </ul>
                ) : (
                  <p className="mt-1 text-slate-500">{report.error ?? "Pending"}</p>
                )}
              </div>
              <div>
                <p className="font-semibold text-slate-800">Reasoning</p>
                <p className="mt-1 text-slate-600">{analysis?.reasoning ?? "-"}</p>
                {report.caption ? <p className="mt-2 italic text-slate-500">Citizen note: {report.caption}</p> : null}
              </div>
              <div>
                <p className="font-semibold text-slate-800">Sentinel-5P context</p>
                {report.satelliteMetrics ? (
                  <ul className="mt-1 space-y-0.5">
                    <li>UV aerosol index: {report.satelliteMetrics.aerAi?.toFixed(2) ?? "-"}</li>
                    <li>NO2 column: {report.satelliteMetrics.no2TroposphericMolM2 !== null && report.satelliteMetrics.no2TroposphericMolM2 !== undefined ? `${(report.satelliteMetrics.no2TroposphericMolM2 * 1e6).toFixed(1)} umol/m2` : "-"}</li>
                    <li>CO column: {report.satelliteMetrics.coColumnMolM2?.toFixed(4) ?? "-"} mol/m2</li>
                    <li>MODIS AOD 470 nm: {report.satelliteMetrics.aod047?.toFixed(2) ?? "-"}</li>
                  </ul>
                ) : (
                  <p className="mt-1 text-slate-500">Not available for this report</p>
                )}
              </div>
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}

import { bandForAqi } from "./aqi";
import type { CitizenReport, PredictedHotspot } from "./types";

export interface DashboardStats {
  totalReports: number;
  analyzedReports: number;
  activeCitizens: number;
  citiesCovered: number;
  averageAqi: number | null;
  maxPredictedAqi: number | null;
  hotspotsAboveThreshold: number;
  alertsSent: number;
  averageConfidence: number | null;
}

export interface TrendPoint {
  time: number;
  label: string;
  observedAqi: number | null;
  predictedAqi: number | null;
  reports: number;
}

export interface SourceCount {
  source: string;
  label: string;
  count: number;
}

export interface CategoryCount {
  category: string;
  label: string;
  count: number;
  color: string;
}

const SOURCE_LABELS: Record<string, string> = {
  vehicular: "Vehicular",
  industrial: "Industrial",
  construction_dust: "Construction dust",
  road_dust: "Road dust",
  crop_residue_burning: "Crop residue burning",
  waste_burning: "Waste burning",
  biomass_cooking: "Biomass cooking",
  fireworks: "Fireworks",
  power_plant: "Power plant",
  natural_dust: "Natural dust",
  fog: "Fog",
  unknown: "Unknown",
};

export function labelForSource(source: string): string {
  return SOURCE_LABELS[source] ?? source.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** Keep only the latest prediction per geohash cell. */
export function latestHotspotsPerCell(hotspots: PredictedHotspot[]): PredictedHotspot[] {
  const byCell = new Map<string, PredictedHotspot>();
  for (const hotspot of hotspots) {
    const existing = byCell.get(hotspot.geohash);
    const generated = hotspot.generatedAt?.getTime() ?? 0;
    if (!existing || generated > (existing.generatedAt?.getTime() ?? 0)) {
      byCell.set(hotspot.geohash, hotspot);
    }
  }
  return Array.from(byCell.values()).sort((a, b) => b.predictedAqi - a.predictedAqi);
}

export function computeStats(reports: CitizenReport[], hotspots: PredictedHotspot[], threshold: number): DashboardStats {
  const analyzed = reports.filter((r) => r.status === "analyzed" && r.estimatedAqi !== null);
  const latest = latestHotspotsPerCell(hotspots);
  const aqiValues = analyzed.map((r) => r.estimatedAqi as number);
  const confidences = latest.map((h) => h.confidence).filter((c) => c > 0);
  return {
    totalReports: reports.length,
    analyzedReports: analyzed.length,
    activeCitizens: new Set(reports.map((r) => r.phoneHash).filter(Boolean)).size,
    citiesCovered: new Set(reports.map((r) => r.city).filter(Boolean)).size,
    averageAqi: aqiValues.length ? Math.round(aqiValues.reduce((a, b) => a + b, 0) / aqiValues.length) : null,
    maxPredictedAqi: latest.length ? Math.round(Math.max(...latest.map((h) => h.predictedAqi))) : null,
    hotspotsAboveThreshold: latest.filter((h) => h.predictedAqi >= threshold).length,
    alertsSent: hotspots.filter((h) => h.alertStatus === "sent").length,
    averageConfidence: confidences.length ? confidences.reduce((a, b) => a + b, 0) / confidences.length : null,
  };
}

function bucketKey(date: Date, bucketMinutes: number): number {
  const ms = bucketMinutes * 60_000;
  return Math.floor(date.getTime() / ms) * ms;
}

/** Build an hourly (or coarser) series of observed vs predicted AQI. */
export function buildTrend(reports: CitizenReport[], hotspots: PredictedHotspot[], hours: number): TrendPoint[] {
  const bucketMinutes = hours <= 6 ? 30 : hours <= 24 ? 60 : hours <= 72 ? 180 : 360;
  const observed = new Map<number, { sum: number; count: number }>();
  for (const report of reports) {
    if (report.status !== "analyzed" || report.estimatedAqi === null || !report.createdAt) {
      continue;
    }
    const key = bucketKey(report.createdAt, bucketMinutes);
    const entry = observed.get(key) ?? { sum: 0, count: 0 };
    entry.sum += report.estimatedAqi;
    entry.count += 1;
    observed.set(key, entry);
  }
  const predicted = new Map<number, { sum: number; count: number }>();
  for (const hotspot of hotspots) {
    if (!hotspot.forecastFor) {
      continue;
    }
    const key = bucketKey(hotspot.forecastFor, bucketMinutes);
    const entry = predicted.get(key) ?? { sum: 0, count: 0 };
    entry.sum += hotspot.predictedAqi;
    entry.count += 1;
    predicted.set(key, entry);
  }
  const keys = Array.from(new Set([...observed.keys(), ...predicted.keys()])).sort((a, b) => a - b);
  const formatter = new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    ...(hours > 24 ? { day: "2-digit", month: "short" } : {}),
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return keys.map((time) => {
    const obs = observed.get(time);
    const pred = predicted.get(time);
    return {
      time,
      label: formatter.format(new Date(time)),
      observedAqi: obs ? Math.round(obs.sum / obs.count) : null,
      predictedAqi: pred ? Math.round(pred.sum / pred.count) : null,
      reports: obs?.count ?? 0,
    };
  });
}

export function countSources(reports: CitizenReport[], top = 8): SourceCount[] {
  const counts = new Map<string, number>();
  for (const report of reports) {
    for (const source of report.pollutionSources) {
      if (source && source !== "unknown") {
        counts.set(source, (counts.get(source) ?? 0) + 1);
      }
    }
  }
  return Array.from(counts.entries())
    .map(([source, count]) => ({ source, label: labelForSource(source), count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, top);
}

export function countCategories(reports: CitizenReport[]): CategoryCount[] {
  const counts = new Map<string, number>();
  for (const report of reports) {
    if (report.status === "analyzed" && report.estimatedAqi !== null) {
      const band = bandForAqi(report.estimatedAqi);
      counts.set(band.category, (counts.get(band.category) ?? 0) + 1);
    }
  }
  return ["good", "satisfactory", "moderate", "poor", "very_poor", "severe"].map((category) => {
    const band = bandForAqi(category === "good" ? 25 : category === "satisfactory" ? 75 : category === "moderate" ? 150 : category === "poor" ? 250 : category === "very_poor" ? 350 : 450);
    return { category, label: band.label, count: counts.get(category) ?? 0, color: band.color };
  });
}

export function cityLeaderboard(reports: CitizenReport[], top = 6): Array<{ city: string; reports: number; averageAqi: number | null }> {
  const byCity = new Map<string, { count: number; sum: number; analyzed: number }>();
  for (const report of reports) {
    const city = report.city ?? "Unknown";
    const entry = byCity.get(city) ?? { count: 0, sum: 0, analyzed: 0 };
    entry.count += 1;
    if (report.status === "analyzed" && report.estimatedAqi !== null) {
      entry.sum += report.estimatedAqi;
      entry.analyzed += 1;
    }
    byCity.set(city, entry);
  }
  return Array.from(byCity.entries())
    .map(([city, entry]) => ({ city, reports: entry.count, averageAqi: entry.analyzed ? Math.round(entry.sum / entry.analyzed) : null }))
    .sort((a, b) => b.reports - a.reports)
    .slice(0, top);
}

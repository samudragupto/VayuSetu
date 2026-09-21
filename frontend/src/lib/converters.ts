import type { DocumentData, QueryDocumentSnapshot, Timestamp } from "firebase/firestore";

import type { AlertLogEntry, CitizenReport, GeoPointLike, PredictedHotspot } from "./types";

function toDate(value: unknown): Date | null {
  if (!value) {
    return null;
  }
  if (value instanceof Date) {
    return value;
  }
  if (typeof (value as Timestamp).toDate === "function") {
    return (value as Timestamp).toDate();
  }
  if (typeof value === "string") {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }
  return null;
}

function toNumber(value: unknown): number | null {
  const parsed = typeof value === "string" ? Number(value) : value;
  return typeof parsed === "number" && Number.isFinite(parsed) ? parsed : null;
}

function toGeoPoint(value: unknown): GeoPointLike | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const candidate = value as { latitude?: unknown; longitude?: unknown; _lat?: unknown; _long?: unknown };
  const latitude = toNumber(candidate.latitude ?? candidate._lat);
  const longitude = toNumber(candidate.longitude ?? candidate._long);
  if (latitude === null || longitude === null) {
    return null;
  }
  return { latitude, longitude };
}

function toStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function reportFromDoc(doc: QueryDocumentSnapshot<DocumentData>): CitizenReport {
  const data = doc.data();
  const analysis = (data.geminiAnalysis as CitizenReport["geminiAnalysis"]) ?? null;
  const satellite = (data.satelliteMetrics as Record<string, unknown> | undefined) ?? null;
  return {
    id: doc.id,
    phoneHash: String(data.phoneHash ?? ""),
    status: (data.status as CitizenReport["status"]) ?? "received",
    location: toGeoPoint(data.location),
    geohash: (data.geohash as string | null) ?? null,
    city: (data.city as string | null) ?? null,
    caption: (data.caption as string | null) ?? null,
    createdAt: toDate(data.createdAt),
    analyzedAt: toDate(data.analyzedAt),
    hazeIndex: toNumber(data.hazeIndex ?? analysis?.haze_index),
    visibilityKm: toNumber(data.visibilityKm ?? analysis?.visibility_km),
    estimatedAqi: toNumber(data.estimatedAqi ?? analysis?.estimated_aqi),
    estimatedAqiCategory: (data.estimatedAqiCategory as string | null) ?? analysis?.estimated_aqi_category ?? null,
    pollutionSources: toStringArray(data.pollutionSources ?? analysis?.pollution_sources),
    modelName: (data.modelName as string | null) ?? null,
    geminiAnalysis: analysis,
    satelliteMetrics: satellite
      ? {
          aerAi: toNumber(satellite.aerAi),
          no2TroposphericMolM2: toNumber(satellite.no2TroposphericMolM2),
          coColumnMolM2: toNumber(satellite.coColumnMolM2),
          aod047: toNumber(satellite.aod047),
          s5pImageCount: toNumber(satellite.s5pImageCount) ?? undefined,
          fetchedAt: toDate(satellite.fetchedAt),
        }
      : null,
    error: (data.error as string | null) ?? null,
  };
}

export function hotspotFromDoc(doc: QueryDocumentSnapshot<DocumentData>): PredictedHotspot {
  const data = doc.data();
  const features: Record<string, number> = {};
  if (data.features && typeof data.features === "object") {
    for (const [key, value] of Object.entries(data.features as Record<string, unknown>)) {
      const parsed = toNumber(value);
      if (parsed !== null) {
        features[key] = parsed;
      }
    }
  }
  return {
    id: doc.id,
    geohash: String(data.geohash ?? doc.id.split("_")[0]),
    latitude: toNumber(data.latitude) ?? 0,
    longitude: toNumber(data.longitude) ?? 0,
    city: (data.city as string | null) ?? null,
    generatedAt: toDate(data.generatedAt),
    forecastFor: toDate(data.forecastFor),
    horizonHours: toNumber(data.horizonHours) ?? 12,
    predictedAqi: toNumber(data.predictedAqi) ?? 0,
    predictedCategory: String(data.predictedCategory ?? "moderate"),
    currentAqiEstimate: toNumber(data.currentAqiEstimate),
    reportCount: toNumber(data.reportCount) ?? 0,
    confidence: toNumber(data.confidence) ?? 0,
    modelVersion: String(data.modelVersion ?? "unknown"),
    dominantSources: toStringArray(data.dominantSources),
    alertStatus: (data.alertStatus as PredictedHotspot["alertStatus"]) ?? "not_required",
    features,
  };
}

export function alertFromDoc(doc: QueryDocumentSnapshot<DocumentData>): AlertLogEntry {
  const data = doc.data();
  return {
    id: doc.id,
    hotspotId: String(data.hotspotId ?? ""),
    geohash: String(data.geohash ?? ""),
    predictedAqi: toNumber(data.predictedAqi) ?? 0,
    authorityId: String(data.authorityId ?? ""),
    authorityName: String(data.authorityName ?? "Unknown authority"),
    channel: String(data.channel ?? "voice"),
    language: String(data.language ?? "en"),
    status: String(data.status ?? "unknown"),
    messageText: String(data.messageText ?? ""),
    twilioSid: (data.twilioSid as string | null) ?? null,
    error: (data.error as string | null) ?? null,
    sentAt: toDate(data.sentAt),
  };
}

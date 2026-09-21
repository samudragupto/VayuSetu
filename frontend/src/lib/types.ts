export interface GeoPointLike {
  latitude: number;
  longitude: number;
}

export type ReportStatus = "received" | "analyzing" | "analyzed" | "failed";

export interface GeminiAnalysis {
  is_outdoor_scene?: boolean;
  haze_index?: number;
  visibility_km?: number;
  visibility_category?: string;
  sky_condition?: string;
  smoke_detected?: boolean;
  dust_detected?: boolean;
  fog_or_mist_detected?: boolean;
  open_burning_detected?: boolean;
  vehicle_density_score?: number;
  construction_activity_score?: number;
  industrial_emission_score?: number;
  pollution_sources?: string[];
  estimated_aqi_category?: string;
  estimated_aqi?: number;
  confidence?: number;
  reasoning?: string;
}

export interface SatelliteMetrics {
  aerAi?: number | null;
  no2TroposphericMolM2?: number | null;
  coColumnMolM2?: number | null;
  aod047?: number | null;
  s5pImageCount?: number;
  fetchedAt?: Date | null;
}

export interface CitizenReport {
  id: string;
  phoneHash: string;
  status: ReportStatus;
  location: GeoPointLike | null;
  geohash: string | null;
  city: string | null;
  caption: string | null;
  createdAt: Date | null;
  analyzedAt: Date | null;
  hazeIndex: number | null;
  visibilityKm: number | null;
  estimatedAqi: number | null;
  estimatedAqiCategory: string | null;
  pollutionSources: string[];
  modelName: string | null;
  geminiAnalysis: GeminiAnalysis | null;
  satelliteMetrics: SatelliteMetrics | null;
  error: string | null;
}

export type AlertStatus =
  | "pending"
  | "processing"
  | "sent"
  | "failed"
  | "skipped"
  | "not_required"
  | "below_threshold"
  | "suppressed_cooldown"
  | "no_recipients";

export interface PredictedHotspot {
  id: string;
  geohash: string;
  latitude: number;
  longitude: number;
  city: string | null;
  generatedAt: Date | null;
  forecastFor: Date | null;
  horizonHours: number;
  predictedAqi: number;
  predictedCategory: string;
  currentAqiEstimate: number | null;
  reportCount: number;
  confidence: number;
  modelVersion: string;
  dominantSources: string[];
  alertStatus: AlertStatus;
  features: Record<string, number>;
}

export interface AlertLogEntry {
  id: string;
  hotspotId: string;
  geohash: string;
  predictedAqi: number;
  authorityId: string;
  authorityName: string;
  channel: "voice" | "whatsapp" | string;
  language: string;
  status: string;
  messageText: string;
  twilioSid: string | null;
  error: string | null;
  sentAt: Date | null;
}

export interface TimeRange {
  label: string;
  hours: number;
}

export const TIME_RANGES: TimeRange[] = [
  { label: "6 h", hours: 6 },
  { label: "24 h", hours: 24 },
  { label: "3 d", hours: 72 },
  { label: "7 d", hours: 168 },
];

/** Indian National AQI (CPCB) categories. */
export type AqiCategory = "good" | "satisfactory" | "moderate" | "poor" | "very_poor" | "severe";

export interface AqiBand {
  category: AqiCategory;
  label: string;
  min: number;
  max: number;
  color: string;
  textColor: string;
  advice: string;
}

export const AQI_BANDS: AqiBand[] = [
  { category: "good", label: "Good", min: 0, max: 50, color: "#009966", textColor: "#ffffff", advice: "Minimal impact" },
  { category: "satisfactory", label: "Satisfactory", min: 51, max: 100, color: "#8bc34a", textColor: "#0b2456", advice: "Minor breathing discomfort to sensitive people" },
  { category: "moderate", label: "Moderate", min: 101, max: 200, color: "#ffde33", textColor: "#0b2456", advice: "Breathing discomfort to people with lung or heart disease" },
  { category: "poor", label: "Poor", min: 201, max: 300, color: "#ff9933", textColor: "#0b2456", advice: "Breathing discomfort to most people on prolonged exposure" },
  { category: "very_poor", label: "Very Poor", min: 301, max: 400, color: "#cc0033", textColor: "#ffffff", advice: "Respiratory illness on prolonged exposure" },
  { category: "severe", label: "Severe", min: 401, max: 500, color: "#7e0023", textColor: "#ffffff", advice: "Affects healthy people and seriously impacts those with existing diseases" },
];

export function bandForAqi(aqi: number | null | undefined): AqiBand {
  if (aqi === null || aqi === undefined || Number.isNaN(aqi)) {
    return AQI_BANDS[2]!;
  }
  const value = Math.max(0, Math.min(500, aqi));
  return AQI_BANDS.find((band) => value <= band.max) ?? AQI_BANDS[AQI_BANDS.length - 1]!;
}

export function bandForCategory(category: string | null | undefined): AqiBand {
  return AQI_BANDS.find((band) => band.category === category) ?? AQI_BANDS[2]!;
}

export function formatCategory(category: string | null | undefined): string {
  if (!category) {
    return "Unknown";
  }
  return bandForCategory(category).label;
}

export const ALERT_THRESHOLD = 300;

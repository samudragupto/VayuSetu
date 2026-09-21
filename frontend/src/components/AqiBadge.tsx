import { bandForAqi, bandForCategory } from "@/lib/aqi";

export function AqiBadge({ aqi, category }: { aqi?: number | null; category?: string | null }) {
  const band = aqi !== null && aqi !== undefined ? bandForAqi(aqi) : bandForCategory(category);
  return (
    <span className="badge" style={{ backgroundColor: band.color, color: band.textColor }}>
      {aqi !== null && aqi !== undefined ? `${Math.round(aqi)} ` : ""}
      {band.label}
    </span>
  );
}

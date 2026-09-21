import ngeohash from "ngeohash";

export interface Coordinates {
  latitude: number;
  longitude: number;
}

export interface CityMatch {
  city: string;
  state: string;
  distanceKm: number;
}

/**
 * Compact reference list of major Indian cities used to attach a human
 * readable city label without calling a paid geocoding API. The nearest city
 * within `maxDistanceKm` is used; otherwise the report keeps a null city.
 */
const CITIES: ReadonlyArray<{ city: string; state: string; latitude: number; longitude: number }> = [
  { city: "New Delhi", state: "Delhi", latitude: 28.6139, longitude: 77.209 },
  { city: "Gurugram", state: "Haryana", latitude: 28.4595, longitude: 77.0266 },
  { city: "Noida", state: "Uttar Pradesh", latitude: 28.5355, longitude: 77.391 },
  { city: "Ghaziabad", state: "Uttar Pradesh", latitude: 28.6692, longitude: 77.4538 },
  { city: "Faridabad", state: "Haryana", latitude: 28.4089, longitude: 77.3178 },
  { city: "Mumbai", state: "Maharashtra", latitude: 19.076, longitude: 72.8777 },
  { city: "Navi Mumbai", state: "Maharashtra", latitude: 19.033, longitude: 73.0297 },
  { city: "Pune", state: "Maharashtra", latitude: 18.5204, longitude: 73.8567 },
  { city: "Nagpur", state: "Maharashtra", latitude: 21.1458, longitude: 79.0882 },
  { city: "Bengaluru", state: "Karnataka", latitude: 12.9716, longitude: 77.5946 },
  { city: "Hyderabad", state: "Telangana", latitude: 17.385, longitude: 78.4867 },
  { city: "Chennai", state: "Tamil Nadu", latitude: 13.0827, longitude: 80.2707 },
  { city: "Coimbatore", state: "Tamil Nadu", latitude: 11.0168, longitude: 76.9558 },
  { city: "Kolkata", state: "West Bengal", latitude: 22.5726, longitude: 88.3639 },
  { city: "Howrah", state: "West Bengal", latitude: 22.5958, longitude: 88.2636 },
  { city: "Ahmedabad", state: "Gujarat", latitude: 23.0225, longitude: 72.5714 },
  { city: "Surat", state: "Gujarat", latitude: 21.1702, longitude: 72.8311 },
  { city: "Vadodara", state: "Gujarat", latitude: 22.3072, longitude: 73.1812 },
  { city: "Jaipur", state: "Rajasthan", latitude: 26.9124, longitude: 75.7873 },
  { city: "Jodhpur", state: "Rajasthan", latitude: 26.2389, longitude: 73.0243 },
  { city: "Lucknow", state: "Uttar Pradesh", latitude: 26.8467, longitude: 80.9462 },
  { city: "Kanpur", state: "Uttar Pradesh", latitude: 26.4499, longitude: 80.3319 },
  { city: "Agra", state: "Uttar Pradesh", latitude: 27.1767, longitude: 78.0081 },
  { city: "Varanasi", state: "Uttar Pradesh", latitude: 25.3176, longitude: 82.9739 },
  { city: "Prayagraj", state: "Uttar Pradesh", latitude: 25.4358, longitude: 81.8463 },
  { city: "Meerut", state: "Uttar Pradesh", latitude: 28.9845, longitude: 77.7064 },
  { city: "Patna", state: "Bihar", latitude: 25.5941, longitude: 85.1376 },
  { city: "Ranchi", state: "Jharkhand", latitude: 23.3441, longitude: 85.3096 },
  { city: "Dhanbad", state: "Jharkhand", latitude: 23.7957, longitude: 86.4304 },
  { city: "Bhopal", state: "Madhya Pradesh", latitude: 23.2599, longitude: 77.4126 },
  { city: "Indore", state: "Madhya Pradesh", latitude: 22.7196, longitude: 75.8577 },
  { city: "Raipur", state: "Chhattisgarh", latitude: 21.2514, longitude: 81.6296 },
  { city: "Chandigarh", state: "Chandigarh", latitude: 30.7333, longitude: 76.7794 },
  { city: "Ludhiana", state: "Punjab", latitude: 30.901, longitude: 75.8573 },
  { city: "Amritsar", state: "Punjab", latitude: 31.634, longitude: 74.8723 },
  { city: "Jalandhar", state: "Punjab", latitude: 31.326, longitude: 75.5762 },
  { city: "Dehradun", state: "Uttarakhand", latitude: 30.3165, longitude: 78.0322 },
  { city: "Srinagar", state: "Jammu and Kashmir", latitude: 34.0837, longitude: 74.7973 },
  { city: "Guwahati", state: "Assam", latitude: 26.1445, longitude: 91.7362 },
  { city: "Bhubaneswar", state: "Odisha", latitude: 20.2961, longitude: 85.8245 },
  { city: "Visakhapatnam", state: "Andhra Pradesh", latitude: 17.6868, longitude: 83.2185 },
  { city: "Vijayawada", state: "Andhra Pradesh", latitude: 16.5062, longitude: 80.648 },
  { city: "Kochi", state: "Kerala", latitude: 9.9312, longitude: 76.2673 },
  { city: "Thiruvananthapuram", state: "Kerala", latitude: 8.5241, longitude: 76.9366 },
  { city: "Madurai", state: "Tamil Nadu", latitude: 9.9252, longitude: 78.1198 },
  { city: "Mysuru", state: "Karnataka", latitude: 12.2958, longitude: 76.6394 },
  { city: "Nashik", state: "Maharashtra", latitude: 19.9975, longitude: 73.7898 },
  { city: "Aurangabad", state: "Maharashtra", latitude: 19.8762, longitude: 75.3433 },
  { city: "Jamshedpur", state: "Jharkhand", latitude: 22.8046, longitude: 86.2029 },
  { city: "Gwalior", state: "Madhya Pradesh", latitude: 26.2183, longitude: 78.1828 },
];

const EARTH_RADIUS_KM = 6371.0088;

export function haversineKm(a: Coordinates, b: Coordinates): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(b.latitude - a.latitude);
  const dLon = toRad(b.longitude - a.longitude);
  const lat1 = toRad(a.latitude);
  const lat2 = toRad(b.latitude);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function nearestCity(point: Coordinates, maxDistanceKm = 60): CityMatch | null {
  let best: CityMatch | null = null;
  for (const candidate of CITIES) {
    const distanceKm = haversineKm(point, candidate);
    if (distanceKm <= maxDistanceKm && (best === null || distanceKm < best.distanceKm)) {
      best = { city: candidate.city, state: candidate.state, distanceKm };
    }
  }
  return best;
}

export function encodeGeohash(point: Coordinates, precision: number): string {
  return ngeohash.encode(point.latitude, point.longitude, precision);
}

export function isValidCoordinates(latitude: unknown, longitude: unknown): boolean {
  const lat = Number(latitude);
  const lon = Number(longitude);
  return Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 && !(lat === 0 && lon === 0);
}

/**
 * Parse coordinates from a Twilio WhatsApp location message payload
 * (Latitude/Longitude form fields) or from a free-text "lat, lon" message.
 */
export function parseCoordinates(input: { Latitude?: string; Longitude?: string; Body?: string }): Coordinates | null {
  if (input.Latitude !== undefined && input.Longitude !== undefined && isValidCoordinates(input.Latitude, input.Longitude)) {
    return { latitude: Number(input.Latitude), longitude: Number(input.Longitude) };
  }
  const body = (input.Body ?? "").trim();
  const match = body.match(/(-?\d{1,2}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)/);
  if (match && isValidCoordinates(match[1], match[2])) {
    return { latitude: Number(match[1]), longitude: Number(match[2]) };
  }
  return null;
}

/** Returns true when the point lies inside India's approximate bounding box. */
export function isWithinIndia(point: Coordinates): boolean {
  return point.latitude >= 6.5 && point.latitude <= 37.5 && point.longitude >= 68.0 && point.longitude <= 97.5;
}

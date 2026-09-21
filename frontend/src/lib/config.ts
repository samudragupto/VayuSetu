/**
 * Public runtime configuration. Values are inlined at build time by Next.js,
 * so every setting must use the NEXT_PUBLIC_ prefix.
 */
export interface DashboardConfig {
  firebase: {
    apiKey: string;
    authDomain: string;
    projectId: string;
    storageBucket: string;
    messagingSenderId: string;
    appId: string;
  };
  googleMapsApiKey: string;
  googleMapsMapId: string | undefined;
  adminDomains: string[];
  apiGatewayUrl: string;
  defaultCenter: { lat: number; lng: number };
  useEmulators: boolean;
  firestoreEmulatorHost: string;
  authEmulatorUrl: string;
}

function parseCenter(value: string | undefined): { lat: number; lng: number } {
  const [latText, lngText] = (value ?? "").split(",");
  const lat = Number(latText);
  const lng = Number(lngText);
  if (Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180) {
    return { lat, lng };
  }
  return { lat: 28.6139, lng: 77.209 };
}

export const config: DashboardConfig = {
  firebase: {
    apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY ?? "",
    authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN ?? "",
    projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "",
    storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET ?? "",
    messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID ?? "",
    appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID ?? "",
  },
  googleMapsApiKey: process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ?? "",
  googleMapsMapId: process.env.NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID || undefined,
  adminDomains: (process.env.NEXT_PUBLIC_ADMIN_DOMAIN ?? "")
    .split(",")
    .map((domain) => domain.trim().toLowerCase())
    .filter(Boolean),
  apiGatewayUrl: (process.env.NEXT_PUBLIC_API_GATEWAY_URL ?? "").replace(/\/+$/, ""),
  defaultCenter: parseCenter(process.env.NEXT_PUBLIC_DEFAULT_MAP_CENTER),
  useEmulators: (process.env.NEXT_PUBLIC_USE_EMULATORS ?? "false").toLowerCase() === "true",
  firestoreEmulatorHost: process.env.NEXT_PUBLIC_FIRESTORE_EMULATOR_HOST ?? "localhost:8080",
  authEmulatorUrl: process.env.NEXT_PUBLIC_AUTH_EMULATOR_URL ?? "http://localhost:9099",
};

export function isFirebaseConfigured(): boolean {
  return Boolean(config.firebase.projectId && (config.firebase.apiKey || config.useEmulators));
}

export function isAdminEmail(email: string | null | undefined): boolean {
  if (!email) {
    return false;
  }
  if (config.adminDomains.length === 0) {
    // Without a configured domain the dashboard only works against emulators.
    return config.useEmulators;
  }
  const domain = email.toLowerCase().split("@")[1] ?? "";
  return config.adminDomains.includes(domain);
}

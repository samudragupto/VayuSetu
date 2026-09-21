import { z } from "zod";

const booleanFromEnv = z
  .union([z.boolean(), z.string()])
  .transform((value) => {
    if (typeof value === "boolean") {
      return value;
    }
    return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
  });

const configSchema = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  PORT: z.coerce.number().int().min(1).max(65535).default(8080),
  LOG_LEVEL: z.enum(["trace", "debug", "info", "warn", "error", "fatal"]).default("info"),

  GCP_PROJECT_ID: z.string().min(1, "GCP_PROJECT_ID is required"),
  GCS_BUCKET: z.string().min(1, "GCS_BUCKET is required"),
  GCS_REPORT_PREFIX: z.string().default("reports"),

  TWILIO_ACCOUNT_SID: z.string().min(1, "TWILIO_ACCOUNT_SID is required"),
  TWILIO_AUTH_TOKEN: z.string().min(1, "TWILIO_AUTH_TOKEN is required"),
  TWILIO_WHATSAPP_FROM: z.string().default(""),
  TWILIO_VALIDATE_SIGNATURE: booleanFromEnv.default(true),
  TWILIO_MEDIA_BASE_URL: z.string().url().optional(),

  PHONE_HASH_SECRET: z.string().min(8, "PHONE_HASH_SECRET must be at least 8 characters"),

  ADMIN_DOMAIN: z.string().default(""),
  PUBLIC_BASE_URL: z.string().url().optional(),
  HOTSPOT_GEOHASH_PRECISION: z.coerce.number().int().min(3).max(9).default(5),
  REPORT_GEOHASH_PRECISION: z.coerce.number().int().min(5).max(12).default(7),
  LOCATION_MAX_AGE_HOURS: z.coerce.number().min(0.1).default(24),
  PENDING_LOCATION_WINDOW_MINUTES: z.coerce.number().min(1).default(30),
  MAX_IMAGE_BYTES: z.coerce.number().int().min(1024).default(10 * 1024 * 1024),
  RATE_LIMIT_PER_HOUR: z.coerce.number().int().min(1).default(30),
  REQUEST_TIMEOUT_MS: z.coerce.number().int().min(1000).default(12000),

  FIRESTORE_EMULATOR_HOST: z.string().optional(),
  STORAGE_EMULATOR_HOST: z.string().optional(),
});

export type AppConfig = z.infer<typeof configSchema>;

/**
 * Parse and validate configuration from environment variables.
 * Fails fast with a readable message when a required setting is missing.
 */
export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  const result = configSchema.safeParse(env);
  if (!result.success) {
    const problems = result.error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`).join("; ");
    throw new Error(`Invalid configuration: ${problems}`);
  }
  return result.data;
}

export const SUPPORTED_LANGUAGES = ["en", "hi", "bn", "ta", "te", "mr", "gu", "kn", "ml", "pa"] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

export function isSupportedLanguage(value: string): value is SupportedLanguage {
  return (SUPPORTED_LANGUAGES as readonly string[]).includes(value);
}

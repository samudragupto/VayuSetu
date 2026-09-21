import pino from "pino";

/**
 * Structured JSON logger compatible with Cloud Logging. The `severity` field
 * lets Cloud Run map log levels correctly and `message` is used as the
 * primary display field.
 */
const PINO_TO_GCP_SEVERITY: Record<string, string> = {
  trace: "DEBUG",
  debug: "DEBUG",
  info: "INFO",
  warn: "WARNING",
  error: "ERROR",
  fatal: "CRITICAL",
};

export function createLogger(level: string = process.env.LOG_LEVEL ?? "info", service = "vayusetu-api-gateway") {
  return pino({
    level,
    base: { service },
    messageKey: "message",
    timestamp: pino.stdTimeFunctions.isoTime,
    formatters: {
      level(label: string) {
        return { severity: PINO_TO_GCP_SEVERITY[label] ?? "DEFAULT", level: label };
      },
    },
    redact: {
      paths: ["req.headers.authorization", "req.headers.cookie", "phoneNumber", "*.phoneNumber", "From", "body.From"],
      censor: "[redacted]",
    },
  });
}

export type Logger = ReturnType<typeof createLogger>;

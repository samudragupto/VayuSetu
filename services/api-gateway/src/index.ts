import { loadConfig } from "./config";
import { createApp } from "./app";
import { createLogger } from "./logger";
import { FirebaseTokenVerifier } from "./middleware/firebaseAuth";
import { createFirestore, FirestoreReportRepository, FirestoreUserRepository, FirestoreWebhookEventStore } from "./services/firestore";
import { IngestionService } from "./services/ingestion";
import { createStorage, GcsImageStore } from "./services/storage";
import { TwilioMediaFetcher } from "./services/twilio";

async function main(): Promise<void> {
  const config = loadConfig();
  const logger = createLogger(config.LOG_LEVEL);

  const firestore = createFirestore(config.GCP_PROJECT_ID);
  const storage = createStorage(config.GCP_PROJECT_ID);

  const ingestion = new IngestionService({
    config,
    logger,
    reports: new FirestoreReportRepository(firestore),
    users: new FirestoreUserRepository(firestore),
    events: new FirestoreWebhookEventStore(firestore),
    images: new GcsImageStore(storage, config.GCS_BUCKET, config.GCS_REPORT_PREFIX, logger),
    media: new TwilioMediaFetcher(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN, logger, {
      allowedBaseUrl: config.TWILIO_MEDIA_BASE_URL,
      timeoutMs: Math.min(config.REQUEST_TIMEOUT_MS - 2000, 8000),
    }),
  });

  const app = createApp({
    config,
    logger,
    ingestion,
    firestore,
    tokenVerifier: new FirebaseTokenVerifier(config.GCP_PROJECT_ID),
    readinessProbes: [
      {
        name: "firestore",
        check: async () => {
          await firestore.collection("config").doc("access").get();
        },
      },
    ],
  });

  const server = app.listen(config.PORT, "0.0.0.0", () => {
    logger.info(
      {
        port: config.PORT,
        env: config.NODE_ENV,
        bucket: config.GCS_BUCKET,
        signatureValidation: config.TWILIO_VALIDATE_SIGNATURE,
        emulators: { firestore: config.FIRESTORE_EMULATOR_HOST ?? null, storage: config.STORAGE_EMULATOR_HOST ?? null },
      },
      "VayuSetu API gateway listening"
    );
  });
  server.keepAliveTimeout = 620_000;
  server.headersTimeout = 650_000;

  const shutdown = (signal: string) => {
    logger.info({ signal }, "Shutting down");
    server.close((error) => {
      if (error) {
        logger.error({ err: error }, "Error during shutdown");
        process.exit(1);
      }
      process.exit(0);
    });
    setTimeout(() => process.exit(1), 10_000).unref();
  };
  process.on("SIGTERM", () => shutdown("SIGTERM"));
  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("unhandledRejection", (reason) => logger.error({ err: reason }, "Unhandled promise rejection"));
}

main().catch((error) => {
  console.error("Fatal startup error:", error);
  process.exit(1);
});

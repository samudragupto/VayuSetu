import express from "express";
import type { Express } from "express";
import type { Firestore } from "@google-cloud/firestore";
import helmet from "helmet";
import { pinoHttp } from "pino-http";

import type { AppConfig } from "./config";
import type { Logger } from "./logger";
import type { TokenVerifier } from "./middleware/firebaseAuth";
import { errorHandler, notFoundHandler } from "./middleware/errorHandler";
import { apiRouter } from "./routes/api";
import { healthRouter } from "./routes/health";
import type { ReadinessProbe } from "./routes/health";
import { webhookRouter } from "./routes/webhooks";
import type { IngestionService } from "./services/ingestion";

export interface AppDependencies {
  config: AppConfig;
  logger: Logger;
  ingestion: IngestionService;
  firestore?: Firestore;
  tokenVerifier?: TokenVerifier;
  readinessProbes?: ReadinessProbe[];
}

/** Build the Express application with all routes and middleware wired. */
export function createApp(deps: AppDependencies): Express {
  const { config, logger } = deps;
  const app = express();

  app.set("trust proxy", true);
  app.disable("x-powered-by");
  app.use(helmet({ contentSecurityPolicy: false }));
  app.use(
    pinoHttp({
      logger,
      autoLogging: { ignore: (req) => req.url === "/healthz" || req.url === "/readyz" },
      customProps: (req) => ({ requestId: req.headers["x-cloud-trace-context"] ?? req.headers["x-request-id"] }),
    })
  );
  app.use(express.urlencoded({ extended: false, limit: "64kb" }));
  app.use(express.json({ limit: "256kb" }));

  app.use(healthRouter(config, deps.readinessProbes ?? []));
  app.use("/webhooks", webhookRouter(config, logger, deps.ingestion));
  if (deps.firestore && deps.tokenVerifier) {
    app.use("/api/v1", apiRouter(config, logger, deps.firestore, deps.tokenVerifier));
  }

  app.use(notFoundHandler);
  app.use(errorHandler(logger));
  return app;
}

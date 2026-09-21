import { Router } from "express";

import type { AppConfig } from "../config";

export interface ReadinessProbe {
  name: string;
  check: () => Promise<void>;
}

export function healthRouter(config: AppConfig, probes: ReadinessProbe[] = [], version = process.env.SERVICE_VERSION ?? "dev"): Router {
  const router = Router();
  const startedAt = new Date();

  router.get("/healthz", (_req, res) => {
    res.json({ status: "ok", service: "vayusetu-api-gateway", version, uptimeSeconds: Math.round(process.uptime()), startedAt });
  });

  router.get("/readyz", async (_req, res) => {
    const results: Record<string, string> = {};
    let healthy = true;
    await Promise.all(
      probes.map(async (probe) => {
        try {
          await probe.check();
          results[probe.name] = "ok";
        } catch (error) {
          healthy = false;
          results[probe.name] = (error as Error).message;
        }
      })
    );
    res.status(healthy ? 200 : 503).json({
      status: healthy ? "ready" : "degraded",
      checks: results,
      config: {
        projectId: config.GCP_PROJECT_ID,
        bucket: config.GCS_BUCKET,
        signatureValidation: config.TWILIO_VALIDATE_SIGNATURE,
        geohashPrecision: config.HOTSPOT_GEOHASH_PRECISION,
      },
    });
  });

  return router;
}

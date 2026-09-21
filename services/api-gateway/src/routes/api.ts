import { Router } from "express";
import type { Firestore } from "@google-cloud/firestore";
import { Timestamp } from "@google-cloud/firestore";

import type { AppConfig } from "../config";
import type { Logger } from "../logger";
import { firebaseAuthMiddleware } from "../middleware/firebaseAuth";
import type { TokenVerifier } from "../middleware/firebaseAuth";
import { COLLECTIONS } from "../services/firestore";

function clampInt(value: unknown, fallback: number, min: number, max: number): number {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, parsed));
}

function serialise(value: unknown): unknown {
  if (value instanceof Timestamp) {
    return value.toDate().toISOString();
  }
  if (Array.isArray(value)) {
    return value.map(serialise);
  }
  if (value && typeof value === "object") {
    const candidate = value as { latitude?: unknown; longitude?: unknown };
    if (typeof candidate.latitude === "number" && typeof candidate.longitude === "number" && Object.keys(value).length <= 3) {
      return { latitude: candidate.latitude, longitude: candidate.longitude };
    }
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, serialise(v)]));
  }
  return value;
}

/**
 * Authority-facing read API. The dashboard primarily reads Firestore
 * directly with security rules, but these endpoints provide an audited,
 * server-side alternative for integrations and demos.
 */
export function apiRouter(config: AppConfig, logger: Logger, db: Firestore, verifier: TokenVerifier): Router {
  const router = Router();
  router.use(firebaseAuthMiddleware(config, verifier, logger));

  router.get("/hotspots", async (req, res, next) => {
    try {
      const hours = clampInt(req.query.hours, 24, 1, 24 * 14);
      const limit = clampInt(req.query.limit, 200, 1, 1000);
      const since = Timestamp.fromMillis(Date.now() - hours * 3_600_000);
      const snapshot = await db
        .collection(COLLECTIONS.hotspots)
        .where("generatedAt", ">=", since)
        .orderBy("generatedAt", "desc")
        .limit(limit)
        .get();
      res.json({ count: snapshot.size, items: snapshot.docs.map((doc) => ({ id: doc.id, ...(serialise(doc.data()) as object) })) });
    } catch (error) {
      next(error);
    }
  });

  router.get("/reports", async (req, res, next) => {
    try {
      const hours = clampInt(req.query.hours, 24, 1, 24 * 14);
      const limit = clampInt(req.query.limit, 500, 1, 2000);
      const since = Timestamp.fromMillis(Date.now() - hours * 3_600_000);
      const snapshot = await db
        .collection(COLLECTIONS.reports)
        .where("createdAt", ">=", since)
        .orderBy("createdAt", "desc")
        .limit(limit)
        .get();
      const items = snapshot.docs.map((doc) => {
        const data = serialise(doc.data()) as Record<string, unknown>;
        // Never expose the message SID or raw metadata to dashboard consumers.
        delete data.messageSid;
        delete data.metadata;
        return { id: doc.id, ...data };
      });
      res.json({ count: items.length, items });
    } catch (error) {
      next(error);
    }
  });

  router.get("/stats", async (req, res, next) => {
    try {
      const hours = clampInt(req.query.hours, 24, 1, 24 * 14);
      const since = Timestamp.fromMillis(Date.now() - hours * 3_600_000);
      const [reports, analyzed, hotspots, alerts] = await Promise.all([
        db.collection(COLLECTIONS.reports).where("createdAt", ">=", since).count().get(),
        db.collection(COLLECTIONS.reports).where("createdAt", ">=", since).where("status", "==", "analyzed").count().get(),
        db.collection(COLLECTIONS.hotspots).where("generatedAt", ">=", since).count().get(),
        db.collection(COLLECTIONS.hotspots).where("generatedAt", ">=", since).where("alertStatus", "in", ["pending", "sent"]).count().get(),
      ]);
      res.json({
        windowHours: hours,
        reports: reports.data().count,
        analyzedReports: analyzed.data().count,
        hotspots: hotspots.data().count,
        alerts: alerts.data().count,
        requestedBy: req.identity?.email,
      });
    } catch (error) {
      next(error);
    }
  });

  return router;
}

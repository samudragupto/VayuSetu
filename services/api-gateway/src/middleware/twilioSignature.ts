import type { NextFunction, Request, Response } from "express";

import type { AppConfig } from "../config";
import type { Logger } from "../logger";
import { validateTwilioSignature } from "../services/twilio";

/**
 * Reconstruct the public URL Twilio used when signing the request. Behind
 * Cloud Run the request arrives over HTTP with X-Forwarded-Proto set, so the
 * forwarded values (or an explicit PUBLIC_BASE_URL) take precedence.
 */
export function publicRequestUrl(req: Request, publicBaseUrl?: string): string {
  if (publicBaseUrl) {
    return `${publicBaseUrl.replace(/\/+$/, "")}${req.originalUrl}`;
  }
  const protoHeader = req.get("x-forwarded-proto");
  const proto = protoHeader ? protoHeader.split(",")[0]?.trim() : req.protocol;
  const hostHeader = req.get("x-forwarded-host") ?? req.get("host") ?? "";
  const host = hostHeader.split(",")[0]?.trim() ?? "";
  return `${proto}://${host}${req.originalUrl}`;
}

function flattenBody(body: unknown): Record<string, string> {
  const result: Record<string, string> = {};
  if (typeof body !== "object" || body === null) {
    return result;
  }
  for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
    if (Array.isArray(value)) {
      result[key] = String(value[value.length - 1] ?? "");
    } else if (value !== undefined && value !== null) {
      result[key] = String(value);
    }
  }
  return result;
}

export function twilioSignatureMiddleware(config: AppConfig, logger: Logger) {
  return (req: Request, res: Response, next: NextFunction): void => {
    if (!config.TWILIO_VALIDATE_SIGNATURE) {
      next();
      return;
    }
    const signature = req.get("x-twilio-signature");
    const url = publicRequestUrl(req, config.PUBLIC_BASE_URL);
    const valid = validateTwilioSignature(config.TWILIO_AUTH_TOKEN, signature, url, flattenBody(req.body));
    if (!valid) {
      logger.warn({ url, hasSignature: Boolean(signature) }, "Rejected request with invalid Twilio signature");
      res.status(403).type("text/plain").send("Invalid Twilio signature");
      return;
    }
    next();
  };
}

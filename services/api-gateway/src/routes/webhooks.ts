import { Router } from "express";
import type { Request, Response } from "express";

import type { AppConfig } from "../config";
import type { Logger } from "../logger";
import { twilioSignatureMiddleware } from "../middleware/twilioSignature";
import type { IngestionService, InboundMedia, InboundMessage } from "../services/ingestion";
import { buildTwimlReply } from "../services/twilio";

function field(body: Record<string, unknown>, key: string): string | undefined {
  const value = body[key];
  if (Array.isArray(value)) {
    return value.length ? String(value[value.length - 1]) : undefined;
  }
  return value === undefined || value === null ? undefined : String(value);
}

/** Convert a Twilio inbound webhook form payload into a typed message. */
export function parseInboundMessage(body: Record<string, unknown>): InboundMessage | null {
  const messageSid = field(body, "MessageSid") ?? field(body, "SmsMessageSid");
  const from = field(body, "From");
  if (!messageSid || !from) {
    return null;
  }
  const numMedia = Math.max(0, Math.min(10, Number(field(body, "NumMedia") ?? 0) || 0));
  const media: InboundMedia[] = [];
  for (let index = 0; index < numMedia; index += 1) {
    const url = field(body, `MediaUrl${index}`);
    if (url) {
      media.push({ url, contentType: field(body, `MediaContentType${index}`) ?? "application/octet-stream" });
    }
  }
  return {
    messageSid,
    from,
    to: field(body, "To") ?? "",
    body: field(body, "Body") ?? "",
    profileName: field(body, "ProfileName") ?? null,
    media,
    latitude: field(body, "Latitude"),
    longitude: field(body, "Longitude"),
    address: field(body, "Address"),
    label: field(body, "Label"),
  };
}

function sendTwiml(res: Response, replies: string[]): void {
  res.status(200).type("text/xml").send(buildTwimlReply(replies));
}

export function webhookRouter(config: AppConfig, logger: Logger, ingestion: IngestionService): Router {
  const router = Router();
  const verifySignature = twilioSignatureMiddleware(config, logger);

  router.post("/twilio/whatsapp", verifySignature, async (req: Request, res: Response) => {
    const message = parseInboundMessage((req.body ?? {}) as Record<string, unknown>);
    if (!message) {
      res.status(400).type("text/plain").send("MessageSid and From are required");
      return;
    }

    // Twilio times out webhooks after 15 seconds; answer within budget and let
    // the remaining work finish in the background if the media is slow.
    let responded = false;
    const timer = setTimeout(() => {
      if (!responded) {
        responded = true;
        logger.warn({ messageSid: message.messageSid }, "Ingestion exceeded response budget; replying early");
        sendTwiml(res, ["Thank you. Your report is being processed and you will receive a confirmation shortly."]);
      }
    }, config.REQUEST_TIMEOUT_MS);

    try {
      const outcome = await ingestion.handle(message);
      clearTimeout(timer);
      if (!responded) {
        responded = true;
        req.log?.info({ outcome: outcome.kind, reportId: outcome.reportId }, "Webhook processed");
        sendTwiml(res, outcome.replies);
      }
    } catch (error) {
      clearTimeout(timer);
      logger.error({ err: error, messageSid: message.messageSid }, "Webhook handler failed");
      if (!responded) {
        responded = true;
        sendTwiml(res, ["We could not process your message right now. Please try again in a few minutes."]);
      }
    }
  });

  router.post("/twilio/status", verifySignature, (req: Request, res: Response) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    logger.info(
      {
        messageSid: field(body, "MessageSid"),
        status: field(body, "MessageStatus") ?? field(body, "SmsStatus"),
        errorCode: field(body, "ErrorCode"),
      },
      "Twilio delivery status update"
    );
    res.status(204).end();
  });

  return router;
}

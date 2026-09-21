import { request as undiciRequest } from "undici";
import type { Dispatcher } from "undici";
import twilio from "twilio";

import { withRetry } from "../lib/retry";
import type { Logger } from "../logger";

export interface MediaDownload {
  body: Buffer;
  contentType: string;
}

export interface MediaFetcher {
  fetch(mediaUrl: string, maxBytes: number): Promise<MediaDownload>;
}

export class MediaTooLargeError extends Error {
  constructor(public readonly limit: number) {
    super(`Media exceeds the ${limit} byte limit`);
    this.name = "MediaTooLargeError";
  }
}

export class MediaDownloadError extends Error {
  constructor(message: string, public readonly status?: number) {
    super(message);
    this.name = "MediaDownloadError";
  }
}

type RequestFn = (url: string, options: { method: "GET"; headers: Record<string, string>; headersTimeout: number; bodyTimeout: number }) => Promise<Dispatcher.ResponseData>;

/**
 * Downloads WhatsApp media from Twilio using HTTP basic authentication.
 * Media URLs are only fetched if they belong to the Twilio API host (or a
 * configured local mock) to prevent server-side request forgery.
 */
export class TwilioMediaFetcher implements MediaFetcher {
  private readonly allowedHosts: Set<string>;

  constructor(
    private readonly accountSid: string,
    private readonly authToken: string,
    private readonly logger: Logger,
    options: { allowedBaseUrl?: string; timeoutMs?: number; requestFn?: RequestFn } = {}
  ) {
    this.allowedHosts = new Set(["api.twilio.com", "media.twiliocdn.com"]);
    if (options.allowedBaseUrl) {
      this.allowedHosts.add(new URL(options.allowedBaseUrl).host);
    }
    this.timeoutMs = options.timeoutMs ?? 8000;
    this.requestFn = options.requestFn ?? ((url, opts) => undiciRequest(url, opts));
  }

  private readonly timeoutMs: number;
  private readonly requestFn: RequestFn;

  isAllowed(mediaUrl: string): boolean {
    try {
      const parsed = new URL(mediaUrl);
      const host = parsed.host;
      return (
        (parsed.protocol === "https:" || parsed.hostname === "localhost" || parsed.hostname.endsWith(".internal") || /^[a-z0-9-]+$/i.test(parsed.hostname)) &&
        this.allowedHosts.has(host)
      );
    } catch {
      return false;
    }
  }

  async fetch(mediaUrl: string, maxBytes: number): Promise<MediaDownload> {
    if (!this.isAllowed(mediaUrl)) {
      throw new MediaDownloadError(`Refusing to download media from untrusted host: ${mediaUrl}`);
    }
    const credentials = Buffer.from(`${this.accountSid}:${this.authToken}`).toString("base64");

    return withRetry(
      async () => {
        const response = await this.requestFn(mediaUrl, {
          method: "GET",
          headers: { authorization: `Basic ${credentials}`, accept: "image/*" },
          headersTimeout: this.timeoutMs,
          bodyTimeout: this.timeoutMs,
        });
        if (response.statusCode >= 400) {
          await response.body.dump();
          throw new MediaDownloadError(`Twilio media download failed with HTTP ${response.statusCode}`, response.statusCode);
        }
        const declared = Number(response.headers["content-length"] ?? 0);
        if (declared > maxBytes) {
          await response.body.dump();
          throw new MediaTooLargeError(maxBytes);
        }
        const chunks: Buffer[] = [];
        let total = 0;
        for await (const chunk of response.body) {
          const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
          total += buffer.byteLength;
          if (total > maxBytes) {
            throw new MediaTooLargeError(maxBytes);
          }
          chunks.push(buffer);
        }
        const contentTypeHeader = response.headers["content-type"];
        const contentType = (Array.isArray(contentTypeHeader) ? contentTypeHeader[0] : contentTypeHeader) ?? "application/octet-stream";
        return { body: Buffer.concat(chunks, total), contentType: contentType.split(";")[0]?.trim() ?? contentType };
      },
      {
        attempts: 3,
        shouldRetry: (error) => error instanceof MediaDownloadError && (error.status === undefined || error.status === 429 || error.status >= 500),
        onRetry: (error, attempt, delayMs) => this.logger.warn({ err: error, attempt, delayMs }, "Retrying Twilio media download"),
      }
    );
  }
}

/** Build a TwiML messaging response with one or more messages. */
export function buildTwimlReply(messages: string[]): string {
  const response = new twilio.twiml.MessagingResponse();
  for (const message of messages) {
    response.message(message);
  }
  return response.toString();
}

export function validateTwilioSignature(authToken: string, signature: string | undefined, url: string, params: Record<string, string>): boolean {
  if (!signature) {
    return false;
  }
  return twilio.validateRequest(authToken, signature, url, params);
}

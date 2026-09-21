import { randomUUID } from "node:crypto";

import type { AppConfig } from "../config";
import { encodeGeohash, isWithinIndia, nearestCity, parseCoordinates } from "../lib/geo";
import type { Coordinates } from "../lib/geo";
import { hashPhoneNumber, maskPhoneNumber, normalisePhoneNumber } from "../lib/phone";
import type { Logger } from "../logger";
import type { LocationSource, ReportRepository, UserProfile, UserRepository, WebhookEventStore } from "./firestore";
import { parseLanguageCommand, renderMessage, shortReportId } from "./messages";
import type { ImageStore } from "./storage";
import { isSupportedImage } from "./storage";
import { MediaTooLargeError } from "./twilio";
import type { MediaFetcher } from "./twilio";

export interface InboundMedia {
  url: string;
  contentType: string;
}

export interface InboundMessage {
  messageSid: string;
  from: string;
  to: string;
  body: string;
  profileName: string | null;
  media: InboundMedia[];
  latitude?: string;
  longitude?: string;
  address?: string;
  label?: string;
}

export type OutcomeKind =
  | "report_created"
  | "location_saved"
  | "language_set"
  | "help"
  | "status"
  | "rejected"
  | "duplicate"
  | "rate_limited"
  | "error";

export interface IngestionOutcome {
  kind: OutcomeKind;
  replies: string[];
  reportId?: string;
  reason?: string;
}

export interface IngestionDependencies {
  config: AppConfig;
  logger: Logger;
  reports: ReportRepository;
  users: UserRepository;
  events: WebhookEventStore;
  images: ImageStore;
  media: MediaFetcher;
  now?: () => Date;
  idGenerator?: () => string;
}

interface ResolvedLocation {
  coordinates: Coordinates;
  source: LocationSource;
}

/**
 * Orchestrates the WhatsApp ingestion flow: identity, idempotency, location
 * handling, media validation, Firestore logging and Cloud Storage upload.
 *
 * Ordering matters: the Firestore report document is created before the
 * image is uploaded so that the storage-triggered vision function always
 * finds the report metadata when it starts processing.
 */
export class IngestionService {
  private readonly now: () => Date;
  private readonly newId: () => string;

  constructor(private readonly deps: IngestionDependencies) {
    this.now = deps.now ?? (() => new Date());
    this.newId = deps.idGenerator ?? (() => randomUUID().replace(/-/g, ""));
  }

  async handle(message: InboundMessage): Promise<IngestionOutcome> {
    const { config, logger } = this.deps;
    const phoneNumber = normalisePhoneNumber(message.from);
    const phoneHash = hashPhoneNumber(phoneNumber, config.PHONE_HASH_SECRET);
    const log = logger.child({ messageSid: message.messageSid, phone: maskPhoneNumber(phoneNumber), phoneHash });

    const fresh = await this.deps.events.recordOnce(message.messageSid, {
      phoneHash,
      numMedia: message.media.length,
      hasLocation: Boolean(message.latitude && message.longitude),
    });
    if (!fresh) {
      log.info("Duplicate webhook delivery ignored");
      return { kind: "duplicate", replies: [] };
    }

    const user = await this.deps.users.upsertOnContact(phoneHash, `whatsapp:${phoneNumber}`, message.profileName);
    const language = user.language || "en";

    try {
      const shared = parseCoordinates({ Latitude: message.latitude, Longitude: message.longitude });
      if (shared) {
        return await this.handleLocation(phoneHash, shared, message, language, log);
      }
      if (message.media.length > 0) {
        return await this.handleMedia(phoneHash, user, message, language, log);
      }
      return await this.handleText(phoneHash, message.body, language, log);
    } catch (error) {
      log.error({ err: error }, "Ingestion failed");
      return { kind: "error", replies: [renderMessage(language, "temporaryFailure")], reason: (error as Error).message };
    }
  }

  private async handleLocation(
    phoneHash: string,
    coordinates: Coordinates,
    message: InboundMessage,
    language: string,
    log: Logger
  ): Promise<IngestionOutcome> {
    if (!isWithinIndia(coordinates)) {
      log.info({ coordinates }, "Location outside supported area");
      return { kind: "rejected", replies: [renderMessage(language, "outsideIndia")], reason: "outside_india" };
    }
    const label = message.address ?? message.label ?? null;
    await this.deps.users.updateLocation(phoneHash, coordinates, label);
    const match = nearestCity(coordinates);

    const windowStart = new Date(this.now().getTime() - this.deps.config.PENDING_LOCATION_WINDOW_MINUTES * 60_000);
    const pendingReportId = await this.deps.reports.findPendingLocationReport(phoneHash, windowStart);
    if (pendingReportId) {
      const geohash = encodeGeohash(coordinates, this.deps.config.REPORT_GEOHASH_PRECISION);
      await this.deps.reports.attachLocation(pendingReportId, coordinates, geohash, match?.city ?? null, match?.state ?? null);
      log.info({ reportId: pendingReportId, city: match?.city }, "Attached location to pending report");
      return {
        kind: "location_saved",
        reportId: pendingReportId,
        replies: [renderMessage(language, "locationAttached", { shortId: shortReportId(pendingReportId), city: match?.city ?? null })],
      };
    }

    log.info({ city: match?.city }, "Saved user location");
    return { kind: "location_saved", replies: [renderMessage(language, "locationSaved", { city: match?.city ?? null })] };
  }

  private resolveLocation(user: UserProfile, body: string): ResolvedLocation | null {
    const fromText = parseCoordinates({ Body: body });
    if (fromText && isWithinIndia(fromText)) {
      return { coordinates: fromText, source: "text" };
    }
    const last = user.lastLocation;
    const lastAt = user.lastLocationAt;
    if (last && lastAt) {
      const ageMs = this.now().getTime() - lastAt.toMillis();
      if (ageMs <= this.deps.config.LOCATION_MAX_AGE_HOURS * 3_600_000) {
        return { coordinates: { latitude: last.latitude, longitude: last.longitude }, source: "user_profile" };
      }
    }
    return null;
  }

  private async handleMedia(
    phoneHash: string,
    user: UserProfile,
    message: InboundMessage,
    language: string,
    log: Logger
  ): Promise<IngestionOutcome> {
    const { config } = this.deps;
    const image = message.media.find((item) => isSupportedImage(item.contentType));
    if (!image) {
      log.info({ types: message.media.map((m) => m.contentType) }, "Unsupported media rejected");
      return { kind: "rejected", replies: [renderMessage(language, "unsupportedMedia")], reason: "unsupported_media" };
    }

    const hourAgo = new Date(this.now().getTime() - 3_600_000);
    const recent = await this.deps.reports.countRecentForUser(phoneHash, hourAgo);
    if (recent >= config.RATE_LIMIT_PER_HOUR) {
      log.warn({ recent }, "Per-user rate limit reached");
      return { kind: "rate_limited", replies: [renderMessage(language, "rateLimited", { limit: config.RATE_LIMIT_PER_HOUR })] };
    }

    let download;
    try {
      download = await this.deps.media.fetch(image.url, config.MAX_IMAGE_BYTES);
    } catch (error) {
      if (error instanceof MediaTooLargeError) {
        return { kind: "rejected", replies: [renderMessage(language, "mediaTooLarge", { limit: config.MAX_IMAGE_BYTES })], reason: "too_large" };
      }
      throw error;
    }
    const contentType = isSupportedImage(download.contentType) ? download.contentType : image.contentType;

    const reportId = this.newId();
    const receivedAt = this.now();
    const location = this.resolveLocation(user, message.body);
    const cityMatch = location ? nearestCity(location.coordinates) : null;
    const objectName = this.deps.images.buildObjectName(reportId, contentType, receivedAt);
    const imageUri = `gs://${config.GCS_BUCKET}/${objectName}`;

    await this.deps.reports.create({
      reportId,
      phoneHash,
      messageSid: message.messageSid,
      imageUri,
      contentType,
      caption: message.body.trim() || null,
      location: location?.coordinates ?? null,
      geohash: location ? encodeGeohash(location.coordinates, config.REPORT_GEOHASH_PRECISION) : null,
      city: cityMatch?.city ?? null,
      state: cityMatch?.state ?? null,
      locationSource: location?.source ?? "unknown",
      source: "whatsapp",
      metadata: { profileName: message.profileName, to: message.to, sizeBytes: download.body.byteLength },
    });

    try {
      await this.deps.images.upload({
        reportId,
        phoneHash,
        messageSid: message.messageSid,
        contentType,
        body: download.body,
        receivedAt,
      });
    } catch (error) {
      await this.deps.reports.markUploadFailed(reportId, `upload_failed: ${(error as Error).message}`);
      throw error;
    }

    await this.deps.users.incrementReportCount(phoneHash);
    log.info({ reportId, imageUri, locationSource: location?.source ?? "unknown", city: cityMatch?.city }, "Citizen report created");

    const shortId = shortReportId(reportId);
    const reply = location
      ? renderMessage(language, "reportAccepted", { shortId, city: cityMatch?.city ?? null })
      : renderMessage(language, "reportAcceptedNoLocation", { shortId });
    return { kind: "report_created", reportId, replies: [reply] };
  }

  private async handleText(phoneHash: string, body: string, language: string, log: Logger): Promise<IngestionOutcome> {
    const text = body.trim();
    const requestedLanguage = parseLanguageCommand(text);
    if (requestedLanguage) {
      await this.deps.users.setLanguage(phoneHash, requestedLanguage);
      log.info({ language: requestedLanguage }, "Language preference updated");
      return { kind: "language_set", replies: [renderMessage(requestedLanguage, "languageSet", { language: requestedLanguage })] };
    }

    if (/^(status|स्थिति)$/i.test(text)) {
      const latest = await this.deps.reports.latestForUser(phoneHash);
      if (!latest) {
        return { kind: "status", replies: [renderMessage(language, "statusNone")] };
      }
      const shortId = shortReportId(latest.reportId);
      if (latest.status === "analyzed") {
        return {
          kind: "status",
          reportId: latest.reportId,
          replies: [
            renderMessage(language, "statusAnalyzed", {
              shortId,
              aqi: latest.estimatedAqi === null ? null : Math.round(latest.estimatedAqi),
              category: latest.estimatedAqiCategory,
              city: latest.city,
            }),
          ],
        };
      }
      return { kind: "status", reportId: latest.reportId, replies: [renderMessage(language, "statusPending", { shortId })] };
    }

    const coordinates = parseCoordinates({ Body: text });
    if (coordinates && isWithinIndia(coordinates)) {
      await this.deps.users.updateLocation(phoneHash, coordinates, null);
      const match = nearestCity(coordinates);
      return { kind: "location_saved", replies: [renderMessage(language, "locationSaved", { city: match?.city ?? null })] };
    }

    return { kind: "help", replies: [renderMessage(language, "help")] };
  }
}

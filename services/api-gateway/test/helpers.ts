import { GeoPoint, Timestamp } from "@google-cloud/firestore";

import { loadConfig } from "../src/config";
import type { AppConfig } from "../src/config";
import { createLogger } from "../src/logger";
import type { NewReport, ReportRepository, ReportSummary, UserProfile, UserRepository, WebhookEventStore } from "../src/services/firestore";
import type { Coordinates } from "../src/lib/geo";
import type { ImageStore, UploadRequest, UploadResult } from "../src/services/storage";
import type { MediaDownload, MediaFetcher } from "../src/services/twilio";

export const TEST_ENV = {
  NODE_ENV: "test",
  GCP_PROJECT_ID: "vayusetu-test",
  GCS_BUCKET: "vayusetu-test-citizen-images",
  TWILIO_ACCOUNT_SID: "ACtest",
  TWILIO_AUTH_TOKEN: "12345678901234567890123456789012",
  TWILIO_WHATSAPP_FROM: "whatsapp:+14155238886",
  TWILIO_VALIDATE_SIGNATURE: "false",
  PHONE_HASH_SECRET: "unit-test-secret",
  ADMIN_DOMAIN: "example.gov.in",
  LOG_LEVEL: "fatal",
};

export function testConfig(overrides: Record<string, string> = {}): AppConfig {
  return loadConfig({ ...TEST_ENV, ...overrides });
}

export const silentLogger = createLogger("fatal");

export class FakeReports implements ReportRepository {
  created: NewReport[] = [];
  failed: Array<{ reportId: string; reason: string }> = [];
  attached: Array<{ reportId: string; location: Coordinates; geohash: string; city: string | null }> = [];
  pending: string | null = null;
  latest: ReportSummary | null = null;
  recentCount = 0;

  async create(report: NewReport): Promise<void> {
    this.created.push(report);
  }
  async markUploadFailed(reportId: string, reason: string): Promise<void> {
    this.failed.push({ reportId, reason });
  }
  async attachLocation(reportId: string, location: Coordinates, geohash: string, city: string | null): Promise<void> {
    this.attached.push({ reportId, location, geohash, city });
  }
  async findPendingLocationReport(): Promise<string | null> {
    return this.pending;
  }
  async latestForUser(): Promise<ReportSummary | null> {
    return this.latest;
  }
  async countRecentForUser(): Promise<number> {
    return this.recentCount;
  }
}

export class FakeUsers implements UserRepository {
  profiles = new Map<string, UserProfile>();
  locations: Array<{ phoneHash: string; location: Coordinates; label: string | null }> = [];
  languages: Array<{ phoneHash: string; language: string }> = [];
  increments = 0;

  seed(phoneHash: string, overrides: Partial<UserProfile>): void {
    const now = Timestamp.now();
    this.profiles.set(phoneHash, {
      phoneNumber: "whatsapp:+919876543210",
      language: "en",
      reportCount: 0,
      createdAt: now,
      updatedAt: now,
      lastLocation: null,
      lastLocationAt: null,
      ...overrides,
    });
  }
  async get(phoneHash: string): Promise<UserProfile | null> {
    return this.profiles.get(phoneHash) ?? null;
  }
  async upsertOnContact(phoneHash: string, phoneNumber: string, profileName: string | null): Promise<UserProfile> {
    const existing = this.profiles.get(phoneHash);
    if (existing) {
      return existing;
    }
    const now = Timestamp.now();
    const profile: UserProfile = { phoneNumber, profileName, language: "en", reportCount: 0, createdAt: now, updatedAt: now, lastLocation: null, lastLocationAt: null };
    this.profiles.set(phoneHash, profile);
    return profile;
  }
  async updateLocation(phoneHash: string, location: Coordinates, label: string | null): Promise<void> {
    this.locations.push({ phoneHash, location, label });
    const profile = this.profiles.get(phoneHash);
    if (profile) {
      profile.lastLocation = new GeoPoint(location.latitude, location.longitude);
      profile.lastLocationAt = Timestamp.now();
    }
  }
  async setLanguage(phoneHash: string, language: string): Promise<void> {
    this.languages.push({ phoneHash, language });
  }
  async incrementReportCount(): Promise<void> {
    this.increments += 1;
  }
}

export class FakeEvents implements WebhookEventStore {
  seen = new Set<string>();
  async recordOnce(messageSid: string): Promise<boolean> {
    if (this.seen.has(messageSid)) {
      return false;
    }
    this.seen.add(messageSid);
    return true;
  }
}

export class FakeImages implements ImageStore {
  uploads: UploadRequest[] = [];
  failWith: Error | null = null;
  constructor(private readonly bucket = TEST_ENV.GCS_BUCKET) {}
  buildObjectName(reportId: string, contentType: string): string {
    return `reports/2026/11/02/${reportId}.${contentType === "image/png" ? "png" : "jpg"}`;
  }
  async upload(request: UploadRequest): Promise<UploadResult> {
    if (this.failWith) {
      throw this.failWith;
    }
    this.uploads.push(request);
    const objectName = this.buildObjectName(request.reportId, request.contentType);
    return { bucket: this.bucket, objectName, gsUri: `gs://${this.bucket}/${objectName}`, sizeBytes: request.body.byteLength };
  }
}

export class FakeMedia implements MediaFetcher {
  requests: string[] = [];
  response: MediaDownload = { body: Buffer.from("fake-jpeg-bytes"), contentType: "image/jpeg" };
  error: Error | null = null;
  async fetch(mediaUrl: string): Promise<MediaDownload> {
    this.requests.push(mediaUrl);
    if (this.error) {
      throw this.error;
    }
    return this.response;
  }
}

export function twilioForm(overrides: Record<string, string> = {}): Record<string, string> {
  return {
    MessageSid: "SM0001",
    AccountSid: "ACtest",
    From: "whatsapp:+919876543210",
    To: "whatsapp:+14155238886",
    Body: "",
    NumMedia: "0",
    ProfileName: "Asha",
    ...overrides,
  };
}

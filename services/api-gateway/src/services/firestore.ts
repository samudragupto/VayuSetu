import { FieldValue, Firestore, GeoPoint, Timestamp } from "@google-cloud/firestore";
import type { DocumentReference } from "@google-cloud/firestore";

import type { Coordinates } from "../lib/geo";

export const COLLECTIONS = {
  reports: "citizen_reports",
  users: "users",
  hotspots: "predicted_hotspots",
  webhookEvents: "webhook_events",
} as const;

export type ReportStatus = "received" | "analyzing" | "analyzed" | "failed";
export type LocationSource = "message" | "user_profile" | "text" | "follow_up" | "unknown";

export interface UserProfile {
  phoneNumber: string;
  profileName?: string | null;
  language: string;
  lastLocation?: GeoPoint | null;
  lastLocationAt?: Timestamp | null;
  lastLocationLabel?: string | null;
  reportCount: number;
  createdAt: Timestamp;
  updatedAt: Timestamp;
}

export interface NewReport {
  reportId: string;
  phoneHash: string;
  messageSid: string;
  imageUri: string;
  contentType: string;
  caption: string | null;
  location: Coordinates | null;
  geohash: string | null;
  city: string | null;
  state: string | null;
  locationSource: LocationSource;
  source: "whatsapp";
  metadata?: Record<string, unknown>;
}

export interface ReportSummary {
  reportId: string;
  status: ReportStatus;
  estimatedAqi: number | null;
  estimatedAqiCategory: string | null;
  hazeIndex: number | null;
  city: string | null;
  createdAt: Date | null;
}

export interface ReportRepository {
  create(report: NewReport): Promise<void>;
  markUploadFailed(reportId: string, reason: string): Promise<void>;
  attachLocation(reportId: string, location: Coordinates, geohash: string, city: string | null, state: string | null): Promise<void>;
  findPendingLocationReport(phoneHash: string, since: Date): Promise<string | null>;
  latestForUser(phoneHash: string): Promise<ReportSummary | null>;
  countRecentForUser(phoneHash: string, since: Date): Promise<number>;
}

export interface UserRepository {
  get(phoneHash: string): Promise<UserProfile | null>;
  upsertOnContact(phoneHash: string, phoneNumber: string, profileName: string | null): Promise<UserProfile>;
  updateLocation(phoneHash: string, location: Coordinates, label: string | null): Promise<void>;
  setLanguage(phoneHash: string, language: string): Promise<void>;
  incrementReportCount(phoneHash: string): Promise<void>;
}

export interface WebhookEventStore {
  /** Returns true if the event was newly recorded, false if it was already seen (idempotency). */
  recordOnce(messageSid: string, payload: Record<string, unknown>): Promise<boolean>;
}

function toNumberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export class FirestoreReportRepository implements ReportRepository {
  constructor(private readonly db: Firestore) {}

  private ref(reportId: string): DocumentReference {
    return this.db.collection(COLLECTIONS.reports).doc(reportId);
  }

  async create(report: NewReport): Promise<void> {
    const now = FieldValue.serverTimestamp();
    await this.ref(report.reportId).create({
      phoneHash: report.phoneHash,
      messageSid: report.messageSid,
      imageUri: report.imageUri,
      contentType: report.contentType,
      caption: report.caption,
      location: report.location ? new GeoPoint(report.location.latitude, report.location.longitude) : null,
      geohash: report.geohash,
      city: report.city,
      state: report.state,
      locationSource: report.locationSource,
      source: report.source,
      status: "received" satisfies ReportStatus,
      receivedAt: now,
      createdAt: now,
      updatedAt: now,
      metadata: report.metadata ?? {},
    });
  }

  async markUploadFailed(reportId: string, reason: string): Promise<void> {
    await this.ref(reportId).set(
      { status: "failed" satisfies ReportStatus, error: reason.slice(0, 500), updatedAt: FieldValue.serverTimestamp() },
      { merge: true }
    );
  }

  async attachLocation(reportId: string, location: Coordinates, geohash: string, city: string | null, state: string | null): Promise<void> {
    await this.ref(reportId).set(
      {
        location: new GeoPoint(location.latitude, location.longitude),
        geohash,
        city,
        state,
        locationSource: "follow_up" satisfies LocationSource,
        updatedAt: FieldValue.serverTimestamp(),
      },
      { merge: true }
    );
  }

  async findPendingLocationReport(phoneHash: string, since: Date): Promise<string | null> {
    const snapshot = await this.db
      .collection(COLLECTIONS.reports)
      .where("phoneHash", "==", phoneHash)
      .where("createdAt", ">=", Timestamp.fromDate(since))
      .orderBy("createdAt", "desc")
      .limit(5)
      .get();
    for (const doc of snapshot.docs) {
      if (doc.get("location") === null) {
        return doc.id;
      }
    }
    return null;
  }

  async latestForUser(phoneHash: string): Promise<ReportSummary | null> {
    const snapshot = await this.db
      .collection(COLLECTIONS.reports)
      .where("phoneHash", "==", phoneHash)
      .orderBy("createdAt", "desc")
      .limit(1)
      .get();
    const doc = snapshot.docs[0];
    if (!doc) {
      return null;
    }
    const createdAt = doc.get("createdAt") as Timestamp | undefined;
    return {
      reportId: doc.id,
      status: (doc.get("status") as ReportStatus | undefined) ?? "received",
      estimatedAqi: toNumberOrNull(doc.get("estimatedAqi")),
      estimatedAqiCategory: (doc.get("estimatedAqiCategory") as string | undefined) ?? null,
      hazeIndex: toNumberOrNull(doc.get("hazeIndex")),
      city: (doc.get("city") as string | undefined) ?? null,
      createdAt: createdAt ? createdAt.toDate() : null,
    };
  }

  async countRecentForUser(phoneHash: string, since: Date): Promise<number> {
    const snapshot = await this.db
      .collection(COLLECTIONS.reports)
      .where("phoneHash", "==", phoneHash)
      .where("createdAt", ">=", Timestamp.fromDate(since))
      .count()
      .get();
    return snapshot.data().count;
  }
}

export class FirestoreUserRepository implements UserRepository {
  constructor(private readonly db: Firestore) {}

  private ref(phoneHash: string): DocumentReference {
    return this.db.collection(COLLECTIONS.users).doc(phoneHash);
  }

  async get(phoneHash: string): Promise<UserProfile | null> {
    const snapshot = await this.ref(phoneHash).get();
    return snapshot.exists ? (snapshot.data() as UserProfile) : null;
  }

  async upsertOnContact(phoneHash: string, phoneNumber: string, profileName: string | null): Promise<UserProfile> {
    const ref = this.ref(phoneHash);
    return this.db.runTransaction(async (tx) => {
      const snapshot = await tx.get(ref);
      const now = Timestamp.now();
      if (!snapshot.exists) {
        const profile: UserProfile = {
          phoneNumber,
          profileName,
          language: "en",
          lastLocation: null,
          lastLocationAt: null,
          lastLocationLabel: null,
          reportCount: 0,
          createdAt: now,
          updatedAt: now,
        };
        tx.set(ref, profile);
        return profile;
      }
      const existing = snapshot.data() as UserProfile;
      const updates: Partial<UserProfile> = { updatedAt: now, phoneNumber };
      if (profileName && profileName !== existing.profileName) {
        updates.profileName = profileName;
      }
      tx.set(ref, updates, { merge: true });
      return { ...existing, ...updates };
    });
  }

  async updateLocation(phoneHash: string, location: Coordinates, label: string | null): Promise<void> {
    await this.ref(phoneHash).set(
      {
        lastLocation: new GeoPoint(location.latitude, location.longitude),
        lastLocationAt: FieldValue.serverTimestamp(),
        lastLocationLabel: label,
        updatedAt: FieldValue.serverTimestamp(),
      },
      { merge: true }
    );
  }

  async setLanguage(phoneHash: string, language: string): Promise<void> {
    await this.ref(phoneHash).set({ language, updatedAt: FieldValue.serverTimestamp() }, { merge: true });
  }

  async incrementReportCount(phoneHash: string): Promise<void> {
    await this.ref(phoneHash).set(
      { reportCount: FieldValue.increment(1), lastReportAt: FieldValue.serverTimestamp(), updatedAt: FieldValue.serverTimestamp() },
      { merge: true }
    );
  }
}

export class FirestoreWebhookEventStore implements WebhookEventStore {
  constructor(private readonly db: Firestore) {}

  async recordOnce(messageSid: string, payload: Record<string, unknown>): Promise<boolean> {
    try {
      await this.db.collection(COLLECTIONS.webhookEvents).doc(messageSid).create({
        ...payload,
        receivedAt: FieldValue.serverTimestamp(),
        // Documents are removed by a Firestore TTL policy on this field (see Terraform).
        expiresAt: Timestamp.fromMillis(Date.now() + 7 * 24 * 60 * 60 * 1000),
      });
      return true;
    } catch (error) {
      const code = (error as { code?: number | string }).code;
      // 6 = ALREADY_EXISTS in gRPC status codes.
      if (code === 6 || code === "already-exists" || code === "ALREADY_EXISTS") {
        return false;
      }
      throw error;
    }
  }
}

export function createFirestore(projectId: string): Firestore {
  return new Firestore({ projectId, ignoreUndefinedProperties: true });
}

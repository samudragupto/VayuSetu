import { GeoPoint, Timestamp } from "@google-cloud/firestore";

import { hashPhoneNumber } from "../src/lib/phone";
import { IngestionService } from "../src/services/ingestion";
import type { InboundMessage } from "../src/services/ingestion";
import { MediaTooLargeError } from "../src/services/twilio";
import { FakeEvents, FakeImages, FakeMedia, FakeReports, FakeUsers, silentLogger, testConfig } from "./helpers";

const FROM = "whatsapp:+919876543210";
const PHONE_HASH = hashPhoneNumber(FROM, "unit-test-secret");

function build(overrides: Partial<InboundMessage> = {}): InboundMessage {
  return { messageSid: "SM1", from: FROM, to: "whatsapp:+1415", body: "", profileName: "Asha", media: [], ...overrides };
}

function harness(configOverrides: Record<string, string> = {}) {
  const reports = new FakeReports();
  const users = new FakeUsers();
  const events = new FakeEvents();
  const images = new FakeImages();
  const media = new FakeMedia();
  let counter = 0;
  const service = new IngestionService({
    config: testConfig(configOverrides),
    logger: silentLogger,
    reports,
    users,
    events,
    images,
    media,
    now: () => new Date("2026-11-02T06:00:00Z"),
    idGenerator: () => `report${(counter += 1).toString().padStart(4, "0")}`,
  });
  return { service, reports, users, events, images, media };
}

describe("IngestionService", () => {
  it("creates the Firestore report before uploading the image and uses the stored location", async () => {
    const h = harness();
    h.users.seed(PHONE_HASH, { lastLocation: new GeoPoint(28.6139, 77.209), lastLocationAt: Timestamp.fromDate(new Date("2026-11-02T05:00:00Z")) });
    const order: string[] = [];
    const originalCreate = h.reports.create.bind(h.reports);
    const originalUpload = h.images.upload.bind(h.images);
    h.reports.create = async (r) => {
      order.push("create");
      return originalCreate(r);
    };
    h.images.upload = async (u) => {
      order.push("upload");
      return originalUpload(u);
    };

    const outcome = await h.service.handle(build({ media: [{ url: "https://api.twilio.com/media/1", contentType: "image/jpeg" }], body: "smoky evening" }));

    expect(outcome.kind).toBe("report_created");
    expect(order).toEqual(["create", "upload"]);
    const report = h.reports.created[0]!;
    expect(report.reportId).toBe("report0001");
    expect(report.imageUri).toBe("gs://vayusetu-test-citizen-images/reports/2026/11/02/report0001.jpg");
    expect(report.geohash).toBe("ttnfucj");
    expect(report.city).toBe("New Delhi");
    expect(report.locationSource).toBe("user_profile");
    expect(report.caption).toBe("smoky evening");
    expect(h.images.uploads[0]!.reportId).toBe("report0001");
    expect(h.users.increments).toBe(1);
    expect(outcome.replies[0]).toContain("REPORT00");
  });

  it("accepts an image without location and asks for one", async () => {
    const h = harness();
    const outcome = await h.service.handle(build({ media: [{ url: "https://api.twilio.com/media/2", contentType: "image/png" }] }));
    expect(outcome.kind).toBe("report_created");
    expect(h.reports.created[0]!.location).toBeNull();
    expect(h.reports.created[0]!.locationSource).toBe("unknown");
    expect(outcome.replies[0]).toContain("share your location");
  });

  it("attaches a follow-up location to the pending report", async () => {
    const h = harness();
    h.reports.pending = "report9999";
    const outcome = await h.service.handle(build({ latitude: "19.076", longitude: "72.8777", address: "Marine Drive" }));
    expect(outcome.kind).toBe("location_saved");
    expect(h.reports.attached[0]).toMatchObject({ reportId: "report9999", city: "Mumbai" });
    expect(h.users.locations[0]!.label).toBe("Marine Drive");
    expect(outcome.replies[0]).toContain("Mumbai");
  });

  it("rejects locations outside India", async () => {
    const h = harness();
    const outcome = await h.service.handle(build({ latitude: "51.5", longitude: "-0.12" }));
    expect(outcome.kind).toBe("rejected");
    expect(h.users.locations).toHaveLength(0);
  });

  it("marks the report failed when the upload fails", async () => {
    const h = harness();
    h.images.failWith = new Error("bucket unavailable");
    const outcome = await h.service.handle(build({ media: [{ url: "https://api.twilio.com/media/3", contentType: "image/jpeg" }] }));
    expect(outcome.kind).toBe("error");
    expect(h.reports.failed[0]).toMatchObject({ reportId: "report0001" });
    expect(h.reports.failed[0]!.reason).toContain("bucket unavailable");
  });

  it("enforces per-user rate limits and media validation", async () => {
    const h = harness({ RATE_LIMIT_PER_HOUR: "2" });
    h.reports.recentCount = 2;
    const limited = await h.service.handle(build({ messageSid: "SM-a", media: [{ url: "https://api.twilio.com/m", contentType: "image/jpeg" }] }));
    expect(limited.kind).toBe("rate_limited");

    const unsupported = await h.service.handle(build({ messageSid: "SM-b", media: [{ url: "https://api.twilio.com/m", contentType: "video/mp4" }] }));
    expect(unsupported.kind).toBe("rejected");

    h.reports.recentCount = 0;
    h.media.error = new MediaTooLargeError(1024);
    const tooLarge = await h.service.handle(build({ messageSid: "SM-c", media: [{ url: "https://api.twilio.com/m", contentType: "image/jpeg" }] }));
    expect(tooLarge.kind).toBe("rejected");
    expect(tooLarge.reason).toBe("too_large");
  });

  it("ignores duplicate deliveries of the same MessageSid", async () => {
    const h = harness();
    await h.service.handle(build({ body: "help" }));
    const second = await h.service.handle(build({ body: "help" }));
    expect(second.kind).toBe("duplicate");
    expect(second.replies).toHaveLength(0);
  });

  it("handles text commands: language, status and help", async () => {
    const h = harness();
    const lang = await h.service.handle(build({ messageSid: "SM-l", body: "lang hi" }));
    expect(lang.kind).toBe("language_set");
    expect(h.users.languages[0]!.language).toBe("hi");

    h.reports.latest = { reportId: "abcdef123456", status: "analyzed", estimatedAqi: 287.4, estimatedAqiCategory: "very_poor", hazeIndex: 0.8, city: "New Delhi", createdAt: new Date() };
    const status = await h.service.handle(build({ messageSid: "SM-s", body: "STATUS" }));
    expect(status.kind).toBe("status");
    expect(status.replies[0]).toContain("287");
    expect(status.replies[0]).toContain("very poor");

    const help = await h.service.handle(build({ messageSid: "SM-h", body: "namaste" }));
    expect(help.kind).toBe("help");
  });
});

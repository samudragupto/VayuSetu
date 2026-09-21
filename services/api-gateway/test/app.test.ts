import request from "supertest";
import twilio from "twilio";

import { createApp } from "../src/app";
import { IngestionService } from "../src/services/ingestion";
import { isAllowedAdminEmail } from "../src/middleware/firebaseAuth";
import { parseInboundMessage } from "../src/routes/webhooks";
import { FakeEvents, FakeImages, FakeMedia, FakeReports, FakeUsers, silentLogger, testConfig, twilioForm } from "./helpers";

function buildApp(configOverrides: Record<string, string> = {}) {
  const config = testConfig(configOverrides);
  const reports = new FakeReports();
  const users = new FakeUsers();
  const ingestion = new IngestionService({
    config,
    logger: silentLogger,
    reports,
    users,
    events: new FakeEvents(),
    images: new FakeImages(),
    media: new FakeMedia(),
    idGenerator: () => "fixedreportid0001",
  });
  return { app: createApp({ config, logger: silentLogger, ingestion }), reports, users, config };
}

describe("HTTP application", () => {
  it("exposes health endpoints", async () => {
    const { app } = buildApp();
    const health = await request(app).get("/healthz");
    expect(health.status).toBe(200);
    expect(health.body.status).toBe("ok");
    const ready = await request(app).get("/readyz");
    expect(ready.status).toBe(200);
    expect(ready.body.config.bucket).toBe("vayusetu-test-citizen-images");
  });

  it("returns TwiML for a help message", async () => {
    const { app } = buildApp();
    const response = await request(app).post("/webhooks/twilio/whatsapp").type("form").send(twilioForm({ Body: "help" }));
    expect(response.status).toBe(200);
    expect(response.headers["content-type"]).toMatch(/xml/);
    expect(response.text).toContain("<Message>");
    expect(response.text).toContain("VayuSetu");
  });

  it("ingests an image message and writes the report", async () => {
    const { app, reports } = buildApp();
    const response = await request(app)
      .post("/webhooks/twilio/whatsapp")
      .type("form")
      .send(twilioForm({ NumMedia: "1", MediaUrl0: "https://api.twilio.com/2010-04-01/Accounts/AC/Messages/SM/Media/ME", MediaContentType0: "image/jpeg", Body: "19.076, 72.8777" }));
    expect(response.status).toBe(200);
    expect(reports.created).toHaveLength(1);
    expect(reports.created[0]!.city).toBe("Mumbai");
    expect(reports.created[0]!.locationSource).toBe("text");
    expect(response.text).toContain("FIXEDREP");
  });

  it("rejects malformed webhook payloads", async () => {
    const { app } = buildApp();
    const response = await request(app).post("/webhooks/twilio/whatsapp").type("form").send({ Body: "no sid" });
    expect(response.status).toBe(400);
  });

  it("validates Twilio signatures when enabled", async () => {
    const { app, config } = buildApp({ TWILIO_VALIDATE_SIGNATURE: "true", PUBLIC_BASE_URL: "https://gateway.example.com" });
    const form = twilioForm({ Body: "help" });
    const unsigned = await request(app).post("/webhooks/twilio/whatsapp").type("form").send(form);
    expect(unsigned.status).toBe(403);

    const signature = twilio.getExpectedTwilioSignature(config.TWILIO_AUTH_TOKEN, "https://gateway.example.com/webhooks/twilio/whatsapp", form);
    const signed = await request(app).post("/webhooks/twilio/whatsapp").type("form").set("X-Twilio-Signature", signature).send(form);
    expect(signed.status).toBe(200);
  });

  it("accepts delivery status callbacks", async () => {
    const { app } = buildApp();
    const response = await request(app).post("/webhooks/twilio/status").type("form").send({ MessageSid: "SM1", MessageStatus: "delivered" });
    expect(response.status).toBe(204);
  });

  it("returns 404 JSON for unknown routes", async () => {
    const { app } = buildApp();
    const response = await request(app).get("/nope");
    expect(response.status).toBe(404);
    expect(response.body.error).toBe("not found");
  });
});

describe("helpers", () => {
  it("parses inbound messages including media and location fields", () => {
    const parsed = parseInboundMessage(twilioForm({ NumMedia: "2", MediaUrl0: "https://a", MediaContentType0: "image/jpeg", MediaUrl1: "https://b", MediaContentType1: "image/png", Latitude: "28.6", Longitude: "77.2" }));
    expect(parsed?.media).toHaveLength(2);
    expect(parsed?.latitude).toBe("28.6");
    expect(parseInboundMessage({ Body: "x" })).toBeNull();
  });

  it("restricts administrators to the configured domains", () => {
    expect(isAllowedAdminEmail("officer@example.gov.in", "example.gov.in")).toBe(true);
    expect(isAllowedAdminEmail("officer@example.gov.in", "other.org, example.gov.in")).toBe(true);
    expect(isAllowedAdminEmail("someone@gmail.com", "example.gov.in")).toBe(false);
    expect(isAllowedAdminEmail("someone@gmail.com", "")).toBe(false);
  });
});

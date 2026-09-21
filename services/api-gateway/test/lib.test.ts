import { encodeGeohash, haversineKm, isWithinIndia, nearestCity, parseCoordinates } from "../src/lib/geo";
import { hashPhoneNumber, maskPhoneNumber, normalisePhoneNumber, verifyPhoneHash } from "../src/lib/phone";
import { isTransientError, withRetry } from "../src/lib/retry";
import { loadConfig } from "../src/config";
import { parseLanguageCommand, renderMessage } from "../src/services/messages";
import { TEST_ENV } from "./helpers";

describe("phone helpers", () => {
  it("normalises WhatsApp identifiers to E.164", () => {
    expect(normalisePhoneNumber("whatsapp:+91 98765 43210")).toBe("+919876543210");
    expect(normalisePhoneNumber("919876543210")).toBe("+919876543210");
  });

  it("produces a stable keyed hash that can be verified", () => {
    const hash = hashPhoneNumber("whatsapp:+919876543210", "secret");
    expect(hash).toHaveLength(32);
    expect(hashPhoneNumber("+919876543210", "secret")).toBe(hash);
    expect(hashPhoneNumber("+919876543210", "other")).not.toBe(hash);
    expect(verifyPhoneHash("+919876543210", "secret", hash)).toBe(true);
    expect(maskPhoneNumber("+919876543210")).toBe("*********3210");
  });
});

describe("geo helpers", () => {
  it("matches Delhi coordinates to the geohash used across the platform", () => {
    expect(encodeGeohash({ latitude: 28.6139, longitude: 77.209 }, 7)).toBe("ttnfucj");
    expect(encodeGeohash({ latitude: 28.6139, longitude: 77.209 }, 5)).toBe("ttnfu");
  });

  it("finds the nearest city and computes distances", () => {
    const match = nearestCity({ latitude: 28.5, longitude: 77.1 });
    expect(match?.city).toBe("Gurugram");
    expect(haversineKm({ latitude: 28.6139, longitude: 77.209 }, { latitude: 19.076, longitude: 72.8777 })).toBeCloseTo(1153, -1);
    expect(nearestCity({ latitude: 10.0, longitude: 90.0 })).toBeNull();
  });

  it("parses coordinates from location payloads and text", () => {
    expect(parseCoordinates({ Latitude: "28.61", Longitude: "77.21" })).toEqual({ latitude: 28.61, longitude: 77.21 });
    expect(parseCoordinates({ Body: "I am at 19.07, 72.87 now" })).toEqual({ latitude: 19.07, longitude: 72.87 });
    expect(parseCoordinates({ Body: "hello" })).toBeNull();
    expect(parseCoordinates({ Latitude: "0", Longitude: "0" })).toBeNull();
    expect(isWithinIndia({ latitude: 51.5, longitude: -0.12 })).toBe(false);
  });
});

describe("retry helper", () => {
  it("retries transient errors and eventually succeeds", async () => {
    let calls = 0;
    const result = await withRetry(
      async () => {
        calls += 1;
        if (calls < 3) {
          throw Object.assign(new Error("busy"), { status: 429 });
        }
        return "ok";
      },
      { attempts: 4, baseDelayMs: 1, maxDelayMs: 2 }
    );
    expect(result).toBe("ok");
    expect(calls).toBe(3);
  });

  it("does not retry permanent errors", async () => {
    let calls = 0;
    await expect(
      withRetry(
        async () => {
          calls += 1;
          throw Object.assign(new Error("bad request"), { status: 400 });
        },
        { attempts: 3, baseDelayMs: 1 }
      )
    ).rejects.toThrow("bad request");
    expect(calls).toBe(1);
    expect(isTransientError(Object.assign(new Error("x"), { code: "ECONNRESET" }))).toBe(true);
  });
});

describe("config and messages", () => {
  it("validates required environment variables", () => {
    expect(() => loadConfig({ ...TEST_ENV, GCS_BUCKET: "" })).toThrow(/GCS_BUCKET/);
    const config = loadConfig(TEST_ENV);
    expect(config.TWILIO_VALIDATE_SIGNATURE).toBe(false);
    expect(config.HOTSPOT_GEOHASH_PRECISION).toBe(5);
  });

  it("renders localised messages and parses language commands", () => {
    expect(renderMessage("hi", "help")).toContain("VayuSetu");
    expect(renderMessage("xx", "statusNone")).toContain("No reports found");
    expect(parseLanguageCommand("LANG HI")).toBe("hi");
    expect(parseLanguageCommand("language: tamil")).toBe("ta");
    expect(parseLanguageCommand("lang klingon")).toBeNull();
    expect(parseLanguageCommand("hello")).toBeNull();
  });
});

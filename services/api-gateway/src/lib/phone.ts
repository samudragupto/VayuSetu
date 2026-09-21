import { createHmac, timingSafeEqual } from "node:crypto";

/**
 * Normalise a WhatsApp sender identifier ("whatsapp:+91 98765 43210") to
 * canonical E.164 with the channel prefix removed.
 */
export function normalisePhoneNumber(raw: string): string {
  const withoutChannel = raw.trim().replace(/^whatsapp:/i, "");
  const digits = withoutChannel.replace(/[^\d+]/g, "");
  if (!digits.startsWith("+")) {
    return `+${digits}`;
  }
  return digits;
}

/**
 * Deterministic, keyed hash of the phone number used as the Firestore user
 * identifier so that raw numbers are never used as document keys.
 */
export function hashPhoneNumber(phoneNumber: string, secret: string): string {
  const normalised = normalisePhoneNumber(phoneNumber);
  return createHmac("sha256", secret).update(normalised).digest("hex").slice(0, 32);
}

export function verifyPhoneHash(phoneNumber: string, secret: string, expected: string): boolean {
  const actual = Buffer.from(hashPhoneNumber(phoneNumber, secret));
  const expectedBuffer = Buffer.from(expected);
  return actual.length === expectedBuffer.length && timingSafeEqual(actual, expectedBuffer);
}

/** Mask all but the last four digits for logging. */
export function maskPhoneNumber(phoneNumber: string): string {
  const normalised = normalisePhoneNumber(phoneNumber);
  if (normalised.length <= 4) {
    return "****";
  }
  return `${"*".repeat(normalised.length - 4)}${normalised.slice(-4)}`;
}

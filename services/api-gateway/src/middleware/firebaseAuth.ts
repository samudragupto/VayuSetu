import type { NextFunction, Request, Response } from "express";
import type { App } from "firebase-admin/app";

import type { AppConfig } from "../config";
import type { Logger } from "../logger";

export interface VerifiedIdentity {
  uid: string;
  email: string;
  emailVerified: boolean;
  name?: string;
}

export interface TokenVerifier {
  verify(idToken: string): Promise<VerifiedIdentity>;
}

declare module "express-serve-static-core" {
  interface Request {
    identity?: VerifiedIdentity;
  }
}

/** Token verifier backed by the Firebase Admin SDK (lazy-loaded). */
export class FirebaseTokenVerifier implements TokenVerifier {
  private app: App | null = null;

  constructor(private readonly projectId: string) {}

  private async getAuth() {
    const { getApps, initializeApp } = await import("firebase-admin/app");
    const { getAuth } = await import("firebase-admin/auth");
    if (!this.app) {
      this.app = getApps()[0] ?? initializeApp({ projectId: this.projectId });
    }
    return getAuth(this.app);
  }

  async verify(idToken: string): Promise<VerifiedIdentity> {
    const auth = await this.getAuth();
    const decoded = await auth.verifyIdToken(idToken, true);
    return {
      uid: decoded.uid,
      email: decoded.email ?? "",
      emailVerified: Boolean(decoded.email_verified),
      name: typeof decoded.name === "string" ? decoded.name : undefined,
    };
  }
}

export function isAllowedAdminEmail(email: string, adminDomain: string): boolean {
  if (!email || !adminDomain) {
    return false;
  }
  const domains = adminDomain
    .split(",")
    .map((d) => d.trim().toLowerCase())
    .filter(Boolean);
  const emailDomain = email.toLowerCase().split("@")[1] ?? "";
  return domains.includes(emailDomain);
}

/**
 * Require a Firebase ID token from a verified Google account whose email
 * domain is in ADMIN_DOMAIN. Used for the authority-facing read API.
 */
export function firebaseAuthMiddleware(config: AppConfig, verifier: TokenVerifier, logger: Logger) {
  return async (req: Request, res: Response, next: NextFunction): Promise<void> => {
    const header = req.get("authorization") ?? "";
    const [scheme, token] = header.split(" ");
    if (scheme?.toLowerCase() !== "bearer" || !token) {
      res.status(401).json({ error: "missing bearer token" });
      return;
    }
    try {
      const identity = await verifier.verify(token);
      if (!identity.emailVerified || !isAllowedAdminEmail(identity.email, config.ADMIN_DOMAIN)) {
        logger.warn({ email: identity.email }, "Authenticated user is not an authorised administrator");
        res.status(403).json({ error: "account is not authorised for this dashboard" });
        return;
      }
      req.identity = identity;
      next();
    } catch (error) {
      logger.warn({ err: error }, "Firebase ID token verification failed");
      res.status(401).json({ error: "invalid or expired token" });
    }
  };
}

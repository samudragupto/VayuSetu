"use client";

import { getApps, initializeApp, type FirebaseApp } from "firebase/app";
import { connectAuthEmulator, getAuth, GoogleAuthProvider, type Auth } from "firebase/auth";
import { connectFirestoreEmulator, getFirestore, type Firestore } from "firebase/firestore";

import { config, isFirebaseConfigured } from "./config";

let app: FirebaseApp | null = null;
let auth: Auth | null = null;
let db: Firestore | null = null;
let emulatorsConnected = false;

/**
 * Lazily initialise Firebase on the client. Returns null when configuration
 * is missing so the UI can render an explanatory message instead of crashing.
 */
export function getFirebase(): { app: FirebaseApp; auth: Auth; db: Firestore } | null {
  if (typeof window === "undefined" || !isFirebaseConfigured()) {
    return null;
  }
  if (!app) {
    app =
      getApps()[0] ??
      initializeApp({
        apiKey: config.firebase.apiKey || "emulator-api-key",
        authDomain: config.firebase.authDomain || undefined,
        projectId: config.firebase.projectId,
        storageBucket: config.firebase.storageBucket || undefined,
        messagingSenderId: config.firebase.messagingSenderId || undefined,
        appId: config.firebase.appId || undefined,
      });
    auth = getAuth(app);
    db = getFirestore(app);
    if (config.useEmulators && !emulatorsConnected) {
      const [host, port] = config.firestoreEmulatorHost.split(":");
      connectFirestoreEmulator(db, host ?? "localhost", Number(port ?? 8080));
      connectAuthEmulator(auth, config.authEmulatorUrl, { disableWarnings: true });
      emulatorsConnected = true;
    }
  }
  return { app, auth: auth!, db: db! };
}

export function createGoogleProvider(): GoogleAuthProvider {
  const provider = new GoogleAuthProvider();
  provider.setCustomParameters({
    prompt: "select_account",
    ...(config.adminDomains[0] ? { hd: config.adminDomains[0] } : {}),
  });
  provider.addScope("email");
  return provider;
}

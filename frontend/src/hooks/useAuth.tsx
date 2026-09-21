"use client";

import { onAuthStateChanged, signInWithPopup, signOut as firebaseSignOut, type User } from "firebase/auth";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { isAdminEmail, isFirebaseConfigured } from "@/lib/config";
import { createGoogleProvider, getFirebase } from "@/lib/firebase";

export type AuthStatus = "initialising" | "unconfigured" | "signed_out" | "unauthorised" | "authorised";

interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  error: string | null;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("initialising");
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isFirebaseConfigured()) {
      setStatus("unconfigured");
      return;
    }
    const firebase = getFirebase();
    if (!firebase) {
      setStatus("unconfigured");
      return;
    }
    const unsubscribe = onAuthStateChanged(firebase.auth, (nextUser) => {
      setUser(nextUser);
      if (!nextUser) {
        setStatus("signed_out");
      } else if (isAdminEmail(nextUser.email)) {
        setStatus("authorised");
        setError(null);
      } else {
        setStatus("unauthorised");
        setError(`${nextUser.email ?? "This account"} is not part of an authorised administrator domain.`);
      }
    });
    return unsubscribe;
  }, []);

  const signIn = useCallback(async () => {
    const firebase = getFirebase();
    if (!firebase) {
      setError("Firebase is not configured for this build.");
      return;
    }
    setError(null);
    try {
      const credential = await signInWithPopup(firebase.auth, createGoogleProvider());
      if (!isAdminEmail(credential.user.email)) {
        await firebaseSignOut(firebase.auth);
        setStatus("signed_out");
        setError(`${credential.user.email ?? "This account"} is not part of an authorised administrator domain.`);
      }
    } catch (signInError) {
      const code = (signInError as { code?: string }).code ?? "";
      if (code !== "auth/popup-closed-by-user" && code !== "auth/cancelled-popup-request") {
        setError((signInError as Error).message);
      }
    }
  }, []);

  const signOut = useCallback(async () => {
    const firebase = getFirebase();
    if (firebase) {
      await firebaseSignOut(firebase.auth);
    }
    setStatus("signed_out");
  }, []);

  const value = useMemo<AuthContextValue>(() => ({ status, user, error, signIn, signOut }), [status, user, error, signIn, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

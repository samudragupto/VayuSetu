"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/hooks/useAuth";
import { config } from "@/lib/config";

import { ErrorState, LoadingState } from "./States";

export function LoginPanel() {
  const { status, error, signIn } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "authorised") {
      router.replace("/");
    }
  }, [status, router]);

  const domainText = config.adminDomains.length > 0 ? config.adminDomains.join(", ") : "the configured administrator domain";

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-brand-900 via-brand-700 to-brand-500 px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-xl">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-600 text-base font-bold text-white">VS</span>
          <div>
            <h1 className="text-xl font-semibold text-slate-900">VayuSetu</h1>
            <p className="text-sm text-slate-500">Authority dashboard sign in</p>
          </div>
        </div>
        <p className="mt-6 text-sm text-slate-600">
          Access is limited to verified Google Workspace accounts on {domainText}. Sign in to view live citizen reports, satellite-fused AQI forecasts and alert history.
        </p>

        <div className="mt-6 space-y-3">
          {status === "initialising" ? <LoadingState message="Checking your session" /> : null}
          {status === "unconfigured" ? (
            <ErrorState message="Firebase is not configured for this build. Set the NEXT_PUBLIC_FIREBASE_* variables (or NEXT_PUBLIC_USE_EMULATORS=true with the Firebase Local Emulator Suite) and rebuild." />
          ) : null}
          {error ? <ErrorState message={error} /> : null}
          {status === "signed_out" || status === "unauthorised" ? (
            <button type="button" className="btn-primary w-full" onClick={() => void signIn()}>
              <svg aria-hidden="true" width="18" height="18" viewBox="0 0 48 48">
                <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.3l7.9 6.1C12.4 13.4 17.7 9.5 24 9.5z" />
                <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4.1 7.1-10.1 7.1-17.5z" />
                <path fill="#FBBC05" d="M10.5 28.6A14.5 14.5 0 0 1 9.7 24c0-1.6.3-3.1.8-4.6l-7.9-6.1A24 24 0 0 0 0 24c0 3.9.9 7.5 2.6 10.7l7.9-6.1z" />
                <path fill="#34A853" d="M24 48c6.3 0 11.7-2.1 15.6-5.7l-7.5-5.8c-2.1 1.4-4.8 2.3-8.1 2.3-6.3 0-11.6-3.9-13.5-9.4l-7.9 6.1C6.5 42.6 14.6 48 24 48z" />
              </svg>
              Sign in with Google
            </button>
          ) : null}
        </div>

        <p className="mt-8 text-xs text-slate-400">Reports are pseudonymous. Phone numbers are never displayed on this dashboard.</p>
      </div>
    </div>
  );
}
